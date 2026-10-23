"""Everything every run records, in the database named by config.DATABASE_URL.

Four tables, whose columns are built from FORM_FIELDS and PAGE_FIELDS so
config.py stays the single source of truth:

    runs        one row per --out, with the command and when it last started
    forms       one row per unique form, keyed (run, site, form_sig)
    pages       one row per page visit
    sites_done  the resume log, per run

Every row carries a `run`, which is the name of the --out directory, so runs
can be compared in SQL rather than by hand:

    SELECT run, form_type, count(*) FROM forms GROUP BY run, form_type;

Screenshots and HTML stay as files under --out; the tables hold their paths.

Access goes through SQLAlchemy Core, so pointing DATABASE_URL at Postgres or
MySQL needs no code change here. Nothing below is dialect-specific: duplicates
are handled by catching IntegrityError rather than by INSERT OR IGNORE, and the
SQLite tuning is applied only when the engine is SQLite.

Shards under --jobs all write here, as do separate runs going at once. On
SQLite that works because of WAL mode plus a busy timeout: one writer at a
time, the rest queue. The primary key does the de-duplication that the old
merge step did, so there is nothing to merge afterwards; merge_parts() survives
only for shards run on machines that cannot reach this database.
"""

import csv
import json
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import (Column, Float, Integer, MetaData, String, Table, Text, event,
                        insert, inspect, select, text)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from crawler.config import DATABASE_URL, FORM_FIELDS, PAGE_FIELDS

log = logging.getLogger(__name__)

# Columns worth storing as numbers, so queries can compare them rather than
# string-sorting. Everything else is Text; a list is stored as JSON.
_INTEGER = {"rank_on_page", "z_index", "n_fields", "n_checkboxes",
            "n_checkboxes_prechecked", "fields_missing_label", "width", "height",
            "http_status", "n_new_forms"}
_REAL = {"viewport_coverage"}

_RUN = 128      # a run name is a directory name; keep it bounded for backends that need it
_KEY = 512      # site and page_url are keys on some backends, which cap index width


def database_url():
    """The configured database, overridable per run without editing config.py."""
    return os.environ.get("FIND_FORMS_DATABASE_URL") or DATABASE_URL


def _coltype(name, key=False):
    if name in _INTEGER:
        return Integer
    if name in _REAL:
        return Float
    return String(_KEY) if key else Text


def build_metadata():
    """The four tables, with columns taken from config.py."""
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
    return md


METADATA = build_metadata()
FORMS, PAGES, RUNS, DONE = (METADATA.tables["forms"], METADATA.tables["pages"],
                            METADATA.tables["runs"], METADATA.tables["sites_done"])

_engines = {}


def get_engine(url=None):
    """One engine per URL per process. On SQLite this also turns on the settings
    that let several shards write at once."""
    from sqlalchemy import create_engine
    url = url or database_url()
    if url in _engines:
        return _engines[url]
    kwargs = {"future": True}
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"timeout": 60}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, connection_record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")    # readers never block the writer
            cur.execute("PRAGMA busy_timeout=60000")  # queue behind another writer
            cur.execute("PRAGMA synchronous=NORMAL")  # a crash costs the last transaction
            cur.close()
    _engines[url] = engine
    return engine


def ensure_schema(engine):
    """Create the tables, or bring an existing database up to the current columns.

    A column appended to FORM_FIELDS is added, so an older database keeps
    working and simply has NULL for it. A column *removed* from the config
    cannot be reconciled that way, so the database is refused rather than
    silently read with a stale meaning.
    """
    METADATA.create_all(engine)
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in (FORMS, PAGES):
            have = [c["name"] for c in insp.get_columns(table.name)]
            for col in table.columns:
                if col.name not in have:
                    kind = col.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {kind}'))
                    log.info(f"  {table.name}: added column {col.name}")
            stale = [c for c in have if c not in table.columns]
            if stale:
                log.error(f"{table.name}: this database has columns the current schema does not: "
                          f"{', '.join(stale)}.\n  Point DATABASE_URL (config.py) at a new database "
                          f"for this version of the crawler, or export the old one to CSV first.")
                sys.exit(1)


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


def record_run(out_dir, command, engine=None):
    """Note this run in the `runs` table. Called once per invocation from main(),
    including the --jobs parent, which never writes rows of its own."""
    from crawler.util import now
    engine = engine or get_engine()
    ensure_schema(engine)
    label, stamp = run_label(out_dir), now()
    with engine.begin() as conn:
        updated = conn.execute(RUNS.update().where(RUNS.c.run == label).values(
            out_dir=str(Path(out_dir).resolve()), command=command, last_started=stamp)).rowcount
        if not updated:
            conn.execute(RUNS.insert().values(
                run=label, out_dir=str(Path(out_dir).resolve()), command=command,
                first_started=stamp, last_started=stamp))


