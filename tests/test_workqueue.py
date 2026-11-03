#!/usr/bin/env python3
"""Check the database layer and the shared work queue, without a browser.

    python3 tests/test_workqueue.py

Runs on a throwaway SQLite file, and on PostgreSQL too when
FIND_FORMS_TEST_DATABASE_URL names one. For the local container:

    docker compose --profile test up -d postgres
    FIND_FORMS_TEST_DATABASE_URL=postgresql://forms:forms@localhost:5432/forms \
        python3 tests/test_workqueue.py

On PostgreSQL every check works in a schema of its own, created for the run
and dropped afterwards, so it can point at a database that holds real runs.

What it covers: how the database URL and password are read; that a claim is
one statement, skipping locked rows on PostgreSQL; queueing, claiming and
finishing; a site whose worker went quiet being taken over, and given up after
QUEUE_MAX_ATTEMPTS; the heartbeat; retrying through a dropped connection; the
--submit lock; several processes claiming at once (each site exactly once) and
creating the tables at once; and the whole worker loop, crawl_queue(), in
three processes with the browser replaced by a stub.
"""
import argparse
import logging
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from sqlalchemy import create_engine, func, select, text, update      # noqa: E402
from sqlalchemy.dialects import postgresql, sqlite                       # noqa: E402
from sqlalchemy.engine import make_url                                   # noqa: E402
from sqlalchemy.exc import IntegrityError, OperationalError              # noqa: E402

from crawler import workqueue                                            # noqa: E402
from crawler.config import QUEUE_MAX_ATTEMPTS                            # noqa: E402
from crawler.output import (DONE, FORMS, PAGES, QUEUE, Output, database_url,  # noqa: E402
                            describe_database, ensure_schema, get_engine, run_tx, sqlite_path,
                            submit_lock)
from crawler.workqueue import Heartbeat, WorkQueue, _ago                 # noqa: E402

OLD = "2000-01-01T00:00:00+00:00"     # a stamp older than any QUEUE_STALE_S
RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(bool(ok))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if detail and not ok else ""))


def quiet():
    """The crawler logs its retries and takeovers; keep them out of the report."""
    lg = logging.getLogger("crawler")
    lg.addHandler(logging.NullHandler())
    lg.propagate = False


def _set(engine, run, site, **values):
    with engine.begin() as conn:
        conn.execute(update(QUEUE).where(QUEUE.c.run == run, QUEUE.c.site == site).values(**values))


def _get(engine, run, site, col):
    with engine.connect() as conn:
        return conn.execute(select(QUEUE.c[col]).where(QUEUE.c.run == run,
                                                       QUEUE.c.site == site)).scalar()


# ---------------------------------------------------------------------------
# No database needed
# ---------------------------------------------------------------------------

def url_checks():
    keys = ("FIND_FORMS_DATABASE_URL", "FIND_FORMS_DATABASE_PASSWORD")
    saved = {k: os.environ.get(k) for k in keys}
    password = "p@ss#w%rd:/?"      # what an RDS-generated password can look like
    try:
        os.environ["FIND_FORMS_DATABASE_URL"] = (
            "postgres://crawler@forms.abc123.us-east-1.rds.amazonaws.com:5432/forms"
            "?sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-global-bundle.pem")
        os.environ["FIND_FORMS_DATABASE_PASSWORD"] = password
        url = database_url()
        check("postgres:// is read as PostgreSQL through psycopg2",
              url.drivername == "postgresql+psycopg2", url.drivername)
        check("the password comes from FIND_FORMS_DATABASE_PASSWORD, unescaped",
              url.password == password)
        check("TLS settings in the query are kept",
              url.query.get("sslmode") == "verify-full" and "sslrootcert" in url.query)
        shown = describe_database(url)
        check("the logged form hides the password", "p@ss" not in shown and "***" in shown, shown)
        check("the full URL keeps the password intact through escaping",
              make_url(url.render_as_string(hide_password=False)).password == password)
        del os.environ["FIND_FORMS_DATABASE_PASSWORD"]
        os.environ["FIND_FORMS_DATABASE_URL"] = "sqlite:///outputs/crawl.db"
        check("a SQLite URL names its file", sqlite_path(database_url()) == Path("outputs/crawl.db"))
        check("an in-memory SQLite has no file", sqlite_path("sqlite://") is None)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def compile_checks():
    stmt = WorkQueue(None, "run", worker="host:1").claim_statement()
    pg = str(stmt.compile(dialect=postgresql.dialect()))
    lite = str(stmt.compile(dialect=sqlite.dialect()))
    check("on PostgreSQL a claim skips rows another worker is claiming", "FOR UPDATE SKIP LOCKED" in pg)
    check("on SQLite it is plain, its write lock being enough", "FOR UPDATE" not in lite)
    check("on both it is one UPDATE that returns the site",
          pg.startswith("UPDATE") and "RETURNING" in pg and "RETURNING" in lite)


