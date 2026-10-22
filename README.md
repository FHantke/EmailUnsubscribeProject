# Find Forms

A detection-only crawler for studying how websites design their email
subscription forms: newsletter signups, popups, sticky bars and footer forms.
For each site it finds the signup forms and saves screenshots, HTML and UX
metadata for later manual coding.

**It never types into, fills, submits or clicks anything.** It loads pages,
waits, scrolls and moves the mouse the way a first-time visitor would, and
records what appears. It waits between page loads and visits at most
`--max-pages` pages per site. It does **not** consult robots.txt.

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
| `--stealth` | off | Drive Chrome through `undetected_chromedriver`, hiding the fingerprints sites use to spot a crawler. |

## Output

Each run writes into its `--out` directory:

| File | Contents |
|---|---|
| `forms.csv`, `forms.jsonl` | One row per unique form per site. |
| `pages.csv` | One row per page visit, with status and errors. |
| `screens/<site>/` | Element screenshot and in-context viewport screenshot per form. |
| `html/<site>/` | The form's HTML. |
| `sites_done.txt` | Progress log used for resuming. |
| `run.log` | Everything printed during the run, with timestamps, the time taken per site and the total run time. |

Columns such as
`placement_guess`, `modal_hint`, `login_like` and `consent_text_hint` are
heuristics: spot-check them against the screenshots before relying on them.
The full column reference and schema history are in [CLAUDE.md](CLAUDE.md#outputs---out-default-outputsresults).

## Code layout

```
src/find_forms.py      entry point: command line and the main loop
src/crawler/
  config.py            timing budgets, keyword regexes, output columns
  js.py                JavaScript run in the page (form detection, scrolling, exit intent)
  browser.py           driver setup, page loading, phased detection, screenshots
  crawl.py             per-site flow: landing page, then ranked links
  output.py            CSV/JSONL writing, resuming, merging parallel runs
  jobs.py              --jobs process supervisor, Ctrl-C handling
  util.py              small shared helpers
docker/                Dockerfile, entrypoint and notes for the containerised run
inputs/                site lists
scripts/               misc helper scripts (cleanup, analysis, conversions)
outputs/               one directory per run (not committed)
```

[docs/crawl-flow.md](docs/crawl-flow.md) walks through a crawl step by step.
[CLAUDE.md](CLAUDE.md) has the detailed architecture, the rules the code must
keep (detection only, browser only, polite delays), the testing procedure and the
known limitations.
