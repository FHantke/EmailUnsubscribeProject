"""Everything every run records, in one SQLite database.

By default `outputs/crawl.db` (change it with --db). Four tables, whose columns
come from FORM_FIELDS and PAGE_FIELDS so config.py stays the single source of
truth:

    runs        one row per --out, with the command and when it last started
    forms       one row per unique form, keyed (run, site, form_sig)
    pages       one row per page visit
    sites_done  the resume log, per run

Every row carries a `run`, which is the name of the --out directory, so runs
can be compared in SQL rather than by hand:

    SELECT run, form_type, count(*) FROM forms GROUP BY run, form_type;

Screenshots and HTML stay as files under --out; the tables hold their paths.

Shards under --jobs all write here, as do separate runs going at once. SQLite
in WAL mode takes one writer at a time and queues the rest, and rows arrive a
few per second, so there is nothing to merge afterwards: the primary key does
the de-duplication that merge_parts() used to do. merge_parts() survives only
for shards run on *other* machines, which cannot share the file.
"""

import csv
import json
import logging
import sqlite3
import sys
from pathlib import Path

from crawler.config import FORM_FIELDS, PAGE_FIELDS

log = logging.getLogger(__name__)

DEFAULT_DB = Path("outputs") / "crawl.db"

# Columns worth storing as numbers, so queries can compare them rather than
# string-sorting. Everything else is TEXT; a list is stored as JSON.
_INTEGER = {"rank_on_page", "z_index", "n_fields", "n_checkboxes",
            "n_checkboxes_prechecked", "fields_missing_label", "width", "height",
            "http_status", "n_new_forms"}
_REAL = {"viewport_coverage"}


def run_label(out_dir):
    """How a run is named in the database: the name of its --out directory."""
    return Path(out_dir).resolve().name


def _coltype(name):
    return "INTEGER" if name in _INTEGER else "REAL" if name in _REAL else "TEXT"


def _connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=60, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")    # readers never block the writer
    db.execute("PRAGMA busy_timeout=60000")  # queue behind another writer rather than failing
    db.execute("PRAGMA synchronous=NORMAL")  # durable enough; a crash costs the last transaction
    return db


def _table_columns(db, table, schema="main"):
    return [r[1] for r in db.execute(f"PRAGMA {schema}.table_info({table})")]


def _ensure_schema(db):
    """Create the tables, or bring an existing database up to the current columns.

    A column appended to FORM_FIELDS is added to the table, so an older database
    keeps working and simply has NULL for it. A column *removed* from the config
    cannot be reconciled that way, so the file is refused rather than silently
    read with a stale meaning.
    """
    db.execute("CREATE TABLE IF NOT EXISTS runs ("
               "run TEXT PRIMARY KEY, out_dir TEXT, command TEXT, "
               "first_started TEXT, last_started TEXT)")
    cols = ", ".join(f'"{c}" {_coltype(c)}' for c in FORM_FIELDS)
    db.execute(f'CREATE TABLE IF NOT EXISTS forms ("run" TEXT NOT NULL, {cols}, '
               f'PRIMARY KEY (run, site, form_sig))')
    cols = ", ".join(f'"{c}" {_coltype(c)}' for c in PAGE_FIELDS)
    db.execute(f'CREATE TABLE IF NOT EXISTS pages ("run" TEXT NOT NULL, {cols})')
    db.execute("CREATE TABLE IF NOT EXISTS sites_done ("
               "run TEXT NOT NULL, site TEXT NOT NULL, finished_at TEXT, "
               "PRIMARY KEY (run, site))")
    db.execute("CREATE INDEX IF NOT EXISTS pages_run_site ON pages (run, site)")
    # Makes re-merging a database from another machine idempotent.
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pages_once "
               "ON pages (run, timestamp, site, page_url, status)")

    for table, want in (("forms", ["run"] + FORM_FIELDS), ("pages", ["run"] + PAGE_FIELDS)):
        have = _table_columns(db, table)
        for c in want:
            if c not in have:
                db.execute(f'ALTER TABLE {table} ADD COLUMN "{c}" {_coltype(c)}')
                log.info(f"  {table}: added column {c}")
        stale = [c for c in have if c not in want]
        if stale:
            log.error(f"{table}: this database has columns the current schema does not: "
                      f"{', '.join(stale)}.\n  Point --db at a new file for this version of the "
                      f"crawler, or export the old one to CSV first.")
            sys.exit(1)


def _encode(value):
    """A cell as SQLite can store it: lists become JSON, bools become 0/1."""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def record_run(db_path, out_dir, command):
    """Note this run in the `runs` table. Called once per invocation from main(),
    including the --jobs parent, which never writes rows of its own."""
    from crawler.util import now
    db = _connect(db_path)
    try:
        _ensure_schema(db)
        db.execute(
            "INSERT INTO runs (run, out_dir, command, first_started, last_started) "
            "VALUES (?,?,?,?,?) ON CONFLICT(run) DO UPDATE SET "
            "out_dir=excluded.out_dir, command=excluded.command, "
            "last_started=excluded.last_started",
            (run_label(out_dir), str(Path(out_dir).resolve()), command, now(), now()))
    finally:
        db.close()


