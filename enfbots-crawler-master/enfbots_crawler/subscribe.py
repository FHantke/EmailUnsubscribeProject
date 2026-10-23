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
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, cast

import tldextract
from bs4 import BeautifulSoup
from bs4.element import Tag
from hyperlink import URL
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoAlertPresentException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from enfbots_crawler import Config, InputType, capture
from enfbots_crawler.captcha_solver import CaptchaRecorder
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.browser import EnfbotsBrowser
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
# Submit controls that aren't form inputs, e.g. Royal Caribbean's <a role="button" type="submit">
_TYPED_SUBMIT = "[type=submit]:not(button):not(input)"
_ROLE_BUTTON = "[role=button]:not(button):not(input)"
_PLAIN_BUTTON = "button[type=button]"
_ANY_SUBMIT = "input[type=submit], button[type=submit], input[type=image]"
# Curly quotes and non-breaking spaces, so "You’re in." matches the keyword "you're in"
_PLAIN_TEXT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', " ": " "})

# The form's state: is its email field still shown, what does it hold, does the browser consider
# the form valid (null when the form is gone, or isn't a <form>). Elements by [uuid, id], inside
# the shadow root the hosts lead to. The text includes what the form's fields show, since some
# forms write their thank-you into the email field itself (purple.com)
_OBSERVE_JS = """
const [formKeys, emailKeys, hosts] = arguments;
let root = document;
for (const h of hosts || []) {
    const host = root.querySelector(`[data-enfbots-uuid="${h}"]`);
    root = host && host.shadowRoot;
    if (!root) break;
}
const byKeys = ([uuid, id]) => {
    if (!root) return null;
    let found = null;
    try { found = uuid ? root.querySelector(`[data-enfbots-uuid="${uuid}"]`) : null; } catch (e) {}
    return found || (id ? root.getElementById(id) : null);
};
const form = byKeys(formKeys);
const email = byKeys(emailKeys);
const shown = (e) => !!e && e.isConnected && e.getClientRects().length > 0
                     && getComputedStyle(e).visibility !== 'hidden';
const fields = form ? [...form.querySelectorAll('input:not([type=hidden]):not([type=password]), textarea')]
    .map(e => `${e.value || ''} ${e.placeholder || ''}`).join(' ') : '';
const inShadow = root && root !== document ? [...root.children].map(e => e.innerText || '').join(' ') : '';
return {
    text: [document.body ? document.body.innerText : '', inShadow, fields].join(' '),
    formVisible: shown(email),
    emailValue: email ? email.value : '',
    valid: form && form.isConnected && form.checkValidity ? form.checkValidity() : null,
};
"""
# Chrome's own error page (e.g. ERR_HTTP2_PROTOCOL_ERROR when Mailchimp's page didn't load)
_PAGE_ERROR = re.compile(r"\berr_[a-z0-9_]+\b")
# A JavaScript alert after the submit that is a CAPTCHA's verdict (cokesburykids:
# "Google reCAPTCHA verification failed.")
_CAPTCHA_ALERT = re.compile(r"captcha|robot|verification failed", re.I)


def is_sms_box(inp: InputBS) -> bool:
    if inp.estimated_type == InputType.CHECKBOX_SMS:
        return True
    hints = (inp.label, get_attr(inp.element, "name"), inp.id, get_attr(inp.element, "value"))
    return bool(_SMS.search(" ".join(h for h in hints if h).replace("_", " ")))


def _wants_tick(inp: InputBS) -> bool:
    """A consent or required box that isn't ticked yet; never an SMS box."""
    return (
        not is_sms_box(inp)
        and (inp.estimated_type in CONSENT_BOXES or bool(inp.required))
        and not inp.prechecked
    )


