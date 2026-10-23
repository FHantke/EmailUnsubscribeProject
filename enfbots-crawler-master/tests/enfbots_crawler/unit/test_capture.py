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


SUBSCRIBE = '<button type="submit">Subscribe</button>'


@pytest.mark.parametrize(
    "html,url,reason",
    [
        # mclaneedgers: reCAPTCHA's token textarea is no message box (and no image CAPTCHA)
        (
            f"""<form><input type="email" name="email"><textarea name="g-recaptcha-response"
               style="display: none"></textarea>{SUBSCRIBE}</form>""",
            None,
            None,
        ),
        (
            f"""<form><input type="email" name="email"><textarea name="h-captcha-response">
               </textarea>{SUBSCRIBE}</form>""",
            None,
            None,
        ),
        # whitepages: the classifier took "search-name" for an email field
        (
            """<form><input type="text" name="search-name" placeholder="Name">
               <input type="text" name="search-location" placeholder="City, State">
               <button>Search</button></form>""",
            None,
            "search",
        ),
        # brecks: Shopify's password recovery
        (
            """<form action="/account/recover" method="post">
               <input type="hidden" name="form_type" value="recover_customer_password">
               <input type="email" name="email"><button type="submit">Submit</button></form>""",
            None,
            "account",
        ),
        # ms.now: the sign-in page its newsletter link leads to
        (
            """<form><label for="e">Email address</label><input type="email" name="msnow-sign-in-email"
               id="e"><button type="submit">Continue</button></form>""",
            "https://www.ms.now/sign-in?redirectTo=https://www.ms.now/newsletters",
            "login",
        ),
        # payrollnetwork: an email-first login on the homepage
        (
            """<form><p>Welcome. Enter your account email to log in</p>
               <input type="email" name="Input.Username2"><button type="submit">Continue</button></form>""",
            "https://payrollnetwork.myisolved.com/",
            "login",
        ),
        # deseretbook: order tracking
        (
            """<form><p>Check order: see your order even if you are not a registered user.
               Enter the order number</p><input type="text" name="trackOrderNumber">
               <input type="email" name="trackOrderEmail"><button>Check status</button></form>""",
            None,
            "order_lookup",
        ),
        # basecampleasing: a lead form
        (
            """<form><input type="text" name="FirstName"><input type="email" name="Email">
               <button type="submit">Appraise My Property</button></form>""",
            None,
            "lead_form",
        ),
    ],
)
def test_round2_false_positives_and_negatives(html, url, reason):
    assert capture.eligibility(_form(html), capture.captcha_info(_form(html)), url) == (
        capture.Eligibility(reason is None, reason)
    )


def test_shopify_newsletter_is_no_contact_form():
    # role4initiative: skipped as "contact" in the sign-up test
    html = """<form action="/contact#cc-popup" method="post">
        <input type="hidden" name="form_type" value="customer">
        <input type="hidden" name="contact[tags]" value="prospect,newsletter">
        <input type="email" name="contact[email]" placeholder="Your email" required>
        <button type="submit">Subscribe</button></form>"""
    assert capture.eligibility(_form(html)) == capture.Eligibility(True, None)


def test_email_hint_in_an_old_style_value():
    # socialsecurityadvisors: value="E-mail Newsletter Sign-up", cleared on focus
    html = """<form action="/gdform.php"><input type="text" name="newsletter_signup_address"
        value="E-mail Newsletter Sign-up"><input type="submit" name="submit" value="Subscribe"></form>"""
    assert capture.is_capture_candidate(_form(html))


def test_newsletter_field_named_like_a_login_stays_eligible():
    # newegg: the newsletter's email field is called "LoginName"
    html = f'<form><input type="email" name="LoginName">{SUBSCRIBE}</form>'
    assert capture.eligibility(_form(html)) == capture.Eligibility(True, None)


def test_text_fields_count_as_email_only_if_they_say_so():
    # baptistmessenger: "subscriber_id" was classified MAIL
    lookup = _form(
        """<form><label for="s">Subscriber ID</label><input type="text" name="subscriber_id" id="s">
           <button>Look up my subscription</button></form>"""
    )
    assert not capture.is_capture_candidate(lookup)
    footer = _form(f'<form><input type="text" name="newsletter_email">{SUBSCRIBE}</form>')
    assert capture.is_capture_candidate(footer)


@pytest.mark.parametrize(
    "src, expected",
    [
        ("https://www.google.com/recaptcha/api2/anchor?k=x&size=invisible", ("recaptcha_v2_invisible", False)),
        ("https://www.google.com/recaptcha/api2/anchor?k=x&size=normal", ("recaptcha_v2", True)),
    ],
)
def test_recaptcha_frames_invisible_or_checkbox(src, expected):
    form = _form(f'<form><input type="email" name="email"><iframe src="{src}"></iframe></form>')
    assert tuple(capture.captcha_info(form)) == expected


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


def test_hidden_honeypot_textarea_in_a_shown_form_is_no_message_box():
    # test_subscribe_local's newsletter page; Mailchimp's hosted pages have "b_comment"
    html = """<form><input type="email" name="email" data-enfbots-uuid="e">
        <textarea name="comment" data-enfbots-uuid="hp" style="display: none"></textarea>
        <button type="submit">Join the list</button></form>"""
    shown = FormBS(bs4.BeautifulSoup(html, "html.parser").form, EN, {"e": True, "hp": False})
    assert capture.eligibility(shown) == capture.Eligibility(True, None)
    # A pop-up form hidden as a whole: its textarea can't be told apart from a message box
    hidden = FormBS(bs4.BeautifulSoup(html, "html.parser").form, EN, {"e": False, "hp": False})
    assert capture.eligibility(hidden).reject_reason == "message_field"