def read_done(out_dir, engine=None):
    """Every site this run has already finished."""
    engine = engine or get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(select(DONE.c.site).where(DONE.c.run == run_label(out_dir)))
            return {r[0] for r in rows}
    except SQLAlchemyError:
        return set()


class Output:
    """Append-only writer for one run. Every row is committed as it is written,
    so a crash loses at most the form in progress, and sites_done makes the next
    run resume where this one stopped."""

    def __init__(self, out_dir, part=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run = run_label(out_dir)
        self.part = part                 # which shard this is; only used in logging
        self.engine = get_engine()
        ensure_schema(self.engine)
        self.conn = self.engine.connect()
        self.done = {r[0] for r in
                     self.conn.execute(select(DONE.c.site).where(DONE.c.run == self.run))}
        self.conn.commit()               # close the transaction that select autobegan
        self.n_forms = 0                 # forms written by this process, for the run summary

    def _write(self, table, values, ignore_duplicate):
        """One row, committed. A duplicate is skipped by catching the constraint
        rather than with INSERT OR IGNORE, which is SQLite-only.

        The connection autobegins its transaction, so this commits rather than
        opening one of its own.
        """
        try:
            self.conn.execute(insert(table).values(**values))
            self.conn.commit()
        except IntegrityError:
            self.conn.rollback()
            if not ignore_duplicate:
                raise

    def form(self, row):
        """Write one form. A form already recorded for this run and site is left
        alone, which is what the old merge step did when folding shards together."""
        self.n_forms += 1
        values = {"run": self.run}
        values.update({c: _encode(row[c]) for c in FORM_FIELDS if c in row})
        self._write(FORMS, values, ignore_duplicate=True)

    def page(self, row):
        values = {"run": self.run}
        values.update({c: _encode(row[c]) for c in PAGE_FIELDS if c in row})
        self._write(PAGES, values, ignore_duplicate=True)

    def mark_done(self, site):
        from crawler.util import now
        stamp = now()
        updated = self.conn.execute(
            DONE.update().where(DONE.c.run == self.run, DONE.c.site == site)
            .values(finished_at=stamp)).rowcount
        if not updated:
            self.conn.execute(DONE.insert().values(run=self.run, site=site, finished_at=stamp))
        self.conn.commit()
        self.done.add(site)

    def rel(self, path):
        """A path relative to --out, as stored in the tables."""
        return str(Path(path).relative_to(self.out))

    def close(self):
        try:
            self.conn.close()
        except SQLAlchemyError:
            pass


def merge_parts(clean=False):
    """Fold databases from machines that cannot reach this one into it.

    Copy their SQLite file in beside this database as <name>.part<N>.db and run
    --merge. Run labels are carried over, so rows land in the run they belong
    to. Shards that can reach the configured database already write straight in.
    """
    url = database_url()
    if not url.startswith("sqlite"):
        log.error("--merge folds in SQLite files; DATABASE_URL is not SQLite. "
                  "Point the other machines at this database instead.")
        sys.exit(1)
    target = Path(url.split("///", 1)[-1])
    others = sorted(p for p in target.parent.glob("*.db")
                    if p.name != target.name and "wal" not in p.name and "shm" not in p.name)
    if not others:
        log.info(f"no other .db files beside {target} to merge")
        return
    engine = get_engine()
    ensure_schema(engine)
    forms = pages = 0
    with engine.begin() as conn:
        for other in others:
            conn.execute(text("ATTACH DATABASE :p AS src"), {"p": str(other)})
            try:
                for table in (FORMS, PAGES):
                    src_cols = {r[1] for r in conn.execute(text(f"PRAGMA src.table_info({table.name})"))}
                    cols = ",".join(f'"{c.name}"' for c in table.columns if c.name in src_cols)
                    before = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar()
                    conn.execute(text(f"INSERT OR IGNORE INTO {table.name} ({cols}) "
                                      f"SELECT {cols} FROM src.{table.name}"))
                    added = conn.execute(text(f"SELECT count(*) FROM {table.name}")).scalar() - before
                    forms, pages = ((forms + added, pages) if table is FORMS else (forms, pages + added))
                conn.execute(text("INSERT OR IGNORE INTO sites_done (run, site, finished_at) "
                                  "SELECT run, site, finished_at FROM src.sites_done"))
                conn.execute(text("INSERT OR IGNORE INTO runs SELECT * FROM src.runs"))
            finally:
                conn.execute(text("DETACH DATABASE src"))
    log.info(f"merged {len(others)} database(s): {forms} new form rows, {pages} new page rows")
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
    url = database_url()
    beside = Path(url.split("///", 1)[-1]).parent if url.startswith("sqlite:///") else Path("outputs")
    dest_dir = Path(out_dir) if out_dir else beside
    dest_dir.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        for table, fields in ((FORMS, FORM_FIELDS), (PAGES, PAGE_FIELDS)):
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
