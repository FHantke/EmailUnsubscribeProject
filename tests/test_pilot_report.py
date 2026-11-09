"""Tests for scripts/pilot_report.py, on a synthetic mail tree, test_cases table and log.

Run from the repository root:  .venv/bin/python -m pytest tests/test_pilot_report.py
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pilot_report.py"
spec = importlib.util.spec_from_file_location("pilot_report", SCRIPT)
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)

SITES = {"https://a.example": ("news1000000001@pilot.example", "news1000000002@pilot.example"),
         "https://b.example": ("news2000000001@pilot.example", "news2000000002@pilot.example"),
         "https://c.example": ("news3000000001@pilot.example", "news3000000002@pilot.example"),
         "https://d.example": ("news4000000001@pilot.example", "news4000000002@pilot.example")}


def db(path):
    if path.exists():   # a test that reports twice reuses it
        return str(path)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE websites (id INTEGER PRIMARY KEY, url TEXT)")
    con.execute("CREATE TABLE test_cases (id INTEGER PRIMARY KEY, website_id INTEGER, study_id TEXT,"
                " arm TEXT, alias TEXT, submit_status TEXT)")
    for i, (site, (treatment, control)) in enumerate(SITES.items(), 1):
        con.execute("INSERT INTO websites VALUES (?, ?)", (i, site))
        con.execute("INSERT INTO test_cases (website_id, study_id, arm, alias, submit_status)"
                    " VALUES (?, 'pilot1', 'treatment', ?, 'success_text')", (i, treatment))
        con.execute("INSERT INTO test_cases (website_id, study_id, arm, alias, submit_status)"
                    " VALUES (?, 'pilot1', 'control', ?, 'success_text')", (i, control))
    con.execute("INSERT INTO websites VALUES (9, 'https://old.example')")
    con.execute("INSERT INTO test_cases (website_id, study_id, arm, alias, submit_status)"
                " VALUES (9, 'round3', 'test', 'test1@test.invalid', 'success_text')")
    con.commit()
    con.close()
    return str(path)


def deliver(mail, n, recipient, day, subject="Deals", html=""):
    folder = mail / "primary" / "2026" / "11" / f"{day:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    head = f"From: shop@x.example\r\nTo: {recipient}\r\nSubject: {subject}\r\n"
    if html:
        head += "Content-Type: text/html\r\n"
    (folder / f"{n}.eml").write_bytes((head + "\r\n" + (html or "Hi") + "\r\n").encode())
    (folder / f"{n}.json").write_text(json.dumps(
        {"envelope_recipient": recipient, "received_utc": f"2026-11-{day:02d}T12:00:00+00:00"}))


def unsubscribed(mail, recipient, day, test_suffix=False):
    with open(mail.parent / "unsubscribe_log.jsonl", "a") as f:
        f.write(json.dumps({"time": f"2026-11-{day:02d}T13:00:00+00:00", "recipient": recipient,
                            "method": "POST", "status": 200, "outcome": "accepted",
                            "test_suffix": test_suffix}) + "\n")


@pytest.fixture
def pilot(tmp_path):
    """Site a: worked. Site b: failed. Site c: no mail since to either. Site d: only its
    confirmation emails so far."""
    mail = tmp_path / "mail"
    (ta, ca), (tb, cb), (tc, cc), (td, cd) = SITES.values()
    for n, (who, day) in enumerate([(ta, 10), (ca, 10), (ta, 11), (ca, 15), (ca, 18),
                                    (tb, 10), (cb, 10), (tb, 16), (cb, 16),
                                    (tc, 10), (cc, 10)]):
        deliver(mail, n, who, day)
    deliver(mail, 50, td, 10, "Please confirm your subscription",
            '<a href="https://d.example/confirm?t=1">Confirm</a>')
    deliver(mail, 51, cd, 10, "Please confirm your subscription")
    for who in (ta, tb, tc):
        unsubscribed(mail, who, 11)
    return tmp_path, mail


def run(capsys, tmp_path, mail, *extra):
    code = report.main(["--mail", str(mail), "--test-cases", db(tmp_path / "c.sqlite"),
                        "--study-id", "pilot1", "--now", "2026-11-20T00:00:00+00:00", *extra])
    return code, capsys.readouterr().out


def outcomes(out):
    return [l.split("-> ")[1] for l in out.splitlines() if "-> " in l]


def test_outcomes_per_site(capsys, pilot):
    code, out = run(capsys, *pilot)
    assert code == 0
    assert outcomes(out) == ["WORKED", "FAILED", "INCONCLUSIVE", "waiting: open the confirmation"]


def test_mail_inside_the_grace_period_does_not_count(capsys, pilot):
    tmp_path, mail = pilot
    # treatment a got mail on the 11th at 12:00, before its unsubscribe at 13:00; a message an
    # hour after the unsubscribe is still inside the 2-day grace period
    deliver(mail, 60, SITES["https://a.example"][0], 12)
    assert outcomes(run(capsys, tmp_path, mail)[1])[0] == "WORKED"


def test_still_in_the_grace_period(capsys, pilot):
    tmp_path, mail = pilot
    code = report.main(["--mail", str(mail), "--test-cases", db(tmp_path / "c.sqlite"),
                        "--study-id", "pilot1", "--now", "2026-11-12T00:00:00+00:00"])
    assert outcomes(capsys.readouterr().out)[0] == "grace period until 2026-11-13 13:00 UTC"


def test_unsubscribes_with_the_test_suffix_do_not_count(capsys, tmp_path):
    mail = tmp_path / "mail"
    treatment, control = SITES["https://a.example"]
    deliver(mail, 1, treatment, 10)
    deliver(mail, 2, control, 10)
    unsubscribed(mail, treatment, 11, test_suffix=True)
    assert outcomes(run(capsys, tmp_path, mail)[1])[0] == "ready to unsubscribe"


def test_confirmations_listed_and_links_only_on_request(capsys, pilot):
    out = run(capsys, *pilot)[1]
    assert "Confirmations to open" in out and "news4000000001@pilot.example" in out
    assert "https://d.example/confirm?t=1" not in out
    assert "https://d.example/confirm?t=1" in run(capsys, *pilot, "--show-links")[1]


def test_other_studies_are_left_out(capsys, pilot):
    out = run(capsys, *pilot)[1]
    assert "old.example" not in out


def test_confirmation_link_from_the_plain_text_part_not_the_cancel_link(capsys, tmp_path):
    # Grab Calendar's shape: no links in the HTML part; in the plain part the confirmation
    # link, then "If you did not request this, cancel here: <url>"
    mail = tmp_path / "mail"
    folder = mail / "primary" / "2026" / "11" / "09"
    folder.mkdir(parents=True)
    treatment = SITES["https://a.example"][0]
    (folder / "1.eml").write_bytes((
        f"From: hi@a.example\r\nTo: {treatment}\r\nSubject: Confirm your A subscription\r\n"
        "Content-Type: multipart/alternative; boundary=b\r\n\r\n--b\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "Click the link and press Confirm to subscribe to A:\r\nhttps://a.example/s/confirm/abc\r\n"
        "If you did not request this, cancel here:\r\nhttps://a.example/s/xyz\r\n"
        "--b\r\nContent-Type: text/html\r\n\r\n<p>Press <b>Confirm</b> to subscribe.</p>\r\n--b--\r\n").encode())
    (folder / "1.json").write_text(json.dumps(
        {"envelope_recipient": treatment, "received_utc": "2026-11-09T16:51:00+00:00"}))
    out = run(capsys, tmp_path, mail, "--show-links")[1]
    assert "https://a.example/s/confirm/abc" in out
    assert "https://a.example/s/xyz" not in out


def test_the_clock_starts_when_the_unsubscribe_was_completed(capsys, tmp_path):
    # Newegg's shape: the GET's page wanted the address and a button press, which a person then
    # did by hand; the grace period runs from then, not from the GET
    mail = tmp_path / "mail"
    treatment, control = SITES["https://a.example"]
    deliver(mail, 1, treatment, 10)
    deliver(mail, 2, control, 10)
    with open(mail.parent / "unsubscribe_log.jsonl", "a") as f:
        for day, method, outcome in ((11, "GET", "needs_confirmation"), (14, "MANUAL", "completed_by_hand")):
            f.write(json.dumps({"time": f"2026-11-{day:02d}T13:00:00+00:00", "recipient": treatment,
                                "method": method, "status": 200, "outcome": outcome,
                                "test_suffix": False}) + "\n")
    code = report.main(["--mail", str(mail), "--test-cases", db(tmp_path / "c.sqlite"),
                        "--study-id", "pilot1", "--now", "2026-11-15T00:00:00+00:00"])
    out = capsys.readouterr().out
    assert "grace period until 2026-11-16 13:00 UTC" in outcomes(out)[0]
    assert "MANUAL 200 completed_by_hand" in out
