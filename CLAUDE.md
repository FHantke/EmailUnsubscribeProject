# CLAUDE.md

## Project overview

Academic research project studying the design of email subscription forms (newsletter signups, popups, sticky bars, footer forms) across hundreds to thousands of websites. The core tool is `find_forms.py`, a Selenium crawler that discovers signup forms and records screenshots, HTML, and UX metadata for later manual coding and analysis.

Form-detection logic is adapted from Englehardt, Han & Narayanan (2018), "I never signed up for this! Privacy implications of email tracking," *Proceedings on Privacy Enhancing Technologies* 2018(1):109–126, Section 3 and Appendix 10.1. Cite this paper when describing the method.

## Hard rules

- **Crawling is detection only.** A crawl must never type into, fill, or submit forms, and must never click elements on the page. Navigation happens by `driver.get()` on link URLs. Keep it that way: do not add form-filling, clicking, or submission to `scan_page()`, `crawl_site()` or anything they call.
- **Submission is a separate phase**, in `crawler/submit.py`, reached only by `--submit` (built 2026-10-23 at the project lead's request). It is the one module that types or clicks, it never runs during a crawl, and it works from forms already in the database rather than from a live scan. Everything it needs is behind `opts.withElements` in `DETECT_JS`, off by default. If it ever needs to run inside a crawl, that is a decision to take explicitly, not a refactor.
- robots.txt is **not** consulted (removed 2026-10-08 at the project lead's decision). Per-site politeness rests on the page delays below and on `--max-pages`. Report this in the methods section.
- **Browser only.** Every request comes from Chromium page loads; there are no requests outside the browser. Do not reintroduce plain-HTTP pre-screening or recording forms from served markup (removed 2026-10-08).
- **Selenium**, since 2026-10-21 (was Playwright). Chrome is driven through chromedriver, one driver per site. The exact viewport is set with a CDP `Emulation.setDeviceMetricsOverride` and `--hide-scrollbars`; both are required for recorded `width` and `viewport_coverage` to mean the same thing as in earlier runs, so do not drop them for `--window-size`.
- Keep polite delays between page loads (`--page-delay` plus random jitter). Do not add parallelism within a single process; scale across separate processes with `--shard`, or `--jobs N`, which spawns those shards for you and merges their output. The `--jobs` parent never crawls.
- Do not add dependencies beyond `selenium`, `undetected-chromedriver`, `SQLAlchemy` and the Python standard library without asking. SQLAlchemy is how `DATABASE_URL` in `config.py` can name a database other than SQLite without a code change. `undetected-chromedriver` is the default driver since 2026-10-22; it is imported inside `_stealth_driver()`, so `--no-stealth` still runs without it installed. (Playwright is no longer used by the crawler; `docs/` rendering still uses it, which is why `requirements.txt` mentions it in a comment.)

## Setup and commands

```bash
pip install -r requirements.txt
# Chrome and a matching chromedriver must be on PATH (Selenium Manager fetches one if not).
# Or run it containerised, with a virtual screen to watch over VNC: see docker/README.md.

python src/find_forms.py inputs/sites.txt --out outputs/results                   # default: desktop only, up to 3 pages/site
python src/find_forms.py inputs/sites.txt --limit 20                       # quick pilot
python src/find_forms.py inputs/tranco.csv --explore --max-pages 5         # catalog more page types per site
python src/find_forms.py inputs/sites.txt --jobs 4                          # 4 shard processes + auto-merge
python src/find_forms.py inputs/sites.txt --shard 0/4                      # or drive the shards yourself
python src/find_forms.py --export-csv                                     # forms.csv + pages.csv, every run
python src/find_forms.py inputs/sites.txt --export-csv --out outputs/results  # just that run
python src/find_forms.py --merge --out outputs/results                     # fold in a crawl.db from another machine
python src/find_forms.py inputs/sites.txt --headless                      # hide the browser (default: visible window)
python src/find_forms.py inputs/sites.txt --no-stealth                    # plain Selenium (default: undetected_chromedriver)

# Submission: a separate phase over a run that has already been crawled.
python src/find_forms.py --submit --out outputs/run6 \
    --submit-email 'study+{site}@gmail.com' --submit-dry-run             # fill and photograph, never click
python src/find_forms.py --submit --out outputs/run6 \
    --submit-email 'study+{site}@gmail.com' --submit-limit 5             # really sign up, to 5 sites
```

Rerunning the same command resumes; sites already in the database's `sites_done` table for that run are skipped.

## Architecture

Selenium 4 (Chrome via chromedriver), Python 3.8+. Run from the repo root. `src/find_forms.py` is the entry point (module docstring, `parse_args()`, `main()`); everything else lives in `src/crawler/`:

| Module | Contents |
|---|---|
| `config.py` | timing budgets, `DETECT_PATTERNS` (form-detection keywords), `FORM_TYPES` (form classification), `LINK_TIERS`, `STOP`, `DATABASE_URL`, `FORM_FIELDS`/`PAGE_FIELDS` |
| `js.py` | `DETECT_JS`, `FIELD_INFO_JS`, `OBSERVE_JS`, `LINKS_JS`, `SCROLL_JS`, `EXIT_INTENT_JS` — measurement only since 2026-10-30 |
| `classify.py` | `form_type()`, `vendor()`, `rank()`, `annotate()` — the rules that decide what a form is, in Python so they can be tested and replayed |
| `util.py` | `now`, `slug`, `same_site`, `load_sites`, `form_signature`, `link_tier`, ... |
| `browser.py` | `make_driver()` (`_stealth_driver()` for `--stealth`), `detect_options()`, `rank_links()`, `capture()`, `scan_page()`, `detect_in_all_frames()` |
| `crawl.py` | `crawl_site()` |
| `submit.py` | `submit_run()`, `_find_target()`, `_fill()`, `_freeze()`, `_submit_one()` — `--submit` only; the one module that types or clicks |
| `output.py` | `Output` (SQLAlchemy Core), `database_url()`, `build_metadata()`, `ensure_schema()`, `record_run()`, `read_done()`, `merge_parts()`, `export_csv()` |
| `jobs.py` | `run_jobs()` (relaunches `sys.argv[0]` per shard), `install_stop_handler()` |
 Site lists live in `inputs/`; misc helper scripts (cleanup, analysis, conversions; not part of the crawler) live in `scripts/`; each run gets its own directory under `outputs/` (git-ignored), e.g. `outputs/news_sites/`.

- `main()`: loads the site list, applies `--limit` **then** `--shard` (so `--jobs`/`--shard` only divide the same total work), skips done sites, (under `--jobs` the children get a hidden `--shard-todo` and split only the sites not done yet, so a resumed run keeps all N browsers busy; a manual `--shard` keeps the fixed split by position, since shards on other machines cannot see each other's `sites_done`), and catches per-site errors so the run continues. It no longer launches or holds a browser: each site's driver is created and quit inside `crawl_site()`. A `SiteWatchdog` thread (`jobs.py`) kills the process's Chromium when one site exceeds its time limit (`--site-time-limit`, default `SITE_TIME_LIMIT_PER_PAGE_S` × `--max-pages`); the stuck call then fails, the site is logged as `site_timeout`, and the next site gets a fresh browser. The thread is a timer, not a second crawler: it never touches Playwright.
- `crawl_site()`: per site, opens its own Chrome via `make_driver()` (Selenium has no cheap per-context isolation, so one driver per site is what keeps each site's profile clean), scans the landing page, and follows links from `rank_links()` up to `--max-pages`, stopping at the first page with a form unless `--explore` is set.
- `run_jobs()`: with `--jobs N`, supervises N `--shard i/N` child processes, pumps their output through a single-threaded `selectors` loop, and calls `merge_parts()` when they exit (or the `merge` callback a script passes in; `scripts/collect_tier1_keywords.py --jobs` reuses it this way). It never drives a browser itself.
- `merge_parts()`: folds other `*.db` files in `--out` into `crawl.db`, for shards run on another machine. Idempotent, and it keeps the source databases.
- Shutdown is cooperative: SIGINT sets `STOP` and the crawl ends at the next page boundary, so rows are flushed and the driver is quit rather than left orphaned. (Under Playwright this was mandatory for a second reason, now gone: an interrupt landing inside a sync call corrupted its greenlet dispatch and the process span forever.)
- `scan_page()`: loads a page, then runs detection after four phases in order: `on_load`, `after_delay` (`--popup-wait`), `after_scroll` (`SCROLL_JS`), and `after_exit_intent` (`simulate_exit_intent()`). Detection runs in every frame. New forms are captured and written immediately.
- `DETECT_JS`: JavaScript evaluated in each frame. Implements top-down detection (`<form>` elements with a visible email input) and bottom-up detection (walk up from an email input outside any form to the first container holding a submit-like element), searches open shadow DOM, tags each candidate with `data-ux-form-id`, and returns metadata. **It measures; it does not judge** (since 2026-10-30): what a form *is*, and how the candidates rank, is decided in `classify.py`.
- `classify.py`: `annotate()` is called by `_scan_frame()` on the list `DETECT_JS` returns, and sets `form_type` and `vendor`, then `rank()` orders the candidates by the paper's rules and numbers them. It works from three fields `DETECT_JS` reports for this purpose and which are dropped afterwards: `form_html` (the form's markup with `<option>` lists stripped, 50 KB), `near_text` (the wording around it, links and buttons excluded), and `input_types` (every input type present, **including hidden and invisible ones**, so a password box counts whether or not it is on screen).
- `rank_links()` / `link_tier()`: score same-site visible links using `LINK_TIERS` (the paper's Table 1, plus a signup-address group added 2026-10-11) and skip `LINK_BLACKLIST` text matches, `URL_BLACKLIST` address matches and file links.
- `capture()`: saves outerHTML, an element screenshot, and an in-context viewport screenshot.
- `form_signature()`: deduplicates forms. The `seen` set persists across pages and phases within a site, so a form is recorded once with the first phase it appeared in.
- `Output`: inserts into the shared database, tagging every row with the run, and commits after every row. `record_run()` notes the run itself, called once from `main()` so a `--jobs` run appears even though its parent writes no rows. `ensure_schema()` adds any column appended to `FORM_FIELDS` to an existing database (`ALTER TABLE ADD COLUMN`), so an older run keeps working with NULL for it; a column *removed* from the config cannot be reconciled and the file is refused, which is the database equivalent of the old header check. The tables themselves are built from `FORM_FIELDS`/`PAGE_FIELDS` as SQLAlchemy `Table` objects, so they are dialect-agnostic and duplicates are caught as `IntegrityError` rather than with SQLite-only syntax.

### Ranking rules (from the paper, in priority order)

1. Highest effective z-index first (walk ancestors until a non-`auto` value). Ties broken by modal/dialog hints.
2. Forms whose `form_type` is not `subscription` rank lower. `FORM_TYPES` in `config.py` classifies each form; first rule that matches wins, and each rule may carry an `unless` blacklist that cancels a match. The five other types (`login`, `checkout`, `comment`, `contact`, `search`) are tried first, then `subscription`, which has its own positive rules rather than being a leftover bin. A form matching nothing is `unknown` (`DEFAULT_FORM_TYPE`), which means "not recognised, code it by hand" — about 10% of forms collected so far. `TARGET_FORM_TYPE` names the one the study is about: `subscription`.
3. Forms with more fields rank higher.

### Intentional differences from the paper

Bottom-up runs on every page rather than only as a fallback; every candidate is recorded rather than just the best; detection is phased to record triggers; shadow DOM is searched; links are navigated rather than clicked; the paper's `/2017` URL keyword is generalized to `/20\d\d/`; the paper's tier 1 link keyword "subscribe" is shortened to the stem "subscri" (2026-10-11) so links reading "subscription(s)" or "subscriber" also rank first, after a keyword collection on 146 known signup pages (forms found on 118; button and form text analysed for 108–115 of them) showed "update my subscriptions" going unmatched. The data, analysis and every accepted and rejected keyword are in `docs/link-keywords.md`. The same collection's button texts extended `SUBMIT_HINT` in `DETECT_JS` (the words that make a `<div>`/`<span>`/link count as a submit button in bottom-up detection) with `next`, `save` and the stems `suscr` (Spanish) and `inscr` (Portuguese/French). Its signup-specific button wordings were also added to the tier 2 link keywords: `suscr`, `inscr`, `count me in`, `send me`. Generic button words (`submit`, `next`, `save`, `send`, `get`) were deliberately not added to any link tier, because they match ordinary links such as "Next page".

History: from 2026-10-07 to 2026-10-08 the crawler pre-screened pages with a plain HTTP GET and recorded some forms from served markup without a browser visit (`source=http`), with link triage and a `--calibrate` sample. That was removed on 2026-10-08; every row is again browser-rendered, and the measurement regime is the pre-2026-10-07 one. Output from runs in that window may contain `source=http` rows (no screenshot, layout measurements or popup observation) and `ok_http`/`http_dead`/`offsite_redirect` page statuses; exclude or re-crawl those rows.

Also 2026-10-08: robots.txt is no longer fetched or honoured; earlier runs skipped disallowed sites and links (`robots_disallowed` in `pages.csv`), so their site coverage differs.

Also 2026-10-11: `login_like` was tightened and widened. The paper's "log in"/"sign in" text check matched inside other words, notably "By signing up", so newsletter forms were marked login-like (3 of the 5 `login_like` rows in the `isec_lab_sample` pilot). It now needs a word start and no following "g". Two signals were added for two-step logins such as `auth.hulu.com/web/create-account/enter-email`, which show only an email box and "Continue" because the password box is on the next screen: the login words in the plain text around the form (links and buttons excluded), and a login/account page address. `login_like` values are therefore not comparable with runs before this date.

Also 2026-10-21: the crawler was moved from Playwright to Selenium at the project lead's request. The measurement regime is unchanged and was verified: on the local fixture both drivers return byte-identical rows for all 7 forms (placement, ranking, field types, text, widths, coverage), once the viewport is forced through CDP and scrollbars are hidden. Two mechanics differ. `http_status` now comes from `PerformanceNavigationTiming.responseStatus` in the page rather than the response object. Media is blocked by URL pattern (`BLOCKED_URL_PATTERNS`) instead of by resource type, so audio or video served from an address without a file extension now loads where it used to be dropped; this costs bandwidth, not data.

Also 2026-10-22: the boolean `login_like` became a six-way `form_type`, because the crawler records every form with an email box and a good number of those are not signups. A scan of the 116 forms collected so far found roughly 26 login/account, 8 checkout and 10 contact forms among them, which is what the type list is drawn from. Rules are data, in `FORM_TYPES`, each with detect patterns and an optional `unless` blacklist. The `login` rules are unchanged from `login_like`, so that classification is comparable across the change; the other types are new and have no equivalent in earlier runs.

`subscription`, the target category, is named for what the study is about and recognised by its own rules (newsletter/subscribe wording, and the embed markup of Mailchimp, Klaviyo, Substack and similar), not by elimination: a form that matches nothing is `unknown`, so quote requests, registrations and gated downloads no longer inflate it. Replaying the rules over the 166 forms collected so far gives roughly 105 subscription, 29 login, 8 contact, 4 search, 3 checkout and 17 unknown; the unknowns are mostly non-English buttons, empty headings and registration forms, and are a manual-coding queue rather than a residual category.

Also 2026-10-23: a spot-check of all 81 forms in the `isec_sample_run5_undetect` sample against their screenshots found 4 subscription forms given another type, and no subscription false positives beyond one judgement call (a Google for Education sales form carrying a newsletter opt-in). All four came from the same mechanism: the five non-subscription types are tested before `subscription` and read the text *around* the form, which on a real page includes site chrome — "Sign in" in a header, "checkout" in cart links. `login` and `checkout` gained the `unless` blacklist that `contact` and `search` already had, and a `fields` match (a password box) now overrides `unless`, since that is hard evidence where wording is not. Replayed over those 81: 5 rows change, all corrections, with 46 subscription rows rather than 44. A bare `join` was tried for the remaining miss and rejected — it typed a job application ("joining our team", a `join-us` class) as a subscription.

Also 2026-10-22: the crawler drives Chrome through `undetected_chromedriver` by default, so that sites which serve automated browsers different content (or block them) are crawled as an ordinary visitor would see them. The measurements are unaffected — verified identical with and without it on the fixture — so data collected before and after this change is comparable. `--no-stealth` reproduces the earlier plain-Selenium behaviour.

Also 2026-10-23: output moved from CSV/JSONL to a single database (SQLite at `outputs/crawl.db` by default, reached through SQLAlchemy so `DATABASE_URL` in `config.py` can name another one) shared by every run, each row tagged with the run's name. No column changed and no value changed; `--export-csv` reproduces the old files byte-for-byte in layout, with lists flattened back to `a | b`. The part-file and merge machinery is gone for same-machine runs, so a `--jobs` crawl no longer has a window in which its rows exist only in unmerged parts.

Also 2026-10-30: `isSubmitLike` in `DETECT_JS` was corrected in three ways, after `royalcaribbean.com` was found recording its **country picker** as the form's submit button. **This changes `submit_text`, and `form_signature()` is built partly from `submit_text`, so affected forms get a new `form_sig`.** No database existed yet when this landed — every run to date is CSV-era — so nothing stored was invalidated; a CSV run compared against a newer one will differ on these columns.

1. **A menu-opener is never a submit button.** Anything with `aria-expanded`, or `aria-haspopup` other than `false`, is rejected whatever its tag. Royal Caribbean's picker is `<button type="button" aria-haspopup="listbox">`, and the `tag === 'BUTTON'` rule accepted any `<button>` outright.
2. **The `children.length > 2` cap no longer applies to an element that declares itself a button** (`type="submit"` or `role="button"`). That cap exists to stop an anonymous wrapper `<div>` being read as a button; it was throwing away real ones. Royal Caribbean's submit is `<a role="button" type="submit">` holding a spinner `<div>`, a `<span>Sign Up</span>` and an `<svg>` icon — three children, an ordinary button. The text tests after it (submit wording, ≤40 characters, visible) are unchanged, so a large element that calls itself a button is still rejected, by those instead.
3. **A button's own parts no longer count as separate buttons.** A label `<span>` inside a button carries the same words and inherits `cursor: pointer`, so it qualified on its own; candidates contained by another candidate are now dropped. This was the widest of the three: **53 of 262** recorded rows had a repeated `submit_text` entry.

Effect on earlier data: `submit_text` may gain a value where a declared button was being rejected (6 of 114 distinct forms had none at all), lose a wrong one (2 forms had a picker), and lose duplicates (53 rows). Bottom-up detection also depends on `isSubmitLike` to decide which container is the form, so a form found bottom-up may now resolve to a different container — spot-check before pooling runs from either side of this date.

Also 2026-10-30: five changes drawn from another study's capture module (an RFC 8058 crawler the project lead shared). **Three change recorded values**; the rest are new columns. That crawler also decides a form's *eligibility* at capture time, in a rule chain separate from its type, and records `reject_reason` for every form it will not use. That part was built and then **removed the same day at the project lead's request** — classification stays the only judgement detection makes, and `--submit` goes on deciding what it can fill at fill time, recording `skipped_<reason>` in `submissions`. If it comes back, it belongs beside `formType()` in `js.py` with its patterns in `SUBMIT_REFUSE`, which is where it was.

1. **`form_signature()` is structural** (measurement change). It was frame host + detection method + email field attributes + **submit text** + field count + heading. It is now frame host + the form's **action** + its fields sorted by name and type + heading. The button's text had to go: on `royalcaribbean.com` it held the visitor's country, so the same form hashed differently depending on where it was crawled from. Sorting means re-rendering fields in another order no longer makes a new form. The heading stays, or a site's footer form and its popup — often identical in fields and action — would collapse into one row.
2. **A dropdown's options are no longer the form's wording** (measurement change). `innerText` includes every `<option>`, so a country select spent the whole 600-character `form_text` budget on country names, and `form_type` matching got a vote from them — a "Reason for enquiry" dropdown reads as a contact form. Options are now subtracted from `form_text`, skipped by `plainText()`, and stripped from the HTML the form-type rules match. Nothing else about `innerText` changes, so hidden text is still left out.
3. **The form's `action` is read** (measurement change, small). It joins the page address that `FORM_TYPES` url rules match, so a login form sitting on a homepage is caught by posting to `/account/login`. It is also recorded as `form_action`.
4. **`vendor`** records the email platform behind the form, from `VENDOR_HINTS` — 23 platforms. The patterns were already there as classification evidence and the answer was being thrown away.
5. **`captcha_type` / `captcha_visible`** record a CAPTCHA widget inside the form and whether it needs the visitor to act. 20 of the 81 forms in the run5 sample carried CAPTCHA markup with nowhere to put it. **`field_required`** records, per field in `field_types` order, whether the form insists on it.

Signatures therefore differ either side of this date, as do `form_text` and `form_type` for forms containing a dropdown. No database existed when this landed, so nothing stored was invalidated.

Also 2026-10-30: the form-type, vendor and ranking rules moved out of `DETECT_JS` into `crawler/classify.py`. **No recorded value changes** — verified by running the fixture before and after and comparing all 41 columns of all 19 forms, which were identical. The split is by who needs a rendered page: anything using `getComputedStyle`, a bounding box, `innerText` or a shadow root stays in JavaScript, and what only reads markup and wording is Python.

Three things stay in `js.py` on purpose. CAPTCHA detection walks the DOM by selector and would need an HTML parser in Python, which the project deliberately does not ship. `consent_text_hint` reads the text *including* links, because consent wording is usually inside one, whereas the text `classify.py` is given has links removed — a "Sign in" link beside a newsletter box must not type it `login`. And `SUBMIT_SEL`, sizes, depths and counts are thresholds, which `config.py` has never held.

What this buys: `tests/test_classify.py` checks the rules in **26 ms** without a browser, where the same check through `run_fixture.py` needs a two-minute crawl; and `scripts/replay_form_types.py` re-types every form already collected from the HTML saved beside it, so a rule change can be checked against real pages in under a second. Replaying the current rules over `isec_sample_run5_undetect` reproduces the 2026-10-23 audit exactly — the same 5 rows change, and 46 subscription rows rather than 44 — which is independent evidence that the Python rules behave as the JavaScript ones did. The replay is an indication, not a verdict: the wording *around* a form is not saved, so it stands in `form_text`, and a run from before a rule change was typed by the older rules.

Keep this list current if the method changes, since it belongs in the methods section.

## Outputs (`--out`, default `outputs/results/`)

**One database holds every run**: `DATABASE_URL` in `config.py`, `sqlite:///outputs/crawl.db` by default. There is no `--db` flag; set `FIND_FORMS_DATABASE_URL` to override it for one run. Any SQLAlchemy URL works (`postgresql+psycopg://...`, `mysql+pymysql://...`), since the tables are built from the column lists rather than written out by hand. It replaced `forms.csv`, `forms.jsonl` and `pages.csv` on 2026-10-23. `--out` no longer separates runs' data — it is the directory for this run's screenshots and HTML, and **its name is the run's name in the database**. Four tables, whose columns come from `FORM_FIELDS` and `PAGE_FIELDS` so `config.py` stays the single source of truth:
  - `runs`, one row per `--out`, with the command and when it first and last started.
  - `forms`, one row per unique form, primary key `(run, site, form_sig)`. List columns (`field_types`, `field_names`, `submit_text`, `other_clickable_text`) are stored as JSON, so `json_each()` and `json_array_length()` work on them; `forms.jsonl` is gone because nothing is lost any more.
  - `pages`, one row per page visit. Statuses: `ok`, `load_error`, `site_error`, `site_timeout` (over its time limit; browser killed; since 2026-10-11) (`robots_disallowed` appears only in runs before 2026-10-08). A unique index on `(run, timestamp, site, page_url, status)` makes re-merging idempotent.
  - `sites_done`, the resume log, **keyed `(run, site)`** — resume is per run, so a new `--out` starts from nothing even though it shares the database.
  - `submissions`, one row per form `--submit` filled in, keyed `(run, site, form_sig)`, columns from `SUBMISSION_FIELDS`. Written only by `crawler/submit.py`; an ordinary crawl never touches it. Re-submitting the same form in the same run replaces its row (a dry run followed by a real one is the normal way `--submit` is used); what stops a site being signed up to twice is `Output.submitted_sites()`, which spans every run.

  Comparing runs is now a query rather than a script:
  ```sql
  SELECT form_type, sum(run='run3') AS plain, sum(run='run5') AS stealth
  FROM forms GROUP BY form_type;
  ```
- `forms.csv` / `pages.csv`: written only by `--export-csv`, for Excel, R or pandas. With a sites argument it exports that one run into `--out`; without one, every run, beside the database file, with `run` as the first column. Lists are flattened back to `a | b`, so they read like the files written before 2026-10-23.
- Under `--jobs`, every shard writes into the same database, as do separate runs going at once: SQLite in WAL mode takes one writer at a time and queues the rest, and the primary key does the de-duplication the old merge step did, so there are no part files and nothing to merge. `--merge` remains only for shards run on **another machine**, which cannot share the file: copy their SQLite file in beside this one as `<name>.part<N>.db` and run it; run labels are carried over. `--clean-parts` deletes those after merging.
- `run.log`: everything printed, with a timestamp and level per line: the command, each site with its time and new-form count, a summary, and the total run time (also logged after Ctrl-C). Appended to on every run. A shard writes `run.part<N>.log`; under `--jobs` the parent's `run.log` also holds every shard's lines, prefixed `[s<N>]`. All modules log through the `crawler` logger, set up by `setup_logging()` in `crawler/util.py`; use it instead of `print()`.
- `screens/<site>/`: `<sig>.png` and `<sig>_context.png`.
- `html/<site>/`: `<sig>.html`.

Schema stability matters because downstream analysis depends on it. Add new columns to the **end** of `FORM_FIELDS`, never rename or reorder existing ones, and note changes here. Since the move to SQLite an appended column no longer needs a fresh `--out`: the table is migrated in place. A removed or renamed one still does.

Schema changes so far:

- 2026-10-30: five columns **appended to the end** of `FORM_FIELDS`: `form_action`, `field_required`, `vendor`, `captcha_type`, `captcha_visible`. Append-only, so an existing database gains them by `ALTER TABLE ADD COLUMN`. `form_signature()` also changed on this date, which is not a schema change but does mean `form_sig` values are not comparable across it.

- 2026-10-30: eight columns were **appended to the end** of `SUBMISSION_FIELDS` for the submission verdict: `result`, `success_keywords`, `failure_keywords`, `form_visible_after`, `email_kept`, `form_valid_after`, `alert_text`, `new_tab_url`. Append-only, so an existing database gains them by `ALTER TABLE ADD COLUMN` and rows written before this date have NULL for all eight. `outcome` is unchanged in meaning, but gained the values `skipped_*` and `failed_fill`.

- 2026-10-23: `submissions` was **added as a new table**, with its columns in `SUBMISSION_FIELDS` (`config.py`), for `--submit`. No existing column changed, and `METADATA.create_all()` adds the table to an existing database on the next run, so nothing needs a fresh `--out`. `SUBMISSION_FIELDS` is append-only on the same terms as `FORM_FIELDS`. Note that four places in `output.py` list the tables by hand rather than walking the metadata — `ensure_schema()`, `merge_parts()`, `export_csv()` and the module's unpack — so a sixth table has to be named in all of them, `merge_parts()` especially, or remote shards lose its rows silently.

- 2026-10-22: `login_like` was **replaced in place** by `form_type`, a fourth deliberate exception to the append-only rule. Same position and same column count, so only the name and the values change: the boolean becomes one of `subscription`, `login`, `checkout`, `comment`, `contact`, `search`, `unknown`. `login` keeps the three signals `login_like` used, so forms that were `login_like=True` are typed `login`; everything that was `False` is now typed, most of it `signup`. Classification lives in `FORM_TYPES` in `config.py`. `Output` refuses to append to a `forms.csv` with the old header, so use a fresh `--out` directory.
- 2026-10-13: `has_privacy_link` was **removed** from `FORM_FIELDS` at the project lead's request, a third deliberate exception to the append-only rule, together with its `privacy` pattern in `DETECT_PATTERNS`. The 10 columns after it (`consent_text_hint` through `field_names`) each moved one position left. `forms.csv` files written before this date are not column-compatible; `Output` refuses to append to them, so use a fresh `--out` directory.
- 2026-10-10: `field_names` was **appended to the end** of `FORM_FIELDS`: one entry per field, in the same order as `field_types`, holding the field's `name` attribute, else its `id`, else empty (a radio group gets the group's name). Example: `field_types` = `email | text | checkbox`, `field_names` = `EMAIL | FNAME | gdpr_consent`.
- 2026-10-10: `axe_violations` was **removed** from `FORM_FIELDS` at the project lead's request, a second deliberate exception to the append-only rule. `screenshot`, `context_screenshot`, `html_file`, `form_text` and `source` each moved one position left. `forms.csv` files written before this date are not column-compatible: use a fresh `--out` directory. `Output` now refuses to append to a CSV whose header differs from the current schema, so mixing versions fails loudly instead of misaligning columns.
- 2026-10-08: no column change. `--axe` was removed (its column stayed, empty, until 2026-10-10); pages also now run under their own Content Security Policy (`bypass_csp` was only there for axe injection). `source` is kept (append-only rule) but is now always `browser`; `calibration.csv` is no longer written.
- 2026-10-07: `source` (`browser` | `http`) was **appended to the end** of `FORM_FIELDS` so rows read from markup are distinguishable from rendered ones. This follows the append-only rule — nothing was renamed or reordered — but earlier `forms.csv` files have one fewer column, so a run after this change needs a fresh `--out` directory.
- 2026-10-06: mobile crawling was removed, so the `device` column was dropped from `FORM_FIELDS` and `PAGE_FIELDS`, and the `<device>_` prefix was dropped from screenshot and HTML filenames. This was a deliberate one-time exception to the append-only rule, taken while only a two-site pilot existed. Output written before this date is not column-compatible and must be kept in a separate `--out` directory. The append-only rule still governs every future change.

`source` is always `browser` in current output. In runs from 2026-10-07 it can be `http`, meaning the row was read from served markup and has no screenshot or rendered-layout columns; filter on `source = 'browser'` for those runs.

Several columns are heuristics, not ground truth: `placement_guess`, `modal_hint`, `form_type`, `consent_text_hint`, `heading`, `other_clickable_text` and `vendor`. They are starting points for manual coding and must be spot-checked against screenshots.

## Conventions

- **`js.py` measures, `classify.py` judges** (since 2026-10-30). Anything needing `getComputedStyle`, a bounding box, `innerText` or a shadow root belongs in the page; a rule that only reads markup or wording belongs in Python, where it can be tested without a browser. Adding a new keyword rule to `DETECT_JS` is the wrong place for it.
- Keep the JavaScript in raw strings (`r"""..."""`) so regex backslashes survive. The page scripts are arrow functions; Selenium's `execute_script` runs statements, so `browser.py` wraps them with `_call()` / `_call_async()` (the async one is for `SCROLL_JS`, via `execute_async_script`). Keep them as arrow functions so both wrappers keep working.
- Detection keyword patterns live in `DETECT_PATTERNS` in `crawler/config.py` (moved there from the top of `DETECT_JS` on 2026-10-11, unchanged). They are passed into the page through `detect_options()` in `browser.py` and compiled there as case-insensitive JavaScript regexes, so write them in syntax that means the same in Python and JavaScript. `FORM_TYPES` and `VENDOR_HINTS` are no longer sent into the page at all: since 2026-10-30 they are compiled and applied by `classify.py`, as ordinary Python regexes. Thresholds (sizes, depths, counts) stay in `DETECT_JS`. Change patterns in `config.py`, not inline, and record the change here.
- Timing budgets are constants in `crawler/config.py`: `LOAD_SETTLE_MS` (3000, replaces a 10s `networkidle` wait), `PAINT_SETTLE_MS` (1000, the settle before `on_load` detection — lowering it shifts `first_seen_phase`), `SCROLL_BUDGET_MS` (5000), `DETECT_BUDGET_MS` (4000), `MAX_SHADOW_SCAN` (15000), plus `BLOCKED_URL_PATTERNS` (audio/video addresses only — never block images, which are the deliverable, fonts, which change layout metrics, or third-party scripts, which host many signup embeds), `MAX_JOBS` (8), `SHUTDOWN_GRACE` (90), `SITE_TIME_LIMIT_PER_PAGE_S` (120) and `SCRIPT_TIMEOUT_S` (30).
- Catch `SeErr` (Selenium's `WebDriverException`, the base class for every driver error including timeouts) around browser operations; one failing page or frame must never stop a crawl.
- Keep the module docstring's usage and output sections in sync with the code.
- `docs/crawl-flow.md` is the step-by-step description of a crawl (phases, timings, constants). Update it whenever the flow, a phase, or a timing constant changes.

## Testing

Run `python3 tests/test_classify.py` before and after any change to `FORM_TYPES`, `VENDOR_HINTS` or the ranking rules. It takes about 30 ms and needs no browser: 25 checks over the cases those rules have got wrong before, each dated to this file's method history. It does not replace the fixture — it covers only the half of detection that does not need a rendered page.

Run `python3 tests/run_fixture.py` before and after any change to detection or `FORM_TYPES`. It serves `tests/fixture/`, crawls it, and checks the `form_type` of all 20 forms against what each one is built to produce, plus `submit_text` where which element was picked as the submit button is the point (`EXPECTED_SUBMIT`), and `vendor`/`captcha_*` where that is (`EXPECTED_COLS`); it exits non-zero on a mismatch. 28 checks. Every expectation there is a case the rules got wrong at some point, so add one whenever a spot-check finds another.

The fixture covers: a footer `<form>` with a labeled email input, a delayed `position: fixed` modal with a placeholder-only email field, a prechecked consent checkbox, and confirmshaming dismiss text; an exit-intent sticky bar; a `<div>`-based form with no `<form>` tag; a shadow DOM widget; a signup form inside an iframe; a header login form (should rank last, `form_type = login`); a search input mentioning "email" (should not be detected); and an "unsubscribe" link (should not be followed); one form per `FORM_TYPES` entry; and the cases that have caught the rules out — a newsletter box saying "Already subscribed? Sign in", a footer offering both a newsletter and a way to get in touch, a quote request and a job application (both `unknown`, not `subscription`), a discount popup on a page whose header says "Sign in", and a newsletter bar on a page mentioning checkout; and `royalcaribbean.com`'s shape — a `<button>` country picker beside an `<a role="button" type="submit">` whose spinner, label and icon make three children — where `submit_text` must come out as exactly `["Sign Up"]`; and a Mailchimp embed with a required phone number, a country dropdown and a visible reCAPTCHA, which must come out `vendor = mailchimp`, `captcha_type = recaptcha_v2`, `captcha_visible = 1`, and whose `form_text` must contain none of its dropdown's options.

After a test run, confirm in the server log that no POST or form-action requests were made, and spot-check screenshots in `outputs/<run>/screens/`.

Run `python3 tests/run_submit_fixture.py` before and after any change to `crawler/submit.py`. It is the one test that expects a POST, and it counts them exactly: 0 for the crawl, 0 for `--submit-dry-run`, 1 for `--submit`, 0 for a second `--submit`. 39 checks; it exits non-zero on any failure. It uses its own throwaway database and serves two sites, on two ports so that each gets its own submission:

- `tests/fixture/submit/` — a newsletter form that really POSTs. Checks the alias substitution; that the required name field was filled and the required consent box ticked; that the **optional** box was left alone and the **pre-ticked SMS** box unticked; that the filled-form capture exists and its saved HTML holds what was typed; that the POST body carries the alias and no `s_sms`; that the form was sent by its **Subscribe** button and not its **"No thanks"** one; and that the verdict is `success_text` from the keyword the result page newly showed — while "check your inbox", which that page's marketing copy says all along, is correctly **not** counted.
- `tests/fixture/submit/phone/` — a newsletter form demanding a phone number. Must end `skipped_phone`, with nothing typed and no POST ever sent to it.

## Known limitations / backlog

- Cookie consent banners can suppress or delay newsletter popups, especially on EU sites. Handling them would require clicking, which is currently out of scope.
- **`undetected_chromedriver` is the default driver** (since 2026-10-22; `--no-stealth` falls back to plain Selenium). It hides `navigator.webdriver` and related fingerprints, which plain Selenium sets to `True`. Three things it needs, all handled in `browser.py` and none optional:
  - `_chrome_major()` pins it to the installed browser's major version. Left alone it fetches the newest chromedriver, which drifts ahead and fails with "only supports Chrome version N".
  - Options are passed through intact. Dropping them silently changes the measurement regime: `--hide-scrollbars` alone moves every recorded width by 15px. Verified identical measurements with and without stealth on the fixture.
  - `user_multi_procs=True`, plus `prepare_stealth_driver()` called once from `main()` before any shard starts. Without the first, `--jobs` shards overwrite one shared driver binary and all but one die with `RemoteDisconnected` **after writing partial rows**; without the second, a cold cache fails with "max() arg is an empty sequence".
  Measured cost is negligible: 10.5s per site against 10.4s for plain Selenium on the fixture, and the one-time driver fetch adds under a second to a run. (An early measurement of 24s per site was a transient: uc's cache held a driver for a different Chrome major than `_chrome_major()` was asking for. It disappeared once the cache held a matching one.) `--no-stealth` stays because the library is unmaintained (3.5.5, 2023) and patches Selenium internals.
- Headless Chromium can be detected and served different content, so the browser is visible by default (since 2026-10-11; one window per shard under `--jobs`). `--headless` hides it, e.g. on a machine without a display; compare a few sites both ways before a large headless run.
- A browsered page takes roughly 15–20 seconds; the deliberate waits (`--popup-wait`, exit intent) dominate.
- Closed shadow roots, canvas-rendered UIs, and forms behind CAPTCHAs are not detected.
- A submit button built from a `<div>` or `<span>` with **an icon and no text at all** is not recognised: for anything that is not a real `<button>` or `<input>`, the words on it are the only evidence that it is a button. `clickText()` falls back through `innerText`, `value`, `aria-label`, `title` and `alt`, so a properly labelled icon button is found; one with none of those is not. A real `<button>` or `<input type="submit">` needs no text at all. The cost is asymmetric: a top-down form is still recorded, just with an empty `submit_text`, but a **bottom-up** form is missed entirely, since the climb never finds a container holding a submit control. Since 2026-10-30 `--submit` presses Enter in the email box for such a form rather than giving up, which is how a person would send it.
- A page whose JavaScript never lets go is bounded in two places since the Selenium switch: `SCRIPT_TIMEOUT_S` caps every `execute_script`, which Playwright could not do, and `SiteWatchdog` still backs it up for a page that wedges during load, where no script call is in flight. The watchdog kills Chrome and chromedriver found through `/proc`, so it works on **Linux only**; elsewhere it logs a warning and the site can still hang. A timed-out site gets no form rows for the page it was stuck on.
- `--jobs` is capped at 8 by RAM, not CPU: roughly 500 MB per shard, spiking to ~800 MB on iframe-heavy pages. In Docker, `shm_size` must be raised from the default 64 MB or Chromium crashes tabs; `docker-compose.yml` sets 2 GB.
- `make_driver()` reads `FIND_FORMS_CHROME_BINARY`, `FIND_FORMS_CHROMEDRIVER` and `FIND_FORMS_CHROME_FLAGS` from the environment. They exist for the Docker image, which ships its own Chromium and needs `--no-sandbox`; all three are unset on a normal machine.
- The post-submit experience (confirmation flow, double opt-in, welcome email) is out of scope for the crawler and is studied manually on a small subsample using a dedicated research email address.

## Form submission (`--submit`, built 2026-10-23)

Signing up for real, to study what happens after: confirmation flow, double opt-in,
welcome email, and whether an address is later leaked or sold. Raised 2026-10-14,
built 2026-10-23 when the project lead asked for it. `crawler/submit.py` is the
only module in the project that types into a page or clicks anything.

**It is a separate phase, not a step in a crawl.** `--submit` takes no sites
argument: it reads the `forms` table for the run named by `--out`. A crawl is
therefore still detection-only in the strongest sense — the submitting code is
never on its path — and the forms can be spot-checked against their screenshots
before anything real is sent, which matters given that the 2026-10-23 audit found
4 of 81 forms mistyped.

Per site it takes the lowest-`rank_on_page` form typed `subscription`, reopens its
`page_url`, replays the four detection stimuli until the form's `form_sig`
reappears, fills it, saves the filled form, clicks submit, and records the result.
Decisions, settled with the project lead before any of it was written:

- **Scope.** The top-ranked subscription form, **one submission per site, ever**.
  Enforced by `Output.submitted_sites()`, which spans every run; `--submit-again`
  overrides it. Only outcomes that reached the click count, so a site whose form
  could not be found stays open to a later attempt.
- **Identity.** `--submit-email` is required and has no default, so no address is
  ever guessed. `{site}` in it is replaced by the site's hostname, giving per-site
  aliases (`study+example.com@gmail.com`) so a later leak or sale is traceable to
  the site that received it.
- **What gets filled.** The email box gets the alias, as does a second "confirm your
  email" box. Other fields are touched only when the form marks them **required**
  (`required` or `aria-required`), with values from `SUBMIT_FILL` in `config.py`;
  required selects take their first non-empty option. Only unchecked **required**
  checkboxes are ticked. A form's optional fields and the default state of its
  consent boxes are themselves study variables, so they are left exactly as the
  site set them.
- **What is refused** (added 2026-10-30). A form that *requires* phone, password,
  username, street address, card details or a verification code is **skipped**,
  outcome `skipped_<reason>`, rather than filled with invented data — a made-up
  phone number or address is harder to defend than not signing up, and a password
  or username would create an account rather than a subscription. The rules are
  `SUBMIT_REFUSE` in `config.py`, checked before `SUBMIT_FILL` and never against the
  email box. Nothing is typed into a form that is going to be skipped, and the site
  stays eligible for a later attempt. A required field matching no rule is still
  filled with `SUBMIT_FILL_DEFAULT` and recorded in `fields_filled`, which is where
  this is laxer than the reference implementation it was taken from.
- **SMS opt-ins are never accepted** (added 2026-10-30). A text-message box
  (`SUBMIT_SMS`) is never ticked, and a **pre-ticked** one is unticked: the study
  signs up for email and gives no phone number for anyone to text. This is the one
  deliberate exception to leaving defaults alone, and it costs nothing, because the
  pre-ticked state was already recorded at detection time in
  `n_checkboxes_prechecked`.
- **The address is read back before anything is sent** (added 2026-10-30). A popup
  taking focus mid-typing would otherwise submit a half-typed address and subscribe
  a stranger. If the email box does not hold the alias, it is typed once more, and
  failing that the outcome is `failed_fill` and the form is not submitted.
- **The filled form is captured before the click**: `<sig>_filled.png`,
  `<sig>_filled_context.png` and `<sig>_filled.html`, the record of precisely what
  was typed and which boxes were ticked. `_freeze()` copies each field's value
  *property* into its *attribute* first, because `outerHTML` serializes attributes
  and would otherwise save a blank form. It changes nothing about what is submitted,
  which reads the properties. The result page is captured the same way with
  `_after`. Under `--submit-dry-run` the run stops after the filled capture.
- **The row is written before the click**, with outcome `submitting`, then updated.
  `SiteWatchdog` can SIGKILL Chromium mid-submit, and a real subscription must never
  go unrecorded. An error afterwards updates that row rather than replacing it, so
  what was filled in survives the failure.
- **The submit guard did not come back.** `SUBMIT_GUARD_JS` cancelled every submit
  event until it was removed on 2026-10-08; the project lead's decision on
  2026-10-23 was that detection and submission being separate phases is the
  separation that matters, so nothing is reinstalled.
- **Pacing.** `--submit-delay` (default `SUBMIT_DELAY_S`, 30s) between sites, ten
  times `--page-delay`, because a submission is a write. `--submit` refuses
  `--jobs > 1`: one writer, one pace. `--submit-limit N` caps a run.
- **Ethics/IRB: still open.** Submitting creates real subscriptions, and sometimes
  real accounts, on real sites, which detection-only crawling does not. The project
  lead deferred the question on 2026-10-23. **Record the answer here before any
  large live run**; until then prefer `--submit-dry-run` and `--submit-limit`.

- **Which button is clicked** (added 2026-10-30). `DETECT_JS` counts any `<button>`
  as submit-like whatever its text says — right for detection, wrong here, since a
  popup's "No thanks" is a button too and clicking it dismisses the form instead of
  sending it. `_submit_controls()` drops `SUBMIT_DISMISS` wording and menu-openers
  (`aria-expanded`/`aria-haspopup`), tries visible controls before hidden ones, and
  falls back to pressing Enter in the email box. Never `form.submit()`, which skips
  the site's own handlers and can send an AJAX form twice.

**Two columns describe a submission**: `outcome` is what the crawler did, `result`
(added 2026-10-30) is what the site appears to have done about it.

`outcome`: `submitted`, `filled_only` (dry run), `not_found` (the form did not
reappear), `no_email_field`, `skipped_<phone|password|username|address|payment_card|
verification_code>`, `failed_fill` (the address would not go in), `no_submit_button`,
`click_failed`, `submitting` (killed between the click and the result),
`site_timeout`, `error`. A site skipped because it was already submitted to gets no
row at all.

`result`, from `classify_outcome()`, comparing the page just before the click with
the page after it: `success_text`, `failed`, `page_error`, `redirect`, `form_gone`,
`form_reset` (the box was emptied, which AJAX forms do on success), `no_change`.

The thing that makes this worth more than a keyword search: **only text that newly
appeared counts** (`_new_keywords()`). A success message is usually already in the
page before anything is submitted — the fixture page says "Check your inbox each
Monday" in its marketing copy — so presence afterwards proves nothing. The lists are
`SUBSCRIBE_SUCCESS_KEYWORDS` and `SUBSCRIBE_FAILURE_KEYWORDS` in `config.py`;
`success_keywords`/`failure_keywords` record which ones actually fired, so a verdict
can always be traced to its evidence. `OBSERVE_JS` also reads the form's own field
values, because some forms write their answer into the email box, and
`form.checkValidity()`, because a browser refusing the form is strong evidence of
failure — but only when the form is still on screen with the address still in it,
since a form that emptied or hid itself is invalid for the opposite reason.
When a form navigates away its elements go stale, so the observation falls back to
reading the page text alone; without that every ordinary non-AJAX form would look
like a bare `redirect`. `result` is a heuristic like `form_type`: spot-check it
against the `_after` screenshots.

Still out of scope: the post-submit experience itself (confirmation flow, double
opt-in, welcome email) is studied manually on a small subsample from the research
mailbox, not by the crawler.
