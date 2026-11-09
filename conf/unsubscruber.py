"""Unsubscribe from the mail in a folder: RFC 8058 one-click POST, else the body's unsubscribe link.

    python conf/unsubscruber.py <mail dir> [--dry-run]
    python conf/unsubscruber.py <mail dir> --test-cases <db>... [--no-test-suffix] [--dry-run]

With --test-cases only treatment aliases are unsubscribed, once each. Every request is logged
to unsubscribe_log.jsonl beside the mail folder. Requests carry Chrome's User-Agent and an
X-Research-Study header naming the study and abuse@<the mail server's domain>, read from each
message's delivery record, since that domain changes between tests.
How it decides, and why, is in reports/2026-11-09_unsubscriber_report.md.
"""
import argparse
import json
import os
import pdb
import re
import sqlite3
import sys
from datetime import datetime, timezone
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests
from fast_mail_parser import parse_email

ONE_CLICK = "List-Unsubscribe=One-Click"
# Chrome on macOS, in the version the crawler's image installs (scripts/install_chrome.sh).
# Change the version together with that script.
CHROME_USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/143.0.0.0 Safari/537.36")
STUDY_HEADER = "X-Research-Study"
STUDY_PRODUCT = "NortheasternSecLabUnsubscribeStudy/1.0"

UNSUBSCRIBE_WORDS = re.compile(
    r"unsubscri|opt[\s_-]?out|remove me|abmeld|abbestell|d[ée]sabonn|d[ée]sinscri|"
    r"dar(se)? de baja|desuscri|cancelar (la |mi )?suscrip|descadastr|cancelar (a )?inscri|"
    r"disiscri|отпис|afmeld|uitschrijv", re.I)
UNSUBSCRIBE_URL = re.compile(r"unsubscri|opt[_-]?out", re.I)
GENERIC_LINK_TEXT = re.compile(
    r"((click|tap|klicken sie|cliquez|haga clic|clique) )?"
    r"(here|this link|the link|link|hier|ici|aqu[ií]|aqui|qui|по ссылке|ссылк[еуа])", re.I)

UNSUBSCRIBED_TEXT = re.compile(
    r"been unsubscribed|(you are|you're|you've|you have)( now| successfully)? unsubscribed|"
    r"successfully unsubscribed|unsubscribed successfully|unsubscribe (was |is )?(successful|complete)|"
    r"been removed from|been opted out|(you've|you have) opted out|"
    r"abgemeldet|désabonné|désinscrit|dado de baja|desuscrito|descadastrado|disiscritto|"
    r"отписан|afgemeld|uitgeschreven", re.I)
CONFIRM_BUTTON = re.compile(
    r"unsubscri|opt[\s_-]?out|confirm|remove me|^yes\b|abmeld|d[ée]sabonn|d[ée]sinscri|baja|"
    r"desuscri|descadastr|disiscri|отпис|afmeld|uitschrijv", re.I)
NOT_CONFIRM_BUTTON = re.compile(r"re-?subscri|subscribe again|keep me|stay subscribed|^(no|cancel)\b", re.I)

CONFIRMATION_SUBJECT = re.compile(
    r"\bconfirm(ation)?\b|\bverify\b|\bverification\b|\bactivate\b|\bactivation\b|"
    r"one (more|last) step|almost (done|there|finished)|double opt-?in", re.I)
CONFIRMATION_BODY = re.compile(
    r"(confirm|verify|activate) (your|my|the) (subscription|e-?mail|address|sign[- ]?up)|"
    r"click (the link|the button|below|here) to (confirm|verify|activate)", re.I)


def email_analysis(email):
    return


def unsubscribe_request(url, study):
    request = requests.post(
        url=url,
        headers={"User-Agent":CHROME_USER_AGENT,STUDY_HEADER:study,"Content-Type":"application/x-www-form-urlencoded"},
        data=b"List-Unsubscribe=One-Click",
        verify=False,
        allow_redirects=False,
        timeout=30,
        proxies={"http":"http://127.0.0.1:8080", "https":"http://127.0.0.1:8080"} #TODO: Remove proxies => these are for local testing / Can just comment out
    )
    return request