# Scrolls a field to the middle of the screen; true if something outside its form (a pop-up,
# a cookie banner) is on top of it there. Floating labels inside the form don't count. Asks the
# field's own shadow root, if any, which would otherwise answer with its host
_COVERED_JS = """
const el = arguments[0];
el.scrollIntoView({block: "center", inline: "center"});
const r = el.getBoundingClientRect();
const root = el.getRootNode().elementFromPoint ? el.getRootNode() : document;
const top = root.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
const own = el.form || el.parentElement || el;
return !!top && top !== el && !el.contains(top) && !own.contains(top);
"""
_INNER_TEXT_JS = "return document.body ? document.body.innerText : '';"
# True if a hidden checkbox has a shown label, i.e. it is drawn by the site rather than hidden
_LABEL_SHOWN_JS = """
const el = arguments[0];
const shown = (e) => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
const labels = [...(el.labels || [])];
if (el.closest('label')) labels.push(el.closest('label'));
return labels.some(shown);
"""


def uncover(br: Any, elem: Any) -> str:
    """
    Brings a field into view and, if a pop-up covers it, closes that with Escape (only then, so
    a pop-up that is itself the sign-up form stays open). Returns no / closed_by_escape /
    still_covered.
    """
    if not br.execute_script(_COVERED_JS, elem):
        return "no"
    ActionChains(br.driver).send_keys(Keys.ESCAPE).perform()
    time.sleep(0.5)
    return "still_covered" if br.execute_script(_COVERED_JS, elem) else "closed_by_escape"


class FillAction(NamedTuple):
    # The input's data-enfbots-uuid (ids can be empty or repeated on a page)
    input_id: str
    # alias, persona, tick, untick, tick_styled, untick_styled, select or radio
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
        if est == InputType.HONEYPOT or direct in capture._CONTROL_TYPES:
            continue
        required = bool(inp.required)
        field = est.name.lower()
        key = inp.uuid or ""
        if not inp.visible:
            # A styled checkbox: the real box is hidden behind one the site draws (Brevo's
            # "input_replaced"). apply_fill touches it only if its label is shown
            if direct == InputType.CHECKBOX_OTHER:
                if is_sms_box(inp) and inp.prechecked:
                    actions.append(FillAction(key, "untick_styled", "checkbox_sms"))
                elif _wants_tick(inp):
                    actions.append(FillAction(key, "tick_styled", field))
            continue

        if inp.tag_name == "textarea":
            if required and not capture.is_captcha_response(inp):
                return FillPlan(actions, "message_required")
        elif direct in textual_types:
            if capture.looks_like_email(inp):
                actions.append(FillAction(key, "alias", field))
            elif capture._is_card_field(inp):
                if required:
                    return FillPlan(actions, "payment_card_required")
            elif est in FORBIDDEN:
                if required:
                    return FillPlan(actions, f"{FORBIDDEN[est]}_required")
            elif est in PERSONA_FIELDS:
                if required or fill_all:
                    actions.append(FillAction(key, "persona", field, PERSONA_FIELDS[est]))
            elif required:
                return FillPlan(actions, "unknown_required_field")
        elif direct == InputType.CHECKBOX_OTHER:
            if is_sms_box(inp):
                if inp.prechecked:
                    actions.append(FillAction(key, "untick", "checkbox_sms"))
            elif _wants_tick(inp):
                actions.append(FillAction(key, "tick", field))
        elif direct == InputType.SELECT_OTHER:
            if required:
                actions.append(FillAction(key, "select", field))
        elif direct == InputType.RADIO_OTHER:
            group = get_attr(inp.element, "name") or key
            if required and group not in radio_groups:
                radio_groups.add(group)
                actions.append(FillAction(key, "radio", field))
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
    # Visible challenge, e.g. "hcaptcha" or "datadome"; '' if none
    challenge: str


def _new_keywords(keywords: list[str], before: str, after: str) -> list[str]:
    return [k for k in keywords if k in after and k not in before]


