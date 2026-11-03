#!/usr/bin/env python3
"""
find_forms.py - Discover and catalog email subscription forms for UX research.

CRAWLING IS DETECTION ONLY. A crawl never types into, fills, or submits forms.
It loads pages, triggers popups the way a first-time visitor would (waiting,
scrolling, moving the mouse toward the top of the window), detects email signup
forms, and saves screenshots, HTML, and UX-relevant metadata for later coding.

Signing up is a separate phase behind --submit (crawler/submit.py), which works
from the forms a crawl already recorded rather than from a live scan. See the
Submitting section below.

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
    python src/find_forms.py inputs/sites.txt --jobs 4      # 4 workers sharing the run's queue
    python src/find_forms.py --out outputs/results --jobs 4  # join a run already queued (another machine)
    python src/find_forms.py --status --out outputs/results  # how far the run has got, and who holds what
    python src/find_forms.py --merge --out outputs/results   # fold in SQLite files from offline machines

Parallel runs: the site list goes into the run's `queue` table, and every
worker takes the next site from there - --jobs N on this machine, and the same
command on any other machine pointed at the same database (PostgreSQL; a SQLite
file is one machine's). No two workers ever get the same site, a fast worker
just takes more, and a site whose worker died is taken over after
QUEUE_STALE_S. Rerunning the command resumes.

Submitting (a separate phase, over a run that has already been crawled):
    python src/find_forms.py --submit --out outputs/run6 \
        --submit-email 'study+{site}@gmail.com' --submit-dry-run   # fill and photograph only
    python src/find_forms.py --submit --out outputs/run6 \
        --submit-email 'study+{site}@gmail.com' --submit-limit 5   # really sign up

Takes no sites argument: it reads the forms recorded for --out, takes the
top-ranked subscription form per site, refills it, saves the filled form, and
submits it. One submission per site, ever. --submit-email is required and
{site} in it becomes the site's hostname, so a later leak is traceable.

Input: one site per line, as a bare domain or URL. Lines containing commas
(like a Tranco "rank,domain" CSV) use the last field. Lines starting with # are skipped.

Output, inside --out:
    screens/        element screenshots and in-context viewport screenshots
    html/           outerHTML of each detected form
    run.log         everything printed, with timestamps, per-site times and the total
                    run time; appended to on every run (run.worker<N>.log for a
                    --jobs worker)

The rows go into one database shared by every run, tagged with the run's name,
which is the name of its --out directory: forms, pages, sites_done (the resume
log), runs, and the queue. It is DATABASE_URL in crawler/config.py,
sqlite:///outputs/crawl.db unless changed; SQLite or PostgreSQL (e.g. AWS RDS).
FIND_FORMS_DATABASE_URL overrides it for one run and FIND_FORMS_DATABASE_PASSWORD
supplies the password. --export-csv writes forms.csv and pages.csv back out. --submit
adds rows to a `submissions` table, and saves <sig>_filled.* (the form holding
what was typed, before the click) and <sig>_after.* beside the crawl's shots.

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

from crawler.config import (MAX_JOBS, QUEUE_MAX_ATTEMPTS, QUEUE_MAX_START_FAILURES, QUEUE_POLL_S,
                            QUEUE_STALE_S, QUEUE_START_RETRY_S, SITE_TIME_LIMIT_PER_PAGE_S, STOP,
                            SUBMIT_DELAY_S)
from crawler.browser import prepare_stealth_driver
from crawler.crawl import BrowserStartError, crawl_site
from crawler.jobs import SiteWatchdog, install_stop_handler, run_jobs
from crawler.output import (Output, describe_database, ensure_schema, export_csv, get_engine,
                            merge_parts, read_done, record_run, run_label, submit_lock)
from crawler.submit import submit_run
from crawler.util import fmt_duration, load_sites, now, setup_logging, short
from crawler.workqueue import Heartbeat, WorkQueue

log = logging.getLogger("crawler")


def parse_args():
    """Parse and validate the command line."""
    ap = argparse.ArgumentParser(description="Detection-only crawler for email subscription forms (UX research).")
    ap.add_argument("sites", nargs="?",
                    help="Text file with one site per line, or a rank,domain CSV. Its sites are "
                         "added to the run's queue. Leave it out to work on a run that is "
                         "already queued, e.g. from a second machine.")
    ap.add_argument("--out", default="outputs/results",
                    help="Directory for this run's screenshots and HTML (default: outputs/results). "
                         "Its name is also the run's name in the database, which is set by "
                         "DATABASE_URL in crawler/config.py.")
    ap.add_argument("--max-pages", type=int, default=3, help="Max pages per site (default: 3)")
    ap.add_argument("--explore", action="store_true",
                    help="Keep visiting top-ranked links even after forms are found (catalogs more page types)")
    ap.add_argument("--popup-wait", type=int, default=8, help="Seconds to wait for delayed popups (default: 8)")
    ap.add_argument("--page-delay", type=float, default=3, help="Base seconds between page loads (default: 3)")
    ap.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    ap.add_argument("--user-agent", help="Override the browser user agent")
    # Set by --jobs on its children: the worker's number, for its log. The
    # parent has already queued the list, so a worker only takes from it.
    ap.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    ap.add_argument("--limit", type=int,
                    help="Only queue the first N sites of the list (a run that already "
                         "queued more keeps them)")
    ap.add_argument("--headless", action="store_true",
                    help="Hide the browser window (default: visible; with --jobs N, one window per worker)")
    ap.add_argument("--no-stealth", action="store_true",
                    help="Drive Chrome with plain Selenium. The default is undetected_chromedriver, "
                         "which hides the automation fingerprints sites use to spot a crawler.")
    ap.add_argument("--site-time-limit", type=float,
                    help=f"Seconds one site may take before its browser is killed and it is logged as "
                         f"site_timeout (default: {SITE_TIME_LIMIT_PER_PAGE_S} x --max-pages)")
    ap.add_argument("--jobs", type=int, default=1,
                    help=f"Run N workers as separate processes, all taking sites from the "
                         f"run's queue (default: 1, max {MAX_JOBS} per machine). ~500 MB RAM "
                         f"each. This process does not crawl.")
    ap.add_argument("--status", action="store_true",
                    help="Show how far the run named by --out has got: sites pending, being "
                         "crawled (and by which worker), done and given up. Then exit.")
    ap.add_argument("--merge", action="store_true",
                    help="Fold other SQLite files beside the configured database into it, then "
                         "exit. Only needed for a machine that could not reach the database.")
    ap.add_argument("--export-csv", action="store_true",
                    help="Write forms.csv and pages.csv from the database, then exit. With a sites "
                         "argument, just that run into --out; without one, every run beside the database.")
    ap.add_argument("--clean-parts", action="store_true",
                    help="Delete the merged-in databases after a successful merge (default: keep them)")

    # Submission. Off unless --submit is given, and a separate phase from the
    # crawl: it works from the forms already in the database for --out, so they
    # can be reviewed before anything real is sent. See crawler/submit.py.
    sub = ap.add_argument_group(
        "submitting forms",
        "Signs up to one form per site of an already-crawled run. This types into and "
        "submits real forms on real sites; an ordinary crawl never does.")
    sub.add_argument("--submit", action="store_true",
                     help="Submit to the top-ranked subscription form of each site in the "
                          "run named by --out, then exit. Needs --submit-email.")
    sub.add_argument("--submit-email", metavar="ADDRESS",
                     help="The address to sign up with. {site} is replaced by the site's "
                          "hostname, e.g. 'study+{site}@gmail.com', so a later leak can be "
                          "traced to the site that received it.")
    sub.add_argument("--submit-dry-run", action="store_true",
                     help="Fill every form in and save the filled-in screenshots, but never "
                          "click submit")
    sub.add_argument("--submit-delay", type=float, default=SUBMIT_DELAY_S,
                     help=f"Seconds between one site's submission and the next "
                          f"(default: {SUBMIT_DELAY_S})")
    sub.add_argument("--submit-limit", type=int, metavar="N",
                     help="Stop after N submissions (default: no limit)")
    sub.add_argument("--submit-again", action="store_true",
                     help="Allow a site that has already been submitted to in some run "
                          "(default: each site is submitted to at most once, ever)")
    args = ap.parse_args()
    args.stealth = not args.no_stealth   # browser.py reads this
    if args.submit:
        # Nothing about the identity used to sign up is ever guessed.
        if not args.submit_email:
            ap.error("--submit needs --submit-email, e.g. --submit-email 'study+{site}@gmail.com'")
        if args.sites:
            ap.error("--submit works from the forms already crawled into --out, "
                     "so it takes no sites argument")
        if args.jobs > 1:
            ap.error("--submit runs as one process: one writer, and submissions are paced "
                     "with --submit-delay")
    if not 1 <= args.jobs <= MAX_JOBS:
        ap.error(f"--jobs must be between 1 and {MAX_JOBS}")
    return args


def main():
    """Merge, report, submit, supervise --jobs workers, or crawl as one worker.

    Everything is logged to the console and to run.log in --out
    (run.worker<i>.log for a --jobs worker), ending with the total run time,
    also when stopped by Ctrl-C.
    """
    args = parse_args()
    worker = args.worker
    setup_logging(Path(args.out) / ("run.log" if worker is None else f"run.worker{worker}.log"))
    log.info("Run started: %s", " ".join(sys.argv))
    if args.jobs > 4:
        log.warning(f"{args.jobs} workers is ~{args.jobs * 500} MB of Chromium")
    t0 = time.monotonic()
    try:
        if args.export_csv:
            # With a sites argument the user means "this run"; without one, every run.
            export_csv(Path(args.out) if args.sites else None)
            return
        if args.merge:
            merge_parts(clean=args.clean_parts)
            return
        if worker is None:
            log.info("Database: %s", describe_database())
        if args.status:
            show_status(args)
            return
        if args.submit:
            # A phase of its own, over a run that has already been crawled.
            record_run(Path(args.out), " ".join(sys.argv))
            # --jobs is refused for it; this also stops a second --submit on
            # another machine sharing the database from signing sites up twice.
            with submit_lock() as mine:
                if not mine:
                    log.error("Another --submit is already running against this database. "
                              "Wait for it to finish.")
                    sys.exit(1)
                prepare_stealth_driver(args)
                submit_run(args)
            return
        # Note the run and queue its sites before anything crawls, so a --jobs
        # run appears in the runs table even though its parent writes no rows,
        # and its workers find the list already there.
        if worker is None:
            if args.sites:
                queue_sites(args)
            elif not queued(args):
                log.error(f"Nothing is queued for run '{run_label(args.out)}'. "
                          f"Give the site list to queue it.")
                sys.exit(1)
            record_run(Path(args.out), " ".join(sys.argv))
        # Warm the stealth driver cache here, in one process, before any worker
        # or site needs it.
        prepare_stealth_driver(args)
        if args.jobs > 1:
            sys.exit(run_jobs(args, lambda i, n: ["--worker", str(i)], tag="w"))
        else:
            crawl_queue(args, worker)
    finally:
        log.info("Total run time: %s", fmt_duration(time.monotonic() - t0))


def queue_sites(args):
    """Put the site list into the run's queue, in list order.

    Sites already queued keep their state, so every machine can be given the
    same command and a rerun adds nothing. --limit queues only the first N.
    Sites the run finished before the queue existed (its sites_done) go in as
    done.
    """
    sites = load_sites(args.sites)
    if args.limit:
        sites = sites[: args.limit]
    engine = get_engine()
    ensure_schema(engine)
    queue = WorkQueue(engine, run_label(args.out))
    added = queue.enqueue(sites, done=read_done(args.out, engine))
    log.info(f"{len(sites)} sites in the list; {added} newly queued, "
             f"{len(sites) - added} already in the run's queue")


def queued(args):
    """How many sites the run named by --out has in its queue, in any state."""
    engine = get_engine()
    ensure_schema(engine)
    return WorkQueue(engine, run_label(args.out)).counts()["total"]


def show_status(args):
    """How far the run named by --out has got, and which worker holds what."""
    engine = get_engine()
    ensure_schema(engine)
    run = run_label(args.out)
    queue = WorkQueue(engine, run)
    n = queue.counts()
    if not n["total"]:
        log.info(f"Nothing is queued for run '{run}'.")
        return
    log.info(f"Run '{run}': {n['total']} sites. {n['pending']} pending, {n['running']} being "
             f"crawled ({n['stale']} of them by workers that stopped responding), "
             f"{n['done']} done, {n['failed']} given up after {QUEUE_MAX_ATTEMPTS} attempts.")
    for who, site, claimed, beat in queue.running():
        log.info(f"  {who:32} {site}  (since {claimed}, last stamp {beat})")


def _idle(seconds):
    """Wait, but wake for Ctrl-C at once."""
    end = time.monotonic() + seconds
    while time.monotonic() < end and not STOP["now"]:
        time.sleep(1)


def crawl_queue(args, worker):
    """Crawl sites from the run's queue until none is left.

    Any number of these run at once, here (--jobs) or on other machines; each
    claim hands out a site nobody else holds. When nothing is left to claim but
    other workers are still busy, this one waits rather than exits: if one of
    them dies, its site goes stale after QUEUE_STALE_S and is picked up here.

    A browser that will not start is this worker's fault, not the site's, and
    left alone it would fail every site in milliseconds and mark it done,
    draining the queue for every worker (it did, twice, in the 2026-11-03
    tests). So the site goes back to the queue uncounted, and after
    QUEUE_MAX_START_FAILURES in a row the worker stops with an error.
    """
    output = Output(Path(args.out), part=worker)
    queue = WorkQueue(output.engine, output.run)
    n = queue.counts()
    log.info(f"{n['pending']} of {n['total']} sites to crawl ({n['done'] + n['failed']} done, "
             f"{n['running']} being crawled by other workers)")

    install_stop_handler()
    watchdog = SiteWatchdog()
    heartbeat = Heartbeat(queue)
    limit = args.site_time_limit or SITE_TIME_LIMIT_PER_PAGE_S * args.max_pages
    interrupted = broken = False
    n_done = n_errors = n_timeouts = start_failures = 0
    try:
        while True:
            if STOP["now"]:
                interrupted = True
                break
            for site in queue.give_up():
                n_errors += 1
                log.error(f"{site}: given up; its worker stopped responding on all "
                          f"{QUEUE_MAX_ATTEMPTS} attempts")
                output.page({"timestamp": now(), "site": site, "status": "site_error",
                             "error": f"worker stopped responding on all {QUEUE_MAX_ATTEMPTS} attempts"})
                output.mark_done(site)
            site = queue.claim()
            if site is None:
                if not queue.counts()["running"]:
                    break                 # nothing pending, nothing in progress anywhere
                _idle(QUEUE_POLL_S)       # others are busy; one may yet leave its site
                continue
            log.info(f"[{n_done + 1}] {site} ({queue.counts()['pending']} left in the queue)")
            started, forms_before = time.monotonic(), output.n_forms
            watchdog.start(site, limit)
            heartbeat.start(site, limit)
            error = start_error = None
            try:
                crawl_site(site, args, output)
            except BrowserStartError as e:
                start_error = e
            except Exception as e:  # keep going on any per-site failure
                error = e
            watchdog.stop()
            heartbeat.stop()
            if start_error is not None:
                queue.release(site)
                start_failures += 1
                log.error(f"  the browser would not start ({short(start_error)}); "
                          f"{site} handed back to the queue")
                if start_failures >= QUEUE_MAX_START_FAILURES:
                    log.error(f"Stopping this worker: its browser failed to start {start_failures} "
                              f"times in a row. No site was marked done because of it; fix the "
                              f"browser or driver and rerun the same command.")
                    broken = True
                    break
                _idle(QUEUE_START_RETRY_S)
                continue
            start_failures = 0
            n_done += 1
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
            if not queue.finish(site):
                log.warning(f"  another worker took {site} over meanwhile: this one did not "
                            f"stamp it for over {fmt_duration(QUEUE_STALE_S)}")
            log.info(f"  done in {fmt_duration(time.monotonic() - started)}, "
                     f"{output.n_forms - forms_before} new form(s)")
            if STOP["now"]:
                interrupted = True
                break
    except KeyboardInterrupt:  # fallback: interrupt before the handler was installed
        # Teardown must not be interruptible: a second Ctrl-C landing in the
        # finally below would skip output.close().
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        interrupted = True
        log.warning("Interrupted. Progress is saved; rerun the same command to resume.")
    finally:
        # Each site's driver is already quit inside crawl_site(), so only this is left.
        try:
            output.close()
        except Exception:
            pass
    log.info(f"Crawled {n_done} site(s): {output.n_forms} new form(s), "
             f"{n_errors} site error(s), {n_timeouts} timed out")
    if interrupted:
        log.warning("Stopped. Progress is saved; rerun the same command to resume.")
        sys.exit(130)
    if broken:
        sys.exit(1)


if __name__ == "__main__":
    main()
