#!/usr/bin/env python3
"""Where a control/treatment sign-up test stands, site by site, and what the unsubscribes did.

Reads the mail downloaded from the study's mail server (the <class>/YYYY/MM/DD/ tree with
each message's .json delivery record), the crawler's test_cases, and the results log of
conf/unsubscruber.py. Changes nothing.

    .venv/bin/python scripts/pilot_report.py --mail testrun/pilot1/mail \\
        --test-cases testrun/discovery-3_p*.sqlite --study-id pilot1

Per site and arm it counts the mail received, leaving out double opt-in confirmations, and
lists confirmations still to be opened. Once the treatment alias has really been unsubscribed
(the testing suffix off), mail after the unsubscribe plus a grace period decides the outcome:

    WORKED          the treatment alias gets no more mail, the control alias still does
    FAILED          the treatment alias is still mailed
    INCONCLUSIVE    neither alias has had mail since, so nothing can be told yet
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fast_mail_parser import parse_email

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("unsubscruber", ROOT / "conf" / "unsubscruber.py")
u = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u)

CONFIRM_LINK = re.compile(r"confirm|verif|activat|opt-?in", re.I)
# The way out of a confirmation email, which must never be offered as the link to open:
# Grab Calendar's reads "If you did not request this, cancel here: <url>"
NOT_CONFIRM_LINK = re.compile(r"cancel|unsubscri|opt-?out|not request|didn'?t request", re.I)


def parse_time(text):
    try:
        t = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def received_at(eml):
    """When the mail server received the message: its delivery record, else the file's time."""
    try:
        with open(eml[:-len(".eml")] + ".json", encoding="utf-8") as f:
            t = parse_time(json.load(f).get("received_utc"))
            if t:
                return t
    except (OSError, ValueError):
        pass
    return datetime.fromtimestamp(os.path.getmtime(eml), timezone.utc)


def confirm_link(email):
    """The link a confirmation email asks to be opened: in the HTML part, a link whose words or
    address say confirm; else, in the plain-text part, a URL after such words or containing them
    (Grab Calendar's HTML part has no links at all). Cancel and unsubscribe links never count."""
    page = u.PageParser()
    page.feed("".join(email.text_html or []))
    for link in page.links:
        words = link["text"] + " " + link["href"]
        if link["href"].startswith("http") and CONFIRM_LINK.search(words) and not NOT_CONFIRM_LINK.search(words):
            return link["href"]
    plain = "".join(email.text_plain or [])
    previous_end = 0
    for m in re.finditer(r"https?://[^\s<>\"']+", plain):
        before, previous_end = plain[previous_end:m.start()][-100:], m.end()
        url = m.group(0).rstrip(".,;)]")
        if NOT_CONFIRM_LINK.search(before + " " + url):
            continue
        if CONFIRM_LINK.search(before) or CONFIRM_LINK.search(url):
            return url
    return ""


def read_mail(mail_dir):
    """recipient -> list of messages (time, subject, confirmation?, confirm link), oldest first."""
    by_recipient = {}
    for root, dirs, names in os.walk(mail_dir):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(root, name)
            if not name.endswith(".eml") or os.path.getsize(path) == 0:
                continue
            with open(path, "rb") as f:
                email = parse_email(f.read())
            confirmation = u.looks_like_confirmation(email)
            by_recipient.setdefault(u.recipient_of(path, email), []).append({
                "time": received_at(path),
                "subject": " ".join(u.get_header(email, "Subject")),
                "confirmation": confirmation,
                "link": confirm_link(email) if confirmation else "",
            })
    for messages in by_recipient.values():
        messages.sort(key=lambda m: m["time"])
    return by_recipient


# Outcomes that mean the unsubscribe went through, as far as the request can tell. A GET whose
# page still wanted a click (needs_confirmation) or said nothing (unclear) did not finish it;
# completed_by_hand is a log line added for an unsubscribe a person then finished in a browser.
COMPLETED = {"accepted", "redirect", "unsubscribed_text", "completed_by_hand"}