# ---------------------------------------------------------------------------
# Against a database
# ---------------------------------------------------------------------------

def queue_checks(engine):
    run = f"q_{uuid.uuid4().hex[:8]}"
    a, b, c = (WorkQueue(engine, run, worker=w) for w in ("host-a:1", "host-b:2", "host-c:3"))
    sites = [f"https://s{i}.example" for i in range(5)]
    check("queueing a list adds every site", a.enqueue(sites) == 5)
    check("queueing it again adds nothing", b.enqueue(sites) == 0)
    check("a longer list adds only the new site", a.enqueue(sites + ["https://s5.example"]) == 1)

    got_a, got_b = a.claim(), b.claim()
    check("claims follow the list order, one site each", (got_a, got_b) == (sites[0], sites[1]),
          f"{got_a}, {got_b}")
    check("a worker can finish the site it holds", a.finish(got_a))
    check("finishing it twice does nothing", not a.finish(got_a))
    check("a worker cannot finish a site another holds", not a.finish(got_b))

    _set(engine, run, got_b, heartbeat_at=OLD)         # b's machine went away
    got_c = c.claim()
    check("a site whose worker went quiet is taken over", got_c == got_b, str(got_c))
    check("  with its attempt counted", _get(engine, run, got_c, "attempts") == 2)
    check("  and its old worker can no longer finish it", not b.finish(got_b))
    check("  but the new one can", c.finish(got_c))

    doomed = a.claim()
    _set(engine, run, doomed, heartbeat_at=OLD, attempts=QUEUE_MAX_ATTEMPTS)
    check(f"a site that went quiet on all {QUEUE_MAX_ATTEMPTS} attempts is given up",
          b.give_up() == [doomed])
    check("  once, to one caller", c.give_up() == [])
    left = [a.claim() for _ in range(4)]
    check("  and never claimed again; the rest come out in order, then nothing",
          left == sites[3:] + ["https://s5.example", None], str(left))
    n = a.counts()
    check("counts add up", (n["pending"], n["running"], n["done"], n["failed"], n["total"])
          == (0, 3, 2, 1, 6), str(n))

    run3 = f"q_{uuid.uuid4().hex[:8]}"
    e, f = WorkQueue(engine, run3, worker="host-e:5"), WorkQueue(engine, run3, worker="host-f:6")
    e.enqueue(["https://r.example"])
    held = e.claim()
    check("a worker cannot release a site another holds", not f.release(held))
    check("a worker can hand back a site it holds", e.release(held))
    check("  which is pending again, with that claim not counted",
          (_get(engine, run3, held, "status"), _get(engine, run3, held, "attempts"),
           _get(engine, run3, held, "worker")) == ("pending", 0, None))
    check("  and the next worker gets it as a first attempt",
          f.claim() == held and _get(engine, run3, held, "attempts") == 1)

    run2 = f"q_{uuid.uuid4().hex[:8]}"
    d = WorkQueue(engine, run2, worker="host-d:4")
    d.enqueue(["https://x.example", "https://y.example"], done={"https://x.example"})
    check("sites already in sites_done go in as done", d.claim() == "https://y.example")


