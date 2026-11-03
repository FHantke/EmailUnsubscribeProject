"""Everything every run records, in the database named by config.DATABASE_URL.

Six tables. Five hold the data, and their columns are built from FORM_FIELDS,
PAGE_FIELDS and SUBMISSION_FIELDS so config.py stays the single source of truth:

    runs         one row per --out, with the command and when it last started
    forms        one row per unique form, keyed (run, site, form_sig)
    pages        one row per page visit
    sites_done   the resume log, per run
    submissions  one row per form --submit filled in, keyed (run, site, form_sig)

The sixth, `queue`, is the work list workers take sites from (crawler/workqueue.py).
It is state rather than data, so --export-csv and --merge leave it alone.

Every row carries a `run`, which is the name of the --out directory, so runs
can be compared in SQL rather than by hand:

    SELECT run, form_type, count(*) FROM forms GROUP BY run, form_type;

Screenshots and HTML stay as files under --out; the tables hold their paths.

Access goes through SQLAlchemy Core, on SQLite or PostgreSQL (e.g. AWS RDS).
Duplicates are handled by catching IntegrityError rather than by INSERT OR
IGNORE, and the SQLite tuning is applied only when the engine is SQLite.

Every worker writes here: --jobs on this machine, and other machines pointed at
the same PostgreSQL server. Each write is one short transaction on a connection
taken from the pool, so nothing is held open between writes. On PostgreSQL the
pool tests a connection before handing it out, replacing one the server has
dropped, and a write that meets an outage is retried on a fresh connection for
up to DB_RETRY_FOR_S. On SQLite, WAL mode plus a busy timeout: one writer at a
time, the rest queue. The primary key does the de-duplication that the old
merge step did; merge_parts() survives only for SQLite files from machines that
could not reach this database.
"""

import csv
import json
import logging
import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (Column, Float, Index, Integer, MetaData, String, Table, Text,
                        create_engine, event, insert, inspect, select, text)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import (DBAPIError, IntegrityError, InterfaceError, OperationalError,
                            SQLAlchemyError)

from crawler.config import (DATABASE_URL, DB_CONNECT_TIMEOUT_S, DB_RETRY_FOR_S, FORM_FIELDS,
                            PAGE_FIELDS, SUBMISSION_FIELDS, TARGET_FORM_TYPE)
from crawler.util import now, short

log = logging.getLogger(__name__)

# Columns worth storing as numbers, so queries can compare them rather than
# string-sorting. Everything else is Text; a list is stored as JSON.
_INTEGER = {"rank_on_page", "z_index", "n_fields", "n_checkboxes",
            "n_checkboxes_prechecked", "fields_missing_label", "width", "height",
            "http_status", "n_new_forms",
            "n_checkboxes_ticked", "http_status_after", "dry_run",
            "form_visible_after", "email_kept", "form_valid_after",
            "captcha_visible"}
_REAL = {"viewport_coverage"}

_RUN = 128      # a run name is a directory name; keep it bounded for backends that need it
_KEY = 512      # site and page_url are keys on some backends, which cap index width

# PostgreSQL advisory lock keys: any two fixed 64-bit numbers, as long as
# nothing else using the same database picks them.
_SCHEMA_LOCK = 0x66696E645F666F72   # "find_for"
_SUBMIT_LOCK = 0x7375626D69740000   # "submit"


def database_url():
    """The configured database as a SQLAlchemy URL.

    FIND_FORMS_DATABASE_URL, else DATABASE_URL, with FIND_FORMS_DATABASE_PASSWORD
    as its password when that is set. Keeping the password out of the URL means
    it needs no escaping (an RDS password may hold @, # or %) and is never
    written anywhere the URL is, such as the log.
    """
    url = make_url(os.environ.get("FIND_FORMS_DATABASE_URL") or DATABASE_URL)
    if url.drivername in ("postgres", "postgresql"):   # postgres:// is how some tools print it
        url = url.set(drivername="postgresql+psycopg2")
    password = os.environ.get("FIND_FORMS_DATABASE_PASSWORD")
    if password:
        url = url.set(password=password)
    return url


def describe_database(url=None):
    """The database for the log: the URL with its password masked."""
    return (url or database_url()).render_as_string(hide_password=True)


def sqlite_path(url):
    """The file behind a SQLite URL, or None (another backend, or in memory)."""
    url = make_url(url)
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return None
    return Path(url.database)


