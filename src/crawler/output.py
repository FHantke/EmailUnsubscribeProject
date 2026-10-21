"""CSV/JSONL writers, resume state, and merging of shard part files."""

import csv
import json
import logging
import re
import sys

from crawler.config import FORM_FIELDS, PAGE_FIELDS
from crawler.util import flat

log = logging.getLogger(__name__)


def read_done(out_dir):
    """Every site finished by any previous run, canonical file plus every shard
    part. Keyed on the site string, so resume stays correct even if --jobs
    changes between runs and reshuffles which shard owns which site."""
    done = set()
    for path in [out_dir / "sites_done.txt", *sorted(out_dir.glob("sites_done.part*.txt"))]:
        if path.exists():
            done |= set(path.read_text(encoding="utf-8").split())
    return done


class Output:
    """Append-only writers for one run, or one shard when `part` is set.

    Every row is flushed as it is written, so a crash loses at most the form in
    progress, and sites_done.txt makes the next run resume where this one stopped.
    """
    def __init__(self, out_dir, part=None):
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        # Shards share one --out (so Output.rel paths stay valid) but write
        # separate files, since appending to one CSV from N processes interleaves.
        sfx = "" if part is None else f".part{part}"
        self.forms_file, self.forms = self._csv(f"forms{sfx}.csv", FORM_FIELDS)
        self.pages_file, self.pages = self._csv(f"pages{sfx}.csv", PAGE_FIELDS)
        self.jsonl = open(self.out / f"forms{sfx}.jsonl", "a", encoding="utf-8")
        self.done_path = self.out / f"sites_done{sfx}.txt"
        self.done = read_done(out_dir)
        self.n_forms = 0   # forms written by this process, for the run summary

    def _csv(self, name, fields):
        """Open a CSV for appending, writing the header only if the file is new or empty.

        An existing file must have exactly the current columns: appending rows with a
        different column list under its old header would shift every value after the
        first difference into the wrong column.
        """
        path = self.out / name
        new = not path.exists() or path.stat().st_size == 0
        if not new:
            with open(path, newline="", encoding="utf-8") as f:
                _check_header(path, next(csv.reader(f), None), fields)
        f = open(path, "a", newline="", encoding="utf-8")
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            writer.writeheader()
        return f, writer

    def form(self, row):
        """Write one form to forms.csv (lists flattened) and forms.jsonl (lists kept)."""
        self.n_forms += 1
        self.forms.writerow({k: flat(v) for k, v in row.items()})
        self.forms_file.flush()
        self.jsonl.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.jsonl.flush()

    def page(self, row):
        """Write one pages.csv row."""
        self.pages.writerow(row)
        self.pages_file.flush()

    def mark_done(self, site):
        """Record a finished site so reruns skip it."""
        with open(self.done_path, "a", encoding="utf-8") as f:
            f.write(site + "\n")
        self.done.add(site)

    def rel(self, path):
        """A path relative to --out, as stored in the CSVs."""
        return str(path.relative_to(self.out))

    def close(self):
        """Close every open output file."""
        for f in (self.forms_file, self.pages_file, self.jsonl):
            f.close()


def _parts(out_dir, stem, ext):
    """The part files for one output, in shard order."""
    return sorted(out_dir.glob(f"{stem}.part*.{ext}"),
                  key=lambda q: int(re.search(r"\.part(\d+)\.", q.name).group(1)))


def _check_header(path, got, want):
    """Exit rather than write to or merge a file whose columns differ from the current schema."""
    if got is not None and list(got) != list(want):
        log.error(f"{path}: header does not match the current schema; refusing to continue.\n"
                  f"  Use a fresh --out directory for this version of the crawler.\n"
                  f"  expected: {','.join(want)}\n  found:    {','.join(got or [])}")
        sys.exit(1)


def _merge_csv(out_dir, stem, fields, key):
    """Append part-file rows the canonical CSV does not have yet (by `key`). Returns the count added."""
    parts = _parts(out_dir, stem, "csv")
    if not parts:
        return 0
    canon = out_dir / f"{stem}.csv"
    seen, fresh = set(), not canon.exists() or canon.stat().st_size == 0
    if not fresh:
        with open(canon, newline="", encoding="utf-8") as f:
            rd = csv.DictReader(f)
            _check_header(canon, rd.fieldnames, fields)
            seen = {key(row) for row in rd}
    added = 0
    with open(canon, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if fresh:
            w.writeheader()
        for part in parts:
            with open(part, newline="", encoding="utf-8") as pf:
                rd = csv.DictReader(pf)
                _check_header(part, rd.fieldnames, fields)
                for row in rd:
                    k = key(row)
                    if k in seen:
                        continue
                    seen.add(k)
                    w.writerow(row)
                    added += 1
    return added


def _merge_jsonl(out_dir):
    """_merge_csv for forms.jsonl, keyed on (site, form_sig)."""
    parts = _parts(out_dir, "forms", "jsonl")
    if not parts:
        return 0
    canon = out_dir / "forms.jsonl"
    key = lambda d: (d.get("site"), d.get("form_sig"))
    seen = set()
    if canon.exists():
        with open(canon, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    seen.add(key(json.loads(line)))
    added = 0
    with open(canon, "a", encoding="utf-8") as f:
        for part in parts:
            with open(part, encoding="utf-8") as pf:
                for line in pf:
                    if not line.strip():
                        continue
                    k = key(json.loads(line))
                    if k in seen:
                        continue
                    seen.add(k)
                    f.write(line if line.endswith("\n") else line + "\n")
                    added += 1
    return added


def merge_parts(out_dir, clean=False):
    """Fold every shard's part files into the canonical outputs.

    Deduplicates on a row key and leaves the parts in place, so the merge is
    idempotent and safe to run after a crash: parts are the durable log, the
    canonical files are a derived view that can always be rebuilt.
    """
    if not out_dir.exists():
        return
    forms = _merge_csv(out_dir, "forms", FORM_FIELDS, lambda r: (r["site"], r["form_sig"]))
    pages = _merge_csv(out_dir, "pages", PAGE_FIELDS, lambda r: tuple(r[k] for k in PAGE_FIELDS))
    _merge_jsonl(out_dir)
    done_parts = _parts(out_dir, "sites_done", "txt")
    if done_parts:
        canon = out_dir / "sites_done.txt"
        have = set(canon.read_text(encoding="utf-8").split()) if canon.exists() else set()
        with open(canon, "a", encoding="utf-8") as f:
            for part in done_parts:
                for site in part.read_text(encoding="utf-8").split():
                    if site not in have:
                        have.add(site)
                        f.write(site + "\n")
    if forms or pages:
        log.info(f"merged: {forms} new form rows, {pages} new page rows")
    if clean:
        for stem, ext in (("forms", "csv"), ("pages", "csv"), ("forms", "jsonl"), ("sites_done", "txt")):
            for part in _parts(out_dir, stem, ext):
                part.unlink()