def unsubscribe_get(url, study):
    """GET a body unsubscribe link, following redirects. Same headers and testing leftovers as unsubscribe_request()."""
    request = requests.get(
        url=url,
        headers={"User-Agent":CHROME_USER_AGENT,STUDY_HEADER:study},
        verify=False,
        allow_redirects=True,
        timeout=30,
        proxies={"http":"http://127.0.0.1:8080", "https":"http://127.0.0.1:8080"} #TODO: Remove proxies => these are for local testing / Can just comment out
    )
    return request


def study_header_for(mail_domain):
    """The X-Research-Study value: the study, its page on the main domain, abuse@ on the mail domain."""
    main_domain = mail_domain.split(".", 1)[1] if mail_domain.count(".") >= 2 else mail_domain
    return f"{STUDY_PRODUCT} (+https://{main_domain}; abuse@{mail_domain})"


def mail_domain_for(record, args, case=None):
    """The mail server's domain for one request: --mail-domain, else the study alias's domain
    (study mode) or the domain the message was delivered to, else $CRAWLER_STUDY_MAIL_DOMAIN."""
    if args.mail_domain:
        return args.mail_domain
    address = record["recipient"] if case else record["delivered_to"]
    if address:
        return address.rsplit("@", 1)[-1]
    return os.environ.get("CRAWLER_STUDY_MAIL_DOMAIN", "")


def get_header(email, name):
    """All values of a header, matching its name in any case; [] if absent."""
    values = []
    for key, value in email.headers.items():
        if key.lower() == name.lower():
            values.extend(value if isinstance(value, list) else [value])
    return values


def unsubscribe_uris(values):
    """The <...> URIs of List-Unsubscribe, in order, with folding whitespace removed."""
    uris = []
    for value in values:
        for uri in re.findall(r"<([^>]*)>", value):
            uri = re.sub(r"\s+", "", uri)
            if uri:
                uris.append(uri)
    return uris


class PageParser(HTMLParser):
    """Links (text, alt, title, aria-label, and the text since the previous link), button labels
    and visible text of an HTML body or page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.buttons, self.text = [], [], []
        self._open_links, self._open_buttons = [], []
        self._since_link = ""
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "a":
            self._open_links.append({"href": a.get("href", "").strip(),
                                     "text": " ".join([a.get("title", ""), a.get("aria-label", "")]),
                                     "before": self._since_link[-100:],
                                     "button": a.get("role", "").lower() == "button"})
        elif tag == "button":
            self._open_buttons.append("")
        elif tag == "input" and a.get("type", "").lower() in ("submit", "button"):
            self.buttons.append(a.get("value", ""))
        elif tag == "img" and self._open_links:
            self._open_links[-1]["text"] += " " + a.get("alt", "")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "a" and self._open_links:
            link = self._open_links.pop()
            self.links.append(link)
            if link["button"]:
                self.buttons.append(link["text"])
            self._since_link = ""
        elif tag == "button" and self._open_buttons:
            self.buttons.append(self._open_buttons.pop())

    def handle_data(self, data):
        if self._skip:
            return
        self.text.append(data)
        self._since_link += data
        for link in self._open_links:
            link["text"] += data
        self._open_buttons = [label + data for label in self._open_buttons]


def body_unsubscribe_link(email):
    """(url, how it was found) for the body's unsubscribe link, or ("", "none in the body")."""
    page = PageParser()
    page.feed("".join(email.text_html or []))
    links = [l for l in page.links if l["href"].lower().startswith(("http://", "https://"))]
    for link in links:
        if UNSUBSCRIBE_WORDS.search(link["text"]):
            return link["href"], "link text"
    for link in links:
        words = " ".join(link["text"].split()).strip(" .:!»›>")
        if GENERIC_LINK_TEXT.fullmatch(words) and UNSUBSCRIBE_WORDS.search(link["before"]):
            return link["href"], "text before the link"
    for link in links:
        if UNSUBSCRIBE_URL.search(link["href"]):
            return link["href"], "link address"
    plain = "".join(email.text_plain or [])
    previous_end = 0
    for m in re.finditer(r"https?://[^\s<>\"']+", plain):
        before = plain[previous_end:m.start()][-100:]
        previous_end = m.end()
        if UNSUBSCRIBE_WORDS.search(before) or UNSUBSCRIBE_URL.search(m.group(0)):
            return m.group(0).rstrip(".,;)]"), "plain-text part"
    return "", "none in the body"