def _coltype(name, key=False):
    if name in _INTEGER:
        return Integer
    if name in _REAL:
        return Float
    return String(_KEY) if key else Text


def build_metadata():
    """The six tables, with the data tables' columns taken from config.py."""
    md = MetaData()
    Table("runs", md,
          Column("run", String(_RUN), primary_key=True),
          Column("out_dir", Text), Column("command", Text),
          Column("first_started", Text), Column("last_started", Text))
    Table("forms", md,
          Column("run", String(_RUN), primary_key=True),
          *[Column(c, _coltype(c, key=c in ("site", "form_sig")),
                   primary_key=c in ("site", "form_sig")) for c in FORM_FIELDS])
    Table("pages", md,
          *[Column(c, _coltype(c)) for c in ["run"] + PAGE_FIELDS])
    Table("sites_done", md,
          Column("run", String(_RUN), primary_key=True),
          Column("site", String(_KEY), primary_key=True),
          Column("finished_at", Text))
    # Keyed like forms, so a site can be submitted to only once per run whatever
    # happens, and a resumed --submit skips what it already sent.
    Table("submissions", md,
          Column("run", String(_RUN), primary_key=True),
          *[Column(c, _coltype(c, key=c in ("site", "form_sig")),
                   primary_key=c in ("site", "form_sig")) for c in SUBMISSION_FIELDS])
    # The work list: one row per site of a run, claimed by one worker at a time.
    # Its columns are fixed here rather than in config.py, since nothing is
    # analysed from them.
    Table("queue", md,
          Column("run", String(_RUN), primary_key=True),
          Column("site", String(_KEY), primary_key=True),
          Column("position", Integer, nullable=False),   # order in the site list
          Column("status", String(16), nullable=False),  # pending, running, done, failed
          Column("attempts", Integer, nullable=False),   # claims so far
          Column("worker", Text),                        # host:pid holding it
          Column("claimed_at", Text), Column("heartbeat_at", Text),
          Column("finished_at", Text),
          Index("queue_next", "run", "status", "position"))
    return md


METADATA = build_metadata()
FORMS, PAGES, RUNS, DONE = (METADATA.tables["forms"], METADATA.tables["pages"],
                            METADATA.tables["runs"], METADATA.tables["sites_done"])
SUBMISSIONS = METADATA.tables["submissions"]
QUEUE = METADATA.tables["queue"]

_engines = {}
_schema_checked = set()


def get_engine(url=None):
    """One engine per URL per process.

    On SQLite this also turns on the settings that let several workers write at
    once. On PostgreSQL the pool is small, since a worker writes one row at a
    time (plus its queue heartbeat), and checks each connection before use.
    """
    url = make_url(url) if url is not None else database_url()
    key = url.render_as_string(hide_password=False)
    if key in _engines:
        return _engines[key]
    backend = url.get_backend_name()
    if backend == "sqlite":
        path = sqlite_path(url)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, future=True, connect_args={"timeout": 60})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, connection_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")    # readers never block the writer
            cur.execute("PRAGMA busy_timeout=60000")  # queue behind another writer
            cur.execute("PRAGMA synchronous=NORMAL")  # a crash costs the last transaction
            cur.close()
    elif backend == "postgresql":
        engine = create_engine(
            url, future=True,
            pool_size=2, max_overflow=3,
            pool_pre_ping=True,      # replace a connection the server or network dropped
            pool_recycle=1800,
            connect_args={
                "connect_timeout": DB_CONNECT_TIMEOUT_S,
                # Shows in pg_stat_activity, so a stuck worker can be found.
                "application_name": f"find_forms {socket.gethostname()}:{os.getpid()}"[:63],
                # Notice a dead peer in about two minutes rather than hanging.
                "keepalives": 1, "keepalives_idle": 60,
                "keepalives_interval": 10, "keepalives_count": 5,
            })
    else:
        log.error(f"Unsupported database {describe_database(url)}: the crawler supports "
                  f"SQLite and PostgreSQL (FIND_FORMS_DATABASE_URL, or DATABASE_URL in config.py).")
        sys.exit(1)
    _engines[key] = engine
    return engine


def _transient(err):
    """A failure worth retrying: the connection or the server went away, or a
    SQLite file stayed locked past its busy timeout. Constraint violations and
    bad SQL are not."""
    if isinstance(err, DBAPIError) and err.connection_invalidated:
        return True
    return isinstance(err, (OperationalError, InterfaceError))


