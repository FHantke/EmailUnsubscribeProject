from pathlib import Path

import bs4
import pytest

from enfbots_crawler import capture
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.languages import Language

EN = Language.get(Path("enfbots_crawler/languages"), "en")


def _form(html: str) -> FormBS:
    return FormBS(bs4.BeautifulSoup(html, "html.parser").form, EN)


NEWSLETTER = """<form action="/subscribe" id="newsletter">
  <label for="nl-email">Sign up for our newsletter</label>
  <input type="email" name="email" id="nl-email">
  <button type="submit">Subscribe</button>
</form>"""

OFFER_WITH_CONSENT = """<form id="offer" action="https://shop.example.com/on/demandware.store/Subscribe">
  <p>Join the community and enjoy 15% off your first purchase.</p>
  <input type="email" name="dwfrm_subscriber_email" placeholder="Enter your email address">
  <input type="checkbox" name="privacyConsent" id="consent">
  <label for="consent">I agree to the privacy policy</label>
  <button type="submit">Join</button>
</form>"""


@pytest.mark.parametrize(
    "html,eligible,reason",
    [
        (NEWSLETTER, True, None),
        (OFFER_WITH_CONSENT, True, None),
        (
            """<form><input type="email" name="email"><input type="email" name="email_confirm">
               <button type="submit">Subscribe</button></form>""",
            True,
            None,
        ),
        (
            """<form><input type="email" name="email">
               <input type="tel" name="phone" placeholder="Phone (optional)">
               <button type="submit">Get 10% off</button></form>""",
            True,
            None,
        ),
        (
            """<form><input type="email" name="e1"><input type="email" name="e2"><input type="email" name="e3">
               <button type="submit">Send</button></form>""",
            False,
            "multiple_email",
        ),
        (
            """<form action="/signup"><input type="email" name="email">
               <input type="password" name="password"><input type="password" name="password2">
               <button type="submit">Create account</button></form>""",
            False,
            "password",
        ),
        (
            """<form><label for="u">Username</label><input type="text" name="username" id="u">
               <input type="email" name="email"><button type="submit">Join</button></form>""",
            False,
            "account",
        ),
        (
            """<form><input type="email" name="email">
               <input type="text" name="cardnumber" autocomplete="cc-number">
               <input type="text" name="cvc"><button type="submit">Pay</button></form>""",
            False,
            "payment_card",
        ),
        (
            """<form><input type="email" name="email"><input type="tel" name="phone" required>
               <button type="submit">Get the offer</button></form>""",
            False,
            "phone_required",
        ),
        (
            """<form><input type="email" name="email"><textarea name="message"></textarea>
               <button type="submit">Send message</button></form>""",
            False,
            "message_field",
        ),
    ],
)
def test_eligibility_rules(html, eligible, reason):
    assert capture.eligibility(_form(html)) == capture.Eligibility(eligible, reason)


def test_forms_without_email_are_not_captures():
    search = _form('<form role="search"><input type="search" name="q"><button>Search</button></form>')
    assert not capture.is_capture_candidate(search)
    assert capture.is_capture_candidate(_form(NEWSLETTER))


def test_kind_from_keywords():
    assert capture.capture_kind(_form(NEWSLETTER)) == "newsletter"


def test_vendor_hint():
    assert capture.vendor_hint(_form(OFFER_WITH_CONSENT)) == "salesforce_commerce_cloud"
    mailchimp = _form(
        '<form action="https://x.us1.list-manage.com/subscribe/post"><input type="email" name="EMAIL"></form>'
    )
    assert capture.vendor_hint(mailchimp) == "mailchimp"
    assert capture.vendor_hint(_form(NEWSLETTER)) is None


def test_signature_ignores_injected_ids_but_not_fields():
    first = _form('<form id="crawleruuid-aaa"><input type="email" id="crawleruuid-bbb"></form>')
    second = _form('<form id="crawleruuid-ccc"><input type="email" id="crawleruuid-ddd"></form>')
    other = _form('<form><input type="email" name="email"><input type="text" name="zip"></form>')

    assert capture.signature(first) == capture.signature(second)
    assert capture.signature(first) != capture.signature(other)


def test_field_summary_skips_buttons():
    fields = capture.field_summary(_form(OFFER_WITH_CONSENT))

    assert [f["name"] for f in fields] == ["dwfrm_subscriber_email", "privacyConsent"]
    assert fields[0]["type"] == "MAIL"
    assert fields[1]["html_type"] == "CHECKBOX_OTHER"