def classify_outcome(before: Observation, after: Observation) -> tuple[str, dict[str, Any]]:
    """
    Judges a submit from the page before and after it. Only text that newly appeared counts,
    since success messages are often in the page (hidden) all along.
    """
    success = _new_keywords(Config().SUBSCRIBE_SUCCESS_KEYWORDS, before.text, after.text)
    failure = _new_keywords(Config().SUBSCRIBE_FAILURE_KEYWORDS, before.text, after.text)
    error_page = [e for e in _PAGE_ERROR.findall(after.text) if e not in before.text]
    email_kept = after.email_value == before.email_value
    detail = {
        "challenge": after.challenge,
        "success_keywords": success,
        "failure_keywords": failure,
        "url_before": before.url,
        "url_after": after.url,
        "form_visible_after": after.form_visible,
        "email_kept": email_kept,
        "form_valid_after": after.form_valid,
    }
    if after.challenge:
        return "captcha_blocked", detail
    if error_page:
        detail["page_error"] = error_page[0]
        return "page_error", detail
    if success:
        return "success_text", detail
    if failure:
        return "failed", detail
    # The browser refused the form as filled in. A form that hid or emptied itself after the
    # submit is invalid too, but because it took the address (carlsgolfland sent mail)
    if after.form_valid is False and after.form_visible and email_kept:
        return "failed", detail
    if after.url != before.url:
        return "redirect", detail
    if not after.form_visible:
        return "form_gone", detail
    if not email_kept:
        # Field emptied or rewritten, form still there: many AJAX forms reset on success
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


def _br(site: WebSite) -> EnfbotsBrowser:
    # WebSite.br is typed with BaseWebsite's unbound TypeVar; sign-ups always run on one
    return cast(EnfbotsBrowser, site.br)


def _match_capture_form(site: WebSite, target: SubscribeTarget) -> Optional[FormBS]:
    forms = [f for f in _br(site).find_forms(site.lang) if capture.is_capture_candidate(f)]
    for form in forms:
        if capture.signature(form) == target.signature:
            return form
    if target.html and forms:
        parsed = BeautifulSoup(target.html, "html.parser")
        # A <form>, or the container of a form without one
        stored_tag = parsed.form or parsed.find(True)
        if isinstance(stored_tag, Tag):
            stored = FormBS(stored_tag, site.lang)
            best = min(forms, key=stored.equality_score)
            if stored.equality_score(best) < 3:
                return best
    return None


def find_capture_form(site: WebSite, target: SubscribeTarget) -> Optional[FormBS]:
    """
    The capture form on the current page, in its iframes and shadow roots included: same
    signature, else the closest stored-HTML match. Ends in the page; enter_frame(form.frame)
    before using the form.
    """
    form = _match_capture_form(site, target)
    if form is not None and not (form.uuid or form.id):
        # Added to the page while it was being tagged, so not findable yet: scan again
        form = _match_capture_form(site, target)
    return form


def _find_shown_form(site: WebSite, target: SubscribeTarget) -> Optional[FormBS]:
    """Finds the form, replaying the pop-up steps until its email field is shown."""
    form = find_capture_form(site, target)
    if form is not None and capture.is_visible(form):
        return form
    steps = site.popup_steps()
    for trigger in Config().POPUP_TRIGGERS:
        if trigger not in steps:
            continue
        logger.info("Sign-up: form not shown yet, pop-up trigger %s", trigger)
        if not site.run_popup_step(trigger):
            continue
        form = find_capture_form(site, target)
        if form is not None and capture.is_visible(form):
            return form
    return form


def _input_map(form_sel: FormSelenium) -> dict[str, InputSelenium]:
    inputs = list(form_sel.inputs)
    for group in form_sel.radio_groups.values():
        inputs.extend(group)
    return {str(i.bs.uuid): i for i in inputs}


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
            elif a.action in ("tick_styled", "untick_styled"):
                if not site.br.execute_script(_LABEL_SHOWN_JS, inp.elem):
                    # Hidden with its label: not part of the form the visitor sees
                    done.append(f"hidden:{a.field}")
                    continue
                if inp.elem.is_selected() != (a.action == "tick_styled"):
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