def page_outcome(response):
    """http_error, unsubscribed_text, needs_confirmation or unclear, for the page a GET reached."""
    if response.status_code >= 400:
        return "http_error"
    page = PageParser()
    page.feed(response.text or "")
    text = " ".join(" ".join(page.text).replace("’", "'").split())
    if UNSUBSCRIBED_TEXT.search(text):
        return "unsubscribed_text"
    for label in page.buttons:
        label = " ".join(label.split())
        if CONFIRM_BUTTON.search(label) and not NOT_CONFIRM_BUTTON.search(label):
            return "needs_confirmation"
    return "unclear"


def post_outcome(status):
    return "accepted" if status < 300 else "redirect" if status < 400 else "http_error"


def looks_like_confirmation(email):
    """A double opt-in confirmation email, which is never used for unsubscribing."""
    subject = " ".join(get_header(email, 'Subject'))
    if CONFIRMATION_SUBJECT.search(subject):
        return True
    page = PageParser()
    page.feed("".join(email.text_html or []))
    text = " ".join((" ".join(page.text) + " " + "".join(email.text_plain or [])).split())
    return bool(CONFIRMATION_BODY.search(text))


def recipient_of(file, email):
    """The envelope recipient from the mail server's .json delivery record, else the first To."""
    recipient = delivered_to(file)
    if recipient:
        return recipient
    to = getaddresses(get_header(email, 'To'))
    return to[0][1].strip().lower() if to else ""


def delivered_to(file):
    """The envelope recipient in the mail server's .json delivery record beside the .eml, or ""."""
    try:
        with open(file[:-len(".eml")] + ".json", encoding="utf-8") as f:
            return (json.load(f).get("envelope_recipient") or "").strip().lower()
    except (OSError, ValueError):
        return ""


def load_test_cases(paths):
    """alias -> its test case, read from the crawler's SQLite database(s), opened read-only."""
    cases = {}
    for path in paths:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT t.id, t.alias, t.arm, t.study_id, t.submit_status, w.url "
                "FROM test_cases t JOIN websites w ON w.id = t.website_id").fetchall()
        finally:
            con.close()
        for test_case_id, alias, arm, study_id, submit_status, site in rows:
            cases[alias.strip().lower()] = {"test_case_id": test_case_id, "arm": arm,
                                            "study_id": study_id, "submit_status": submit_status,
                                            "site": site, "db": str(path)}
    return cases


def log_beside(src):
    """The default results log: next to the mail folder, never inside it."""
    return os.path.join(os.path.dirname(os.path.abspath(src)), "unsubscribe_log.jsonl")


def read_log(path):
    entries = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    pass
    except FileNotFoundError:
        pass
    return entries


