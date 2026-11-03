"""The sites a run still has to crawl, kept in the database so that any number
of worker processes can share them: --jobs N on one machine, and the same
command on other machines pointed at the same database.

    enqueue(sites)  add the run's sites in list order; ones already queued keep their state
    claim()         take the next site; no two workers ever get the same one
    finish(site)    the site is done (also when it failed: the failure is in `pages`)
    release(site)   give a site back untouched, when the fault was the worker's
    give_up()       sites whose workers kept dying on them, to be recorded as site_error
    Heartbeat       re-stamps the claimed site while it is being crawled

A claim is a single UPDATE ... RETURNING, so it is atomic on its own: SQLite
runs it under its one write lock, and on PostgreSQL FOR UPDATE SKIP LOCKED lets
workers claiming at the same moment step past each other's row rather than
queue behind it. Nothing decides the split in advance, so a fast worker simply
takes more sites, and a worker added halfway through starts helping at once.

A worker that dies (killed, out of memory, its machine gone) stops stamping its
site, and once the stamp is QUEUE_STALE_S old the next claim takes the site
over. After QUEUE_MAX_ATTEMPTS claims the site is given up rather than retried
forever, since by then the site itself is the likely cause.

Stamps are now() strings, UTC to the second, so they compare in order as text
from any machine with a set clock (EC2 instances keep theirs within
milliseconds). This module never drives a browser.
"""

import logging
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects import postgresql, sqlite

from crawler.config import QUEUE_HEARTBEAT_S, QUEUE_MAX_ATTEMPTS, QUEUE_STALE_S
from crawler.output import QUEUE, run_tx
from crawler.util import now, short

log = logging.getLogger(__name__)

_BATCH = 500    # sites per INSERT when queueing a list
_STATUSES = ("pending", "running", "done", "failed")


def worker_id():
    """Who holds a claim: this machine (in Docker, the container's id) and process."""
    return f"{socket.gethostname()}:{os.getpid()}"


def _ago(seconds):
    """The now() stamp of `seconds` ago."""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat(timespec="seconds")


