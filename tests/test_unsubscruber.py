"""Tests for conf/unsubscruber.py. No network: unsubscribe_request (the one-click POST)
and unsubscribe_get (the body-link GET) are both replaced by recorders.

Run from the repository root:

    .venv/bin/python -m pytest tests/test_unsubscruber.py

The messages are synthetic. Their List-Unsubscribe headers have the shapes seen in the
real mail from the 2026-10-22/23 sign-up tests (folded Klaviyo headers, Iterable's
https-then-mailto, mailto-then-https), which the script used to mishandle, plus an
RFC 2047-encoded header, which it handled already. The body links copy the shapes
found in that mail's bodies: an "Unsubscribe" link among footer links, "Click here"
after unsubscribe wording, a Russian "по ссылке", and preference-centre links that
must not be taken for unsubscribe links.
"""
import importlib.util
import json
import re
import sqlite3
import sys
from collections import namedtuple
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "conf" / "unsubscruber.py"
SUFFIX = "5512341234"   # the script's testing leftover, appended to every URL it requests
POST = "List-Unsubscribe-Post: List-Unsubscribe=One-Click"
DAY = "primary/2026/10/23/"   # the mail server's <class>/YYYY/MM/DD/ layout

Result = namedtuple("Result", "posts gets out studies")
TEST_MAIL_DOMAIN = "mail.study.example"   # the fixture's $CRAWLER_STUDY_MAIL_DOMAIN


def load():
    spec = importlib.util.spec_from_file_location("unsubscruber", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, text="", status_code=200, url="https://shop.example/done", redirects=0):
        self.text, self.status_code, self.url = text, status_code, url
        self.history = [None] * redirects
        self.headers = {}


DONE_PAGE = FakeResponse("<h1>You have been unsubscribed.</h1>")


def message(*headers, html=None, plain=None):
    head = ["From: Shop <news@shop.example>", "To: news1234567890@study.example", "Subject: Deals"]
    if html is not None:
        head += ["Content-Type: text/html; charset=utf-8", "Content-Transfer-Encoding: 8bit"]
        body = html
    else:
        body = plain if plain is not None else "Hello"
    return ("\r\n".join(head + list(headers)) + "\r\n\r\n" + body + "\r\n").encode()


def footer(*links):
    """An HTML body ending in a footer of (text, href) links, like the real ones."""
    return ("<html><body><p>Our new arrivals are here.</p><p>"
            + " | ".join(f'<a href="{href}">{text}</a>' for text, href in links)
            + "</p></body></html>")


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Write {relative path: raw message} into <tmp_path>/mail, run main() on it, and return the
    URLs that would have been POSTed to and fetched, the printed output, and the X-Research-Study
    values sent. The results log goes beside the mail folder: <tmp_path>/unsubscribe_log.jsonl.
    $CRAWLER_STUDY_MAIL_DOMAIN is set to TEST_MAIL_DOMAIN, whatever the caller's shell says."""
    module = load()
    mail = tmp_path / "mail"
    mail.mkdir()
    monkeypatch.setenv("CRAWLER_STUDY_MAIL_DOMAIN", TEST_MAIL_DOMAIN)

    def _run(messages, fail_on=(), page=DONE_PAGE, options=()):
        posts, gets, studies = [], [], []

        def fake_post(url, study):
            posts.append(url)
            studies.append(study)
            if any(host in url for host in fail_on):
                raise ConnectionError("connection refused")
            return FakeResponse()

        def fake_get(url, study):
            gets.append(url)
            studies.append(study)
            return page

        monkeypatch.setattr(module, "unsubscribe_request", fake_post)
        monkeypatch.setattr(module, "unsubscribe_get", fake_get)
        for rel, raw in messages.items():
            path = mail / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        monkeypatch.setattr(sys, "argv", ["unsubscruber.py", str(mail), *options])
        module.main()
        return Result(posts, gets, capsys.readouterr().out, studies)

    return _run


# --- finding the URL in the header (item 2) ---

def test_folded_header_starting_with_a_space(run):
    # Klaviyo: the value starts on the next line, and long URLs are folded
    r = run({DAY + "a.eml": message(
        "List-Unsubscribe:\r\n <https://manage.kmail-lists.com/subscriptions/unsubscribe?a=Ab1&c=01\r\n 23>",
        POST)})
    assert r.posts == ["https://manage.kmail-lists.com/subscriptions/unsubscribe?a=Ab1&c=0123" + SUFFIX]


