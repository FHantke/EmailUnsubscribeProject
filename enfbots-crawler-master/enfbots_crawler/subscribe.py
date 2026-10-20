"""
Study sign-ups: re-finds a test case's capture form, fills it with the test case's alias (plus the
persona's fields the form requires), submits it once and judges whether that worked.

Never fills phone, password, payment, address or message fields, never touches hidden or
honeypot fields, never ticks SMS boxes and never solves a CAPTCHA. A form that requires any of
these is skipped with a reason rather than filled with made-up text.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

from bs4 import BeautifulSoup
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.keys import Keys

from enfbots_crawler import Config, InputType, capture
from enfbots_crawler.captcha_solver import CaptchaRecorder
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.form_selenium import FormSelenium
from enfbots_crawler.helper import get_attr
from enfbots_crawler.input_bs import InputBS, textual_types
from enfbots_crawler.input_selenium import InputSelenium

if TYPE_CHECKING:
    from enfbots_crawler.website import WebSite

logger = logging.getLogger("enfbots_crawler")

# Persona attribute for each field the study fills when a form requires it
PERSONA_FIELDS = {
    InputType.FIRST_NAME: "first_name",
    InputType.LAST_NAME: "last_name",
    InputType.FULL_NAME: "full_name",
    InputType.ZIP: "postal_code",
    InputType.BIRTH_DAY: "birth_day",
    InputType.BIRTH_MONTH: "birth_month",
    InputType.BIRTH_YEAR: "birth_year",
    InputType.BIRTH_FULL: "birthdate",
}
# Data the study never gives; a form requiring it is skipped (reason "<value>_required")
FORBIDDEN = {
    InputType.PHONE: "phone",
    InputType.PASSWORD: "password",
    InputType.USERNAME: "username",
    InputType.STREET: "address",
    InputType.STREET_NR: "address",
    InputType.STREET_FULL: "address",
    InputType.FULL_ADDRESS: "address",
    InputType.VERIFY_CODE: "code",
}
# Ticked on every sign-up: the email consent is what the study signs up for
CONSENT_BOXES = {
    InputType.CHECKBOX_EMAIL,
    InputType.CHECKBOX_PP,
    InputType.CHECKBOX_TOS,
    InputType.CHECKBOX_PP_TOS,
    InputType.CHECKBOX_PP_TOS_EMAIL,
    InputType.CHECKBOX_AGE,
}
# SMS / text-message opt-ins. The keyword files define none for CHECKBOX_SMS, and the classifier
# calls such boxes CHECKBOX_EMAIL or CHECKBOX_TOS, so they are recognised here as well
_SMS = re.compile(
    r"\bsms\b|\bmms\b|\btext(s|ing| messages?| me| alerts?| offers?)\b|"
    r"mobile (alerts?|messages?|marketing)|\bautodial",
    re.I,
)
# Buttons that close a pop-up instead of submitting it
_DISMISS = re.compile(
    r"no,? thanks|no thank you|close|dismiss|not now|maybe later|decline|cancel|skip|^x$|^×$",
    re.I,
)
_SUBMIT_TYPES = (InputType.BUTTON_SUBSCRIBE, InputType.BUTTON_SUBMIT, InputType.BUTTON_REGISTRATION)

# The form's state after a submit: is its email field still shown, what does it hold, does the
# browser consider the form valid (null when the form is gone)
_OBSERVE_JS = """
const [formId, emailId] = arguments;
const form = document.getElementById(formId);
const email = document.getElementById(emailId);
const shown = (e) => !!e && e.isConnected && e.getClientRects().length > 0
                     && getComputedStyle(e).visibility !== 'hidden';
