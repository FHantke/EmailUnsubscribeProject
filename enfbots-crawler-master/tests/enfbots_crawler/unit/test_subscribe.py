from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import bs4
import pytest

from enfbots_crawler import Config, InputType
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.languages import Language
from enfbots_crawler.subscribe import Observation, classify_outcome, plan_fill, submit

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
                email_value="news1@study.example", form_valid=True, challenge=False)
    return Observation(**(base | kw))


@pytest.mark.parametrize(
    "after, status",
    [
        (dict(challenge=True), "captcha_blocked"),
        (dict(text="join our list thank you! check your inbox"), "success_text"),
        (dict(text="join our list please enter a valid email"), "failed"),
        (dict(form_valid=False), "failed"),
        (dict(url="https://shop.example/thanks"), "redirect"),
        (dict(form_visible=False), "form_gone"),
        (dict(email_value=""), "form_reset"),
        ({}, "no_change"),
    ],
)
def test_classify_outcome(after, status):
    assert classify_outcome(_obs(), _obs(**after))[0] == status


def test_success_text_already_on_the_page_does_not_count():
    before = _obs(text="thank you for visiting")
    assert classify_outcome(before, _obs(text="thank you for visiting"))[0] == "no_change"


def _button(text, type_=InputType.BUTTON_SUBMIT, html_type="submit", shown=True):
    elem = MagicMock(text=text)
    elem.get_attribute.return_value = None
    elem.is_displayed.return_value = shown
    return SimpleNamespace(type=type_, direct_type=type_, html_type=html_type, elem=elem)


def test_submit_clicks_the_submit_button_never_a_dismiss_button():
    no = _button("No thanks", InputType.BUTTON_OTHER, "button")
    close = _button("Close", InputType.BUTTON_SUBMIT)
    yes = _button("Unlock 15% off", InputType.BUTTON_OTHER, "submit")  # <button> without type
    email = SimpleNamespace(elem=MagicMock())
    form = SimpleNamespace(inputs=[no, close, yes])

    assert submit(form, email) == "button:Unlock 15% off"
    yes.elem.click.assert_called_once()
    no.elem.click.assert_not_called()
    close.elem.click.assert_not_called()


def test_submit_presses_enter_without_a_button():
    email = SimpleNamespace(elem=MagicMock())
    assert submit(SimpleNamespace(inputs=[_button("Close")]), email) == "enter"
    email.elem.send_keys.assert_called_once()


def test_us_persona_loads_and_has_no_phone():
    creds = Credentials.load("us_jordan")
    assert (creds.first_name, creds.postal_code) == ("Jordan", "02115")
    assert creds.country == "United States"
    assert creds.phone is None


def test_default_credentials_still_come_from_config(monkeypatch):
    monkeypatch.setattr(Config(), "CREDENTIALS", "us_jordan")
    assert Credentials.get().last_name == "Ellery"