def test_https_before_mailto(run):
    # Iterable: the mailto part used to stay glued onto the URL
    r = run({DAY + "a.eml": message(
        "List-Unsubscribe: <https://links.iterable.com/e/unsub?id=42>, "
        "<mailto:unsub-42@links.iterable.com?subject=unsubscribe>", POST)})
    assert r.posts == ["https://links.iterable.com/e/unsub?id=42" + SUFFIX]


def test_mailto_before_https(run):
    r = run({DAY + "a.eml": message(
        "List-Unsubscribe: <mailto:B6601@unsub.shop.example>,\r\n <https://enews.shop.example/u?id=7>", POST)})
    assert r.posts == ["https://enews.shop.example/u?id=7" + SUFFIX]


def test_first_https_uri_is_the_one_used(run):
    r = run({DAY + "a.eml": message(
        "List-Unsubscribe: <https://first.example/u>, <https://second.example/u>", POST)})
    assert r.posts == ["https://first.example/u" + SUFFIX]


def test_rfc2047_encoded_header(run):
    # fast_mail_parser decodes =?...?= itself; this guards that the script keeps relying on it
    r = run({DAY + "a.eml": message(
        "List-Unsubscribe: =?us-ascii?Q?=3Chttps=3A//shop.example/u=3Fid=3D9=3E?=", POST)})
    assert r.posts == ["https://shop.example/u?id=9" + SUFFIX]


# --- only true one-click mail is POSTed to (item 3) ---

@pytest.mark.parametrize("headers", [
    ("List-Unsubscribe: <https://shop.example/u?id=1>",),                         # no Post header
    ("List-Unsubscribe: <https://shop.example/u?id=1>",
     "List-Unsubscribe-Post: List-Unsubscribe=Yes"),                              # wrong Post value
    ("List-Unsubscribe: <http://shop.example/u?id=1>", POST),                     # http, not https
    ("List-Unsubscribe: <mailto:unsub@shop.example>", POST),                      # mailto only
    ("List-Unsubscribe: https://shop.example/u?id=1", POST),                      # no angle brackets
], ids=["no-post-header", "wrong-post-value", "http-only", "mailto-only", "no-brackets"])
def test_not_one_click_is_not_posted(run, headers):
    r = run({DAY + "a.eml": message(*headers)})
    assert r.posts == [] and r.gets == []
    assert "Not a true OneClick" in r.out


def test_no_list_unsubscribe(run):
    r = run({DAY + "a.eml": message()})
    assert r.posts == [] and r.gets == []
    assert "No Unsubscribe header" in r.out
    assert "none in the body" in r.out


# --- missing headers (item 1) and header-name case (item 6) ---

def test_no_authentication_results_and_no_to(run):
    raw = (b"From: a@shop.example\r\nSubject: x\r\n"
           b"List-Unsubscribe: <https://shop.example/u?id=1>\r\n" + POST.encode() + b"\r\n\r\nbody\r\n")
    r = run({DAY + "a.eml": raw})
    assert r.posts == ["https://shop.example/u?id=1" + SUFFIX]
    assert "[x]" not in r.out


def test_header_names_in_any_case(run):
    r = run({DAY + "a.eml": message(
        "list-unsubscribe: <https://shop.example/u?id=1>",
        "LIST-UNSUBSCRIBE-POST: List-Unsubscribe=One-Click")})
    assert r.posts == ["https://shop.example/u?id=1" + SUFFIX]


# --- one failure does not end the run (item 4) ---

def test_one_failure_does_not_stop_the_run(run):
    r = run({
        DAY + "a.eml": message("List-Unsubscribe: <https://down.example/u>", POST),
        DAY + "b.eml": message("List-Unsubscribe: <https://up.example/u>", POST),
    }, fail_on=("down.example",))
    assert r.posts == ["https://down.example/u" + SUFFIX, "https://up.example/u" + SUFFIX]
    assert "ConnectionError: connection refused" in r.out


def test_empty_file_is_skipped(run):
    r = run({
        DAY + "empty.eml": b"",
        DAY + "b.eml": message("List-Unsubscribe: <https://up.example/u>", POST),
    })
    assert r.posts == ["https://up.example/u" + SUFFIX]
    assert "Empty file" in r.out