def heartbeat_checks(engine):
    run = f"h_{uuid.uuid4().hex[:8]}"
    q = WorkQueue(engine, run, worker="host-h:1")
    q.enqueue(["https://h.example"])
    site = q.claim()
    saved = workqueue.QUEUE_HEARTBEAT_S, workqueue.QUEUE_STALE_S
    workqueue.QUEUE_HEARTBEAT_S = 0.2
    try:
        _set(engine, run, site, heartbeat_at=OLD)
        hb = Heartbeat(q)
        hb.start(site, limit_s=60)
        time.sleep(1.0)
        hb.stop()
        check("the heartbeat re-stamps the site it holds", _get(engine, run, site, "heartbeat_at") > _ago(60))
        _set(engine, run, site, heartbeat_at=OLD)
        workqueue.QUEUE_STALE_S = 0
        hb.start(site, limit_s=0)       # already past limit + stale: stuck beyond the watchdog
        time.sleep(1.0)
        hb.stop()
        check("past its time limit it stops, so the claim can go stale",
              _get(engine, run, site, "heartbeat_at") == OLD)
    finally:
        workqueue.QUEUE_HEARTBEAT_S, workqueue.QUEUE_STALE_S = saved


def retry_checks(engine):
    calls = []

    def flaky(conn):
        calls.append(1)
        if len(calls) == 1:
            raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))
        return conn.execute(text("SELECT 1")).scalar()
    check("a write that meets a dropped connection is retried", run_tx(engine, flaky) == 1 and len(calls) == 2)

    dupes = []

    def dup(conn):
        dupes.append(1)
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))
    try:
        run_tx(engine, dup)
        raised = False
    except IntegrityError:
        raised = True
    check("a duplicate is not retried", raised and len(dupes) == 1)


def lock_checks(engine):
    with submit_lock(engine) as first:
        with submit_lock(engine) as second:
            check("a second --submit cannot take the lock", first and not second)
    with submit_lock(engine) as again:
        check("the lock is free again afterwards", again)


def output_checks(url, tmp):
    """Rows as the crawler writes them, with "" in number columns: SQLite took
    those, PostgreSQL refused the row (ganni.com, 2026-11-03)."""
    saved = os.environ.get("FIND_FORMS_DATABASE_URL")
    os.environ["FIND_FORMS_DATABASE_URL"] = url
    try:
        out = Output(Path(tmp) / f"out_{uuid.uuid4().hex[:8]}")
        out.page({"timestamp": OLD, "site": "https://p.example", "page_url": "https://p.example",
                  "final_url": "", "http_status": "", "status": "ok", "n_new_forms": 0, "error": ""})
        out.form({"timestamp": OLD, "site": "https://p.example", "form_sig": "abc123",
                  "z_index": "", "width": 300, "viewport_coverage": "", "captcha_visible": True,
                  "field_types": ["email", "checkbox"]})
        engine = get_engine(url)
        with engine.connect() as conn:
            page = conn.execute(select(PAGES.c.http_status, PAGES.c.n_new_forms)
                                .where(PAGES.c.run == out.run)).one()
            form = conn.execute(select(FORMS.c.z_index, FORMS.c.width, FORMS.c.viewport_coverage,
                                       FORMS.c.captcha_visible, FORMS.c.field_types)
                                .where(FORMS.c.run == out.run)).one()
        check("a page without an HTTP status is stored, with NULL for it", tuple(page) == (None, 0),
              str(tuple(page)))
        check("empty number cells in a form become NULL; numbers, bools and lists are kept",
              tuple(form) == (None, 300, None, 1, '["email", "checkbox"]'), str(tuple(form)))
    finally:
        if saved is None:
            os.environ.pop("FIND_FORMS_DATABASE_URL", None)
        else:
            os.environ["FIND_FORMS_DATABASE_URL"] = saved


# Child processes: top-level so the spawn start method can import them.

def _claimer(url, run, start, results):
    quiet()
    q = WorkQueue(get_engine(url), run)
    start.wait()
    got = []
    while True:
        site = q.claim()
        if site is None:
            break
        got.append(site)
        time.sleep(0.01)
        q.finish(site)
    results.put(got)


def _schema_maker(url, start, results):
    quiet()
    start.wait()
    try:
        ensure_schema(get_engine(url))
        results.put("ok")
    except BaseException as e:      # SystemExit included
        results.put(f"{type(e).__name__}: {e}")