return {
    text: document.body ? document.body.innerText : '',
    formVisible: shown(email),
    emailValue: email ? email.value : '',
    valid: form && form.isConnected && form.checkValidity ? form.checkValidity() : null,
};
"""


def is_sms_box(inp: InputBS) -> bool:
    if inp.estimated_type == InputType.CHECKBOX_SMS:
        return True
    hints = (inp.label, get_attr(inp.element, "name"), inp.id, get_attr(inp.element, "value"))
    return bool(_SMS.search(" ".join(h for h in hints if h).replace("_", " ")))


class FillAction(NamedTuple):
    input_id: str
    # alias, persona, tick, untick, select or radio
    action: str
    # Field type, for the record
    field: str
    # Persona attribute for action "persona"
    value: Optional[str] = None


class FillPlan(NamedTuple):
    actions: list[FillAction]
    # Why the form can't be signed up to without data the study never gives; None if it can
    skip_reason: Optional[str]


def plan_fill(form: FormBS, fill_all: bool = False) -> FillPlan:
    """
    Decides what to put into each field of a capture form. Optional persona fields stay empty
    unless fill_all (used for a second attempt when a field was required without saying so).
    """
    actions: list[FillAction] = []
    radio_groups: set[str] = set()
    for inp in form.inputs:  # excludes type="hidden"
        est, direct = inp.estimated_type, inp.direct_type
        if not inp.visible or est == InputType.HONEYPOT or direct in capture._CONTROL_TYPES:
            continue
        required = bool(inp.required)
        field = est.name.lower()

        if inp.tag_name == "textarea":
            if required:
                return FillPlan(actions, "message_required")
        elif direct in textual_types:
            if est == InputType.MAIL:
                actions.append(FillAction(inp.id, "alias", field))
            elif capture._is_card_field(inp):
                if required:
                    return FillPlan(actions, "payment_card_required")
            elif est in FORBIDDEN:
                if required:
                    return FillPlan(actions, f"{FORBIDDEN[est]}_required")
            elif est in PERSONA_FIELDS:
                if required or fill_all:
                    actions.append(FillAction(inp.id, "persona", field, PERSONA_FIELDS[est]))
            elif required:
                return FillPlan(actions, "unknown_required_field")
        elif direct == InputType.CHECKBOX_OTHER:
            if is_sms_box(inp):
                if inp.prechecked:
                    actions.append(FillAction(inp.id, "untick", "checkbox_sms"))
            elif (est in CONSENT_BOXES or required) and not inp.prechecked:
                actions.append(FillAction(inp.id, "tick", field))
        elif direct == InputType.SELECT_OTHER:
            if required:
                actions.append(FillAction(inp.id, "select", field))
        elif direct == InputType.RADIO_OTHER:
            group = get_attr(inp.element, "name") or inp.id
            if required and group not in radio_groups:
                radio_groups.add(group)
                actions.append(FillAction(inp.id, "radio", field))
        elif required and direct == InputType.FILE:
            return FillPlan(actions, "file_required")
        elif required and direct != InputType.CAPTCHA_INPUT:
            return FillPlan(actions, "unknown_required_field")

    if not any(a.action == "alias" for a in actions):
        return FillPlan(actions, "no_visible_email_field")
    return FillPlan(actions, None)


class Observation(NamedTuple):
    url: str
    # Visible page text, lower case
    text: str
    form_visible: bool
    email_value: str
    # form.checkValidity(); None when the form is gone
    form_valid: Optional[bool]
    challenge: bool


def _new_keywords(keywords: list[str], before: str, after: str) -> list[str]:
    return [k for k in keywords if k in after and k not in before]


def classify_outcome(before: Observation, after: Observation) -> tuple[str, dict[str, Any]]:
    """
    Judges a submit from the page before and after it. Only text that newly appeared counts,
    since success messages are often in the page (hidden) all along.
    """
    success = _new_keywords(Config().SUBSCRIBE_SUCCESS_KEYWORDS, before.text, after.text)
    failure = _new_keywords(Config().SUBSCRIBE_FAILURE_KEYWORDS, before.text, after.text)
    detail = {
        "success_keywords": success,
        "failure_keywords": failure,
        "url_before": before.url,
        "url_after": after.url,
        "form_visible_after": after.form_visible,
        "email_kept": bool(after.email_value),
        "form_valid_after": after.form_valid,
    }
    if after.challenge:
        return "captcha_blocked", detail
    if success:
        return "success_text", detail
    if failure:
        return "failed", detail
    if after.form_valid is False:
        return "failed", detail
    if after.url != before.url:
        return "redirect", detail
    if not after.form_visible:
        return "form_gone", detail
    if not after.email_value:
        # Field emptied, form still there: many AJAX forms reset on success
        return "form_reset", detail
    return "no_change", detail


class SubscribeTarget(NamedTuple):
    """What a sign-up needs from its test case and capture form, read before the browser work."""

    alias: str
    persona: str
    url: str
    signature: str
    html: Optional[str]


class SubscribeResult(NamedTuple):
    status: str
    detail: dict[str, Any]
    page_url: Optional[str]
    submitted_at: Optional[datetime.datetime]


def find_capture_form(site: WebSite, target: SubscribeTarget) -> Optional[FormBS]:
    """The capture form on the current page: same signature, else the closest stored-HTML match."""
    forms = [f for f in site.br.find_forms(site.lang) if capture.is_capture_candidate(f)]
    for form in forms:
        if capture.signature(form) == target.signature:
            return form
    if target.html and forms:
        stored_tag = BeautifulSoup(target.html, "html.parser").form
        if stored_tag is not None:
            stored = FormBS(stored_tag, site.lang)
            best = min(forms, key=stored.equality_score)
            if stored.equality_score(best) < 3:
                return best
    return None


def _find_shown_form(site: WebSite, target: SubscribeTarget) -> Optional[FormBS]:
    """Finds the form, replaying the pop-up steps until its email field is shown."""
    form = find_capture_form(site, target)
    if form is not None and capture.is_visible(form):
        return form
    steps = {
        "delay": site._wait_for_popup_delay,
        "scroll": site.br.scroll_through_page,
        "exit_intent": site.br.simulate_exit_intent,
    }
    for trigger in Config().POPUP_TRIGGERS:
        if trigger not in steps:
            continue
        logger.info("Sign-up: form not shown yet, pop-up trigger %s", trigger)
        steps[trigger]()
        if trigger != "delay":
            time.sleep(Config().POPUP_STEP_WAIT_SEC)
        form = find_capture_form(site, target)
        if form is not None and capture.is_visible(form):
            return form
    return form


def _input_map(form_sel: FormSelenium) -> dict[str, InputSelenium]:
    inputs = list(form_sel.inputs)
    for group in form_sel.radio_groups.values():
        inputs.extend(group)
    return {i.bs.id: i for i in inputs}


def apply_fill(
    site: WebSite, form_sel: FormSelenium, plan: FillPlan, alias: str, creds: Credentials
) -> list[str]:
    """Carries out the plan; returns what was filled, e.g. ["alias:mail", "tick:checkbox_pp"]."""
    by_id = _input_map(form_sel)
    done = []
    for a in plan.actions:
        inp = by_id.get(a.input_id)
        if inp is None:
            done.append(f"missing:{a.field}")
            continue
        try:
            if a.action == "alias":
                inp.fill_text(alias)
            elif a.action == "persona":
                inp.fill_text(inp.validate_text(getattr(creds, a.value or "")))
            elif a.action == "tick" and not inp.elem.is_selected():
                site.br.activate(inp.elem)
            elif a.action == "untick" and inp.elem.is_selected():
                site.br.activate(inp.elem)
            elif a.action == "select":
                inp.fill(creds, fill_all=True)
            elif a.action == "radio":
                site.br.activate(inp.elem)
            done.append(f"{a.action}:{a.field}")
        except WebDriverException as e:
            logger.warning("Sign-up: could not %s %s: %s", a.action, a.field, e.msg)
            done.append(f"error:{a.field}")
    return done


def _button_text(inp: InputSelenium) -> str:
    elem = inp.elem
    parts = (elem.text, elem.get_attribute("value"), elem.get_attribute("aria-label"))
    return " ".join(x for x in parts if x).strip()


def submit(form_sel: FormSelenium, email: InputSelenium) -> str:
    """
    Clicks the form's submit button, never one that closes a pop-up; without one, presses Enter
    in the email field. Never a JavaScript submit(), which bypasses the site's own handlers
    and can send an AJAX form twice. Returns how it submitted.
    """
    buttons = [
        i for i in form_sel.inputs if i.type in _SUBMIT_TYPES or i.direct_type in _SUBMIT_TYPES
    ]
    # <button> without a type submits too, but the crawler classifies it as BUTTON_OTHER
    buttons += [
        i
        for i in form_sel.inputs
        if i.direct_type in (InputType.BUTTON_OTHER, InputType.IMAGE)
        and (i.html_type or "").lower() in ("submit", "image")
        and i not in buttons
    ]
    for inp in buttons:
        text = _button_text(inp)
        if _DISMISS.search(text):
            continue
        try:
            if inp.elem.is_displayed():
                inp.elem.click()
                return f"button:{text[:40]}"
        except WebDriverException as e:
            logger.info("Sign-up: button %r not clickable: %s", text, e.msg)
    email.elem.send_keys(Keys.ENTER)
    return "enter"


def _observe(site: WebSite, form: FormBS, email_id: str, recorder: CaptchaRecorder) -> Observation:
    state = site.br.execute_script(_OBSERVE_JS, form.id, email_id) or {}
    return Observation(
        url=str(site.br.current_url),
        text=(state.get("text") or "").lower(),
        form_visible=bool(state.get("formVisible")),
        email_value=state.get("emailValue") or "",
        form_valid=state.get("valid"),
        challenge=recorder.challenge_shown(),
    )


def _screenshot(site: WebSite, stage: str) -> None:
    if Config().ALLOW_SCREENSHOTS:
        did = site.dump_id
        site.dump_id += 1
        (site.output_path / f"{did}_subscribe_{stage}.png").write_bytes(site.br.get_screenshot())


def _attempt(
    site: WebSite, form: FormBS, plan: FillPlan, target: SubscribeTarget, creds: Credentials, n: int
) -> tuple[str, dict[str, Any]]:
    """Fills and submits the form once; returns the outcome and its detail."""
    form_sel = FormSelenium.from_bs(site.br, form)
    recorder = CaptchaRecorder(site.br)
    recorder.detect()
    filled = apply_fill(site, form_sel, plan, target.alias, creds)
    _screenshot(site, f"filled_{n}")
    email_id = next(a.input_id for a in plan.actions if a.action == "alias")
    before = _observe(site, form, email_id, recorder)
    detail: dict[str, Any] = {
        "attempt": n,
        "filled": filled,
        "captcha": recorder.captcha_name,
        "captcha_visible": recorder.captcha_visible,
    }
    if Config().SUBSCRIBE_DRY_RUN:
        return "dry_run", detail
    detail["submitted_by"] = submit(form_sel, _input_map(form_sel)[email_id])
    time.sleep(Config().SUBSCRIBE_WAIT_SEC)
    status, observed = classify_outcome(before, _observe(site, form, email_id, recorder))
    _screenshot(site, f"submitted_{n}")
    return status, detail | observed


def run(site: WebSite, target: SubscribeTarget) -> SubscribeResult:
    """One study sign-up on the current browser (a fresh profile per job)."""
    # The study never pays for or solves CAPTCHAs
    Config().CAPTCHA_BACKEND = "none"
    creds = Credentials.load(target.persona)

    site.index_status = site.br.load_page(target.url)
    site._index_loaded_at = time.monotonic()
    try:
        site.real_lang_code, site.lang = site.setup_language()
    except Exception:  # pylint: disable=broad-except
        logger.info("Sign-up: language not detected, keeping %s", site.lang.code)

    form = _find_shown_form(site, target)
    page_url = str(site.br.current_url)
    _screenshot(site, "found")
    if form is None:
        return SubscribeResult("skipped_form_not_found", {}, page_url, None)
    if not capture.is_visible(form):
        return SubscribeResult("skipped_form_not_shown", {}, page_url, None)
    check = capture.eligibility(form, capture.captcha_info(form, site.br.get_html()))
    if not check.eligible:
        return SubscribeResult(f"skipped_{check.reject_reason}", {}, page_url, None)
    plan = plan_fill(form)
    if plan.skip_reason:
        return SubscribeResult(f"skipped_{plan.skip_reason}", {}, page_url, None)

    status, detail = _attempt(site, form, plan, target, creds, 1)
    submitted_at = None if status == "dry_run" else datetime.datetime.now()
    retry = status == "no_change" or (status == "failed" and not detail.get("failure_keywords"))
    if retry:
        # The form may require a persona field without marking it; try once with all of them
        refound = find_capture_form(site, target)
        second = plan_fill(refound, fill_all=True) if refound else None
        if second and second.skip_reason is None and len(second.actions) > len(plan.actions):
            logger.info("Sign-up: %s, retrying with all persona fields", status)
            status, detail2 = _attempt(site, refound, second, target, creds, 2)
            detail = {"first_attempt": detail} | detail2
    try:
        site.br.dump_html(site.output_path, f"{site.dump_id}_subscribe_after")
        site.dump_id += 1
    except WebDriverException:
        pass
    return SubscribeResult(status, detail, page_url, submitted_at)
