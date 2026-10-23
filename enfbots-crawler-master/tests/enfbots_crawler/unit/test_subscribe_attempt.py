"""subscribe._attempt and uncover with a mocked browser (cases from the 2026-10-21 pilot)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock

import pytest
from selenium.common.exceptions import NoAlertPresentException

from enfbots_crawler import Config
from enfbots_crawler import subscribe as signup
from enfbots_crawler.subscribe import FillAction, FillPlan

ADDRESS = "news1234567890@study.example"


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(signup.time, "sleep", lambda _: None)
    monkeypatch.setattr(Config(), "ALLOW_SCREENSHOTS", False)
    monkeypatch.setattr(Config(), "SUBSCRIBE_DRY_RUN", False)
    monkeypatch.setattr(signup, "ActionChains", MagicMock())


def _browser(
    covered=(False,), page_text="join our list", new_tab_text=None, after=None, alert=None
):
    """
    A mocked browser; scripts are answered by kind, covered answers the cover checks in turn.
    The page looks the same after the submit unless after gives its state then; alert is the
    text of an alert open after the submit.
    """
    br = MagicMock()
    br.dismissed_alerts = []
    if alert is None:
        type(br.driver.switch_to).alert = PropertyMock(side_effect=NoAlertPresentException())
    else:
        br.driver.switch_to.alert.text = alert
    covered = list(covered)
    tabs = ["main"]
    shown = {"text": page_text, "formVisible": True, "emailValue": ADDRESS, "valid": True}
    states = [shown, after or shown]

    def script(js, *_args):
        if js == signup._COVERED_JS:
            return covered.pop(0) if covered else False
        if js == signup._OBSERVE_JS:
            return states.pop(0) if len(states) > 1 else states[0]
        if js == signup._INNER_TEXT_JS:
            return new_tab_text
        return None

    br.execute_script.side_effect = script
    br.driver.current_window_handle = "main"
    br.driver.window_handles = tabs
    return br, tabs


def _site(br):
    return SimpleNamespace(br=br, dump_id=0, output_path=None)


# The capture form as find_capture_form returns it: in the page itself
FORM = SimpleNamespace(id="f1", uuid="f1", frame=None, shadow_hosts=[])


def _form_sel(br, typed_values):
    email = SimpleNamespace(
        bs=SimpleNamespace(id="e1", uuid="e1"), elem=MagicMock(), fill_text=MagicMock()
    )
    email.elem.get_property.side_effect = list(typed_values)
    return SimpleNamespace(inputs=[email], radio_groups={}, br=br), email


PLAN = FillPlan([FillAction("e1", "alias", "mail")], None)


def _attempt(monkeypatch, br, typed_values, submitted_by="button:Join", challenge=""):
    form_sel, email = _form_sel(br, typed_values)
    monkeypatch.setattr(signup.FormSelenium, "from_bs", lambda *_: form_sel)
    recorder = MagicMock(captcha_name=None, captcha_visible=None)
    recorder.challenge_name.return_value = challenge
    monkeypatch.setattr(signup, "CaptchaRecorder", lambda *_: recorder)
    submit = MagicMock(return_value=submitted_by)
    monkeypatch.setattr(signup, "submit", submit)
    result = signup._attempt(_site(br), FORM, PLAN, ADDRESS, MagicMock(), 1)
    return result, submit, email


@pytest.mark.parametrize(
    "covered, expected, escapes",
    [
        ((False,), "no", 0),
        ((True, False), "closed_by_escape", 1),
        ((True, True), "still_covered", 1),
    ],
)
def test_uncover_presses_escape_only_when_the_field_is_covered(covered, expected, escapes):
    br, _ = _browser(covered)
    assert signup.uncover(br, MagicMock()) == expected
    assert signup.ActionChains.return_value.send_keys.return_value.perform.call_count == escapes


def test_interrupted_typing_is_retried_and_never_submitted_incomplete(monkeypatch):
    # vivarays: a pop-up took the focus after the first letter, twice
    br, _ = _browser()
    (status, detail), submit, email = _attempt(monkeypatch, br, ["r", "r"])

    assert status == "failed_fill" and detail["typed"] == "r"
    assert email.fill_text.call_count == 2
    submit.assert_not_called()


def test_typing_retried_once_after_a_pop_up_then_submitted(monkeypatch):
    br, _ = _browser(covered=(False, True, False))
    (status, detail), submit, _ = _attempt(monkeypatch, br, ["r", ADDRESS])

    assert detail["covered_while_typing"] == "closed_by_escape"
    submit.assert_called_once()
    assert status == "no_change"  # mocked page: nothing changes after the submit


def test_result_in_a_new_tab_is_read_from_that_tab(monkeypatch):
    # Mailchimp embeds (target="_blank") answer in a new tab
    br, tabs = _browser(new_tab_text="Almost finished... We need to confirm your email address.")
    submit_opens_tab = MagicMock(side_effect=lambda *_: tabs.append("new") or "button:SUBSCRIBE")
    monkeypatch.setattr(signup, "submit", submit_opens_tab)
    form_sel, _ = _form_sel(br, [ADDRESS])
    monkeypatch.setattr(signup.FormSelenium, "from_bs", lambda *_: form_sel)
    recorder = MagicMock(captcha_name=None, captcha_visible=None)
    recorder.challenge_name.return_value = ""
    monkeypatch.setattr(signup, "CaptchaRecorder", lambda *_: recorder)

    status, detail = signup._attempt(
        _site(br), FORM, PLAN, ADDRESS, MagicMock(), 1
    )

    assert status == "success_text"
    assert "new_tab" in detail
    br.driver.close.assert_called_once()
    br.driver.switch_to.window.assert_called_with("main")


def test_bot_challenge_after_submit_is_captcha_blocked(monkeypatch):
    # jasonmarkk: DataDome replaced the page after the submit
    br, _ = _browser()
    (status, detail), _, _ = _attempt(monkeypatch, br, [ADDRESS], challenge="datadome")
    assert status == "captcha_blocked" and detail["challenge"] == "datadome"


def test_thank_you_with_curly_quotes_replacing_the_form_is_a_success(monkeypatch):
    # basecamp: "Thanks! You’re in." took the form's place, which was left empty and invalid
    gone = {"text": "Thanks! You’re in.", "formVisible": False, "emailValue": "", "valid": False}
    br, _ = _browser(after=gone)
    (status, detail), _, _ = _attempt(monkeypatch, br, [ADDRESS])
    assert status == "success_text" and detail["success_keywords"] == ["you're in"]


@pytest.mark.parametrize(
    "action, label_shown, selected, clicked, done",
    [
        ("tick_styled", True, False, True, "tick_styled:checkbox_pp"),
        ("tick_styled", True, True, False, "tick_styled:checkbox_pp"),
        ("untick_styled", True, True, True, "untick_styled:checkbox_pp"),
        ("tick_styled", False, False, False, "hidden:checkbox_pp"),
    ],
)
def test_styled_boxes_are_clicked_only_when_their_label_is_shown(
    action, label_shown, selected, clicked, done
):
    br = MagicMock()
    br.execute_script.side_effect = lambda js, *_: js == signup._LABEL_SHOWN_JS and label_shown
    box = SimpleNamespace(bs=SimpleNamespace(id="cb", uuid="cb"), elem=MagicMock())
    box.elem.is_selected.return_value = selected
    form_sel = SimpleNamespace(inputs=[box], radio_groups={}, br=br)
    plan = FillPlan([FillAction("cb", action, "checkbox_pp")], None)

    assert signup.apply_fill(_site(br), form_sel, plan, ADDRESS, MagicMock()) == [done]
    assert br.activate.called == clicked


@pytest.mark.parametrize(
    "alert, status",
    [
        # cokesburykids: the submit raised UnexpectedAlertPresentException before
        ("Google reCAPTCHA verification failed.", "captcha_blocked"),
        ("Thank you for subscribing!", "success_text"),
    ],
)
def test_alert_after_the_submit_is_read_and_closed(monkeypatch, alert, status):
    br, _ = _browser(alert=alert)
    (got, detail), _, _ = _attempt(monkeypatch, br, [ADDRESS])

    assert got == status and detail["alert"] == alert
    br.driver.switch_to.alert.accept.assert_called_once()


def test_form_that_cannot_be_submitted_sends_nothing(monkeypatch):
    br, _ = _browser()
    (status, detail), submit, _ = _attempt(monkeypatch, br, [ADDRESS], submitted_by="not_submitted")

    assert status == "failed_submit" and detail["submitted_by"] == "not_submitted"
    submit.assert_called_once()


def test_thank_you_written_into_the_email_field_is_a_success(monkeypatch):
    # purple.com: the observation's text includes what the form's fields show
    shown = {"text": "join our list Thanks for signing up!", "formVisible": True,
             "emailValue": "Thanks for signing up!", "valid": True}
    br, _ = _browser(after=shown)
    (status, detail), _, _ = _attempt(monkeypatch, br, [ADDRESS])
    assert status == "success_text" and detail["success_keywords"] == ["thanks for"]


def test_alert_already_dismissed_after_a_javascript_click_still_counts(monkeypatch):
    # post_load_routine dismisses alerts after br.activate (the covered-button click)
    br, _ = _browser()
    br.dismissed_alerts.append("an alert from before the submit")
    form_sel, _ = _form_sel(br, [ADDRESS])
    monkeypatch.setattr(signup.FormSelenium, "from_bs", lambda *_: form_sel)
    recorder = MagicMock(captcha_name=None, captcha_visible=None)
    recorder.challenge_name.return_value = ""
    monkeypatch.setattr(signup, "CaptchaRecorder", lambda *_: recorder)

    def js_click(*_):
        br.dismissed_alerts.append("Please verify you are not a robot")
        return "button_js:Join"

    monkeypatch.setattr(signup, "submit", js_click)
    status, detail = signup._attempt(_site(br), FORM, PLAN, ADDRESS, MagicMock(), 1)

    assert status == "captcha_blocked" and detail["alert"] == "Please verify you are not a robot"
