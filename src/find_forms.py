#!/usr/bin/env python3
"""
find_forms.py - Discover and catalog email subscription forms for UX research.

DETECTION ONLY. This script never types into, fills, or submits forms. It loads
pages, triggers popups the way a first-time visitor would (waiting, scrolling,
moving the mouse toward the top of the window), detects email signup forms, and
saves screenshots, HTML, and UX-relevant metadata for later coding.

Pages are crawled desktop-only, in a 1440x900 viewport.

Detection logic follows Englehardt, Han & Narayanan (2018), "I never signed up
for this! Privacy implications of email tracking", PoPETs 2018(1):109-126,
Section 3 and Appendix 10.1:
  * links are chosen using the keyword tiers in their Table 1
  * top-down detection over <form> elements (and iframes)
  * bottom-up detection that walks up from an email input to the first
    container that also holds a submit button
  * candidates ranked by highest z-index (ties broken by "modal"/"dialog"
    hints), then login forms lower, then more fields higher

Differences from the paper, because the goal is cataloging rather than signing up:
  * Bottom-up runs on every page for email inputs outside <form> tags, not
    only as a fallback, and every candidate is recorded, not just the best one.
  * Detection runs in phases (on load, after a delay, after scrolling, after
    simulated exit intent) so you can see what triggers each form.
  * Open shadow DOM is searched.
  * Links are opened by navigating to their URL rather than clicking them.

Setup:
    pip install -r requirements.txt
    # Chrome + chromedriver on PATH (Selenium Manager fetches a driver if needed)

Usage:
    python src/find_forms.py inputs/sites.txt --out outputs/results
    python src/find_forms.py inputs/tranco.csv --limit 500
    python src/find_forms.py inputs/sites.txt --jobs 4      # 4 shard processes, then auto-merge
    python src/find_forms.py inputs/sites.txt --shard 0/4   # or drive the shards yourself
    python src/find_forms.py --merge --out outputs/results   # fold *.part* files in by hand

Input: one site per line, as a bare domain or URL. Lines containing commas
(like a Tranco "rank,domain" CSV) use the last field. Lines starting with # are skipped.

Output, inside --out:
    forms.csv       one row per unique form per site
    forms.jsonl     same data with lists kept as JSON
    pages.csv       one row per page visit, with status and errors
    screens/        element screenshots and in-context viewport screenshots
    html/           outerHTML of each detected form
    sites_done.txt  progress log; rerunning skips sites listed here
    run.log         everything printed, with timestamps, per-site times and the total
                    run time; appended to on every run (run.part<N>.log for a shard)
    *.part<N>.*     per-shard output; --merge folds these into the files above.
                    Parts are the durable log and are kept after merging, so the
                    canonical files can always be rebuilt.

Every request comes from Chromium page loads; robots.txt is not consulted.
The `source` column is always "browser"
(runs before 2026-10-08 could also contain "http" rows read from served markup).
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from crawler.config import MAX_JOBS, SITE_TIME_LIMIT_PER_PAGE_S, STOP
from crawler.browser import prepare_stealth_driver
from crawler.crawl import crawl_site
from crawler.jobs import SiteWatchdog, install_stop_handler, run_jobs
from crawler.output import DEFAULT_DB, Output, export_csv, merge_parts, record_run
from crawler.util import fmt_duration, load_sites, now, setup_logging, short

log = logging.getLogger("crawler")


def parse_args():
    """Parse and validate the command line."""
    ap = argparse.ArgumentParser(description="Detection-only crawler for email subscription forms (UX research).")
    ap.add_argument("sites", nargs="?",
                    help="Text file with one site per line, or a rank,domain CSV")
    ap.add_argument("--out", default="outputs/results",
                    help="Directory for this run's screenshots and HTML (default: outputs/results). "
                         "Its name is also the run's name in the database.")
    ap.add_argument("--db", default=str(DEFAULT_DB),
                    help=f"The database every run writes to (default: {DEFAULT_DB})")
    ap.add_argument("--max-pages", type=int, default=3, help="Max pages per site (default: 3)")
    ap.add_argument("--explore", action="store_true",
                    help="Keep visiting top-ranked links even after forms are found (catalogs more page types)")
    ap.add_argument("--popup-wait", type=int, default=8, help="Seconds to wait for delayed popups (default: 8)")
    ap.add_argument("--page-delay", type=float, default=3, help="Base seconds between page loads (default: 3)")
    ap.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    ap.add_argument("--user-agent", help="Override the browser user agent")
    ap.add_argument("--shard", help="Process a slice of the list, e.g. 0/4")
    # Set by --jobs on its children: slice only the sites not done yet (see crawl_list).
    ap.add_argument("--shard-todo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--limit", type=int, help="Only process the first N sites")
    ap.add_argument("--headless", action="store_true",
                    help="Hide the browser window (default: visible; with --jobs N, one window per shard)")
    ap.add_argument("--no-stealth", action="store_true",
                    help="Drive Chrome with plain Selenium. The default is undetected_chromedriver, "
                         "which hides the automation fingerprints sites use to spot a crawler.")
    ap.add_argument("--site-time-limit", type=float,
                    help=f"Seconds one site may take before its browser is killed and it is logged as "
                         f"site_timeout (default: {SITE_TIME_LIMIT_PER_PAGE_S} x --max-pages)")
    ap.add_argument("--jobs", type=int, default=1,
                    help=f"Run N shards as separate processes (default: 1, max {MAX_JOBS}). "
                         "~500 MB RAM each. This process does not crawl.")
    ap.add_argument("--merge", action="store_true",
                    help="Fold other .db files beside --db into it, then exit. Only needed for "
                         "shards run on another machine; runs here already share one database.")
    ap.add_argument("--export-csv", action="store_true",
                    help="Write forms.csv and pages.csv from the database, then exit. With a sites "
                         "argument, just that run into --out; without one, every run beside the database.")
    ap.add_argument("--clean-parts", action="store_true",
                    help="Delete the merged-in databases after a successful merge (default: keep them)")
    args = ap.parse_args()
    args.stealth = not args.no_stealth   # browser.py reads this
    if not (args.merge or args.export_csv) and not args.sites:
        ap.error("the sites argument is required unless --merge or --export-csv is given")
    if not 1 <= args.jobs <= MAX_JOBS:
        ap.error(f"--jobs must be between 1 and {MAX_JOBS}")
    if args.jobs > 1 and args.shard:
        ap.error("--jobs and --shard are mutually exclusive")
    return args


def main():
    """Merge, supervise --jobs shards, or crawl: the whole list, or one --shard slice.

    Everything is logged to the console and to run.log in --out (run.part<i>.log
    for a shard), ending with the total run time, also when stopped by Ctrl-C.
    """
    args = parse_args()
    part = int(args.shard.split("/")[0]) if args.shard else None
    setup_logging(Path(args.out) / ("run.log" if part is None else f"run.part{part}.log"))
    log.info("Run started: %s", " ".join(sys.argv))
    if args.jobs > 4:
        log.warning(f"{args.jobs} shards is ~{args.jobs * 500} MB of Chromium")
    t0 = time.monotonic()
    try:
        if args.export_csv:
            # With a sites argument the user means "this run"; without one, every run.
            export_csv(Path(args.db), Path(args.out) if args.sites else None)
            return
        if args.merge:
            merge_parts(Path(args.db), args.clean_parts)
            return
        # Note the run before anything writes rows, so a --jobs run appears in
        # the runs table even though its parent writes none itself.
        if args.shard is None:
            record_run(Path(args.db), Path(args.out), " ".join(sys.argv))
        # Warm the stealth driver cache here, in one process, before any shard
        # or site needs it.
        prepare_stealth_driver(args)
        if args.jobs > 1:
            sys.exit(run_jobs(args, extra_args=["--shard-todo"]))
        else:
            crawl_list(args, part)
    finally:
        log.info("Total run time: %s", fmt_duration(time.monotonic() - t0))


def crawl_list(args, part):
    """Crawl every site in the list (or this shard's slice) that is not done yet."""
    sites = load_sites(args.sites)
    # --limit slices first so --jobs/--shard only divide the same total work.
    if args.limit:
        sites = sites[: args.limit]
    output = Output(Path(args.out), db_path=Path(args.db), part=part)
    n_listed, n_done_before = len(sites), sum(1 for s in sites if s in output.done)
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        if args.shard_todo:
            # Under --jobs, split only what is left, so a resumed run keeps all N
            # browsers busy instead of handing every unfinished site to the shard
            # that stopped early. A manual --shard keeps the fixed split by
            # position: shards on other machines cannot see this one's progress.
            sites = [s for s in sites if s not in output.done]
        sites = [s for k, s in enumerate(sites) if k % n == i]
    todo = [s for s in sites if s not in output.done]
    if args.shard_todo:
        log.info(f"{len(todo)} sites to crawl ({n_done_before} of {n_listed} in the list already done)")
    else:
        log.info(f"{len(todo)} sites to crawl ({len(sites) - len(todo)} already done)")

    install_stop_handler()
    watchdog = SiteWatchdog()
    limit = args.site_time_limit or SITE_TIME_LIMIT_PER_PAGE_S * args.max_pages
    interrupted = False
    n_done = n_errors = n_timeouts = 0
    try:
        for n, site in enumerate(todo, 1):
            if STOP["now"]:
                interrupted = True
                break
            log.info(f"[{n}/{len(todo)}] {site}")
            started, forms_before = time.monotonic(), output.n_forms
            watchdog.start(site, limit)
            error = None
            try:
                crawl_site(site, args, output)
            except Exception as e:  # keep going on any per-site failure
                error = e
            watchdog.stop()
            if watchdog.fired:  # its browser was killed; the next site starts a new one
                n_timeouts += 1
                log.warning(f"  timed out after {fmt_duration(limit)}; browser restarted")
                output.page({"timestamp": now(), "site": site, "status": "site_timeout",
                             "error": f"still running after {fmt_duration(limit)}; browser killed"})
            elif error is not None:
                n_errors += 1
                log.error(f"  failed: {short(error)}")
                output.page({"timestamp": now(), "site": site, "status": "site_error", "error": short(error)})
            output.mark_done(site)
            n_done += 1
            log.info(f"  done in {fmt_duration(time.monotonic() - started)}, "
                     f"{output.n_forms - forms_before} new form(s)")
            if STOP["now"]:
                interrupted = True
                break
    except KeyboardInterrupt:  # fallback: interrupt before the handler was installed
        # Teardown must not be interruptible: a second Ctrl-C landing in the
        # finally below would skip output.close() and lose buffered rows.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        interrupted = True
        log.warning("Interrupted. Progress is saved; rerun the same command to resume.")
    finally:
        # Close the database even if the loop raised: each site's driver is
        # already quit inside crawl_site(), so only this is left.
        try:
            output.close()
        except Exception:
            pass
    log.info(f"Crawled {n_done} of {len(todo)} sites: {output.n_forms} new form(s), "
             f"{n_errors} site error(s), {n_timeouts} timed out")
    if interrupted:
        log.warning("Stopped. Progress is saved; rerun the same command to resume.")
        sys.exit(130)


if __name__ == "__main__":
    main()