def real_unsubscribes(log_path):
    """recipient -> its real unsubscribe: an answer came back and no testing suffix. The first
    that completed it if any did (Newegg's GET needed finishing by hand, so the clock starts
    then), else the first attempt."""
    attempts = {}
    for e in u.read_log(log_path):
        t = parse_time(e.get("time"))
        if e.get("status") is None or e.get("test_suffix") or not t:
            continue
        attempts.setdefault(e["recipient"], []).append({**e, "time": t})
    chosen = {}
    for recipient, entries in attempts.items():
        entries.sort(key=lambda e: e["time"])
        chosen[recipient] = next((e for e in entries if e.get("outcome") in COMPLETED), entries[0])
    return chosen


def site_outcome(treatment_mail, unsub, after, now, cutoff):
    if unsub is None:
        if any(not m["confirmation"] for m in treatment_mail):
            return "ready to unsubscribe"
        if treatment_mail:
            return "waiting: open the confirmation"
        return "waiting for mail"
    if now < cutoff:
        return f"grace period until {cutoff:%Y-%m-%d %H:%M} UTC"
    if after["treatment"]:
        return "FAILED"
    if after["control"]:
        return "WORKED"
    return "INCONCLUSIVE"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--mail", required=True, help="the downloaded mail tree")
    p.add_argument("--test-cases", nargs="+", required=True, metavar="DB", help="the crawler's SQLite database(s)")
    p.add_argument("--study-id", help="only this study's test cases (the sign-up crawl id, e.g. pilot1)")
    p.add_argument("--log", help="the unsubscriber's results log (default: unsubscribe_log.jsonl "
                                 "in the folder that holds --mail, where the unsubscriber writes it)")
    p.add_argument("--grace-days", type=float, default=2, help="mail this soon after the unsubscribe doesn't count (default 2)")
    p.add_argument("--show-links", action="store_true", help="print the links in confirmation emails")
    p.add_argument("--now", help=argparse.SUPPRESS)   # for tests: the time to report at
    args = p.parse_args(argv)

    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    cases = {a: c for a, c in u.load_test_cases(args.test_cases).items()
             if not args.study_id or c["study_id"] == args.study_id}
    if not cases:
        print("No test cases found" + (f" for study {args.study_id}" if args.study_id else ""))
        return 1
    mail = read_mail(args.mail)
    unsubs = real_unsubscribes(args.log or u.log_beside(args.mail))
    grace = timedelta(days=args.grace_days)

    sites = {}
    for alias, case in cases.items():
        sites.setdefault(case["site"], {})[case["arm"]] = alias

    counts = {}
    print(f"{'site':34} {'arm':9} {'sign-up':14} {'mails':>5} {'confirm':>7} {'after':>5}  unsubscribed")
    to_confirm = []
    for site in sorted(sites):
        arms = sites[site]
        unsub = unsubs.get(arms.get("treatment"))
        cutoff = unsub["time"] + grace if unsub else None
        after = {}
        for arm in ("treatment", "control"):
            alias = arms.get(arm)
            messages = mail.get(alias, []) if alias else []
            usable = [m for m in messages if not m["confirmation"]]
            confirms = [m for m in messages if m["confirmation"]]
            after[arm] = sum(1 for m in usable if cutoff and m["time"] > cutoff)
            if confirms and not usable:
                to_confirm += [(site, arm, alias, m) for m in confirms]
            done = ""
            if arm == "treatment" and unsub:
                done = (f"{unsub['time']:%Y-%m-%d %H:%M} {unsub['method']} {unsub['status']} "
                        f"{unsub.get('outcome') or ''}").strip()
            status = cases[alias]["submit_status"] if alias else "-"
            print(f"{site[:34]:34} {arm:9} {status[:14]:14} {len(usable):>5} {len(confirms):>7} "
                  f"{after[arm] if cutoff else '-':>5}  {done}")
        outcome = site_outcome(mail.get(arms.get("treatment"), []), unsub, after, now, cutoff)
        counts[outcome.split(":")[0].split(" until")[0]] = counts.get(outcome.split(":")[0].split(" until")[0], 0) + 1
        print(f"{'':34} -> {outcome}")
    print()
    print("Outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"'after' counts mail more than {args.grace_days:g} day(s) after the treatment alias's unsubscribe.")
    if to_confirm:
        print("\nConfirmations to open (no other mail has arrived for these aliases yet):")
        for site, arm, alias, m in to_confirm:
            print(f"  {site} {arm} {alias}: {m['subject'][:60]!r} received {m['time']:%Y-%m-%d %H:%M}")
            if args.show_links and m["link"]:
                print(f"    {m['link']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
