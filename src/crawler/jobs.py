"""--jobs supervisor, the cooperative SIGINT handler, and the per-site watchdog.
None of this drives a browser itself."""

import logging
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from crawler.config import SHUTDOWN_GRACE, STOP
from crawler.output import merge_parts

log = logging.getLogger(__name__)


def strip_opt(argv, name):
    """Drop `--name value` and `--name=value` from a copy of argv."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] == name:
            i += 2
            continue
        if argv[i].startswith(name + "="):
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return out


def run_jobs(args, merge=None, extra_args=()):
    """Supervise N shard processes. This process never crawls anything.

    Each child is this same command with --jobs replaced by --shard i/N, plus
    `extra_args`. When they exit, `merge()` combines their output; by default
    that is merge_parts() on --out. scripts/ pass their own.
    """
    n = args.jobs
    argv = strip_opt(sys.argv[1:], "--jobs")
    cmd = [sys.executable, "-u", os.path.abspath(sys.argv[0])] + argv + list(extra_args)
    procs = []
    for i in range(n):
        # -u so each child's progress prints reach our pipe unbuffered.
        procs.append(subprocess.Popen(cmd + ["--shard", f"{i}/{n}"],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT))
        time.sleep(0.5)  # stagger so N Chromiums do not allocate at once
    log.info(f"started {n} shards")

    state = {"hits": 0, "at": None}

    def on_signal(signum, frame):
        state["hits"] += 1
        if state["hits"] == 1:
            # A terminal Ctrl-C already reached the children via the process
            # group; this covers the non-tty case. Do not kill yet, or they
            # die mid-flush.
            state["at"] = time.monotonic()
            log.warning(f"Interrupted; giving {n} shards up to {SHUTDOWN_GRACE}s to flush...")
            for pr in procs:
                if pr.poll() is None:
                    try:
                        pr.send_signal(signal.SIGINT)
                    except OSError:
                        pass
        elif state["hits"] == 2:
            for pr in procs:
                pr.terminate()
        else:
            for pr in procs:
                pr.kill()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    sel = selectors.DefaultSelector()
    bufs = {}
    for i, pr in enumerate(procs):
        sel.register(pr.stdout, selectors.EVENT_READ, i)
        bufs[i] = bytearray()
    live = n
    while live:
        for key, _ in sel.select(timeout=1):
            i = key.data
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                if bufs[i]:
                    log.info(f"[s{i}] {bufs[i].decode('utf-8', 'replace')}")
                sel.unregister(key.fileobj)
                key.fileobj.close()
                live -= 1
                continue
            bufs[i] += chunk
            while b"\n" in bufs[i]:
                line, _, rest = bufs[i].partition(b"\n")
                bufs[i] = bytearray(rest)
                log.info(f"[s{i}] {line.decode('utf-8', 'replace')}")
        if state["at"] and time.monotonic() - state["at"] > SHUTDOWN_GRACE:
            for pr in procs:
                if pr.poll() is None:
                    pr.kill()
            break

    codes = [pr.wait() for pr in procs]
    if merge:
        merge()
    else:
        merge_parts(clean=args.clean_parts)
    bad = [(i, c) for i, c in enumerate(codes) if c not in (0, 130)]
    for i, c in bad:
        log.error(f"shard {i} exited {c}")
    if all(c == 130 for c in codes):
        log.warning("Interrupted. Progress is saved; rerun the same command to resume." if not merge
                    else "Interrupted. Results for the pages done so far were written.")
        return 130
    return 1 if bad else 0


def _chromium_pids():
    """Chromium processes started by this process, found through /proc (Linux).
    Returns [] where /proc does not exist, so the watchdog can only warn there."""
    found, todo = [], [os.getpid()]
    while todo:
        pid = todo.pop()
        try:
            tasks = os.listdir(f"/proc/{pid}/task")
        except OSError:
            continue
        for task in tasks:
            try:
                with open(f"/proc/{pid}/task/{task}/children") as f:
                    kids = [int(k) for k in f.read().split()]
            except OSError:
                continue
            for kid in kids:
                todo.append(kid)
                try:
                    with open(f"/proc/{kid}/cmdline", "rb") as f:
                        program = f.read().split(b"\0")[0].lower()
                except OSError:
                    continue
                if b"chrom" in program:   # chrome, chromium, headless_shell and chromedriver
                    found.append(kid)
    return found


class SiteWatchdog:
    """Kills this process's Chromium when one site runs longer than its time limit.

    SCRIPT_TIMEOUT_S already bounds every execute_script, but a page that wedges
    while loading has no script call in flight to time out, and a driver call
    cannot be interrupted from Python (see install_stop_handler). A page whose
    JavaScript never lets go, like timesofindia.indiatimes.com in a 2026-10-11 run
    (stuck 25+ minutes), would block the crawl indefinitely. Killing Chrome and
    chromedriver makes the blocked call fail at once; the crawl then records the
    site as site_timeout and carries on with a fresh driver. This is a timer, not
    a second crawler: the thread never drives a browser.
    """

    def __init__(self):
        self.fired = False
        self._deadline = None
        self._site = None
        self._lock = threading.Lock()
        threading.Thread(target=self._watch, name="site-watchdog", daemon=True).start()

    def start(self, site, limit_s):
        """Begin timing `site`; kill the browser if it is not done in `limit_s` seconds."""
        with self._lock:
            self._site, self._deadline, self.fired = site, time.monotonic() + limit_s, False

    def stop(self):
        """The site finished (or failed) on its own."""
        with self._lock:
            self._deadline = None

    def _watch(self):
        while True:
            time.sleep(2)
            with self._lock:
                late = self._deadline is not None and time.monotonic() > self._deadline
                if late:
                    self._deadline, self.fired, site = None, True, self._site
            if late:
                pids = _chromium_pids()
                if not pids:
                    log.warning(f"  {site} is over its time limit, but no Chromium process was found to stop")
                    continue
                log.warning(f"  {site} is over its time limit; stopping the browser ({len(pids)} processes)")
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except OSError:
                        pass


def install_stop_handler():
    """Stop at the next page boundary instead of raising inside a driver call.

    An interrupt landing mid-call can leave the driver's rows unflushed and its
    chromedriver orphaned, so we trade an immediate stop for a clean one: the
    current page finishes, rows are flushed, the driver is quit, and the crawl
    ends between pages.
    """
    def on_stop(signum, frame):
        if not STOP["now"]:
            STOP["now"] = True
            log.warning("Stopping after the current page; progress is saved.")
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, on_stop)
