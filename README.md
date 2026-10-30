# Find Forms

A detection-only crawler for studying how websites design their email
subscription forms: newsletter signups, popups, sticky bars and footer forms.
For each site it finds the signup forms and saves screenshots, HTML and UX
metadata for later manual coding.

**Crawling never types into, fills, submits or clicks anything.** It loads pages,
waits, scrolls and moves the mouse the way a first-time visitor would, and
records what appears. It waits between page loads and visits at most
`--max-pages` pages per site. It does **not** consult robots.txt.

Signing up is a separate phase with its own flag, `--submit`, described below.
It never runs during a crawl.

## Method

Form detection is adapted from Englehardt, Han & Narayanan (2018), "I never
signed up for this! Privacy implications of email tracking," *Proceedings on
Privacy Enhancing Technologies* 2018(1):109–126, Section 3 and Appendix 10.1.
Cite this paper when describing the method.

Our changes to it (all on purpose, and they belong in a methods section) are
listed under "Intentional differences from the paper" in [CLAUDE.md](CLAUDE.md).
Every page is rendered in Chromium, driven by Selenium; nothing is fetched
outside the browser. (The crawler used Playwright until 2026-10-21; the
recorded measurements are unchanged.)

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Chrome and a matching chromedriver need to be on your PATH; Selenium Manager
downloads a driver automatically if there isn't one.

Or run it in Docker, which brings its own Chromium and a virtual screen you can
watch over VNC while it crawls — see [docker/README.md](docker/README.md):

```bash
docker compose up -d --build
# then open http://localhost:6080/ and
docker compose exec crawler python3 src/find_forms.py inputs/sites.txt --out outputs/run1
```

## Running

Run from the repository root. Put site lists in `inputs/`: one domain or URL per
line, or a Tranco `rank,domain` CSV. Lines starting with `#` are skipped.

```bash
python src/find_forms.py inputs/sites.txt --limit 20 --out outputs/pilot   # quick pilot
python src/find_forms.py inputs/sites.txt --out outputs/news_sites         # full run
python src/find_forms.py inputs/sites.txt --out outputs/news_sites --jobs 4  # 4 parallel processes
python src/find_forms.py inputs/sites.txt --headless                      # hide the browser window
```

Rerun the same command to resume; finished sites are skipped. Ctrl-C stops
cleanly after the current page. `python src/find_forms.py --help` lists every
option. The ones you are most likely to change:

| Option | Default | What it does |
|---|---|---|
| `--out DIR` | `outputs/results` | Output directory. Use one per run. |
| `--max-pages N` | 3 | Pages visited per site. |
| `--explore` | off | Keep visiting pages after a form is found. |
| `--popup-wait S` | 8 | Seconds to wait for delayed popups. |
| `--page-delay S` | 3 | Seconds between page loads on a site, plus jitter. |
| `--jobs N` | 1 | Run N processes (max 8, ~500 MB RAM each) and merge their output. |
| `--site-time-limit S` | 120 × `--max-pages` | Stop a site that runs longer than this (its browser is restarted) and log it as `site_timeout`. |
| `--no-stealth` | off | Use plain Selenium. By default Chrome is driven through `undetected_chromedriver`, which hides the fingerprints sites use to spot a crawler. |

## Submitting forms

`--submit` signs up to the forms a crawl found, to study what happens after:
the confirmation flow, double opt-in, the welcome email, and whether the
address is later leaked or sold. It is the only part of the project that types
into a page or clicks anything, and it is a **separate phase** — it takes no
sites argument, reading instead the forms already recorded for the run named by
`--out`. So you can look through the screenshots first and only then sign up.

```bash
python src/find_forms.py inputs/sites.txt --out outputs/run6          # 1. crawl
python src/find_forms.py --submit --out outputs/run6 \                # 2. rehearse
    --submit-email 'study+{site}@gmail.com' --submit-dry-run
python src/find_forms.py --submit --out outputs/run6 \                # 3. sign up
    --submit-email 'study+{site}@gmail.com' --submit-limit 5
```

Per site it takes the top-ranked subscription form, reopens its page, waits for
the form to reappear, fills it, **saves a screenshot and the HTML of the filled
form before clicking**, submits, and saves the result page. Each site is signed
up to at most once, ever.

