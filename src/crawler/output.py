"""Everything a run records, in one SQLite file per --out directory.

`crawl.db` holds three tables, whose columns come from FORM_FIELDS and
PAGE_FIELDS so config.py stays the single source of truth:

    forms       one row per unique form, keyed (site, form_sig)
    pages       one row per page visit
    sites_done  the resume log

Screenshots and HTML stay as files on disk; the tables hold their paths.

Shards under --jobs all write to this one file. SQLite in WAL mode takes one
writer at a time and queues the rest, and the rows arrive a few per second, so
there is nothing to merge afterwards: the primary key on (site, form_sig) does
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

DB_NAME = "crawl.db"

# Columns worth storing as numbers, so queries can compare them rather than
# string-sorting. Everything else is TEXT; a list is stored as JSON.
_INTEGER = {"rank_on_page", "z_index", "n_fields", "n_checkboxes",
            "n_checkboxes_prechecked", "fields_missing_label", "width", "height",
            "http_status", "n_new_forms"}
_REAL = {"viewport_coverage"}


def _coltype(name):
    return "INTEGER" if name in _INTEGER else "REAL" if name in _REAL else "TEXT"


def _connect(path):
    db = sqlite3.connect(str(path), timeout=60, isolation_level=None)
    db.execute("PRAGMA journal_mode=WAL")    # readers never block the writer
    db.execute("PRAGMA busy_timeout=60000")  # queue behind another shard rather than failing
    db.execute("PRAGMA synchronous=NORMAL")  # durable enough; a crash costs the last transaction
    return db


def _table_columns(db, table, schema="main"):
    return [r[1] for r in db.execute(f"PRAGMA {schema}.table_info({table})")]


def _ensure_schema(db):
    """Create the tables, or bring an existing file up to the current columns.

    A column added to the end of FORM_FIELDS is added to the table, so an older
    database keeps working and simply has NULL for it. A column that has been
    *removed* from the config cannot be reconciled that way, so the file is
    refused rather than silently read with a stale meaning.
    """
    cols = ", ".join(f'"{c}" {_coltype(c)}' for c in FORM_FIELDS)
    db.execute(f"CREATE TABLE IF NOT EXISTS forms ({cols}, PRIMARY KEY (site, form_sig))")
    cols = ", ".join(f'"{c}" {_coltype(c)}' for c in PAGE_FIELDS)
    db.execute(f"CREATE TABLE IF NOT EXISTS pages ({cols})")
    db.execute("CREATE TABLE IF NOT EXISTS sites_done (site TEXT PRIMARY KEY, finished_at TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS pages_site ON pages (site)")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS pages_once "
               "ON pages (timestamp, site, page_url, status)")

    for table, want in (("forms", FORM_FIELDS), ("pages", PAGE_FIELDS)):
        have = _table_columns(db, table)
        for c in want:
            if c not in have:
                db.execute(f'ALTER TABLE {table} ADD COLUMN "{c}" {_coltype(c)}')
                log.info(f"  {table}: added column {c}")
        stale = [c for c in have if c not in want]
        if stale:
            log.error(f"{table}: this database has columns the current schema does not: "
                      f"{', '.join(stale)}.\n  Use a fresh --out directory for this version "
                      f"of the crawler, or export the old one to CSV first.")
            sys.exit(1)


def _encode(value):
    """A cell as SQLite can store it: lists become JSON, bools become 0/1."""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, bool):
        return int(value)
    return value


def read_done(out_dir):
    """Every site finished by any previous run in this directory."""
    path = Path(out_dir) / DB_NAME
    if not path.exists():
        return set()
    db = _connect(path)
    try:
        if not _table_columns(db, "sites_done"):
            return set()
        return {r[0] for r in db.execute("SELECT site FROM sites_done")}
    finally:
        db.close()


class Output:
    """Append-only writer for one run. Every row is committed as it is written,
    so a crash loses at most the form in progress, and sites_done makes the next
    run resume where this one stopped."""

    def __init__(self, out_dir, part=None):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.part = part                 # which shard this is; only used in logging
        self.db = _connect(self.out / DB_NAME)
        _ensure_schema(self.db)
        self.done = {r[0] for r in self.db.execute("SELECT site FROM sites_done")}
        self.n_forms = 0                 # forms written by this process, for the run summary

    def form(self, row):
        """Write one form. A form already recorded for this site is left alone,
        which is what the old merge step did when folding shards together."""
        self.n_forms += 1
        cols = [c for c in FORM_FIELDS if c in row]
        self.db.execute(
            f'INSERT OR IGNORE INTO forms ({",".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({",".join("?" * len(cols))})',
            [_encode(row[c]) for c in cols])

    def page(self, row):
        cols = [c for c in PAGE_FIELDS if c in row]
        self.db.execute(
            f'INSERT OR IGNORE INTO pages ({",".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({",".join("?" * len(cols))})',
            [_encode(row[c]) for c in cols])

    def mark_done(self, site):
        from crawler.util import now
        self.db.execute("INSERT OR REPLACE INTO sites_done (site, finished_at) VALUES (?, ?)",
                        (site, now()))
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


def merge_parts(out_dir, clean=False):
    """Fold other crawl databases in this directory into crawl.db.

    Only needed for shards run on another machine, which cannot write to the
    same file: copy their crawl.db in as crawl.part<N>.db and run --merge.
    Shards on this machine already write straight into crawl.db.
    """
    out_dir = Path(out_dir)
    target = out_dir / DB_NAME
    others = sorted(p for p in out_dir.glob("*.db") if p.name != DB_NAME and "wal" not in p.name)
    if not others:
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
                if table == "forms":
                    forms += added
                else:
                    pages += added
            db.execute("INSERT OR IGNORE INTO sites_done (site, finished_at) "
                       "SELECT site, finished_at FROM src.sites_done")
        finally:
            db.execute("DETACH DATABASE src")
    db.close()
    log.info(f"merged {len(others)} database(s): {forms} new form rows, {pages} new page rows")
    if clean:
        for p in others:
            p.unlink()


def export_csv(out_dir):
    """Write forms.csv and pages.csv from the database, for Excel, R or pandas.

    Lists are flattened back to "a | b", the way the CSV writer used to store
    them, so these files read exactly like the ones written before 2026-10-23.
    """
    out_dir = Path(out_dir)
    path = out_dir / DB_NAME
    if not path.exists():
        log.error(f"{path} does not exist; nothing to export")
        sys.exit(1)
    db = _connect(path)
    try:
        for table, fields in (("forms", FORM_FIELDS), ("pages", PAGE_FIELDS)):
            dest = out_dir / f"{table}.csv"
            with open(dest, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                n = 0
                for row in db.execute(f"SELECT {','.join(chr(34)+c+chr(34) for c in fields)} FROM {table}"):
                    out = {}
                    for col, val in zip(fields, row):
                        if isinstance(val, str) and val.startswith("[") and val.endswith("]"):
                            try:
                                val = " | ".join(str(x) for x in json.loads(val))
                            except ValueError:
                                pass
                        out[col] = "" if val is None else val
                    w.writerow(out)
                    n += 1
            log.info(f"wrote {dest} ({n} rows)")
    finally:
        db.close()