def unsubscribe(record, method, url, args, log_path, case=None):
    """Send one request (or print it under --dry-run) and append the result to the log."""
    sent = url if args.no_test_suffix else url+"5512341234"
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "file": record["file"], "recipient": record["recipient"],
             "test_case_id": case and case["test_case_id"], "site": case and case["site"],
             "arm": case and case["arm"], "method": method, "url": sent,
             "test_suffix": not args.no_test_suffix, "user_agent": CHROME_USER_AGENT,
             "study_header": None,
             "status": None, "location": None, "redirects": None, "final_host": None,
             "outcome": None, "error": None}
    mail_domain = mail_domain_for(record, args, case)
    if not mail_domain:
        entry["error"] = f"No mail domain for the {STUDY_HEADER} header's abuse contact: pass --mail-domain"
        print(f"[x] {entry['error']}; nothing sent")
    else:
        entry["study_header"] = study_header_for(mail_domain)
        print(f"{STUDY_HEADER}: {entry['study_header']}")
    if args.dry_run:
        if entry["study_header"]:
            print(f"[dry-run] Would POST to: {sent}" if method == "POST" else f"[dry-run] Would GET: {sent}")
        return
    try:
        if not entry["study_header"]:
            pass
        elif method == "POST":
            response = unsubscribe_request(sent, entry["study_header"])
            entry.update(status=response.status_code, location=response.headers.get('Location', ''),
                         outcome=post_outcome(response.status_code))
            print(f"Response: {response.status_code} {entry['location']}")
        else:
            response = unsubscribe_get(sent, entry["study_header"])
            entry.update(status=response.status_code, redirects=len(response.history),
                         final_host=urlparse(response.url).hostname, outcome=page_outcome(response))
            print(f"Body link response: {response.status_code} after {entry['redirects']} redirect(s), "
                  f"ending on {entry['final_host']}: {entry['outcome']}")
    except Exception as e:
        entry["error"] = f"{type(e).__name__}: {e}"
        print(f"[x] {method} {sent}: {entry['error']}")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_message(file):
    """Parse one .eml and print what it offers. Its record, or None for an empty file."""
    if os.path.getsize(file) == 0:
        print(f"[-] Empty file, skipped: {file}")
        return None
    with open(file, 'rb') as f:
        email = parse_email(f.read())
    unsubscribe_values = get_header(email, 'List-Unsubscribe')
    post_values = [v.strip() for v in get_header(email, 'List-Unsubscribe-Post')]
    unsubscribe_url = ""
    if not unsubscribe_values:
        print("[-] No Unsubscribe header!")
    else:
        https_uris = [u for u in unsubscribe_uris(unsubscribe_values) if u.lower().startswith("https://")]
        if not post_values:
            print("[!] Not a true OneClick process!")
        elif post_values != [ONE_CLICK]:
            print(f"[!] Not a true OneClick process! List-Unsubscribe-Post is {post_values}")
        elif not https_uris:
            print("[!] Not a true OneClick process! No https:// URI in List-Unsubscribe")
        else:
            print("[+] True OneClick!")
            # reply_to = email.headers['Reply-To']
            unsubscribe_url = https_uris[0]
    addr = (get_header(email, 'To') or [""])[0]
    print("==================")
    print(f"Email file: {file}")
    print(f"Email alias: {addr}")
    print(f"Unsubscribe link: {unsubscribe_url}")
    print(f"Authentication result: {get_header(email, 'Authentication-Results') or 'none'}")
    body_url = ""
    if not unsubscribe_url:
        body_url, how = body_unsubscribe_link(email)
        print(f"Body unsubscribe link: {body_url or '-'} ({how})")
    return {"file": os.path.abspath(file), "recipient": recipient_of(file, email),
            "delivered_to": delivered_to(file),
            "one_click_url": unsubscribe_url, "body_url": body_url,
            "confirmation": looks_like_confirmation(email)}


