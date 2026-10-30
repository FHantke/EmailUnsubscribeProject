#!/usr/bin/env python3
"""Crawl tests/fixture/ and check every form is found and typed as expected.

    python3 tests/run_fixture.py

Serves the fixture on a local port, runs the crawler against it, and compares
form_type per form against what the fixture is built to produce. Exits non-zero
on any mismatch. The expectations double as documentation: each one is a case
the rules got wrong at some point.
"""
import functools, http.server, json, os, sqlite3, subprocess, sys, tempfile, threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8899

# field name -> expected form_type
EXPECTED = {
    "a_news": "subscription",        # plain footer-style newsletter box
    "b_login": "login",              # has a password box
    "c_already": "subscription",     # "Already subscribed? Sign in" must not make it login
    "d_checkout": "checkout",
    "e_contact": "contact",
    "f_comment": "comment",
    "g_footer": "subscription",      # footer that also invites contact
    "h_twostep": "login",            # email-only, but on a /login address
    "i_quote": "unknown",            # a quote request is not a subscription
    "j_esp": "subscription",         # recognised by Mailchimp embed markup alone
    "k_register": "login",           # "Create a New Account", no password box
    "l_bottomup": "subscription",    # no <form> tag, <span> button, Spanish wording
    "m_jobs": "unknown",             # job application: "joining our team" must not count
    "n_discount": "subscription",    # discount popup on a page whose header says Sign in
    "o_sticky": "subscription",      # newsletter bar on a page mentioning checkout
    "p_shadow": "subscription",      # inside open shadow DOM
    "q_delayed": "subscription",     # appears only in the after_delay phase
    "r_iframe": "subscription",      # inside an iframe
    "s_picker": "subscription",      # a country picker beside the real submit
    "t_vendor": "subscription",      # Mailchimp embed; its dropdown must not retype it
}

# field name -> (column, expected value). The columns added 2026-10-30, where
# what a form is wired to and whether the study may use it are the point.
EXPECTED_COLS = {
    "t_vendor": {
        "vendor": "mailchimp",                 # from the list-manage.com action
        "captcha_type": "recaptcha_v2",
        "captcha_visible": 1,
    },
    "a_news": {"vendor": "", "captcha_type": ""},
}

# field name -> expected submit_text. Only where which element was picked as the
# submit button is itself the point of the case.
EXPECTED_SUBMIT = {
    # royalcaribbean.com: the <button> country picker must lose to the
    # <a role=button type=submit>, whose spinner/label/icon children must not
    # disqualify it.
    "s_picker": ["Sign Up"],
}


def serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    httpd = serve(ROOT / "tests" / "fixture")
    out = Path(tempfile.mkdtemp(prefix="fixture-run-"))
    sites = out / "sites.txt"
    sites.write_text(f"http://127.0.0.1:{PORT}/\nhttp://127.0.0.1:{PORT}/login/\n")
    cmd = [sys.executable, str(ROOT / "src" / "find_forms.py"), str(sites),
           "--out", str(out), "--headless",
           "--popup-wait", "5", "--page-delay", "0", "--max-pages", "1"]
    # Into a throwaway database, so a test run never touches the real one.
    env = dict(os.environ, FIND_FORMS_DATABASE_URL=f"sqlite:///{out / 'crawl.db'}")
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=False, env=env)
    httpd.shutdown()

    db = sqlite3.connect(str(out / "crawl.db"))
    extra = sorted({c for cols in EXPECTED_COLS.values() for c in cols})
    rows = db.execute(
        "SELECT field_names, form_type, submit_text, form_text, "
        + ", ".join(extra) + " FROM forms").fetchall()
    found, submits, cols, texts = {}, {}, {}, {}
    for field_names, form_type, submit_text, form_text, *rest in rows:
        for name in json.loads(field_names or "[]"):
            if name in EXPECTED:
                found[name] = form_type
                submits[name] = json.loads(submit_text or "[]")
                cols[name] = dict(zip(extra, rest))
                texts[name] = form_text or ""
    bad = 0
    for name, want in EXPECTED.items():
        got = found.get(name, "NOT DETECTED")
        flag = "ok  " if got == want else "FAIL"
        if got != want:
            bad += 1
        print(f"  {flag} {name:12} -> {got:13} (expected {want})")
    for name, want in EXPECTED_SUBMIT.items():
        got = submits.get(name, "NOT DETECTED")
        flag = "ok  " if got == want else "FAIL"
        if got != want:
            bad += 1
        print(f"  {flag} {name:12} submit_text {got} (expected {want})")
    for name, want in EXPECTED_COLS.items():
        for col, value in want.items():
            got = cols.get(name, {}).get(col, "NOT DETECTED")
            flag = "ok  " if got == value else "FAIL"
            if got != value:
                bad += 1
            print(f"  {flag} {name:12} {col:15} = {got!r} (expected {value!r})")
    # A dropdown's choices are not the form's wording.
    for name, leak in (("t_vendor", "United States"), ("t_vendor", "Contact us for enquiries")):
        got = leak not in texts.get(name, "")
        if not got:
            bad += 1
        print(f"  {'ok  ' if got else 'FAIL'} {name:12} form_text leaves out {leak!r}")
    extra = len(rows) - len([n for n in found])
    n = (len(EXPECTED) + len(EXPECTED_SUBMIT)
         + sum(len(v) for v in EXPECTED_COLS.values()) + 2)
    print(f"\n{len(rows)} forms recorded, {n - bad}/{n} checks as expected. Output: {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