# --- the mail server's folder tree (item 5) ---

def test_walks_the_mail_server_tree(run):
    r = run({
        "primary/2026/10/22/a.eml": message("List-Unsubscribe: <https://a.example/u>", POST),
        "primary/2026/10/22/a.json": b"{}",
        "quarantine/2026/10/23/b.eml": message("List-Unsubscribe: <https://b.example/u>", POST),
    })
    assert r.posts == ["https://a.example/u" + SUFFIX, "https://b.example/u" + SUFFIX]


def test_missing_directory_is_an_error(tmp_path, monkeypatch, capsys):
    module = load()
    monkeypatch.setattr(sys, "argv", ["unsubscruber.py", str(tmp_path / "nope")])
    with pytest.raises(SystemExit) as stop:
        module.main()
    assert stop.value.code == 1
    assert "Not a directory" in capsys.readouterr().out


# --- the body link: when it is used ---

NEWEGG_LIKE = footer(("Customer Service", "https://shop.example/help"),
                     ("UNSUBSCRIBE", "https://shop.example/unsub?t=abc"),
                     ("Privacy Policy", "https://shop.example/privacy"))


def test_body_link_used_when_there_is_no_header(run):
    r = run({DAY + "a.eml": message(html=NEWEGG_LIKE)})
    assert r.posts == []
    assert r.gets == ["https://shop.example/unsub?t=abc" + SUFFIX]
    assert "(link text)" in r.out and "unsubscribed_text" in r.out


def test_body_link_used_when_the_header_is_not_one_click(run):
    r = run({DAY + "a.eml": message("List-Unsubscribe: <https://shop.example/u?id=1>", html=NEWEGG_LIKE)})
    assert r.posts == []
    assert r.gets == ["https://shop.example/unsub?t=abc" + SUFFIX]


def test_one_click_mail_never_gets_the_body_link(run):
    r = run({DAY + "a.eml": message("List-Unsubscribe: <https://shop.example/u?id=1>", POST, html=NEWEGG_LIKE)})
    assert r.posts == ["https://shop.example/u?id=1" + SUFFIX]
    assert r.gets == []


# --- the body link: which link ---

def test_click_here_after_unsubscribe_wording(run):
    # Pottery Barn's shape; the footer links after it must not be picked
    html = ('<p>Our new arrivals are here. <a href="https://shop.example/new">Shop now</a></p>'
            '<p>To unsubscribe from our emails, <a href="https://click.shop.example/u?x=1">Click here</a>.'
            ' <a href="https://shop.example/privacy">Privacy Policy</a></p>')
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://click.shop.example/u?x=1" + SUFFIX]
    assert "(text before the link)" in r.out


def test_footer_links_after_an_unsubscribe_mention_are_not_taken(run):
    # the word comes after the previous link ended only for "Click here", not for these
    html = ('<p>You can unsubscribe at any time by writing to us. '
            '<a href="https://shop.example/privacy">Privacy Policy</a> | '
            '<a href="https://shop.example/help">Customer Service</a></p>')
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == []


def test_russian_link_after_wording(run):
    html = ('<p>Чтобы отписаться от рассылки, перейдите <a href="https://ext.shop.example/r?q=1">по ссылке</a>.</p>')
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://ext.shop.example/r?q=1" + SUFFIX]


def test_image_link_with_unsubscribe_alt_text(run):
    html = '<a href="https://shop.example/u?t=9"><img src="x.png" alt="Unsubscribe"></a>'
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://shop.example/u?t=9" + SUFFIX]


def test_preference_centre_is_not_an_unsubscribe_link(run):
    html = footer(("Update preferences", "https://shop.example/prefs?t=1"),
                  ("Manage Subscriptions", "https://shop.example/manage?t=1"))
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == []
    assert "none in the body" in r.out


def test_resubscribe_is_not_an_unsubscribe_link(run):
    r = run({DAY + "a.eml": message(html=footer(("Resubscribe", "https://shop.example/resub?t=1")))})
    assert r.gets == []


def test_link_text_beats_link_address(run):
    html = footer(("Manage Preferences", "https://links.shop.example/unsub/prefs?t=1"),
                  ("Unsubscribe", "https://links.shop.example/unsub/all?t=1"))
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://links.shop.example/unsub/all?t=1" + SUFFIX]