def unsubscribe_treatment(candidates, cases, done_recipients, args, log_path):
    """Study mode: one request per treatment alias not yet done, one-click preferred."""
    for recipient, records in candidates.items():
        case = cases[recipient]
        print(f"Unsubscribing {recipient} ({case['site']}, test case {case['test_case_id']})")
        try:
            if recipient in done_recipients:
                print("[-] Already unsubscribed in an earlier run: skipped")
                continue
            pick = next((r for r in records if r["one_click_url"]), None)
            if pick:
                method, url = "POST", pick["one_click_url"]
            else:
                pick = next((r for r in records if r["body_url"]), None)
                if pick is None:
                    print("[!] None of its mail has one-click or a body link yet: nothing sent")
                    continue
                method, url = "GET", pick["body_url"]
            print(f"Using {pick['file']}")
            unsubscribe(pick, method, url, args, log_path, case)
        except Exception as e:
            print(f"[x] {recipient}: {type(e).__name__}: {e}")
        finally:
            print("==================")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("src", help="The source directory containing .eml files which will be parsed.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the requests that would be sent; send nothing.")
    parser.add_argument("--test-cases", nargs="+", metavar="DB",
                        help="The crawler's SQLite database(s) with the study's test_cases. Only "
                             "treatment aliases are unsubscribed, once each; control aliases and "
                             "unknown recipients never are.")
    parser.add_argument("--log", help="Results file, one JSON line per request (default: "
                                      "unsubscribe_log.jsonl in the folder that holds src).")
    parser.add_argument("--no-test-suffix", action="store_true",
                        help="Send the unsubscribe URLs as they are, without the testing suffix "
                             "5512341234, so the unsubscribe is real.")
    parser.add_argument("--mail-domain",
                        help="The mail server's domain, for the X-Research-Study header's abuse@ contact. Default: "
                             "the domain each message was delivered to (the study alias's in study "
                             "mode), else $CRAWLER_STUDY_MAIL_DOMAIN.")

    args = parser.parse_args()

    if not args.src:
        sys.exit(-1)

    src = args.src
    if not os.path.isdir(src):
        print(f"[x] Not a directory: {src}")
        sys.exit(1)

    files = []
    for root, dirs, names in os.walk(src):
        dirs.sort()
        files += [os.path.join(root, f) for f in sorted(names) if f.endswith(".eml")]
    if args.dry_run:
        print(f"[dry-run] {len(files)} .eml file(s) found; nothing will be sent.")

    log_path = args.log or log_beside(src)
    stray = os.path.join(src, "unsubscribe_log.jsonl")
    if not args.log and os.path.exists(stray):
        print(f"[x] {stray} is a results log in the old place, inside the mail folder. "
              f"Move it to {log_path} (or point --log at it) so its unsubscribes aren't sent again.")
        sys.exit(1)
    # Only real requests count as done: a response came back and the testing suffix was off.
    done = [e for e in read_log(log_path) if e.get("status") is not None and not e.get("test_suffix")]
    done_files = {e.get("file") for e in done}
    done_recipients = {e.get("recipient") for e in done}

    cases = load_test_cases(args.test_cases) if args.test_cases else None
    candidates = {}
    if cases is not None:
        print(f"Study mode: {len(cases)} test case(s); only treatment aliases are unsubscribed, once each.")

    for file in files:
        try:
            record = read_message(file)
            if record is None:
                continue
            if record["confirmation"]:
                print("[-] Looks like a sign-up confirmation email: never used for unsubscribing")
            elif cases is not None:
                case = cases.get(record["recipient"])
                if case is None:
                    print(f"[-] {record['recipient'] or 'No recipient'} is not a study alias: skipped")
                elif case["arm"] != "treatment":
                    print(f"[-] {case['arm']} alias of {case['site']}: never unsubscribed")
                else:
                    print(f"[+] Treatment alias of {case['site']} (test case {case['test_case_id']})")
                    candidates.setdefault(record["recipient"], []).append(record)
            elif record["file"] in done_files:
                print("[-] Already unsubscribed from this message in an earlier run: skipped")
            elif record["one_click_url"]:
                unsubscribe(record, "POST", record["one_click_url"], args, log_path)
            elif record["body_url"]:
                unsubscribe(record, "GET", record["body_url"], args, log_path)
            # pdb.set_trace()
            print("==================")
        except Exception as e:
            print(f"[x] {file}: {type(e).__name__}: {e}")

    unsubscribe_treatment(candidates, cases, done_recipients, args, log_path)


if __name__ == "__main__":
    main()