| Option | Default | What it does |
|---|---|---|
| `--submit-email ADDRESS` | — | Required. `{site}` becomes the site's hostname, so a leaked address is traceable to the site that received it. |
| `--submit-dry-run` | off | Fill everything in and photograph it, but never click. |
| `--submit-limit N` | no limit | Stop after N submissions. |
| `--submit-delay S` | 30 | Seconds between sites — ten times `--page-delay`, because a submission is a write. |
| `--submit-again` | off | Allow a site that has already been submitted to. |

Only the email box and fields the form marks **required** are filled; optional
fields and consent checkboxes are left exactly as the site set them, since their
defaults are part of what the study measures. Two exceptions, both deliberate:

- A form that **requires** a phone number, password, username, street address,
  card details or a verification code is **skipped** rather than filled with
  invented data (`outcome = skipped_phone`, and so on). Nothing is typed into it
  and nothing is sent.
- A **pre-ticked SMS** box is unticked. The study signs up for email, and gives no
  phone number for anyone to text.

Each row gets both an `outcome` (what the crawler did) and a `result` (what the
site appears to have done): `success_text`, `failed`, `redirect`, `form_gone`,
`form_reset`, `page_error` or `no_change`. The verdict counts only wording that
**newly appeared** after the click, since a "thanks for subscribing" is usually
somewhere on the page before you submit anything; `success_keywords` records which
words actually fired. Like `form_type`, it is a heuristic to spot-check against the
screenshots, not ground truth.

Results land in the `submissions` table. Ethics/IRB sign-off for live submission is
an open question — see
[CLAUDE.md](CLAUDE.md#form-submission---submit-built-2026-10-23).

## Output

Each run writes into its `--out` directory:

| File | Contents |
|---|---|
| `screens/<site>/` | Element screenshot and in-context viewport screenshot per form. |
| `html/<site>/` | The form's HTML. |
| `run.log` | Everything printed during the run, with timestamps, the time taken per site and the total run time. |

The rows themselves go into one database shared by every run, tagged with the
run's name — which is the name of its `--out` directory. Resume is per run, so
a new `--out` starts from scratch. The database is `DATABASE_URL` in
[src/crawler/config.py](src/crawler/config.py), `sqlite:///outputs/crawl.db`
unless you change it; any SQLAlchemy URL works, so it can point at Postgres or
MySQL instead. `FIND_FORMS_DATABASE_URL` overrides it for one run.

Query it with any SQLite tool, or get the old CSVs back whenever you want them:

```bash
sqlite3 outputs/crawl.db "SELECT run, form_type, count(*) FROM forms GROUP BY 1, 2"
python src/find_forms.py --export-csv            # forms.csv + pages.csv for every run
```

Columns such as
`placement_guess`, `modal_hint`, `form_type` and `consent_text_hint` are
heuristics: spot-check them against the screenshots before relying on them.
The full column reference and schema history are in [CLAUDE.md](CLAUDE.md#outputs---out-default-outputsresults).

## Code layout

```
src/find_forms.py      entry point: command line and the main loop
src/crawler/
  config.py            timing budgets, keyword regexes, output columns
  js.py                JavaScript run in the page: measures what only a rendered page knows
  classify.py          decides what a form is and how candidates rank (pure Python, testable)
  browser.py           driver setup, page loading, phased detection, screenshots
  crawl.py             per-site flow: landing page, then ranked links
  submit.py            --submit only: filling in and submitting forms
  output.py            database schema and writing, resuming, CSV export
  jobs.py              --jobs process supervisor, Ctrl-C handling
  util.py              small shared helpers
docker/                Dockerfile, entrypoint and notes for the containerised run
tests/                 test_classify.py (the rules, no browser, ~30ms), run_fixture.py
                       (all 20 forms typed right) and run_submit_fixture.py (--submit,
                       counting POSTs exactly)
inputs/                site lists
scripts/               misc helper scripts (cleanup, analysis, conversions)
outputs/               one directory per run (not committed)
```

[docs/crawl-flow.md](docs/crawl-flow.md) walks through a crawl step by step.
[CLAUDE.md](CLAUDE.md) has the detailed architecture, the rules the code must
keep (detection only, browser only, polite delays), the testing procedure and the
known limitations.
