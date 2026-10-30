#!/usr/bin/env python3
"""Check the form-type, vendor and ranking rules without starting a browser.

    python3 tests/test_classify.py

These are the rules that get edited, so they are the ones worth being able to
re-check in a second rather than in a two-minute fixture crawl. Every case here
is one the rules got wrong at some point - the dates refer to CLAUDE.md's
method history. The browser half of detection is still covered by
tests/run_fixture.py, which this does not replace.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from crawler.classify import form_type, rank, vendor      # noqa: E402

PAGE = "example.com/"

# (name, html, nearby text, page address + action, input types, expected type)
TYPE_CASES = [
    ("plain newsletter box",
     "<form><h2>Newsletter</h2><input type=email></form>", "Subscribe to our newsletter",
     PAGE, ["email"], "subscription"),

    # A password box is hard evidence and ignores the rule's `unless`.
    ("password box wins over newsletter wording",
     "<form><input type=email><input type=password></form>", "Subscribe to our newsletter",
     PAGE, ["email", "password"], "login"),
    ("a hidden password box still counts",
     "<form><input type=email><input type=password style=display:none></form>", "",
     PAGE, ["email", "password"], "login"),

    # 2026-10-23: site chrome around a form was retyping it. Each of these is a
    # real form from the isec_sample_run5_undetect audit.
    ("'Already subscribed? Sign in' stays a subscription",
     "<form><input type=email></form>", "Join our newsletter. Already subscribed? Sign in",
     PAGE, ["email"], "subscription"),
    ("a discount popup on a page whose header says Sign in",
     "<form><input type=email></form>", "Sign in  Sign up and receive $100 OFF your cruise",
     PAGE, ["email"], "subscription"),
    ("a newsletter bar on a shop page mentioning checkout",
     "<form><input type=email></form>", "Checkout  Cart  Subscribe for weekly deals",
     PAGE, ["email"], "subscription"),
    ("a footer offering a newsletter and a way to get in touch",
     "<form><input type=email></form>", "Newsletter signup. Contact us for help.",
     PAGE, ["email"], "subscription"),

    # 2026-10-22/23: these must not be swept into the target category.
    ("a quote request is not a subscription",
     "<form><input type=email></form>", "Request a free quote for your project",
     PAGE, ["email"], "unknown"),
    ("a job application is not a subscription",
     "<form class=join-us><input type=email></form>", "Interested in joining our team?",
     PAGE, ["email"], "unknown"),

    # Recognised by embed markup alone, with no newsletter wording anywhere.
    ("a Mailchimp embed with no wording",
     "<form action='https://x.us1.list-manage.com/subscribe/post'><input type=email></form>",
     "Stay updated", PAGE, ["email"], "subscription"),

    ("a search box mentioning email",
     "<form><input type=search name=q></form>", "Search our site",
     PAGE, ["search"], "search"),

    # 2026-10-30: the address a url rule matches now includes the form's action,
    # so a login form sitting on a homepage is still caught.
    ("action betrays a login form on a homepage",
     "<form action='/account/login'><input type=email></form>", "Continue",
     PAGE + " /account/login", ["email"], "login"),
    ("a two-step login, by page address alone",
     "<form><input type=email></form>", "Continue",
     "auth.hulu.com/web/create-account/enter-email", ["email"], "login"),

    # 2026-10-30: a dropdown's choices are stripped before the rules see them.
    ("a country list cannot retype the form",
     "<form><h2>Newsletter</h2><input type=email>"
     "<select><option>Contact us for enquiries</option></select></form>",
     "Newsletter", PAGE, ["email"], "subscription"),
]

VENDOR_CASES = [
    ("<form action='https://x.us1.list-manage.com/subscribe/post'>", "mailchimp"),
    ("<div class='klaviyo-form-abc'>", "klaviyo"),
    ("<form><input name='contact[tags]' value='newsletter'>", "shopify"),
    ("<form class='sibforms-form'>", "brevo"),
    ("<form><input type=email></form>", ""),
]


def _cand(z=0, modal=False, kind="subscription", fields=1):
    return {"z_index": z, "modal_hint": modal, "form_type": kind, "n_fields": fields}


def rank_cases():
    """The paper's rules, each only breaking ties in the ones before it."""
    out = []
    ranked = rank([_cand(z=0), _cand(z=100)])
    out.append(("higher z-index first", [c["z_index"] for c in ranked] == [100, 0]))

    ranked = rank([_cand(modal=False), _cand(modal=True)])
    out.append(("ties broken by the modal hint", [c["modal_hint"] for c in ranked] == [True, False]))

    ranked = rank([_cand(kind="login"), _cand(kind="subscription")])
    out.append(("anything but a subscription last",
                [c["form_type"] for c in ranked] == ["subscription", "login"]))

    ranked = rank([_cand(fields=1), _cand(fields=4)])
    out.append(("then more fields first", [c["n_fields"] for c in ranked] == [4, 1]))

    # z-index outranks all three of the others at once
    ranked = rank([_cand(z=0, modal=True, fields=9),
                   _cand(z=50, modal=False, kind="login", fields=1)])
    out.append(("z-index outranks the rest", ranked[0]["z_index"] == 50))

    out.append(("rank_on_page is 1-based", [c["rank_on_page"] for c in ranked] == [1, 2]))
    return out


def main():
    bad = 0
    print("form_type")
    for name, html, near, addr, inputs, want in TYPE_CASES:
        got = form_type(html, near, addr, inputs)
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name:52} {got:13} (expected {want})")

    print("\nvendor")
    for html, want in VENDOR_CASES:
        got = vendor(html)
        ok = got == want
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {html[:52]:52} {got!r} (expected {want!r})")

    print("\nrank")
    for name, ok in rank_cases():
        bad += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")

    total = len(TYPE_CASES) + len(VENDOR_CASES) + len(rank_cases())
    print(f"\n{total - bad}/{total} checks as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
