from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import bs4
import pytest
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    ElementNotInteractableException,
)

from enfbots_crawler import Config, InputType
from enfbots_crawler import subscribe as signup
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.languages import Language
from enfbots_crawler.subscribe import (
    Observation,
    SubscribeTarget,
    classify_outcome,
    plan_fill,
    sign_up_address,
    submit,
)

EN = Language.get(Path("enfbots_crawler/languages"), "en")


def _form(html: str, hidden: tuple[str, ...] = ()) -> FormBS:
    # Inputs carrying data-enfbots-uuid in `hidden` count as not visible
    return FormBS(bs4.BeautifulSoup(html, "html.parser").form, EN, {h: False for h in hidden})


def _plan(html: str, hidden: tuple[str, ...] = (), fill_all: bool = False):
    plan = plan_fill(_form(html, hidden), fill_all)
    return [(a.action, a.field) for a in plan.actions], plan.skip_reason


EMAIL = '<label for="e">Email</label><input type="email" name="email" id="e">'
SUBMIT = '<button type="submit">Subscribe</button>'


def test_plain_newsletter_form_gets_only_the_alias():
    assert _plan(f"<form>{EMAIL}{SUBMIT}</form>") == ([("alias", "mail")], None)


def test_persona_fields_only_when_required_unless_fill_all():
    html = f"""<form>{EMAIL}
        <label for="f">First name *</label><input type="text" name="first_name" id="f">
        <label for="l">Last name</label><input type="text" name="last_name" id="l">
        {SUBMIT}</form>"""
    assert _plan(html) == ([("alias", "mail"), ("persona", "first_name")], None)
    actions, reason = _plan(html, fill_all=True)
    assert ("persona", "last_name") in actions and reason is None


@pytest.mark.parametrize(
    "field, reason",
    [
        ('<label for="p">Phone</label><input type="tel" name="phone" id="p" required>',
         "phone_required"),
        ('<label for="w">Password</label><input type="password" name="pw" id="w" required>',
         "password_required"),
        ('<label for="m">Message</label><textarea name="message" id="m" required></textarea>',
         "message_required"),
        ('<label for="q">Favourite colour</label><input type="text" name="q" id="q" required>',
         "unknown_required_field"),
    ],
)
def test_forms_requiring_data_the_study_never_gives_are_skipped(field, reason):
    assert _plan(f"<form>{EMAIL}{field}{SUBMIT}</form>")[1] == reason


def test_optional_phone_and_password_stay_empty():
    html = f"""<form>{EMAIL}<label for="p">Phone</label><input type="tel" name="phone" id="p">
        <label for="w">Password</label><input type="password" name="pw" id="w">{SUBMIT}</form>"""
    assert _plan(html) == ([("alias", "mail")], None)


def test_consent_boxes_ticked_sms_boxes_never():
    html = f"""<form>{EMAIL}
        <input type="checkbox" name="pp" id="pp">
        <label for="pp">I agree to the privacy policy</label>
        <input type="checkbox" name="sms" id="sms" checked>
        <label for="sms">Send me SMS text messages</label>
        {SUBMIT}</form>"""
    actions, reason = _plan(html)
    assert reason is None
    assert ("untick", "checkbox_sms") in actions
    assert any(a == "tick" and f.startswith("checkbox_pp") for a, f in actions)


@pytest.mark.parametrize(
    "label",
    [
        "Send me SMS text messages",  # classified CHECKBOX_EMAIL
        "Sign me up for text messages",  # CHECKBOX_OTHER
        "I agree to receive SMS marketing",  # CHECKBOX_TOS
        "Text me offers",  # CHECKBOX_EMAIL
    ],
)
def test_sms_boxes_are_unticked_whatever_the_classifier_calls_them(label):
    for checked, expected in (("checked", [("untick",)]), ("", [])):
        html = f"""<form>{EMAIL}<input type="checkbox" name="x" id="x" {checked}>
            <label for="x">{label}</label>{SUBMIT}</form>"""
        actions, reason = _plan(html)
        assert reason is None
        assert [(a,) for a, _ in actions if a != "alias"] == expected


def test_email_consent_box_is_not_mistaken_for_sms():
    html = f"""<form>{EMAIL}<input type="checkbox" name="optin" id="o">
        <label for="o">Email me news and offers</label>{SUBMIT}</form>"""
    actions, _ = _plan(html)
    assert [a for a, _ in actions] == ["alias", "tick"]


def test_styled_consent_box_is_ticked_although_the_real_box_is_hidden():
    # powertoolreplacementparts (Brevo): the required box is hidden behind a drawn one
    html = f"""<form>{EMAIL}<label>
        <input type="checkbox" name="IS_SUBSCRIBER" class="input_replaced" data-enfbots-uuid="cb"
               required><span>I agree to receive your newsletters</span></label>{SUBMIT}</form>"""
    actions, reason = _plan(html, hidden=("cb",))
    assert reason is None
    assert [a for a, _ in actions] == ["alias", "tick_styled"]