def read_done(db_path, run):
    """Every site this run has already finished."""
    if not Path(db_path).exists():
        return set()
    db = _connect(db_path)
    try:
        if not _table_columns(db, "sites_done"):
            return set()
        return {r[0] for r in db.execute("SELECT site FROM sites_done WHERE run = ?", (run,))}
    finally:
        db.close()


class Output:
    """Append-only writer for one run. Every row is committed as it is written,
    so a crash loses at most the form in progress, and sites_done makes the next
    run resume where this one stopped."""

    def __init__(self, out_dir, db_path=None, part=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.run = run_label(out_dir)
        self.part = part                 # which shard this is; only used in logging
        self.db = _connect(db_path or DEFAULT_DB)
        _ensure_schema(self.db)
        self.done = {r[0] for r in
                     self.db.execute("SELECT site FROM sites_done WHERE run = ?", (self.run,))}
        self.n_forms = 0                 # forms written by this process, for the run summary

    def form(self, row):
        """Write one form. A form already recorded for this run and site is left
        alone, which is what the old merge step did when folding shards together."""
        self.n_forms += 1
        cols = ["run"] + [c for c in FORM_FIELDS if c in row]
        vals = [self.run] + [_encode(row[c]) for c in FORM_FIELDS if c in row]
        self.db.execute(
            f'INSERT OR IGNORE INTO forms ({",".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({",".join("?" * len(cols))})', vals)

    def page(self, row):
        cols = ["run"] + [c for c in PAGE_FIELDS if c in row]
        vals = [self.run] + [_encode(row[c]) for c in PAGE_FIELDS if c in row]
        self.db.execute(
            f'INSERT OR IGNORE INTO pages ({",".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({",".join("?" * len(cols))})', vals)

    def mark_done(self, site):
        from crawler.util import now
        self.db.execute("INSERT OR REPLACE INTO sites_done (run, site, finished_at) "
                        "VALUES (?,?,?)", (self.run, site, now()))
        self.done.add(site)

    def rel(self, path):
        """A path relative to --out, as stored in the tables."""
        return str(Path(path).relative_to(self.out))

    def close(self):
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.db.close()


def merge_parts(db_path, clean=False):
    """Fold crawl databases from other machines into this one.

    Only needed for shards run elsewhere, which cannot write to the same file:
    copy their database in beside this one as <name>.part<N>.db and run --merge.
    Shards on this machine already write straight in. Run labels are carried
    over, so the rows land in the run they belong to.
    """
    target = Path(db_path)
    others = sorted(p for p in target.parent.glob("*.db")
                    if p.name != target.name and "wal" not in p.name and "shm" not in p.name)
    if not others:
        log.info(f"no other .db files beside {target} to merge")
        return
    db = _connect(target)
    _ensure_schema(db)
    forms = pages = 0
    for other in others:
        db.execute("ATTACH DATABASE ? AS src", (str(other),))
        try:
            for table in ("forms", "pages"):
                shared = [c for c in _table_columns(db, table)
                          if c in _table_columns(db, table, schema="src")]
                cols = ",".join(f'"{c}"' for c in shared)
                before = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                db.execute(f"INSERT OR IGNORE INTO {table} ({cols}) SELECT {cols} FROM src.{table}")
                added = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] - before
                forms, pages = (forms + added, pages) if table == "forms" else (forms, pages + added)
            db.execute("INSERT OR IGNORE INTO sites_done (run, site, finished_at) "
                       "SELECT run, site, finished_at FROM src.sites_done")
            if _table_columns(db, "runs", schema="src"):
                db.execute("INSERT OR IGNORE INTO runs SELECT * FROM src.runs")
        finally:
            db.execute("DETACH DATABASE src")
    db.close()
    log.info(f"merged {len(others)} database(s): {forms} new form rows, {pages} new page rows")
    if clean:
        for p in others:
            p.unlink()


def export_csv(db_path, out_dir=None):
    """Write forms.csv and pages.csv, for Excel, R or pandas.

    With --out, only that run and into that directory; otherwise every run,
    beside the database, with the run name in the first column. Lists are
    flattened back to "a | b", the way the CSV writer stored them before
    2026-10-23, so these files read like the ones written then.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        log.error(f"{db_path} does not exist; nothing to export")
        sys.exit(1)
    run = run_label(out_dir) if out_dir else None
    dest_dir = Path(out_dir) if out_dir else db_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    db = _connect(db_path)
    try:
        for table, fields in (("forms", FORM_FIELDS), ("pages", PAGE_FIELDS)):
            cols = (fields if run else ["run"] + fields)
            sql = f"SELECT {','.join(chr(34)+c+chr(34) for c in cols)} FROM {table}"
            params = ()
            if run:
                sql += " WHERE run = ?"
                params = (run,)
            dest = dest_dir / f"{table}.csv"
            with open(dest, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                n = 0
                for row in db.execute(sql, params):
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
    finally:
        db.close()