def test_link_address_used_when_no_link_says_it(run):
    html = '<a href="https://shop.example/unsubscribe?t=5"><img src="footer-button.png"></a>'
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://shop.example/unsubscribe?t=5" + SUFFIX]
    assert "(link address)" in r.out


def test_mailto_body_link_is_not_requested(run):
    r = run({DAY + "a.eml": message(html=footer(("Unsubscribe", "mailto:unsub@shop.example")))})
    assert r.gets == []


def test_html_entities_in_the_address_are_decoded(run):
    html = '<a href="https://shop.example/u?a=1&amp;b=2">Unsubscribe</a>'
    r = run({DAY + "a.eml": message(html=html)})
    assert r.gets == ["https://shop.example/u?a=1&b=2" + SUFFIX]


def test_plain_text_only_mail(run):
    plain = ("Thanks for joining.\r\nPrivacy: https://shop.example/privacy\r\n"
             "To unsubscribe, visit: https://shop.example/u?t=7.\r\n")
    r = run({DAY + "a.eml": message(plain=plain)})
    assert r.gets == ["https://shop.example/u?t=7" + SUFFIX]
    assert "(plain-text part)" in r.out


# --- the page the body link led to ---

@pytest.mark.parametrize("page, outcome", [
    (FakeResponse("<h1>You’ve been unsubscribed</h1><button>Resubscribe</button>"), "unsubscribed_text"),
    (FakeResponse("<p>Successfully unsubscribed from Deals.</p>"), "unsubscribed_text"),
    (FakeResponse('<p>Are you sure? You will no longer receive our emails.</p>'
                  '<form method="post"><button type="submit">Unsubscribe</button></form>'), "needs_confirmation"),
    (FakeResponse('<form><input type="submit" value="Confirm"></form>'), "needs_confirmation"),
    (FakeResponse('<a role="button" href="#">Yes, unsubscribe me</a>'), "needs_confirmation"),
    (FakeResponse('<div id="root"></div><script>render("You have been unsubscribed")</script>'), "unclear"),
    (FakeResponse("Not found", status_code=404), "http_error"),
], ids=["done-with-resubscribe", "done", "confirm-form", "confirm-input", "role-button",
        "javascript-only", "404"])
def test_page_outcome(page, outcome):
    assert load().page_outcome(page) == outcome


# --- --dry-run ---

def test_dry_run_sends_nothing_and_shows_the_exact_requests(run):
    r = run({
        DAY + "a.eml": message("List-Unsubscribe: <https://shop.example/u?id=1>", POST),
        DAY + "b.eml": message(html=NEWEGG_LIKE),
        DAY + "c.eml": message(),
    }, options=["--dry-run"])
    assert r.posts == [] and r.gets == []
    assert "[dry-run] 3 .eml file(s) found; nothing will be sent." in r.out
    assert f"[dry-run] Would POST to: https://shop.example/u?id=1{SUFFIX}" in r.out
    assert f"[dry-run] Would GET: https://shop.example/unsub?t=abc{SUFFIX}" in r.out
    assert "Response:" not in r.out and "Body link response:" not in r.out


def test_without_dry_run_nothing_says_dry_run(run):
    r = run({DAY + "a.eml": message("List-Unsubscribe: <https://shop.example/u?id=1>", POST)})
    assert r.posts == ["https://shop.example/u?id=1" + SUFFIX]
    assert "dry-run" not in r.out


def test_outcome_and_redirects_are_printed(run):
    page = FakeResponse("<p>Successfully unsubscribed</p>", url="https://prefs.shop.example/done", redirects=2)
    r = run({DAY + "a.eml": message(html=NEWEGG_LIKE)}, page=page)
    assert "Body link response: 200 after 2 redirect(s), ending on prefs.shop.example: unsubscribed_text" in r.out


# --- --no-test-suffix and the results log ---

ONE_CLICK_A = message("List-Unsubscribe: <https://shop.example/u?id=1>", POST)


def test_no_test_suffix_sends_the_url_unchanged(run):
    r = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert r.posts == ["https://shop.example/u?id=1"]


def test_the_log_records_each_request(run, tmp_path):
    run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    [entry] = [json.loads(l) for l in (tmp_path / "unsubscribe_log.jsonl").read_text().splitlines()]
    assert entry["method"] == "POST" and entry["url"] == "https://shop.example/u?id=1"
    assert entry["status"] == 200 and entry["outcome"] == "accepted" and entry["error"] is None
    assert entry["recipient"] == "news1234567890@study.example" and entry["test_suffix"] is False