def test_hidden_boxes_neither_consent_nor_required_stay_untouched():
    html = f"""<form>{EMAIL}<input type="checkbox" name="gift" id="g" data-enfbots-uuid="cb">
        <label for="g">This is a gift</label>
        <input type="checkbox" name="sms" id="s" data-enfbots-uuid="sms" required>
        <label for="s">Send me SMS text messages</label>{SUBMIT}</form>"""
    assert _plan(html, hidden=("cb", "sms")) == ([("alias", "mail")], None)


def test_hidden_fields_and_honeypots_are_never_touched():
    # Mailchimp's hosted forms carry a hidden "required" comment box against bots
    html = f"""<form>{EMAIL}
        <textarea name="b_comment" data-enfbots-uuid="hp" required></textarea>
        <input type="text" name="b_name" data-enfbots-uuid="hp2" required>{SUBMIT}</form>"""
    assert _plan(html, hidden=("hp", "hp2")) == ([("alias", "mail")], None)


def test_form_without_a_shown_email_field_is_skipped():
    html = f'<form><input type="email" name="email" data-enfbots-uuid="e1">{SUBMIT}</form>'
    assert _plan(html, hidden=("e1",))[1] == "no_visible_email_field"


def test_required_select_and_one_radio_per_group():
    html = f"""<form>{EMAIL}
        <label for="s">You are</label><select name="kind" id="s" required>
            <option value="">Choose</option><option value="r">Residential</option></select>
        <input type="radio" name="freq" id="r1" value="w" required><label for="r1">Weekly</label>
        <input type="radio" name="freq" id="r2" value="m" required><label for="r2">Monthly</label>
        {SUBMIT}</form>"""
    actions, reason = _plan(html)
    assert reason is None
    assert [a for a, _ in actions].count("select") == 1
    assert [a for a, _ in actions].count("radio") == 1


def _obs(**kw) -> Observation:
    base = dict(url="https://shop.example/", text="join our list", form_visible=True,
                email_value="news1@study.example", form_valid=True, challenge="")
    return Observation(**(base | kw))


@pytest.mark.parametrize(
    "after, status",
    [
        (dict(challenge="datadome"), "captcha_blocked"),
        (dict(text="join our list thank you! check your inbox"), "success_text"),
        (dict(text="join our list please enter a valid email"), "failed"),
        (dict(form_valid=False), "failed"),
        (dict(url="https://shop.example/thanks"), "redirect"),
        (dict(form_visible=False), "form_gone"),
        # basecamp: the form hid itself, emptied, so the browser calls it invalid
        (dict(form_visible=False, email_value="", form_valid=False), "form_gone"),
        # carlsgolfland (sent mail): still shown, but emptied, so invalid
        (dict(email_value="", form_valid=False), "form_reset"),
        # the field rewritten with a message that is no keyword
        (dict(email_value="See you soon!"), "form_reset"),
        # cookfasteatwell: Mailchimp's page in the new tab didn't load
        (dict(text="this site can't be reached err_http2_protocol_error"), "page_error"),
        (dict(email_value=""), "form_reset"),
        ({}, "no_change"),
    ],
)
def test_classify_outcome(after, status):
    assert classify_outcome(_obs(), _obs(**after))[0] == status


def test_page_error_reports_the_error_code():
    status, detail = classify_outcome(_obs(), _obs(text="err_http2_protocol_error"))
    assert status == "page_error" and detail["page_error"] == "err_http2_protocol_error"


def test_success_text_already_on_the_page_does_not_count():
    before = _obs(text="thank you for visiting")
    assert classify_outcome(before, _obs(text="thank you for visiting"))[0] == "no_change"


def _elem(text, aria_label=None, shown=True, **attrs):
    elem = MagicMock(text=text)
    attrs["aria-label"] = aria_label
    elem.get_attribute.side_effect = lambda name: attrs.get(name.replace("_", "-"))
    elem.is_displayed.return_value = shown
    return elem


def _button(text, type_=InputType.BUTTON_SUBMIT, html_type="submit", shown=True, **attrs):
    return SimpleNamespace(
        type=type_, direct_type=type_, html_type=html_type, elem=_elem(text, shown=shown, **attrs)
    )


def _form_sel(inputs, typed_submit=(), role_buttons=(), plain_buttons=(), any_submit=()):
    """A form whose element holds the given controls, found by submit()'s CSS selectors."""
    by_css = {
        signup._TYPED_SUBMIT: typed_submit,
        signup._ROLE_BUTTON: role_buttons,
        signup._PLAIN_BUTTON: plain_buttons,
        signup._ANY_SUBMIT: any_submit,
    }
    tag = MagicMock()
    tag.find_elements.side_effect = lambda _by, css: list(by_css[css])
    return SimpleNamespace(inputs=inputs, br=MagicMock(), tag=tag)