def run_tx(engine, work):
    """Run work(conn) in one transaction and return its result.

    On a transient failure it is run again from the start, on a fresh
    connection, until DB_RETRY_FOR_S has passed, so a database reboot or
    failover pauses the crawl instead of losing its rows. Anything else, an
    IntegrityError included, is raised at once. A retry after a commit whose
    reply was lost meets its own row as a duplicate, which every writer here
    treats as already done.
    """
    deadline, wait = time.monotonic() + DB_RETRY_FOR_S, 1
    while True:
        try:
            with engine.begin() as conn:
                return work(conn)
        except SQLAlchemyError as e:
            if not _transient(e) or time.monotonic() + wait > deadline:
                raise
            log.warning(f"  database unavailable ({short(e)}); retrying in {wait}s")
            time.sleep(wait)
            wait = min(wait * 2, 30)


def ensure_schema(engine):
    """Create the tables, or bring an existing database up to the current columns.

    A column appended to FORM_FIELDS is added, so an older database keeps
    working and simply has NULL for it. A column *removed* from the config
    cannot be reconciled that way, so the database is refused rather than
    silently read with a stale meaning.

    Checked once per process. On PostgreSQL the check holds a lock, so workers
    starting at the same moment on several machines do not race to create or
    alter the same table.
    """
    if engine in _schema_checked:
        return

    def work(conn):
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _SCHEMA_LOCK})
        METADATA.create_all(conn)
        insp = inspect(conn)
        for table in (FORMS, PAGES, SUBMISSIONS):
            have = [c["name"] for c in insp.get_columns(table.name)]
            for col in table.columns:
                if col.name not in have:
                    kind = col.type.compile(conn.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {kind}'))
                    log.info(f"  {table.name}: added column {col.name}")
            stale = [c for c in have if c not in table.columns]
            if stale:
                return table.name, stale
        return None

    problem = run_tx(engine, work)
    if problem:
        name, stale = problem
        log.error(f"{name}: this database has columns the current schema does not: "
                  f"{', '.join(stale)}.\n  Point FIND_FORMS_DATABASE_URL (or DATABASE_URL in "
                  f"config.py) at a new database for this version of the crawler, or export "
                  f"the old one to CSV first.")
        sys.exit(1)
    _schema_checked.add(engine)


def run_label(out_dir):
    """How a run is named in the database: the name of its --out directory."""
    return Path(out_dir).resolve().name


def _encode(value):
    """A cell as the database can store it: lists become JSON, bools 0/1."""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def _cells(row, columns):
    """The values of `row` for `columns`, encoded. An empty string in a number
    column becomes NULL: SQLite stores "" there without complaint, but
    PostgreSQL refuses the whole row, which on 2026-11-03 cost ganni.com its
    page row and the rest of its crawl. --export-csv writes NULL as "", so the
    CSV files are the same either way."""
    return {c: (None if row[c] == "" and (c in _INTEGER or c in _REAL) else _encode(row[c]))
            for c in columns if c in row}


def _upsert(engine, work):
    """Run an update-else-insert. Two workers can both find no row and both
    insert; the one that loses gets an IntegrityError, and on the second try
    its update finds the winner's row."""
    try:
        return run_tx(engine, work)
    except IntegrityError:
        return run_tx(engine, work)


def record_run(out_dir, command, engine=None):
    """Note this run in the `runs` table. Called once per invocation from main(),
    including the --jobs parent, which never writes rows of its own."""
    engine = engine or get_engine()
    ensure_schema(engine)
    label, stamp, where = run_label(out_dir), now(), str(Path(out_dir).resolve())

    def work(conn):
        updated = conn.execute(RUNS.update().where(RUNS.c.run == label).values(
            out_dir=where, command=command, last_started=stamp)).rowcount
        if not updated:
            conn.execute(RUNS.insert().values(
                run=label, out_dir=where, command=command,
                first_started=stamp, last_started=stamp))
    _upsert(engine, work)


def read_done(out_dir, engine=None):
    """Every site this run has already finished."""
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(select(DONE.c.site).where(DONE.c.run == run_label(out_dir)))
            return {r[0] for r in rows}
    except SQLAlchemyError:
        return set()


def submission_targets(out_dir, engine=None):
    """What --submit would sign up to in a run: per site, the top-ranked form
    typed as a subscription, in the order the sites were crawled.

    One per site, because submitting is a write and a site is signed up to at
    most once. Reading this back from the database rather than from a live
    crawl is what keeps detection and submission separate phases: the forms can
    be reviewed before anything is sent.
    """
    engine = engine or get_engine()
    ensure_schema(engine)
    cols = ["site", "form_sig", "page_url", "frame_url", "form_type",
            "rank_on_page", "heading"]
    best = {}
    with engine.connect() as conn:
        for r in conn.execute(
                select(*[FORMS.c[c] for c in cols])
                .where(FORMS.c.run == run_label(out_dir),
                       FORMS.c.form_type == TARGET_FORM_TYPE)
                .order_by(FORMS.c.site, FORMS.c.rank_on_page, FORMS.c.timestamp)):
            best.setdefault(r[0], dict(zip(cols, r)))
    return list(best.values())


@contextmanager
def submit_lock(engine=None):
    """Let only one --submit at a time run against this database, from any machine.

    Yields True if this process got the lock, False if another holds it. On
    PostgreSQL it is an advisory lock on a connection kept for the duration; on
    SQLite, a lock file beside the database (an in-memory database has no
    other users). Without it, two --submit runs started on two machines would
    both read the same sites as not yet submitted to, and sign each up twice.
    """
    engine = engine or get_engine()
    if engine.dialect.name == "postgresql":
        got = False
        conn = engine.connect()
        try:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"),
                                    {"k": _SUBMIT_LOCK}).scalar())
            conn.commit()
            yield got
        finally:
            try:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SUBMIT_LOCK})
                    conn.commit()
            finally:
                conn.close()
        return
    path = sqlite_path(engine.url)
    if path is None:
        yield True
        return
    import fcntl   # POSIX only, like the watchdog; imported here so the rest loads anywhere
    with open(f"{path}.submit.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class Output:
    """Append-only writer for one run. Every row is committed as it is written,
    so a crash loses at most the form in progress, and sites_done makes the next
    run resume where this one stopped."""

    def __init__(self, out_dir, part=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run = run_label(out_dir)
        self.part = part                 # which worker this is; only used in logging
        self.engine = get_engine()
        ensure_schema(self.engine)
        self.n_forms = 0                 # forms written by this process, for the run summary

    def _write(self, table, values, ignore_duplicate):
        """One row, committed. A duplicate is skipped by catching the constraint
        rather than with INSERT OR IGNORE, which is SQLite-only."""
        try:
            run_tx(self.engine, lambda conn: conn.execute(insert(table).values(**values)))
        except IntegrityError:
            if not ignore_duplicate:
                raise

    def form(self, row):
        """Write one form. A form already recorded for this run and site is left
        alone, so a site crawled again after its worker died adds no duplicates."""
        self.n_forms += 1
        values = {"run": self.run}
        values.update(_cells(row, FORM_FIELDS))
        self._write(FORMS, values, ignore_duplicate=True)

    def page(self, row):
        values = {"run": self.run}
        values.update(_cells(row, PAGE_FIELDS))
        self._write(PAGES, values, ignore_duplicate=True)

    def submission(self, row):
        """Write one submission attempt, replacing any earlier attempt on the
        same form in this run: a dry run followed by a real one is the normal
        way --submit is used, and both describe the same attempt.

        What stops a site being signed up to twice is submitted_sites(), not
        this key, since only outcomes that reached the click count there.
        """
        values = _cells(row, SUBMISSION_FIELDS)

        def work(conn):
            updated = conn.execute(SUBMISSIONS.update().where(
                SUBMISSIONS.c.run == self.run, SUBMISSIONS.c.site == row["site"],
                SUBMISSIONS.c.form_sig == row["form_sig"],
            ).values(**values)).rowcount
            if not updated:
                conn.execute(SUBMISSIONS.insert().values(run=self.run, **values))
        _upsert(self.engine, work)

    def update_submission(self, site, form_sig, **fields):
        """Fill in what the click produced, on the row written before it,
        leaving the rest of that row alone. Returns whether a row was there."""
        return bool(run_tx(self.engine, lambda conn: conn.execute(SUBMISSIONS.update().where(
            SUBMISSIONS.c.run == self.run, SUBMISSIONS.c.site == site,
            SUBMISSIONS.c.form_sig == form_sig,
        ).values(**_cells(fields, fields))).rowcount))

    def submitted_sites(self):
        """Sites that have already had something sent to them, in any run.

        Only outcomes that reached the click count, so a site whose form could
        not be found is still open to a later attempt.
        """
        return run_tx(self.engine, lambda conn: {r[0] for r in conn.execute(
            select(SUBMISSIONS.c.site).distinct()
            .where(SUBMISSIONS.c.outcome.in_(("submitted", "submitting"))))})

    def mark_done(self, site):
        stamp = now()

        def work(conn):
            updated = conn.execute(
                DONE.update().where(DONE.c.run == self.run, DONE.c.site == site)
                .values(finished_at=stamp)).rowcount
            if not updated:
                conn.execute(DONE.insert().values(run=self.run, site=site, finished_at=stamp))
        _upsert(self.engine, work)

    def rel(self, path):
        """A path relative to --out, as stored in the tables."""
        return str(Path(path).relative_to(self.out))

    def close(self):
        """Nothing to release: every write returned its connection to the pool."""


def merge_parts(clean=False):
    """Fold SQLite databases from machines that could not reach this one into it.

    Copy their SQLite file in beside this database as <name>.part<N>.db and run
    --merge. Run labels are carried over, so rows land in the run they belong
    to. Machines that can reach the configured database already write straight
    in, and share its queue. The other machines' queues are not merged: their
    sites_done is, which is what a later crawl of the run resumes from.
    """
    target = sqlite_path(database_url())
    if target is None:
        log.error("--merge folds in SQLite files, and the configured database is not a SQLite "
                  "file. Point the other machines at this database instead.")
        sys.exit(1)
    others = sorted(p for p in target.parent.glob("*.db")
                    if p.name != target.name and "wal" not in p.name and "shm" not in p.name)
    if not others:
        log.info(f"no other .db files beside {target} to merge")
        return
    engine = get_engine()
    ensure_schema(engine)
    added = {}
    with engine.begin() as conn:
        for other in others:
            conn.execute(text("ATTACH DATABASE :p AS src"), {"p": str(other)})
            try:
                for table in (FORMS, PAGES, SUBMISSIONS):
                    src_cols = {r[1] for r in conn.execute(text(f"PRAGMA src.table_info({table.name})"))}
                    if not src_cols:
                        continue      # older database, written before this table existed
                    cols = ",".join(f'"{c.name}"' for c in table.columns if c.name in src_cols)
                    before = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar()
                    conn.execute(text(f"INSERT OR IGNORE INTO {table.name} ({cols}) "
                                      f"SELECT {cols} FROM src.{table.name}"))
                    now_n = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar()
                    added[table.name] = added.get(table.name, 0) + now_n - before
                conn.execute(text("INSERT OR IGNORE INTO sites_done (run, site, finished_at) "
                                  "SELECT run, site, finished_at FROM src.sites_done"))
                conn.execute(text("INSERT OR IGNORE INTO runs SELECT * FROM src.runs"))
            finally:
                conn.execute(text("DETACH DATABASE src"))
    log.info(f"merged {len(others)} database(s): "
             + ", ".join(f"{n} new {name} rows" for name, n in sorted(added.items())))
    if clean:
        for p in others:
            p.unlink()


def export_csv(out_dir=None):
    """Write forms.csv and pages.csv, for Excel, R or pandas.

    With --out, only that run and into that directory; otherwise every run,
    beside the database (or into outputs/ if it is not a local file), with the
    run name in the first column. Lists are flattened
    back to "a | b", the way the CSV writer stored them before 2026-10-23, so
    these files read like the ones written then.
    """
    engine = get_engine()
    ensure_schema(engine)
    run = run_label(out_dir) if out_dir else None
    db_file = sqlite_path(database_url())
    beside = db_file.parent if db_file else Path("outputs")
    dest_dir = Path(out_dir) if out_dir else beside
    dest_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        for table, fields in ((FORMS, FORM_FIELDS), (PAGES, PAGE_FIELDS),
                              (SUBMISSIONS, SUBMISSION_FIELDS)):
            cols = fields if run else ["run"] + fields
            stmt = select(*[table.c[c] for c in cols])
            if run:
                stmt = stmt.where(table.c.run == run)
            dest = dest_dir / f"{table.name}.csv"
            with open(dest, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                n = 0
                for row in conn.execute(stmt):
                    out = {}
                    for col, val in zip(cols, row):
                        if isinstance(val, str) and val.startswith("[") and val.endswith("]"):
                            try:
                                val = " | ".join(str(x) for x in json.loads(val))
                            except ValueError:
                                pass
                        out[col] = "" if val is None else val
                    w.writerow(out)
                    n += 1
            log.info(f"wrote {dest} ({n} rows{' from run ' + run if run else ', all runs'})")