def test_a_dry_run_writes_no_log(run, tmp_path):
    run({DAY + "a.eml": ONE_CLICK_A}, options=["--dry-run"])
    assert not (tmp_path / "unsubscribe_log.jsonl").exists()


def test_a_message_is_not_unsubscribed_from_twice(run):
    first = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    again = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert first.posts == ["https://shop.example/u?id=1"] and again.posts == []
    assert "Already unsubscribed from this message" in again.out


def test_runs_with_the_test_suffix_do_not_count_as_done(run):
    run({DAY + "a.eml": ONE_CLICK_A})                                  # the default: suffix on
    real = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert real.posts == ["https://shop.example/u?id=1"]


def test_a_failed_request_is_tried_again_next_run(run):
    down = message("List-Unsubscribe: <https://down.example/u>", POST)
    first = run({DAY + "a.eml": down}, fail_on=("down.example",), options=["--no-test-suffix"])
    again = run({DAY + "a.eml": down}, options=["--no-test-suffix"])
    assert first.posts == again.posts == ["https://down.example/u"]


# --- double opt-in confirmation emails ---

@pytest.mark.parametrize("subject, body", [
    ("Please confirm your subscription", "Hello"),
    ("Confirmation email", "Hello"),
    ("One more step", "Hello"),
    ("Welcome!", "Click the button below to confirm your subscription."),
], ids=["confirm", "confirmation", "one-more-step", "body"])
def test_confirmation_emails_are_never_used(run, subject, body):
    raw = message("List-Unsubscribe: <https://shop.example/u?id=1>", POST,
                  plain=body).replace(b"Subject: Deals", f"Subject: {subject}".encode())
    r = run({DAY + "a.eml": raw})
    assert r.posts == [] and r.gets == []
    assert "sign-up confirmation" in r.out


@pytest.mark.parametrize("subject", ["Thanks for confirming your subscription", "You're confirmed!"])
def test_welcome_mail_after_confirming_is_used(run, subject):
    raw = ONE_CLICK_A.replace(b"Subject: Deals", f"Subject: {subject}".encode())
    assert run({DAY + "a.eml": raw}).posts == ["https://shop.example/u?id=1" + SUFFIX]


# --- study mode (--test-cases) ---

TREATMENT, CONTROL = "news1111111111@pilot.example", "news2222222222@pilot.example"


