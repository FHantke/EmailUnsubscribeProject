# Running the crawler in Docker, with a screen you can watch

The crawler shows a real browser window by default, because some sites serve
headless browsers different content. In a container that window needs somewhere
to be drawn, so the image runs a virtual screen (Xvfb) and publishes it two
ways: **noVNC** in a browser, and a plain **VNC** port for a desktop client.

## Start it

```bash
docker compose up -d --build        # first build takes a few minutes
```

Then open **http://localhost:6080/** and click Connect. Or point a VNC client
(Remmina, TigerVNC, macOS Screen Sharing) at **localhost:5900**.

The screen is empty until a crawl runs — the container starts the display and
waits, so you can connect first and then watch.

## Crawl

```bash
docker compose exec crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1
docker compose exec crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1 --jobs 4
```

Browser windows appear on the screen as sites are crawled; with `--jobs N` you
get N of them, and fluxbox lets you move and raise each one. `inputs/` is
mounted read-only and `outputs/` is written straight back to the host, so
results survive the container.

## PostgreSQL

The crawler writes to SQLite in `outputs/` unless `FIND_FORMS_DATABASE_URL`
names another database. A shared PostgreSQL is what lets several machines work
on one run: each takes its sites from the run's queue there.

**Locally**, for tests and trial runs, `docker-compose.yml` has a `postgres`
service that only starts when asked for:

```bash
docker compose --profile test up -d postgres

# the database and queue tests, from the host
FIND_FORMS_TEST_DATABASE_URL=postgresql://forms:forms@localhost:5432/forms \
    python3 tests/test_workqueue.py

# a crawl into it, from the crawler container (same compose network)
docker compose up -d crawler
docker compose exec -e FIND_FORMS_DATABASE_URL=postgresql://forms:forms@postgres:5432/forms \
    crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1 --jobs 4

docker compose --profile test down       # add -v to delete the database too
```

**On AWS**, with the crawler on EC2 and the database on RDS for PostgreSQL in
the same region and VPC:

```bash
export FIND_FORMS_DATABASE_URL='postgresql://crawler@forms.abc123.us-east-1.rds.amazonaws.com:5432/forms?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem'
export FIND_FORMS_DATABASE_PASSWORD='...'    # kept out of the URL: no escaping, never logged
docker compose up -d crawler
docker compose exec crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1 --jobs 8 --headless
```

- The image carries RDS's certificate bundle at
  `/etc/ssl/certs/rds-global-bundle.pem`, so `sslmode=verify-full` checks the
  server's certificate as well as encrypting.
- The database named in the URL must exist; the tables are created on first use.
- Run the same command on each EC2 instance to add workers. Each instance can
  run up to 8 (`--jobs`), and they share one queue, so nobody crawls a site
  twice. Leave out the site list to join a run that is already queued, and use
  `--status --out outputs/run1` to see progress.
- Screenshots and HTML are written to `outputs/` on the instance that crawled
  the site; the database holds their paths relative to `--out`. Copy every
  instance's `outputs/run1/` to the same place (e.g. one S3 prefix) to have
  them all together. No two instances write the same site's files.
- Instances' clocks must be right (EC2 keeps them synchronised by default),
  since a worker's claim is judged stale by its timestamp.

Run headless instead when you do not need to watch:

```bash
docker compose exec crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1 --headless
```

## Settings

| | |
|---|---|
| `SCREEN` | virtual screen size, default `1600x1000x24`. Keep it larger than the 1440×900 viewport, or windows get clipped. |
| `VNC_PASSWORD` | set it in `docker-compose.yml` to require a password. Unset means no password. |
| `shm_size` | 2 GB. Chromium crashes tabs on Docker's default 64 MB. |
| `mem_limit` | 8 GB, enough for `--jobs 8` at roughly 500–800 MB per browser. |
| `FIND_FORMS_DATABASE_URL` | the database, passed through from the shell. Unset means SQLite in `outputs/`. |
| `FIND_FORMS_DATABASE_PASSWORD` | its password, passed through from the shell, so it needs no escaping in the URL. |

Both ports are bound to `127.0.0.1`, so the screen is reachable only from this
machine. Before exposing them anywhere else, set `VNC_PASSWORD` — the VNC
session has full control of the browser, not just a view of it.

## Notes

- Chromium and chromedriver both come from Debian, so their versions always
  match. A mismatched pair is the usual cause of "session not created".
- `undetected_chromedriver`, the default driver, does not download anything
  here: the image build puts a patched copy of the image's own
  `/usr/bin/chromedriver` in its cache (since 2026-11-03), and each crawl only
  checks it is still there. Its download is Google's x86-64 Linux build only,
  which dies at once (status -5) in the arm64 image an Apple Silicon Mac
  builds; Debian's driver matches the Chromium beside it on either
  architecture. `--no-stealth` uses `/usr/bin/chromedriver` as is.
- Chromium runs with `--no-sandbox`, which it needs inside a container without
  extra privileges. The crawler reads that from `FIND_FORMS_CHROME_FLAGS`, with
  the binary and driver paths in `FIND_FORMS_CHROME_BINARY` and
  `FIND_FORMS_CHROMEDRIVER`; all three are unset on a normal machine.
- Fonts are installed deliberately. A missing font changes text size, and the
  crawler records the rendered width and height of every form.
- `SiteWatchdog` finds Chrome through `/proc`, which works here: the container
  is Linux whatever the host is.
