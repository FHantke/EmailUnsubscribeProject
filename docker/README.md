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

Both ports are bound to `127.0.0.1`, so the screen is reachable only from this
machine. Before exposing them anywhere else, set `VNC_PASSWORD` — the VNC
session has full control of the browser, not just a view of it.

## Notes

- Chromium and chromedriver both come from Debian, so their versions always
  match. A mismatched pair is the usual cause of "session not created".
- The first crawl downloads the `undetected_chromedriver` binary (~23 MB), the
  default driver. It is cached in the container, so only the first run pays for
  it, and it is re-fetched if you recreate the container. `--no-stealth` skips
  it entirely.
- Chromium runs with `--no-sandbox`, which it needs inside a container without
  extra privileges. The crawler reads that from `FIND_FORMS_CHROME_FLAGS`, with
  the binary and driver paths in `FIND_FORMS_CHROME_BINARY` and
  `FIND_FORMS_CHROMEDRIVER`; all three are unset on a normal machine.
- Fonts are installed deliberately. A missing font changes text size, and the
  crawler records the rendered width and height of every form.
- `SiteWatchdog` finds Chrome through `/proc`, which works here: the container
  is Linux whatever the host is.