def study_db(path, cases=((TREATMENT, "treatment", "https://shop.example"),
                          (CONTROL, "control", "https://shop.example"))):
    """A minimal copy of the crawler's websites and test_cases tables."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE websites (id INTEGER PRIMARY KEY, url TEXT UNIQUE)")
    con.execute("CREATE TABLE test_cases (id INTEGER PRIMARY KEY, website_id INTEGER, study_id TEXT,"
                " arm TEXT, alias TEXT UNIQUE, submit_status TEXT)")
    for alias, arm, site in cases:
        con.execute("INSERT OR IGNORE INTO websites (url) VALUES (?)", (site,))
        (website_id,) = con.execute("SELECT id FROM websites WHERE url = ?", (site,)).fetchone()
        con.execute("INSERT INTO test_cases (website_id, study_id, arm, alias, submit_status)"
                    " VALUES (?, 'pilot1', ?, ?, 'success_text')", (website_id, arm, alias))
    con.commit()
    con.close()
    return str(path)


def delivered(name, recipient, raw):
    """A message and its delivery record, as the mail server writes them."""
    return {DAY + name + ".eml": raw,
            DAY + name + ".json": json.dumps({"envelope_recipient": recipient}).encode()}


def one_click(url):
    return message(f"List-Unsubscribe: <{url}>", POST)


def test_study_unsubscribes_the_treatment_alias_only(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    r = run({**delivered("1", TREATMENT, one_click("https://shop.example/u?t=T")),
             **delivered("2", CONTROL, one_click("https://shop.example/u?t=C")),
             **delivered("3", "news3333333333@pilot.example", one_click("https://other.example/u"))},
            options=["--test-cases", db])
    assert r.posts == ["https://shop.example/u?t=T" + SUFFIX]
    assert "control alias of https://shop.example: never unsubscribed" in r.out
    assert "news3333333333@pilot.example is not a study alias" in r.out


def test_study_sends_once_per_alias(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    r = run({**delivered("1", TREATMENT, one_click("https://shop.example/u?n=1")),
             **delivered("2", TREATMENT, one_click("https://shop.example/u?n=2"))},
            options=["--test-cases", db])
    assert r.posts == ["https://shop.example/u?n=1" + SUFFIX]


def test_study_prefers_one_click_over_an_earlier_body_link(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    r = run({**delivered("1", TREATMENT, message(html=NEWEGG_LIKE)),
             **delivered("2", TREATMENT, one_click("https://shop.example/u?n=2"))},
            options=["--test-cases", db])
    assert r.posts == ["https://shop.example/u?n=2" + SUFFIX] and r.gets == []


def test_study_uses_the_body_link_when_no_mail_has_one_click(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    r = run(delivered("1", TREATMENT, message(html=NEWEGG_LIKE)), options=["--test-cases", db])
    assert r.posts == [] and r.gets == ["https://shop.example/unsub?t=abc" + SUFFIX]


def test_study_waits_while_only_the_confirmation_has_arrived(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    confirm = one_click("https://shop.example/u?n=1").replace(b"Subject: Deals",
                                                               b"Subject: Please confirm your subscription")
    r = run(delivered("1", TREATMENT, confirm), options=["--test-cases", db])
    assert r.posts == [] and "Unsubscribing" not in r.out
    later = run({**delivered("1", TREATMENT, confirm),
                 **delivered("2", TREATMENT, one_click("https://shop.example/u?n=2"))},
                options=["--test-cases", db])
    assert later.posts == ["https://shop.example/u?n=2" + SUFFIX]


def test_study_takes_the_recipient_from_the_delivery_record(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    raw = one_click("https://shop.example/u?t=T").replace(b"To: news1234567890@study.example",
                                                         b"To: Shop subscribers <list@shop.example>")
    r = run(delivered("1", TREATMENT, raw), options=["--test-cases", db])
    assert r.posts == ["https://shop.example/u?t=T" + SUFFIX]


def test_study_rerun_leaves_an_unsubscribed_alias_alone(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    mail = {**delivered("1", TREATMENT, one_click("https://shop.example/u?n=1"))}
    first = run(mail, options=["--test-cases", db, "--no-test-suffix"])
    mail.update(delivered("2", TREATMENT, one_click("https://shop.example/u?n=2")))
    again = run(mail, options=["--test-cases", db, "--no-test-suffix"])
    assert first.posts == ["https://shop.example/u?n=1"] and again.posts == []
    assert "Already unsubscribed in an earlier run" in again.out


def test_study_log_names_the_test_case(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    run(delivered("1", TREATMENT, one_click("https://shop.example/u?t=T")), options=["--test-cases", db])
    [entry] = [json.loads(l) for l in (tmp_path / "unsubscribe_log.jsonl").read_text().splitlines()]
    assert entry["recipient"] == TREATMENT and entry["arm"] == "treatment"
    assert entry["site"] == "https://shop.example" and entry["test_case_id"] == 1
    assert entry["test_suffix"] is True


# --- where the results log lives (moved out of the mail folder 2026-11-09) ---

def test_the_log_survives_a_fresh_download_into_a_new_folder(run, tmp_path, monkeypatch, capsys):
    # the pilot's case: the first download was moved aside and the mail downloaded again
    run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    (tmp_path / "mail").rename(tmp_path / "mail_initial")
    again = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert again.posts == []


def test_a_log_left_inside_the_mail_folder_stops_the_run(run, tmp_path):
    (tmp_path / "mail" / "unsubscribe_log.jsonl").write_text("")
    with pytest.raises(SystemExit) as stop:
        run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert stop.value.code == 1


# --- Chrome's User-Agent, and the X-Research-Study header with the abuse contact on the mail
# server's domain at the time ---

PRODUCT = "NortheasternSecLabUnsubscribeStudy/1.0"
CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/143.0.0.0 Safari/537.36")


@pytest.mark.parametrize("domain, header", [
    ("pilot.sndbxaid.tech", f"{PRODUCT} (+https://sndbxaid.tech; abuse@pilot.sndbxaid.tech)"),
    ("round2.study.example.org", f"{PRODUCT} (+https://study.example.org; abuse@round2.study.example.org)"),
    ("example.org", f"{PRODUCT} (+https://example.org; abuse@example.org)"),
], ids=["pilot", "deeper", "no-subdomain"])
def test_study_header_for(domain, header):
    assert load().study_header_for(domain) == header


def test_the_user_agent_is_chrome_on_macos_in_the_crawlers_version():
    # if this fails after a Chrome update in the image, update CHROME_USER_AGENT's version too
    install = (SCRIPT.parents[1] / "enfbots-crawler-master" / "scripts" / "install_chrome.sh").read_text()
    agent = load().CHROME_USER_AGENT
    assert agent == CHROME
    assert re.search(r"Chrome/(\d+)\.", agent).group(1) == re.search(r"# Chrome version (\d+)", install).group(1)


def test_study_header_from_the_domain_the_mail_was_delivered_to(run):
    # a test round on a new domain needs no setting: the delivery record says where the mail
    # arrived, and the stale $CRAWLER_STUDY_MAIL_DOMAIN of the fixture loses
    r = run(delivered("1", "news1111111111@pilot2.example.org", ONE_CLICK_A))
    assert r.studies == [f"{PRODUCT} (+https://example.org; abuse@pilot2.example.org)"]
    assert f"X-Research-Study: {PRODUCT} (+https://example.org; abuse@pilot2.example.org)" in r.out


def test_study_header_in_study_mode_from_the_treatment_alias(run, tmp_path):
    db = study_db(tmp_path / "cases.sqlite")
    r = run(delivered("1", TREATMENT, one_click("https://shop.example/u?t=T")), options=["--test-cases", db])
    assert r.studies == [f"{PRODUCT} (+https://pilot.example; abuse@pilot.example)"]


def test_the_mail_domain_option_wins(run):
    r = run(delivered("1", "news1111111111@pilot2.example.org", ONE_CLICK_A),
            options=["--mail-domain", "final.example.org"])
    assert r.studies == [f"{PRODUCT} (+https://example.org; abuse@final.example.org)"]


def test_the_setting_counts_for_mail_without_a_delivery_record(run):
    r = run({DAY + "a.eml": ONE_CLICK_A})
    assert r.studies == [f"{PRODUCT} (+https://study.example; abuse@{TEST_MAIL_DOMAIN})"]


def test_nothing_is_sent_without_an_abuse_contact(run, monkeypatch):
    monkeypatch.delenv("CRAWLER_STUDY_MAIL_DOMAIN")
    r = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix"])
    assert r.posts == [] and "No mail domain" in r.out
    again = run({DAY + "a.eml": ONE_CLICK_A}, options=["--no-test-suffix", "--mail-domain", "pilot.example.org"])
    assert again.posts == ["https://shop.example/u?id=1"]      # not counted as done, so tried again


def test_a_dry_run_shows_the_study_header(run):
    r = run(delivered("1", "news1111111111@pilot2.example.org", ONE_CLICK_A), options=["--dry-run"])
    assert r.posts == [] and f"X-Research-Study: {PRODUCT} (+https://example.org; abuse@pilot2.example.org)" in r.out


def test_the_log_records_both_headers(run, tmp_path):
    run(delivered("1", "news1111111111@pilot2.example.org", ONE_CLICK_A))
    entry = json.loads((tmp_path / "unsubscribe_log.jsonl").read_text().splitlines()[-1])
    assert entry["user_agent"] == CHROME
    assert entry["study_header"] == f"{PRODUCT} (+https://example.org; abuse@pilot2.example.org)"


def test_the_requests_send_chrome_and_the_study_header_and_keep_the_proxy(monkeypatch):
    module = load()
    seen = []
    monkeypatch.setattr(module.requests, "post", lambda **kw: seen.append(("post", kw)))
    monkeypatch.setattr(module.requests, "get", lambda **kw: seen.append(("get", kw)))
    module.unsubscribe_request("https://shop.example/u", "STUDY-1")
    module.unsubscribe_get("https://shop.example/u", "STUDY-1")
    assert [m for m, _ in seen] == ["post", "get"]
    for _, kw in seen:
        assert kw["headers"]["User-Agent"] == CHROME
        assert kw["headers"]["X-Research-Study"] == "STUDY-1"
        assert kw["proxies"] == {"http": "http://127.0.0.1:8080", "https": "http://127.0.0.1:8080"}
        assert kw["verify"] is False
    assert seen[0][1]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
