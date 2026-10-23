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
    rows = db.execute("SELECT field_names, form_type FROM forms").fetchall()
    found = {}
    for field_names, form_type in rows:
        for name in json.loads(field_names or "[]"):
            if name in EXPECTED:
                found[name] = form_type
    bad = 0
    for name, want in EXPECTED.items():
        got = found.get(name, "NOT DETECTED")
        flag = "ok  " if got == want else "FAIL"
        if got != want:
            bad += 1
        print(f"  {flag} {name:12} -> {got:13} (expected {want})")
    extra = len(rows) - len([n for n in found])
    print(f"\n{len(rows)} forms recorded, {len(EXPECTED) - bad}/{len(EXPECTED)} as expected. Output: {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
