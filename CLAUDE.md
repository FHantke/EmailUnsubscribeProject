# CLAUDE.md

## Project overview

Academic research project studying the design of email subscription forms (newsletter signups, popups, sticky bars, footer forms) across hundreds to thousands of websites. The core tool is `find_forms.py`, a Selenium crawler that discovers signup forms and records screenshots, HTML, and UX metadata for later manual coding and analysis.

Form-detection logic is adapted from Englehardt, Han & Narayanan (2018), "I never signed up for this! Privacy implications of email tracking," *Proceedings on Privacy Enhancing Technologies* 2018(1):109–126, Section 3 and Appendix 10.1. Cite this paper when describing the method.

## Hard rules

- **Detection only.** The crawler must never type into, fill, or submit forms, and must never click elements on the page. Navigation happens by `page.goto()` on link URLs. Do not add form-filling, clicking, or submission code unless the user explicitly asks for it in the current session. If that is requested, build it as a separate module behind an explicit opt-in flag, never as a default.
- robots.txt is **not** consulted (removed 2026-10-08 at the project lead's decision). Per-site politeness rests on the page delays below and on `--max-pages`. Report this in the methods section.
- **Browser only.** Every request comes from Chromium page loads; there are no requests outside the browser. Do not reintroduce plain-HTTP pre-screening or recording forms from served markup (removed 2026-10-08).
- **Selenium**, since 2026-10-21 (was Playwright). Chrome is driven through chromedriver, one driver per site. The exact viewport is set with a CDP `Emulation.setDeviceMetricsOverride` and `--hide-scrollbars`; both are required for recorded `width` and `viewport_coverage` to mean the same thing as in earlier runs, so do not drop them for `--window-size`.
- Keep polite delays between page loads (`--page-delay` plus random jitter). Do not add parallelism within a single process; scale across separate processes with `--shard`, or `--jobs N`, which spawns those shards for you and merges their output. The `--jobs` parent never crawls.
- Do not add dependencies beyond `selenium` and the Python standard library without asking. (Playwright is no longer used by the crawler; `docs/` rendering still uses it, which is why `requirements.txt` mentions it in a comment.)

## Setup and commands

```bash
pip install -r requirements.txt
# Chrome and a matching chromedriver must be on PATH (Selenium Manager fetches one if not).

python src/find_forms.py inputs/sites.txt --out outputs/results                   # default: desktop only, up to 3 pages/site
python src/find_forms.py inputs/sites.txt --limit 20                       # quick pilot
python src/find_forms.py inputs/tranco.csv --explore --max-pages 5         # catalog more page types per site
python src/find_forms.py inputs/sites.txt --jobs 4                          # 4 shard processes + auto-merge
python src/find_forms.py inputs/sites.txt --shard 0/4                      # or drive the shards yourself
python src/find_forms.py --merge --out outputs/results                     # fold orphaned *.part* files in
python src/find_forms.py inputs/sites.txt --headless                      # hide the browser (default: visible window)
```

Rerunning the same command resumes; sites listed in `outputs/results/sites_done.txt` are skipped.

## Architecture

Selenium 4 (Chrome via chromedriver), Python 3.8+. Run from the repo root. `src/find_forms.py` is the entry point (module docstring, `parse_args()`, `main()`); everything else lives in `src/crawler/`:

| Module | Contents |
|---|---|
| `config.py` | timing budgets, `DETECT_PATTERNS` (form-detection keywords), `LINK_TIERS`, `STOP`, `FORM_FIELDS`/`PAGE_FIELDS` |
| `js.py` | `DETECT_JS`, `LINKS_JS`, `SCROLL_JS`, `EXIT_INTENT_JS` |
| `util.py` | `now`, `slug`, `same_site`, `load_sites`, `form_signature`, `link_tier`, ... |
| `browser.py` | `make_driver()`, `detect_options()`, `rank_links()`, `capture()`, `scan_page()`, `detect_in_all_frames()` |
| `crawl.py` | `crawl_site()` |
| `output.py` | `Output`, `read_done()`, `merge_parts()` |
| `jobs.py` | `run_jobs()` (relaunches `sys.argv[0]` per shard), `install_stop_handler()` |
 Site lists live in `inputs/`; misc helper scripts (cleanup, analysis, conversions; not part of the crawler) live in `scripts/`; each run gets its own directory under `outputs/` (git-ignored), e.g. `outputs/news_sites/`.

- `main()`: loads the site list, applies `--limit` **then** `--shard` (so `--jobs`/`--shard` only divide the same total work), skips done sites, (under `--jobs` the children get a hidden `--shard-todo` and split only the sites not done yet, so a resumed run keeps all N browsers busy; a manual `--shard` keeps the fixed split by position, since shards on other machines cannot see each other's `sites_done`), and catches per-site errors so the run continues. It no longer launches or holds a browser: each site's driver is created and quit inside `crawl_site()`. A `SiteWatchdog` thread (`jobs.py`) kills the process's Chromium when one site exceeds its time limit (`--site-time-limit`, default `SITE_TIME_LIMIT_PER_PAGE_S` × `--max-pages`); the stuck call then fails, the site is logged as `site_timeout`, and the next site gets a fresh browser. The thread is a timer, not a second crawler: it never touches Playwright.
- `crawl_site()`: per site, opens its own Chrome via `make_driver()` (Selenium has no cheap per-context isolation, so one driver per site is what keeps each site's profile clean), scans the landing page, and follows links from `rank_links()` up to `--max-pages`, stopping at the first page with a form unless `--explore` is set.
- `run_jobs()`: with `--jobs N`, supervises N `--shard i/N` child processes, pumps their output through a single-threaded `selectors` loop, and calls `merge_parts()` when they exit (or the `merge` callback a script passes in; `scripts/collect_tier1_keywords.py --jobs` reuses it this way). It never drives a browser itself.
- `merge_parts()`: folds `*.part<N>.*` into the canonical outputs, deduplicating on `(site, form_sig)`. Idempotent, and it keeps the parts, so the canonical files are a derived view that can always be rebuilt.
- Shutdown is cooperative: SIGINT sets `STOP` and the crawl ends at the next page boundary, so rows are flushed and the driver is quit rather than left orphaned. (Under Playwright this was mandatory for a second reason, now gone: an interrupt landing inside a sync call corrupted its greenlet dispatch and the process span forever.)
- `scan_page()`: loads a page, then runs detection after four phases in order: `on_load`, `after_delay` (`--popup-wait`), `after_scroll` (`SCROLL_JS`), and `after_exit_intent` (`simulate_exit_intent()`). Detection runs in every frame. New forms are captured and written immediately.
- `DETECT_JS`: JavaScript evaluated in each frame. Implements top-down detection (`<form>` elements with a visible email input) and bottom-up detection (walk up from an email input outside any form to the first container holding a submit-like element), searches open shadow DOM, ranks candidates, tags each with `data-ux-form-id`, and returns metadata.
- `rank_links()` / `link_tier()`: score same-site visible links using `LINK_TIERS` (the paper's Table 1, plus a signup-address group added 2026-10-11) and skip `LINK_BLACKLIST` text matches, `URL_BLACKLIST` address matches and file links.
- `capture()`: saves outerHTML, an element screenshot, and an in-context viewport screenshot.
- `form_signature()`: deduplicates forms. The `seen` set persists across pages and phases within a site, so a form is recorded once with the first phase it appeared in.
- `Output`: appends to CSV/JSONL and flushes after every row.

### Ranking rules (from the paper, in priority order)

1. Highest effective z-index first (walk ancestors until a non-`auto` value). Ties broken by modal/dialog hints.
2. Login-like forms rank lower: a password field, "log in"/"sign in" as a word in the form's HTML or in the plain text around it, or a login/account page address (see `DETECT_PATTERNS["login"]` and `["login_url"]`).
3. Forms with more fields rank higher.

### Intentional differences from the paper

Bottom-up runs on every page rather than only as a fallback; every candidate is recorded rather than just the best; detection is phased to record triggers; shadow DOM is searched; links are navigated rather than clicked; the paper's `/2017` URL keyword is generalized to `/20\d\d/`; the paper's tier 1 link keyword "subscribe" is shortened to the stem "subscri" (2026-10-11) so links reading "subscription(s)" or "subscriber" also rank first, after a keyword collection on 146 known signup pages (forms found on 118; button and form text analysed for 108–115 of them) showed "update my subscriptions" going unmatched. The data, analysis and every accepted and rejected keyword are in `docs/link-keywords.md`. The same collection's button texts extended `SUBMIT_HINT` in `DETECT_JS` (the words that make a `<div>`/`<span>`/link count as a submit button in bottom-up detection) with `next`, `save` and the stems `suscr` (Spanish) and `inscr` (Portuguese/French). Its signup-specific button wordings were also added to the tier 2 link keywords: `suscr`, `inscr`, `count me in`, `send me`. Generic button words (`submit`, `next`, `save`, `send`, `get`) were deliberately not added to any link tier, because they match ordinary links such as "Next page".

History: from 2026-10-07 to 2026-10-08 the crawler pre-screened pages with a plain HTTP GET and recorded some forms from served markup without a browser visit (`source=http`), with link triage and a `--calibrate` sample. That was removed on 2026-10-08; every row is again browser-rendered, and the measurement regime is the pre-2026-10-07 one. Output from runs in that window may contain `source=http` rows (no screenshot, layout measurements or popup observation) and `ok_http`/`http_dead`/`offsite_redirect` page statuses; exclude or re-crawl those rows.

Also 2026-10-08: robots.txt is no longer fetched or honoured; earlier runs skipped disallowed sites and links (`robots_disallowed` in `pages.csv`), so their site coverage differs.

Also 2026-10-11: `login_like` was tightened and widened. The paper's "log in"/"sign in" text check matched inside other words, notably "By signing up", so newsletter forms were marked login-like (3 of the 5 `login_like` rows in the `isec_lab_sample` pilot). It now needs a word start and no following "g". Two signals were added for two-step logins such as `auth.hulu.com/web/create-account/enter-email`, which show only an email box and "Continue" because the password box is on the next screen: the login words in the plain text around the form (links and buttons excluded), and a login/account page address. `login_like` values are therefore not comparable with runs before this date.

Also 2026-10-21: the crawler was moved from Playwright to Selenium at the project lead's request. The measurement regime is unchanged and was verified: on the local fixture both drivers return byte-identical rows for all 7 forms (placement, ranking, field types, text, widths, coverage), once the viewport is forced through CDP and scrollbars are hidden. Two mechanics differ. `http_status` now comes from `PerformanceNavigationTiming.responseStatus` in the page rather than the response object. Media is blocked by URL pattern (`BLOCKED_URL_PATTERNS`) instead of by resource type, so audio or video served from an address without a file extension now loads where it used to be dropped; this costs bandwidth, not data.

Keep this list current if the method changes, since it belongs in the methods section.

## Outputs (`--out`, default `outputs/results/`)

- `forms.csv` / `forms.jsonl`: one row per unique form per site. Columns are defined in `FORM_FIELDS`.
- `pages.csv`: one row per page visit. Statuses: `ok`, `load_error`, `site_error`, `site_timeout` (over its time limit; browser killed; since 2026-10-11) (`robots_disallowed` appears only in runs before 2026-10-08).
- `*.part<N>.*`: per-shard output, written whenever `--shard` is set (including by `--jobs`). `--merge` folds them into the canonical files. Parts are kept after merging, so the canonical files are a derived view that can always be rebuilt; `--clean-parts` deletes them.
- `run.log`: everything printed, with a timestamp and level per line: the command, each site with its time and new-form count, a summary, and the total run time (also logged after Ctrl-C). Appended to on every run. A shard writes `run.part<N>.log`; under `--jobs` the parent's `run.log` also holds every shard's lines, prefixed `[s<N>]`. All modules log through the `crawler` logger, set up by `setup_logging()` in `crawler/util.py`; use it instead of `print()`.
- `screens/<site>/`: `<sig>.png` and `<sig>_context.png`.
- `html/<site>/`: `<sig>.html`.

Schema stability matters because downstream analysis depends on it. Add new columns to the **end** of `FORM_FIELDS`, never rename or reorder existing ones, and note changes here.

Schema changes so far:

- 2026-10-13: `has_privacy_link` was **removed** from `FORM_FIELDS` at the project lead's request, a third deliberate exception to the append-only rule, together with its `privacy` pattern in `DETECT_PATTERNS`. The 10 columns after it (`consent_text_hint` through `field_names`) each moved one position left. `forms.csv` files written before this date are not column-compatible; `Output` refuses to append to them, so use a fresh `--out` directory.
- 2026-10-10: `field_names` was **appended to the end** of `FORM_FIELDS`: one entry per field, in the same order as `field_types`, holding the field's `name` attribute, else its `id`, else empty (a radio group gets the group's name). Example: `field_types` = `email | text | checkbox`, `field_names` = `EMAIL | FNAME | gdpr_consent`.
- 2026-10-10: `axe_violations` was **removed** from `FORM_FIELDS` at the project lead's request, a second deliberate exception to the append-only rule. `screenshot`, `context_screenshot`, `html_file`, `form_text` and `source` each moved one position left. `forms.csv` files written before this date are not column-compatible: use a fresh `--out` directory. `Output` now refuses to append to a CSV whose header differs from the current schema, so mixing versions fails loudly instead of misaligning columns.
- 2026-10-08: no column change. `--axe` was removed (its column stayed, empty, until 2026-10-10); pages also now run under their own Content Security Policy (`bypass_csp` was only there for axe injection). `source` is kept (append-only rule) but is now always `browser`; `calibration.csv` is no longer written.
- 2026-10-07: `source` (`browser` | `http`) was **appended to the end** of `FORM_FIELDS` so rows read from markup are distinguishable from rendered ones. This follows the append-only rule — nothing was renamed or reordered — but earlier `forms.csv` files have one fewer column, so a run after this change needs a fresh `--out` directory.
- 2026-10-06: mobile crawling was removed, so the `device` column was dropped from `FORM_FIELDS` and `PAGE_FIELDS`, and the `<device>_` prefix was dropped from screenshot and HTML filenames. This was a deliberate one-time exception to the append-only rule, taken while only a two-site pilot existed. Output written before this date is not column-compatible and must be kept in a separate `--out` directory. The append-only rule still governs every future change.

`source` is always `browser` in current output. In runs from 2026-10-07 it can be `http`, meaning the row was read from served markup and has no screenshot or rendered-layout columns; filter on `source = 'browser'` for those runs.

Several columns are heuristics, not ground truth: `placement_guess`, `modal_hint`, `login_like`, `consent_text_hint`, `heading`, `other_clickable_text`. They are starting points for manual coding and must be spot-checked against screenshots.

## Conventions

- Keep the JavaScript in raw strings (`r"""..."""`) so regex backslashes survive. The page scripts are arrow functions; Selenium's `execute_script` runs statements, so `browser.py` wraps them with `_call()` / `_call_async()` (the async one is for `SCROLL_JS`, via `execute_async_script`). Keep them as arrow functions so both wrappers keep working.
- Detection keyword patterns live in `DETECT_PATTERNS` in `crawler/config.py` (moved there from the top of `DETECT_JS` on 2026-10-11, unchanged). They are passed into the page through `detect_options()` in `browser.py` and compiled there as case-insensitive JavaScript regexes, so write them in syntax that means the same in Python and JavaScript. Thresholds (sizes, depths, counts) stay in `DETECT_JS`. Change patterns in `config.py`, not inline, and record the change here.
- Timing budgets are constants in `crawler/config.py`: `LOAD_SETTLE_MS` (3000, replaces a 10s `networkidle` wait), `PAINT_SETTLE_MS` (1000, the settle before `on_load` detection — lowering it shifts `first_seen_phase`), `SCROLL_BUDGET_MS` (5000), `DETECT_BUDGET_MS` (4000), `MAX_SHADOW_SCAN` (15000), plus `BLOCKED_URL_PATTERNS` (audio/video addresses only — never block images, which are the deliverable, fonts, which change layout metrics, or third-party scripts, which host many signup embeds), `MAX_JOBS` (8), `SHUTDOWN_GRACE` (90), `SITE_TIME_LIMIT_PER_PAGE_S` (120) and `SCRIPT_TIMEOUT_S` (30).
- Catch `SeErr` (Selenium's `WebDriverException`, the base class for every driver error including timeouts) around browser operations; one failing page or frame must never stop a crawl.
- Keep the module docstring's usage and output sections in sync with the code.
- `docs/crawl-flow.md` is the step-by-step description of a crawl (phases, timings, constants). Update it whenever the flow, a phase, or a timing constant changes.

## Testing

Test changes against a local fixture site served with `python -m http.server`, never against real sites first. The fixture should include at least: a footer `<form>` with a labeled email input, a delayed `position: fixed` modal with a placeholder-only email field, a prechecked consent checkbox, and confirmshaming dismiss text; an exit-intent sticky bar; a `<div>`-based form with no `<form>` tag; a shadow DOM widget; a signup form inside an iframe; a header login form (should rank last and be `login_like`); a search input mentioning "email" (should not be detected); and an "unsubscribe" link (should not be followed).

After a test run, confirm in the server log that no POST or form-action requests were made, and spot-check screenshots in `outputs/<run>/screens/`.

## Known limitations / backlog

- Cookie consent banners can suppress or delay newsletter popups, especially on EU sites. Handling them would require clicking, which is currently out of scope.
- Headless Chromium can be detected and served different content, so the browser is visible by default (since 2026-10-11; one window per shard under `--jobs`). `--headless` hides it, e.g. on a machine without a display; compare a few sites both ways before a large headless run.
- A browsered page takes roughly 15–20 seconds; the deliberate waits (`--popup-wait`, exit intent) dominate.
- Closed shadow roots, canvas-rendered UIs, and forms behind CAPTCHAs are not detected.
- A page whose JavaScript never lets go is bounded in two places since the Selenium switch: `SCRIPT_TIMEOUT_S` caps every `execute_script`, which Playwright could not do, and `SiteWatchdog` still backs it up for a page that wedges during load, where no script call is in flight. The watchdog kills Chrome and chromedriver found through `/proc`, so it works on **Linux only**; elsewhere it logs a warning and the site can still hang. A timed-out site gets no form rows for the page it was stuck on.
- `--jobs` is capped at 8 by RAM, not CPU: roughly 500 MB per shard, spiking to ~800 MB on iframe-heavy pages.
- The post-submit experience (confirmation flow, double opt-in, welcome email) is out of scope for the crawler and is studied manually on a small subsample using a dedicated research email address.

## Planned: form submission (not built; raised 2026-10-14)

The project lead intends to add actual form submission later, to study what happens
after signup. Nothing is implemented, and the hard rules above still hold until it is:
the crawler stays detection-only.

Decisions to settle **before** writing any of it:

- **Shape.** A separate module behind an explicit opt-in flag, never a default and never
  a change to `scan_page()` (see the hard rule). Detection-only must stay the path a run
  takes unless that flag is passed, so an ordinary crawl can never submit by accident.
- **The submit guard is gone.** `SUBMIT_GUARD_JS` cancelled every submit event as a
  backstop; it was removed on 2026-10-08 at the project lead's request. Nothing now
  prevents a submission except that no code touches forms. Decide whether the guard
  comes back for detection-only runs (installed unless the submit flag is passed), so
  the two modes are separated by more than a code path.
- **Identity.** Which research email address, and whether to use a per-site alias
  (`site@domain` or a catch-all) so a later leak or sale can be traced to the site that
  received it. This is also what makes the post-submit study above measurable.
- **Approval.** Submitting creates real subscriptions and sometimes real accounts on
  real sites, which detection-only crawling does not. Confirm whether ethics/IRB
  sign-off is needed, and record the answer here.
- **Output.** What a submission attempt records (fields filled, response, confirmation
  page, resulting URL) and where: new columns appended to the **end** of `FORM_FIELDS`,
  or a separate `submissions.csv`. The append-only rule governs either choice.
- **Pacing.** Submission is a write, so per-site rate limits should be stricter than
  `--page-delay`, and a site should be submitted to at most once.