def _button_text(elem: Any) -> str:
    parts = (elem.text, elem.get_attribute("value"), elem.get_attribute("aria-label"))
    return " ".join(x for x in parts if x).strip()


def _is_toggle(elem: Any) -> bool:
    """Opens a menu or list (a country selector), so it is never a form's submit button."""
    return elem.get_attribute("aria-expanded") is not None or (
        elem.get_attribute("aria-haspopup") or "false"
    ) not in ("false", "")


def _submit_controls(form_sel: FormSelenium) -> list[Any]:
    """
    The form's submit buttons, best first. Then links and divs the site made into one: those
    with type="submit", and a role="button" element if it is the form's only non-dismiss one.
    Last, a lone shown type="button" <button>: Klaviyo's forms submit from one of those and keep
    their real submit input hidden.
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
    elems = [i.elem for i in buttons]
    elems += form_sel.tag.find_elements(By.CSS_SELECTOR, _TYPED_SUBMIT)
    roles = [
        e
        for e in form_sel.tag.find_elements(By.CSS_SELECTOR, _ROLE_BUTTON)
        if e not in elems and not _DISMISS.search(_button_text(e))
    ]
    if len(roles) == 1:
        elems += roles
    plain = [
        e
        for e in form_sel.tag.find_elements(By.CSS_SELECTOR, _PLAIN_BUTTON)
        if e not in elems
        and not _DISMISS.search(_button_text(e))
        and not _is_toggle(e)
        and e.is_displayed()
    ]
    if len(plain) == 1:
        elems += plain
    return elems


def submit(form_sel: FormSelenium, email: InputSelenium) -> str:
    """
    Clicks the form's submit button, never one that closes a pop-up or opens a menu; without
    one, presses Enter in the email field. Never a JavaScript submit(), which bypasses the
    site's own handlers and can send an AJAX form twice. Returns how it submitted, or
    "not_submitted" if nothing worked.
    """
    for elem in _submit_controls(form_sel):
        text = ""
        try:
            text = _button_text(elem)
            if _DISMISS.search(text) or _is_toggle(elem):
                continue
            if elem.is_displayed():
                # Out from under a bottom cookie banner, if it is down there
                form_sel.br.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", elem
                )
                try:
                    elem.click()
                except ElementClickInterceptedException:
                    # Covered by a pop-up or cookie banner: click the same button through
                    # JavaScript, which still runs the site's own click and submit handlers
                    form_sel.br.activate(elem)
                    return f"button_js:{text[:40]}"
                return f"button:{text[:40]}"
        except WebDriverException as e:
            logger.info("Sign-up: button %r not clickable: %s", text, e.msg)
    try:
        email.elem.send_keys(Keys.ENTER)
        return "enter"
    except WebDriverException as e:
        logger.info("Sign-up: Enter not possible: %s", e.msg)
    # What Enter would have done: the form's own submit control, even a hidden one
    for elem in form_sel.tag.find_elements(By.CSS_SELECTOR, _ANY_SUBMIT):
        try:
            form_sel.br.activate(elem)
            return f"submit_js:{_button_text(elem)[:40]}"
        except WebDriverException as e:
            logger.info("Sign-up: submit control not usable: %s", e.msg)
    return "not_submitted"


def _page_text(text: Optional[str]) -> str:
    return (text or "").translate(_PLAIN_TEXT).lower()


def _observe(site: WebSite, form: FormBS, email: InputBS, recorder: CaptchaRecorder) -> Observation:
    keys = ([form.uuid, form.id], [email.uuid, email.id], form.shadow_hosts)
    state = site.br.execute_script(_OBSERVE_JS, *keys) or {}
    text = state.get("text") or ""
    if form.frame:
        # Challenges and messages can also appear in the page around the iframe
        _br(site).enter_frame(None)
        text += " " + (site.br.execute_script(_INNER_TEXT_JS) or "")
        challenge = recorder.challenge_name()
        try:
            _br(site).enter_frame(form.frame)
        except WebDriverException:
            logger.info("Sign-up: the form's iframe is gone")
    else:
        challenge = recorder.challenge_name()
    return Observation(
        url=str(site.br.current_url),
        text=_page_text(text),
        form_visible=bool(state.get("formVisible")),
        email_value=state.get("emailValue") or "",
        form_valid=state.get("valid"),
        challenge=challenge,
    )


def _take_alert(site: WebSite, dismissed_before: int) -> str:
    """
    Text of the JavaScript alerts the submit opened: one still open (accepted, so the page can
    go on), and those the browser's post_load_routine already dismissed after a JavaScript
    click (dismissed_alerts beyond dismissed_before). '' if there were none.
    """
    texts = list(site.br.dismissed_alerts[dismissed_before:])
    try:
        alert = site.br.driver.switch_to.alert
        texts.append(alert.text or "")
        alert.accept()
    except NoAlertPresentException:
        pass
    except WebDriverException as e:
        logger.info("Sign-up: could not read an alert: %s", e.msg)
    return " ".join(t for t in texts if t)


def _observe_new_tab(site: WebSite, handle: str, recorder: CaptchaRecorder) -> Observation:
    """
    The result of a submit that opened in a new tab (forms with target="_blank", e.g.
    Mailchimp embeds); takes a screenshot of it and closes it again.
    """
    driver = site.br.driver
    original = driver.current_window_handle
    driver.switch_to.window(handle)
    try:
        observed = Observation(
            url=str(site.br.current_url),
            text=_page_text(site.br.execute_script(_INNER_TEXT_JS)),
            form_visible=False,
            email_value="",
            form_valid=None,
            challenge=recorder.challenge_name(),
        )
        _screenshot(site, "new_tab")
    finally:
        driver.close()
        driver.switch_to.window(original)
    return observed


def _screenshot(site: WebSite, stage: str) -> None:
    if Config().ALLOW_SCREENSHOTS:
        did = site.dump_id
        site.dump_id += 1
        (site.output_path / f"{did}_subscribe_{stage}.png").write_bytes(site.br.get_screenshot())


def sign_up_address(creds: Credentials, target: SubscribeTarget) -> str:
    """
    The test case's alias, or for test sign-ups the persona's own address tagged with the site,
    so each message shows which sign-up it came from: jordan+12345@example.org becomes
    jordan+12345-mooncat@example.org on mooncat.com, jordan@example.org jordan+mooncat@example.org
    """
    if not creds.email:
        return target.alias
    local, domain = creds.email.rsplit("@", 1)
    site = re.sub(r"[^a-z0-9-]", "", tldextract.extract(target.url).domain.lower()) or "site"
    return f"{local}{'-' if '+' in local else '+'}{site}@{domain}"


def _attempt(
    site: WebSite, form: FormBS, plan: FillPlan, address: str, creds: Credentials, n: int
) -> tuple[str, dict[str, Any]]:
    """
    Fills and submits the form once with address; returns the outcome and its detail. Submits
    only if the email field really holds the address (a pop-up can take the focus mid-typing).
    The form's iframe, if any, must be the current frame. A StaleElementReferenceException out
    of here means the form re-rendered before anything was sent (submit() handles its own).
    """
    form_sel = FormSelenium.from_bs(_br(site), form)
    recorder = CaptchaRecorder(_br(site))
    recorder.detect()
    email_key = next(a.input_id for a in plan.actions if a.action == "alias")
    email = _input_map(form_sel)[email_key]
    detail: dict[str, Any] = {
        "attempt": n,
        "email_used": address,
        "covered": uncover(site.br, email.elem),
        "captcha": recorder.captcha_name,
        "captcha_visible": recorder.captcha_visible,
    }
    for _ in range(2):
        detail["filled"] = apply_fill(site, form_sel, plan, address, creds)
        typed = email.elem.get_property("value") or ""
        if typed == address:
            break
        # Typing was interrupted (a pop-up took the focus): close it and type again
        detail["covered_while_typing"] = uncover(site.br, email.elem)
    _screenshot(site, f"filled_{n}")
    if typed != address:
        detail["typed"] = typed[:80]
        return "failed_fill", detail
    before = _observe(site, form, email.bs, recorder)
    if Config().SUBSCRIBE_DRY_RUN:
        return "dry_run", detail
    tabs = set(site.br.driver.window_handles)
    dismissed_before = len(site.br.dismissed_alerts)
    detail["submitted_by"] = submit(form_sel, email)
    if detail["submitted_by"] == "not_submitted":
        return "failed_submit", detail
    time.sleep(Config().SUBSCRIBE_WAIT_SEC)
    # First, before anything else the open alert would block
    alert = _take_alert(site, dismissed_before)
    new_tabs = [h for h in site.br.driver.window_handles if h not in tabs]
    if new_tabs:
        after = _observe_new_tab(site, new_tabs[0], recorder)
        detail["new_tab"] = after.url
    else:
        after = _observe(site, form, email.bs, recorder)
    if alert:
        detail["alert"] = alert[:200]
        after = after._replace(
            text=f"{after.text} {_page_text(alert)}",
            challenge=after.challenge or ("captcha_alert" if _CAPTCHA_ALERT.search(alert) else ""),
        )
    status, observed = classify_outcome(before, after)
    _screenshot(site, f"submitted_{n}")
    return status, detail | observed


def run(site: WebSite, target: SubscribeTarget) -> SubscribeResult:
    """One study sign-up on the current browser (a fresh profile per job)."""
    # The study never pays for or solves CAPTCHAs
    Config().CAPTCHA_BACKEND = "none"
    creds = Credentials.load(target.persona)
    address = sign_up_address(creds, target)
    if creds.email:
        logger.warning("Test sign-up: persona %s's own address %s", target.persona, address)

    site.index_status = site.br.load_page(URL.from_text(target.url))
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
    check = capture.eligibility(form, capture.captcha_info(form, site.br.get_html()), page_url)
    if not check.eligible:
        return SubscribeResult(f"skipped_{check.reject_reason}", {}, page_url, None)
    plan = plan_fill(form)
    if plan.skip_reason:
        return SubscribeResult(f"skipped_{plan.skip_reason}", {}, page_url, None)

    try:
        _br(site).enter_frame(form.frame)
        status, detail = _attempt(site, form, plan, address, creds, 1)
    except StaleElementReferenceException:
        # The page re-rendered the form before anything was sent: find it again, once
        logger.info("Sign-up: the form re-rendered, finding it again")
        form = find_capture_form(site, target)
        plan = plan_fill(form) if form else FillPlan([], "form_not_found")
        if form is None or plan.skip_reason:
            return SubscribeResult(f"skipped_{plan.skip_reason}", {"stale": True}, page_url, None)
        _br(site).enter_frame(form.frame)
        status, detail = _attempt(site, form, plan, address, creds, 1)
    # Nothing was sent in a dry run, when the address could not be typed or nothing submitted
    nothing_sent = ("dry_run", "failed_fill", "failed_submit")
    submitted_at = None if status in nothing_sent else datetime.datetime.now()
    retry = status == "no_change" or (status == "failed" and not detail.get("failure_keywords"))
    if retry:
        # The form may require a persona field without marking it; try once with all of them
        refound = find_capture_form(site, target)
        second = plan_fill(refound, fill_all=True) if refound is not None else None
        if (
            refound is not None
            and second is not None
            and second.skip_reason is None
            and len(second.actions) > len(plan.actions)
        ):
            logger.info("Sign-up: %s, retrying with all persona fields", status)
            _br(site).enter_frame(refound.frame)
            status, detail2 = _attempt(site, refound, second, address, creds, 2)
            detail = {"first_attempt": detail} | detail2
    try:
        _br(site).enter_frame(None)
        site.br.dump_html(site.output_path, f"{site.dump_id}_subscribe_after")
        site.dump_id += 1
    except WebDriverException:
        pass
    return SubscribeResult(status, detail, page_url, submitted_at)