def _crawler(url, out_dir, start, mode="ok"):
    """One worker running the real crawl_queue(), with the browser stubbed out.
    mode: "ok"; "broken", every browser start fails; "flaky", only the first."""
    quiet()
    os.environ["FIND_FORMS_DATABASE_URL"] = url
    os.environ.pop("FIND_FORMS_DATABASE_PASSWORD", None)
    import find_forms
    from crawler.crawl import BrowserStartError
    from crawler.util import now
    starts = []

    def fake_crawl_site(site, args, output):
        starts.append(site)
        if mode == "broken" or (mode == "flaky" and len(starts) == 1):
            raise BrowserStartError("Bad CPU type in executable")
        output.page({"timestamp": now(), "site": site, "page_url": site, "status": "ok"})
        time.sleep(0.02)
    find_forms.crawl_site = fake_crawl_site
    find_forms.QUEUE_POLL_S = 0.5
    find_forms.QUEUE_START_RETRY_S = 0.2
    start.wait()
    find_forms.crawl_queue(argparse.Namespace(out=out_dir, site_time_limit=60, max_pages=1), None)


def _start_all(ctx, target, argsets, start):
    procs = [ctx.Process(target=target, args=a) for a in argsets]
    for p in procs:
        p.start()
    time.sleep(1.5)                 # let every process import and reach start.wait()
    start.set()
    return procs


def concurrency_checks(url):
    ctx = multiprocessing.get_context("spawn")
    engine = get_engine(url)
    run = f"c_{uuid.uuid4().hex[:8]}"
    sites = [f"https://c{i}.example" for i in range(120)]
    WorkQueue(engine, run).enqueue(sites)
    start, results = ctx.Event(), ctx.Queue()
    procs = _start_all(ctx, _claimer, [(url, run, start, results)] * 6, start)
    got = [results.get(timeout=120) for _ in procs]
    for p in procs:
        p.join(timeout=30)
    claimed = [s for g in got for s in g]
    check("6 processes claiming at once: every site exactly once",
          sorted(claimed) == sorted(sites) and len(claimed) == len(set(claimed)),
          f"{len(claimed)} claims, {len(set(claimed))} distinct")
    check("  shared between them", sum(1 for g in got if g) >= 3, str([len(g) for g in got]))


def schema_race_checks(fresh_url):
    ctx = multiprocessing.get_context("spawn")
    start, results = ctx.Event(), ctx.Queue()
    procs = _start_all(ctx, _schema_maker, [(fresh_url, start, results)] * 4, start)
    outcomes = [results.get(timeout=120) for _ in procs]
    for p in procs:
        p.join(timeout=30)
    check("4 workers creating the tables at once all succeed",
          outcomes == ["ok"] * 4, "; ".join(o for o in outcomes if o != "ok"))


def loop_checks(url, tmp):
    """The real worker loop, three at once, with a dead worker's site to take
    over and one whose worker kept dying to give up."""
    ctx = multiprocessing.get_context("spawn")
    engine = get_engine(url)
    out_dir = Path(tmp) / f"loop_{uuid.uuid4().hex[:8]}"
    run = out_dir.name
    sites = [f"https://l{i}.example" for i in range(30)]
    q = WorkQueue(engine, run)
    q.enqueue(sites)
    ghost, doomed = sites[3], sites[7]
    _set(engine, run, ghost, status="running", worker="gone:1", attempts=1,
         claimed_at=OLD, heartbeat_at=OLD)
    _set(engine, run, doomed, status="running", worker="gone:2", attempts=QUEUE_MAX_ATTEMPTS,
         claimed_at=OLD, heartbeat_at=OLD)
    start = ctx.Event()
    procs = _start_all(ctx, _crawler, [(url, str(out_dir), start)] * 3, start)
    for p in procs:
        p.join(timeout=180)
    check("3 workers run the queue to the end", all(p.exitcode == 0 for p in procs),
          str([p.exitcode for p in procs]))
    with engine.connect() as conn:
        pages = conn.execute(select(PAGES.c.site, PAGES.c.status).where(PAGES.c.run == run)).all()
        done = conn.execute(select(func.count()).select_from(DONE).where(DONE.c.run == run)).scalar()
    ok_sites = [s for s, st in pages if st == "ok"]
    check("  every site crawled exactly once, the dead worker's included",
          sorted(ok_sites) == sorted(s for s in sites if s != doomed)
          and len(ok_sites) == len(set(ok_sites)), f"{len(ok_sites)} ok rows")
    check("  the site its workers kept dying on recorded as site_error",
          [(s, st) for s, st in pages if st != "ok"] == [(doomed, "site_error")])
    n = q.counts()
    check("  all marked done, in the queue and in sites_done",
          (n["done"], n["failed"], n["pending"], n["running"], done) == (29, 1, 0, 0, 30), f"{n}, {done}")