class WorkQueue:
    """One run's queue, as one worker sees it."""

    def __init__(self, engine, run, worker=None):
        self.engine, self.run = engine, run
        self.worker = worker or worker_id()

    def enqueue(self, sites, done=()):
        """Add `sites` to the run in list order. A site already queued is left
        as it is, so every machine and every rerun can be given the same list.
        Sites in `done` (the run's sites_done, e.g. from before the queue
        existed) go in as done. Returns how many sites were added."""
        insert_for = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
        make = insert_for[self.engine.dialect.name]
        rows = [{"run": self.run, "site": s, "position": i, "attempts": 0,
                 "status": "done" if s in done else "pending"} for i, s in enumerate(sites)]
        added = 0
        for k in range(0, len(rows), _BATCH):
            stmt = (make(QUEUE).values(rows[k:k + _BATCH])
                    .on_conflict_do_nothing(index_elements=["run", "site"]))
            added += run_tx(self.engine, lambda conn: conn.execute(stmt).rowcount)
        return added

    def _claimable(self, stale):
        q = QUEUE.c
        return and_(q.run == self.run, q.attempts < QUEUE_MAX_ATTEMPTS,
                    or_(q.status == "pending",
                        and_(q.status == "running", q.heartbeat_at < stale)))

    def claim_statement(self):
        """The claim, as one statement: the next claimable site in list order,
        marked as this worker's. Separate so the tests can check how it compiles."""
        q, stamp, stale = QUEUE.c, now(), _ago(QUEUE_STALE_S)
        # FOR UPDATE SKIP LOCKED compiles to nothing on SQLite, whose write
        # lock already makes the statement atomic.
        nxt = (select(q.site).where(self._claimable(stale))
               .order_by(q.position, q.site).limit(1)
               .with_for_update(skip_locked=True).scalar_subquery())
        return (update(QUEUE)
                .where(q.run == self.run, q.site == nxt, self._claimable(stale))
                .values(status="running", worker=self.worker, claimed_at=stamp,
                        heartbeat_at=stamp, attempts=q.attempts + 1)
                .returning(q.site, q.attempts))

    def claim(self):
        """Take the next site: a pending one, or one whose worker stopped
        stamping it. Returns the site, or None if nothing is claimable now."""
        stmt = self.claim_statement()
        row = run_tx(self.engine, lambda conn: conn.execute(stmt).first())
        if row is None:
            return None
        site, attempts = row
        if attempts > 1:
            log.warning(f"  taking over {site}: its last worker stopped responding "
                        f"(attempt {attempts} of {QUEUE_MAX_ATTEMPTS})")
        return site

    def beat(self, site):
        """Re-stamp a site this worker holds."""
        q = QUEUE.c
        stmt = (update(QUEUE)
                .where(q.run == self.run, q.site == site, q.worker == self.worker,
                       q.status == "running")
                .values(heartbeat_at=now()))
        run_tx(self.engine, lambda conn: conn.execute(stmt))

    def finish(self, site):
        """Mark a site this worker holds as done. Returns False if it no longer
        holds it: it went quiet for QUEUE_STALE_S and another worker took over."""
        q = QUEUE.c
        stmt = (update(QUEUE)
                .where(q.run == self.run, q.site == site, q.worker == self.worker,
                       q.status == "running")
                .values(status="done", finished_at=now()))
        return bool(run_tx(self.engine, lambda conn: conn.execute(stmt).rowcount))

    def release(self, site):
        """Hand a site this worker holds back to the queue as if it had never
        been claimed: pending again, and the claim not counted against its
        attempts. For a failure that was the worker's, not the site's."""
        q = QUEUE.c
        stmt = (update(QUEUE)
                .where(q.run == self.run, q.site == site, q.worker == self.worker,
                       q.status == "running")
                .values(status="pending", worker=None, claimed_at=None, heartbeat_at=None,
                        attempts=q.attempts - 1))
        return bool(run_tx(self.engine, lambda conn: conn.execute(stmt).rowcount))

    def give_up(self):
        """Sites whose worker went quiet on their last allowed claim. They are
        marked failed and returned, each to exactly one caller, which records
        them; nobody claims them again."""
        q = QUEUE.c
        stmt = (update(QUEUE)
                .where(q.run == self.run, q.status == "running",
                       q.heartbeat_at < _ago(QUEUE_STALE_S),
                       q.attempts >= QUEUE_MAX_ATTEMPTS)
                .values(status="failed", finished_at=now())
                .returning(q.site))
        return [r[0] for r in run_tx(self.engine, lambda conn: conn.execute(stmt).all())]

    def counts(self):
        """How many of the run's sites are pending, running, done and failed,
        and how many of the running ones have gone quiet ("stale")."""
        q = QUEUE.c

        def work(conn):
            n = dict(conn.execute(select(q.status, func.count())
                                  .where(q.run == self.run).group_by(q.status)).all())
            n["stale"] = conn.execute(
                select(func.count()).select_from(QUEUE)
                .where(q.run == self.run, q.status == "running",
                       q.heartbeat_at < _ago(QUEUE_STALE_S))).scalar()
            return n
        n = run_tx(self.engine, work)
        for status in _STATUSES:
            n.setdefault(status, 0)
        n["total"] = sum(n[s] for s in _STATUSES)
        return n

    def running(self):
        """(worker, site, claimed_at, heartbeat_at) for every site being crawled."""
        q = QUEUE.c
        return run_tx(self.engine, lambda conn: [tuple(r) for r in conn.execute(
            select(q.worker, q.site, q.claimed_at, q.heartbeat_at)
            .where(q.run == self.run, q.status == "running")
            .order_by(q.worker, q.claimed_at)).all()])


class Heartbeat:
    """Re-stamps the claimed site every QUEUE_HEARTBEAT_S while it is crawled,
    from a thread of its own, so other workers can tell a slow site from a dead
    worker.

    It stops once the site has run `limit_s` + QUEUE_STALE_S. SiteWatchdog ends
    a site at `limit_s`, so a worker still on it by then is stuck somewhere the
    watchdog cannot reach (it works only on Linux), and letting the claim go
    stale hands the site to a worker that is not. Like the watchdog, this
    thread never touches a browser.
    """

    def __init__(self, queue):
        self.queue = queue
        self._site = self._until = None
        self._warned = False
        self._lock = threading.Lock()
        threading.Thread(target=self._run, name="queue-heartbeat", daemon=True).start()

    def start(self, site, limit_s):
        """Begin stamping `site`, for at most `limit_s` + QUEUE_STALE_S seconds."""
        with self._lock:
            self._site, self._until = site, time.monotonic() + limit_s + QUEUE_STALE_S
            self._warned = False

    def stop(self):
        """The site is over; stop stamping it."""
        with self._lock:
            self._site = None

    def _run(self):
        while True:
            time.sleep(QUEUE_HEARTBEAT_S)
            with self._lock:
                site, overdue = self._site, self._site and time.monotonic() >= self._until
                if overdue and self._warned:
                    continue
                if overdue:
                    self._warned = True
            if site is None:
                continue
            if overdue:
                log.warning(f"  {site} is still running long past its time limit; "
                            f"releasing it to another worker")
                continue
            try:
                self.queue.beat(site)
            except Exception as e:   # a missed stamp only matters if they keep failing
                log.warning(f"  could not stamp {site} in the queue: {short(e)}")
