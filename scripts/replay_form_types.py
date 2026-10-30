#!/usr/bin/env python3
"""Re-run the form-type rules over forms already collected, and report what changes.

    python3 scripts/replay_form_types.py [outputs/<run> ...]

Reads each run's recorded form_type and re-classifies the same form from the
HTML saved beside it, so a change to FORM_TYPES can be checked against real
pages in a second instead of by re-crawling. This is what the 2026-10-23 audit
was done by hand.

Two things make it an indication rather than a verdict, and both only ever
produce *extra* disagreement, never hide a real one:

  * The text around a form is not saved, only the form's own. The rules
    normally also read the wording near it, so a form typed by its surroundings
    may come out differently here.
  * A run from before a rule change was classified by the older rules, so
    disagreement there may be the change working as intended.

Read a disagreement as "go and look at this form", not as a failure.
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from crawler.classify import form_type, vendor      # noqa: E402

_INPUT_TYPE = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?([a-zA-Z]+)", re.I)
_BARE_INPUT = re.compile(r"<input\b(?![^>]*\btype\s*=)", re.I)


def input_types(html):
    """Every input type in the saved markup; a typeless <input> is a text box."""
    found = {m.lower() for m in _INPUT_TYPE.findall(html)}
    if _BARE_INPUT.search(html):
        found.add("text")
    return sorted(found)


def replay(run_dir):
    csv_path = run_dir / "forms.csv"
    if not csv_path.exists():
        return None
    reader = csv.DictReader(open(csv_path, encoding="utf-8"))
    if "form_type" not in (reader.fieldnames or []):
        # Before 2026-10-22 the column was a login_like boolean, so there is
        # nothing here to compare a type against.
        return "pre_form_type"
    rows, changed, missing = 0, [], 0
    was, now = Counter(), Counter()
    for r in reader:
        html_rel = r.get("html_file") or ""
        html_path = run_dir / html_rel if html_rel else None
        if not html_path or not html_path.exists():
            missing += 1
            continue
        html = html_path.read_text(encoding="utf-8", errors="replace")
        rows += 1
        # form_text stands in for the wording around the form, which is not saved.
        got = form_type(html, r.get("form_text") or "", r.get("page_url") or "",
                        input_types(html))
        old = r.get("form_type") or "?"
        was[old] += 1
        now[got] += 1
        if got != old:
            changed.append((r["site"], old, got, vendor(html)))
    return rows, missing, was, now, changed


def main():
    dirs = [Path(a) for a in sys.argv[1:]] or sorted(
        p.parent for p in ROOT.glob("outputs/*/forms.csv"))
    total = total_changed = 0
    for run_dir in dirs:
        result = replay(run_dir)
        if result == "pre_form_type":
            print(f"\n{run_dir.name}: skipped, recorded before form_type existed")
            continue
        if not result:
            continue
        rows, missing, was, now, changed = result
        if not rows:
            continue
        total += rows
        total_changed += len(changed)
        print(f"\n{run_dir.name}: {rows} forms re-classified"
              + (f", {missing} without saved HTML" if missing else ""))
        print(f"  recorded : {dict(was.most_common())}")
        print(f"  replayed : {dict(now.most_common())}")
        for site, old, got, ven in changed[:12]:
            print(f"    {site[:46]:48} {old} -> {got}" + (f"  [{ven}]" if ven else ""))
        if len(changed) > 12:
            print(f"    ... and {len(changed) - 12} more")
    print(f"\n{total} forms, {total_changed} would be typed differently by the current rules.")
    print("Spot-check those against their screenshots before concluding anything.")


if __name__ == "__main__":
    main()