def test_submit_clicks_the_submit_button_never_a_dismiss_button():
    no = _button("No thanks", InputType.BUTTON_OTHER, "button")
    close = _button("Close", InputType.BUTTON_SUBMIT)
    yes = _button("Unlock 15% off", InputType.BUTTON_OTHER, "submit")  # <button> without type
    email = SimpleNamespace(elem=MagicMock())
    form = _form_sel([no, close, yes])

    assert submit(form, email) == "button:Unlock 15% off"
    yes.elem.click.assert_called_once()
    no.elem.click.assert_not_called()
    close.elem.click.assert_not_called()


def test_submit_clicks_a_covered_button_through_javascript():
    # A pop-up or cookie banner over the footer form intercepts the real click
    covered = _button("Sign Up")
    covered.elem.click.side_effect = ElementClickInterceptedException("covered by a modal")
    form = _form_sel([covered])
    email = SimpleNamespace(elem=MagicMock())

    assert submit(form, email) == "button_js:Sign Up"
    form.br.activate.assert_called_once_with(covered.elem)
    email.elem.send_keys.assert_not_called()


def test_submit_presses_enter_without_a_button():
    email = SimpleNamespace(elem=MagicMock())
    assert submit(_form_sel([_button("Close")]), email) == "enter"
    email.elem.send_keys.assert_called_once()


def test_submit_clicks_a_link_with_type_submit():
    # royalcaribbean: <a role="button" type="submit">; the form's only <button> is a dropdown
    country = _button("United States", InputType.BUTTON_OTHER, "button")
    link = _elem("", aria_label="Submit the form to sign up")
    email = SimpleNamespace(elem=MagicMock())
    form = _form_sel([country], typed_submit=[link], role_buttons=[link])

    assert submit(form, email) == "button:Submit the form to sign up"
    link.click.assert_called_once()
    country.elem.click.assert_not_called()
    email.elem.send_keys.assert_not_called()


def test_submit_clicks_a_role_button_only_if_it_is_the_only_one():
    email = SimpleNamespace(elem=MagicMock())
    join, close = _elem("Join"), _elem("", aria_label="Close")
    assert submit(_form_sel([], role_buttons=[join, close]), email) == "button:Join"

    first, second = _elem("Join"), _elem("Learn more")
    assert submit(_form_sel([], role_buttons=[first, second]), email) == "enter"
    first.click.assert_not_called()
    second.click.assert_not_called()


def test_submit_never_clicks_a_menu_toggle():
    # costco: the country selector is a submit-type button too
    country = _button("US", InputType.BUTTON_OTHER, "submit", aria_expanded="false")
    go = _button("Go", aria_label="Go Get Email Offers")
    email = SimpleNamespace(elem=MagicMock())

    assert submit(_form_sel([country, go]), email) == "button:Go Go Get Email Offers"
    country.elem.click.assert_not_called()


def test_submit_clicks_klaviyos_type_button_when_the_real_submit_is_hidden():
    # atrius, secretlab: <button type="button">GET MY 10% OFF</button>, hidden <input type=submit>
    hidden = _button("", InputType.BUTTON_SUBMIT, "submit", shown=False)
    cta = _elem("GET MY 10% OFF")
    email = SimpleNamespace(elem=MagicMock())

    assert submit(_form_sel([hidden], plain_buttons=[cta]), email) == "button:GET MY 10% OFF"
    email.elem.send_keys.assert_not_called()


def test_submit_without_enter_uses_the_hidden_submit_through_javascript():
    email = SimpleNamespace(elem=MagicMock())
    email.elem.send_keys.side_effect = ElementNotInteractableException("element not interactable")
    hidden_submit = _elem("", value="Submit")
    form = _form_sel([], any_submit=[hidden_submit])

    assert submit(form, email) == "submit_js:Submit"
    form.br.activate.assert_called_once_with(hidden_submit)

    assert submit(_form_sel([]), email) == "not_submitted"


def test_us_persona_loads_and_has_no_phone():
    creds = Credentials.load("us_jordan")
    assert (creds.first_name, creds.postal_code) == ("Jordan", "02115")
    assert creds.country == "United States"
    assert creds.phone is None


def test_study_persona_signs_up_with_the_alias():
    target = SubscribeTarget("news1234567890@study.example", "x", "https://shop.example/", "s", None)
    assert sign_up_address(Credentials.load("us_jordan"), target) == target.alias


@pytest.mark.parametrize(
    "email, url, expected",
    [
        ("jordan+12345@test.example", "https://www.mooncat.com/", "jordan+12345-mooncat@test.example"),
        ("jordan@test.example", "https://shop.royalcaribbean.co.uk/deals", "jordan+royalcaribbean@test.example"),
        ("jordan@test.example", "https://tinycraft.co/", "jordan+tinycraft@test.example"),
    ],
)
def test_test_persona_address_is_tagged_with_the_site(email, url, expected):
    target = SubscribeTarget("test1@test.invalid", "x", url, "s", None)
    assert sign_up_address(SimpleNamespace(email=email), target) == expected


def test_default_credentials_still_come_from_config(monkeypatch):
    monkeypatch.setattr(Config(), "CREDENTIALS", "us_jordan")
    assert Credentials.get().last_name == "Ellery"