def start_guard_checks(url, tmp):
    """Workers whose browser will not start must not drain the queue: on
    2026-11-03 two runs had every site marked done with site_error in seconds."""
    ctx = multiprocessing.get_context("spawn")
    engine = get_engine(url)
    sites = [f"https://g{i}.example" for i in range(20)]

    def run(mode):
        out_dir = Path(tmp) / f"guard_{mode}_{uuid.uuid4().hex[:8]}"
        WorkQueue(engine, out_dir.name).enqueue(sites)
        start = ctx.Event()
        procs = _start_all(ctx, _crawler, [(url, str(out_dir), start, mode)] * 3, start)
        for p in procs:
            p.join(timeout=120)
        with engine.connect() as conn:
            pages = conn.execute(select(PAGES.c.site, PAGES.c.status)
                                 .where(PAGES.c.run == out_dir.name)).all()
            done = conn.execute(select(func.count()).select_from(DONE)
                                .where(DONE.c.run == out_dir.name)).scalar()
            attempts = {r[0] for r in conn.execute(select(QUEUE.c.attempts)
                                                    .where(QUEUE.c.run == out_dir.name))}
        return [p.exitcode for p in procs], WorkQueue(engine, out_dir.name).counts(), pages, done, attempts

    codes, n, pages, done, attempts = run("broken")
    check("workers whose browser never starts stop with an error",
          codes == [1, 1, 1], str(codes))
    check("  and leave every site pending and uncounted, nothing recorded or done",
          (n["pending"], n["running"], n["done"], len(pages), done, attempts) == (20, 0, 0, 0, 0, {0}),
          f"{n}, {len(pages)} pages, {done} done, attempts {attempts}")

    codes, n, pages, done, attempts = run("flaky")
    ok_sites = [s for s, st in pages if st == "ok"]
    check("one failed start is retried, and the run completes", codes == [0, 0, 0], str(codes))
    check("  every site crawled exactly once, no error recorded, each a first attempt",
          sorted(ok_sites) == sorted(sites) and len(pages) == 20 and (n["done"], done) == (20, 20)
          and attempts == {1}, f"{len(ok_sites)} ok of {len(pages)} pages, {n}, attempts {attempts}")


# ---------------------------------------------------------------------------

def backends():
    """(name, url, make a fresh empty database, clean up) for each database to test on."""
    tmp = tempfile.mkdtemp(prefix="find_forms_queue_")
    yield ("sqlite", f"sqlite:///{tmp}/crawl.db",
           lambda: f"sqlite:///{tmp}/fresh_{uuid.uuid4().hex[:8]}.db", tmp,
           lambda: shutil.rmtree(tmp, ignore_errors=True))
    base = os.environ.get("FIND_FORMS_TEST_DATABASE_URL")
    if not base:
        print("\npostgresql: skipped (set FIND_FORMS_TEST_DATABASE_URL; see this file's docstring)")
        return
    admin = create_engine(base)
    schemas = []

    def fresh():
        name = f"find_forms_test_{uuid.uuid4().hex[:10]}"
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{name}"'))
        schemas.append(name)
        return make_url(base).update_query_dict(
            {"options": f"-csearch_path={name}"}).render_as_string(hide_password=False)

    def cleanup():
        with admin.begin() as conn:
            for name in schemas:
                conn.execute(text(f'DROP SCHEMA "{name}" CASCADE'))
        admin.dispose()
        shutil.rmtree(tmp2, ignore_errors=True)
    tmp2 = tempfile.mkdtemp(prefix="find_forms_queue_pg_")
    yield "postgresql", fresh(), fresh, tmp2, cleanup


def main():
    quiet()
    print("database URLs")
    url_checks()
    print("\nclaim statement")
    compile_checks()
    for name, url, fresh, tmp, cleanup in backends():
        print(f"\n{name}")
        try:
            engine = get_engine(url)
            ensure_schema(engine)
            queue_checks(engine)
            heartbeat_checks(engine)
            retry_checks(engine)
            lock_checks(engine)
            output_checks(url, tmp)
            concurrency_checks(url)
            schema_race_checks(fresh())
            loop_checks(url, tmp)
            start_guard_checks(url, tmp)
        finally:
            cleanup()
    total, bad = len(RESULTS), RESULTS.count(False)
    print(f"\n{total - bad}/{total} checks as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
