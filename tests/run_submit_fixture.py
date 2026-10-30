#!/usr/bin/env python3
"""Crawl tests/fixture/submit/, then --submit to it, and check what was sent.

    python3 tests/run_submit_fixture.py

The crawler must never submit anything on its own, so this is the one test that
expects a POST, and it counts them exactly:

    crawl                 0 POSTs   detection is detection
    --submit-dry-run      0 POSTs   the form is filled in and photographed only
    --submit              1 POST    with the alias and the consent box in it
    --submit again        0 POSTs   a site is submitted to at most once, ever

Exits non-zero on any mismatch.
"""
import functools, http.server, json, os, sqlite3, subprocess, sys, tempfile, threading
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8898          # the newsletter form that should be signed up to
PORT_PHONE = 8897    # a separate site, so it gets its own submission
EMAIL = "study+{site}@example.org"
WANT_EMAIL = "study+127.0.0.1@example.org"      # {site} becomes the hostname


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serves the fixture and remembers every POST it is sent."""
    posts = []

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        Handler.posts.append((self.path, self.rfile.read(n).decode("utf-8", "replace")))
        body = b"<!doctype html><title>Thanks</title><h1>Thanks for subscribing!</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def run(cmd, env):
    print("  $ " + " ".join(cmd[1:]), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=False, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    handler = functools.partial(Handler, directory=str(ROOT / "tests" / "fixture"))
    servers = [http.server.ThreadingHTTPServer(("127.0.0.1", p), handler)
               for p in (PORT, PORT_PHONE)]
    for httpd in servers:
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    out = Path(tempfile.mkdtemp(prefix="submit-fixture-"))
    db_path = out / "crawl.db"
    env = dict(os.environ, FIND_FORMS_DATABASE_URL=f"sqlite:///{db_path}")
    base = [sys.executable, str(ROOT / "src" / "find_forms.py"), "--out", str(out), "--headless"]
    sites = out / "sites.txt"
    sites.write_text(f"http://127.0.0.1:{PORT}/submit/\n"
                     f"http://127.0.0.1:{PORT_PHONE}/submit/phone/\n")

    def query(sql):
        db = sqlite3.connect(str(db_path))
        try:
            return db.execute(sql).fetchall()
        finally:
            db.close()

    checks = []

    def check(label, ok, detail=""):
        checks.append(ok)
        print(f"  {'ok  ' if ok else 'FAIL'} {label}{'' if ok else '  <- ' + str(detail)}")

    print("\n1. crawl (detection only)")
    run(base + [str(sites), "--popup-wait", "2", "--page-delay", "0", "--max-pages", "1"], env)
    forms = query("SELECT form_type, field_names FROM forms")
    check("two subscription forms detected",
          len(forms) == 2 and {f[0] for f in forms} == {"subscription"}, forms)
    check("crawling sent no POST", not Handler.posts, Handler.posts)

    print("\n2. --submit --submit-dry-run")
    run(base + ["--submit", "--submit-email", EMAIL, "--submit-dry-run", "--popup-wait", "2",
                "--submit-delay", "0"], env)
    rows = query("SELECT outcome, email_used, fields_filled, n_checkboxes_ticked, "
                 "screenshot_filled, context_screenshot_filled, html_filled, dry_run "
                 "FROM submissions WHERE site LIKE '%:" + str(PORT) + "/%'")
    check("one submissions row for the newsletter site", len(rows) == 1, rows)
    if rows:
        outcome, email, filled, ticked, shot, ctx, html, dry = rows[0]
        filled = json.loads(filled or "[]")
        check("outcome is filled_only", outcome == "filled_only", outcome)
        check("dry_run recorded", dry == 1, dry)
        check("alias substituted", email == WANT_EMAIL, email)
        check("the required name field was filled", any(f.startswith("s_name=") for f in filled), filled)
        check("the required consent box was ticked", ticked == 1 and "s_consent=checked" in filled, filled)
        check("the optional box was left alone", not any("s_offers" in f for f in filled), filled)
        check("the pre-ticked SMS box was unticked", "s_sms=unticked_sms" in filled, filled)
        check("filled form photographed", bool(shot) and (out / shot).exists(), shot)
        check("filled form in context", bool(ctx) and (out / ctx).exists(), ctx)
        check("filled HTML saved", bool(html) and (out / html).exists(), html)
        if html and (out / html).exists():
            saved = (out / html).read_text()
            check("saved HTML holds the alias", WANT_EMAIL in saved)
            check("saved filename marks it as the filled one", "_filled." in html, html)
    check("a dry run sent no POST", not Handler.posts, Handler.posts)

    print("\n2b. the form demanding a phone number")
    # Since 2026-10-30 the refusal happens at detection, so --submit never picks
    # the form up at all: the reason lives in `forms`, not in `submissions`.
    rows = query("SELECT eligible, reject_reason, form_type FROM forms "
                 f"WHERE site LIKE '%:{PORT_PHONE}/%'")
    check("one form found on the phone site", len(rows) == 1, rows)
    if rows:
        check("still typed a subscription", rows[0][2] == "subscription", rows[0][2])
        check("but marked ineligible", rows[0][0] == 0, rows[0][0])
        check("with the reason recorded", rows[0][1] == "phone", rows[0][1])
    check("so --submit never opened it at all",
          not query(f"SELECT 1 FROM submissions WHERE site LIKE '%:{PORT_PHONE}/%'"))

    print("\n3. --submit (for real)")
    run(base + ["--submit", "--submit-email", EMAIL, "--popup-wait", "2",
                "--submit-delay", "0"], env)
    check("exactly one POST", len(Handler.posts) == 1, Handler.posts)
    check("the phone form was never POSTed to",
          not any(p == "/submitted-phone" for p, _ in Handler.posts), Handler.posts)
    if Handler.posts:
        path, body = Handler.posts[0]
        sent = urllib.parse.parse_qs(body)      # form-urlencoded: + and @ are escaped
        check("POSTed to the form's action", path == "/submitted", path)
        check("the alias was sent", sent.get("s_email") == [WANT_EMAIL], sent)
        check("the required name was sent", sent.get("s_name") == ["Alex"], sent)
        check("consent was sent", "s_consent" in sent, sent)
        check("the optional box was not sent", "s_offers" not in sent, sent)
        check("SMS was not opted into", "s_sms" not in sent, sent)
    rows = query("SELECT outcome, context_screenshot_after, result_text, http_status_after, "
                 "result, success_keywords, failure_keywords, submit_text_used "
                 f"FROM submissions WHERE dry_run = 0 AND site LIKE '%:{PORT}/%'")
    check("one live submissions row", len(rows) == 1, rows)
    if rows:
        outcome, ctx_after, text, status, result, ok_kw, bad_kw, how = rows[0]
        ok_kw = json.loads(ok_kw or "[]")
        check("outcome is submitted", outcome == "submitted", outcome)
        check("result page photographed", bool(ctx_after) and (out / ctx_after).exists(), ctx_after)
        check("result page text captured", "Thanks for subscribing" in (text or ""), text)
        check("result status recorded", status == 200, status)
        check("verdict is success_text", result == "success_text", result)
        check("the newly appeared keyword counted", "thanks for subscribing" in ok_kw, ok_kw)
        check("the keyword already on the page did not count",
              "check your inbox" not in ok_kw, ok_kw)
        check("no failure keywords", json.loads(bad_kw or "[]") == [], bad_kw)
        check("submitted via Subscribe, not the No thanks button",
              "subscribe" in (how or "").lower(), how)

    print("\n4. --submit again (a site is submitted to once)")
    run(base + ["--submit", "--submit-email", EMAIL, "--popup-wait", "2",
                "--submit-delay", "0"], env)
    check("no second POST", len(Handler.posts) == 1, Handler.posts)
    check("no extra row", len(query(
        f"SELECT 1 FROM submissions WHERE dry_run = 0 AND site LIKE '%:{PORT}/%'")) == 1)

    httpd.shutdown()
    bad = checks.count(False)
    print(f"\n{len(checks) - bad}/{len(checks)} checks passed, "
          f"{len(Handler.posts)} POST(s) total. Output: {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
