"""
Email-capture forms (newsletters, offers, waitlists, ...) for the RFC 8058 study.

Decides whether a form found on a page is a capture the study may sign up to, and turns it
into a database row. Captures needing a password, a phone number or a payment card are out of
scope, as are account registration, login, contact and search forms.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from typing import Any, NamedTuple, Optional

from bs4.element import Tag
from hyperlink import URL, URLParseError

from enfbots_crawler import Config, FormType, InputType
from enfbots_crawler.captcha_solver import classify_captcha_url
from enfbots_crawler.database import DBCaptureForm
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.helper import get_attr
from enfbots_crawler.input_bs import InputBS
from enfbots_crawler.keyword_matching import keyword_score, match_keywords_lemmatized
from enfbots_crawler.languages import KeywordType

# Email + "confirm email" is common on newsletter forms; more suggests something else
MAX_EMAIL_INPUTS = 2

# Language-independent hints for payment-card fields, besides autocomplete="cc-*"
CARD_PATTERN = re.compile(r"card.?(number|num|no\b)|credit.?card|\bcvv|\bcvc|ccnum|cc-?num|expir")

# Token fields a CAPTCHA widget adds to the form (a hidden textarea); no visitor fills them in
_CAPTCHA_RESPONSE = re.compile(r"^(g-recaptcha|h-captcha|cf-turnstile)-response", re.I)

# Something about a text field that says it takes an email address. The keyword classifier
# alone also called "search-name" and "subscriber_id" email fields (discovery-2)
_EMAIL_HINT = re.compile(r"mail|correo|courriel|e-?post|posta|почт|メール|邮箱|이메일", re.I)

# Shopify's account forms carry their purpose in a hidden form_type (the newsletter's is
# "customer", with contact[tags]=newsletter)
_SHOPIFY_ACCOUNT_FORMS = {
    "customer_login",
    "create_customer",
    "recover_customer_password",
    "reset_customer_password",
    "activate_customer_password",
    "guest_login",
}
# Pages and form actions of logins, sign-ups for accounts and password resets
_ACCOUNT_PATH = re.compile(
    r"/(log[_-]?in|sign[_-]?in|signin|auth|account/(login|recover|register|reset)|"
    r"reset[_-]?password|forgot[_-]?password)\b",
    re.I,
)
# Email-first logins ask for the address, then for the password on the next step
_LOGIN_WORDS = re.compile(
    r"\b(log[ _-]?in|sign[ _-]?in|forgot|remember me|reset (your )?password|password)\b", re.I
)
# Words that make it a mailing list after all (e.g. Newegg's newsletter field "LoginName")
_LIST_WORDS = re.compile(
    r"subscri|newsletter|mailing list|e-?mail (updates|offers|list)|% off|discount|deals|offers",
    re.I,
)
_ORDER_WORDS = re.compile(
    r"\btrack(ing)? (your |my |an )?order|\border (number|status|lookup|#)|\bcheck (order )?status",
    re.I,
)
# Sales and service leads: the email is for a callback, not a list
_LEAD_WORDS = re.compile(
    r"\bapprais|\b(get|request) a (free )?(quote|demo|callback|consultation)|\bfree quote|"
    r"\bcontact sales|\btalk to (sales|an expert)|\bschedule a (demo|call)",
    re.I,
)

# Inputs that are controls rather than data fields
_CONTROL_TYPES = {
    InputType.BUTTON_OTHER,
    InputType.BUTTON_SUBMIT,
    InputType.BUTTON_LOGIN,
    InputType.BUTTON_REGISTRATION,
    InputType.BUTTON_CONTACT,
    InputType.BUTTON_SUBSCRIBE,
    InputType.IMAGE,
    InputType.RESET,
}

# Substrings of a form's HTML that point to the email platform behind it, most specific first
_VENDORS = (
    ("klaviyo", "klaviyo"),
    ("list-manage.com", "mailchimp"),
    ("mc4wp", "mailchimp"),
    ("mailchimp", "mailchimp"),
    ("hsforms", "hubspot"),
    ("hubspot", "hubspot"),
    ("sibforms", "brevo"),
    ("sendinblue", "brevo"),
    ("brevo", "brevo"),
    ("omnisend", "omnisend"),
    ("attentive", "attentive"),
    ("privy", "privy"),
    ("convertkit", "convertkit"),
    ("mailerlite", "mailerlite"),
    ("constantcontact", "constantcontact"),
    ("activecampaign", "activecampaign"),
    ("createsend", "campaignmonitor"),
    ("exacttarget", "salesforce_marketing_cloud"),
    ("demandware", "salesforce_commerce_cloud"),
    ("iterable", "iterable"),
    ("braze", "braze"),
    ("contact[tags]", "shopify"),
)

# Keyword types that decide a capture's kind; more follow with the offer keywords
_KIND_KEYWORDS = {"newsletter": KeywordType.NEWSLETTER}

# Ids the crawler injects (browser.load_form_info); random on every page load
_INJECTED_ID_PREFIX = "crawleruuid-"


class Eligibility(NamedTuple):
    eligible: bool
    # First rule the form failed; None if eligible
    reject_reason: Optional[str]


class CaptchaInfo(NamedTuple):
    # recaptcha_v2[_invisible], recaptcha_v3, recaptcha, hcaptcha[_invisible], turnstile, image
    type: str
    # True: needs user interaction; False: runs invisibly; None: on the page, not in this form
    visible: Optional[bool]


_SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", re.I)

# Rendered widget frames: (pattern, kind, shows a checkbox). The challenge frames come later
_WIDGET_FRAMES = (
    (re.compile(r"recaptcha/(api2|enterprise)/anchor.*size=invisible"), "recaptcha_v2_invisible", False),
    (re.compile(r"recaptcha/(api2|enterprise)/anchor"), "recaptcha_v2", True),
    (re.compile(r"hcaptcha\.com.*frame=checkbox"), "hcaptcha", True),
    (re.compile(r"challenges\.cloudflare\.com"), "turnstile", True),
)


def captcha_in(tag: Tag) -> Optional[CaptchaInfo]:
    """
    CAPTCHA widget inside tag (a form, or a whole page). Widgets bound to a button, or with
    data-size="invisible", run without interaction. Turnstile counts as visible unless its
    appearance is "interaction-only"/"execute", erring on the side of not interacting.
    """
    for el in tag.find_all(True):
        classes = set(get_attr(el, "class", "").split())
        on_button = el.name in ("button", "input")
        invisible = get_attr(el, "data-size", "") == "invisible" or on_button
        if "g-recaptcha" in classes:
            if get_attr(el, "data-action") and on_button:
                return CaptchaInfo("recaptcha_v3", False)
            kind = "recaptcha_v2_invisible" if invisible else "recaptcha_v2"
            return CaptchaInfo(kind, not invisible)
        if "h-captcha" in classes:
            return CaptchaInfo("hcaptcha_invisible" if invisible else "hcaptcha", not invisible)
        if "cf-turnstile" in classes:
            hidden = get_attr(el, "data-appearance", "") in ("interaction-only", "execute")
            return CaptchaInfo("turnstile", not hidden)
        if el.name == "iframe":
            src = get_attr(el, "src", "")
            for pattern, kind, checkbox in _WIDGET_FRAMES:
                if pattern.search(src):
                    return CaptchaInfo(kind, checkbox)
    return None


def page_captcha(page_html: str) -> Optional[CaptchaInfo]:
    """
    CAPTCHA script loaded by the page, for forms without a widget of their own.
    reCAPTCHA v3 (render=<sitekey>) is invisible by design; for other scripts it is unknown
    which form they guard, so visible stays None.
    """
    found: Optional[CaptchaInfo] = None
    for src in _SCRIPT_SRC.findall(page_html):
        try:
            url = URL.from_text(html_lib.unescape(src))
        except (URLParseError, ValueError):
            continue
        kind = classify_captcha_url(url)
        if kind == "recaptcha":
            render = dict(url.query).get("render")
            if render and render not in ("explicit", "onload"):
                return CaptchaInfo("recaptcha_v3", False)
            found = CaptchaInfo("recaptcha", None)
        elif kind is not None and found is None:
            found = CaptchaInfo(kind, None)
    return found


def is_captcha_response(inp: InputBS) -> bool:
    return bool(_CAPTCHA_RESPONSE.match(get_attr(inp.element, "name") or inp.id or ""))


def is_honeypot(inp: InputBS, form: FormBS) -> bool:
    """
    A field for bots: the classifier calls it one, or it is hidden while the form's email field
    is shown (Mailchimp's "b_comment" textarea). A pop-up's form hidden as a whole hides every
    field, so those don't count.
    """
    return inp.estimated_type == InputType.HONEYPOT or (not inp.visible and is_visible(form))


def captcha_info(form: FormBS, page_html: Optional[str] = None) -> Optional[CaptchaInfo]:
    """The form's own CAPTCHA if it has one, else whatever the page loads."""
    widget = captcha_in(form.tag)
    if widget is not None:
        return widget
    if any(
        i.estimated_type == InputType.CAPTCHA_INPUT and not is_captcha_response(i)
        for i in form.inputs
    ):
        return CaptchaInfo("image", True)
    if page_html:
        return page_captcha(page_html)
    return None


def looks_like_email(inp: InputBS) -> bool:
    """An email field: type="email", or a field the classifier took for one that says "mail"."""
    if inp.estimated_type != InputType.MAIL:
        return False
    if inp.direct_type == InputType.MAIL:
        return True
    # value: old pages put the hint there ("E-mail Newsletter Sign-up", cleared on focus)
    hints = (
        get_attr(inp.element, a)
        for a in ("name", "placeholder", "autocomplete", "aria-label", "value")
    )
    return bool(_EMAIL_HINT.search(" ".join(x for x in (*hints, inp.id, inp.label) if x)))


def email_inputs(form: FormBS) -> list[InputBS]:
    return [i for i in form.inputs if looks_like_email(i)]


def is_capture_candidate(form: FormBS) -> bool:
    """Any form with an email field; eligibility decides whether the study can use it."""
    return len(email_inputs(form)) > 0


def is_visible(form: FormBS) -> bool:
    """Whether an email field is shown; a pop-up's form can sit hidden in the page until then."""
    return any(i.visible for i in email_inputs(form))


def _is_card_field(inp: InputBS) -> bool:
    autocomplete = get_attr(inp.element, "autocomplete", "").lower()
    if autocomplete.startswith("cc-"):
        return True
    hints = " ".join(
        x
        for x in (
            get_attr(inp.element, "name"),
            inp.id,
            get_attr(inp.element, "placeholder"),
            inp.label,
        )
        if x
    ).lower()
    return bool(CARD_PATTERN.search(hints))


def _rule_text(form: FormBS) -> str:
    """What the rules read: the form's text, its buttons' values and its fields' names."""
    parts = [form_text(form, limit=2000)]
    for i in form.inputs:
        for attr in ("value", "name", "placeholder", "aria-label"):
            if attr == "value" and i.direct_type not in _CONTROL_TYPES:
                continue
            parts.append(get_attr(i.element, attr) or "")
        if i.id and not i.id.startswith(_INJECTED_ID_PREFIX):
            parts.append(i.id)
    return " ".join(p for p in parts if p)


def _hidden_value(form: FormBS, name: str) -> Optional[str]:
    return next(
        (get_attr(i.element, "value") for i in form.hidden_inputs
         if get_attr(i.element, "name") == name),
        None,
    )


def _is_account_form(form: FormBS) -> bool:
    action = get_attr(form.tag, "action") or ""
    return _hidden_value(form, "form_type") in _SHOPIFY_ACCOUNT_FORMS or bool(
        _ACCOUNT_PATH.search(action)
    )


def _is_shopify_newsletter(form: FormBS) -> bool:
    """Shopify's own sign-up; its contact[email] field makes the classifier call it a contact form."""
    return "newsletter" in (_hidden_value(form, "contact[tags]") or "")


def _is_login_page(url: Optional[str]) -> bool:
    if not url:
        return False
    try:
        path = URL.from_text(url).path
    except (URLParseError, ValueError):
        return False
    return bool(_ACCOUNT_PATH.search("/" + "/".join(path)))


def eligibility(
    form: FormBS, captcha: Optional[CaptchaInfo] = None, url: Optional[str] = None
) -> Eligibility:
    """
    Checks the study's rules in a fixed order and reports the first one the form fails.
    Inputs count whether or not they are visible, since pop-up forms are often hidden at first.
    A visible CAPTCHA disqualifies: the study never interacts with a CAPTCHA widget.
    url is the page the form is on; login and password-reset pages are out of scope.
    """
    inputs = form.inputs  # excludes type="hidden"

    def has(predicate: Any) -> bool:
        return any(predicate(i) for i in inputs)

    n_email = len(email_inputs(form))
    text = _rule_text(form)
    mailing_list = bool(_LIST_WORDS.search(text))

    if form.type == FormType.SEARCH or has(lambda i: i.estimated_type == InputType.SEARCH):
        return Eligibility(False, "search")
    if n_email == 0:
        return Eligibility(False, "no_email")
    if n_email > MAX_EMAIL_INPUTS:
        return Eligibility(False, "multiple_email")
    if has(lambda i: InputType.PASSWORD in (i.estimated_type, i.direct_type)):
        return Eligibility(False, "password")
    if has(lambda i: i.estimated_type == InputType.USERNAME) or _is_account_form(form):
        return Eligibility(False, "account")
    if has(_is_card_field):
        return Eligibility(False, "payment_card")
    if has(lambda i: i.estimated_type == InputType.PHONE and i.required):
        return Eligibility(False, "phone_required")
    if has(
        lambda i: i.tag_name == "textarea"
        and not is_captcha_response(i)
        and not is_honeypot(i, form)
    ):
        return Eligibility(False, "message_field")
    if form.type == FormType.LOGIN or _is_login_page(url):
        return Eligibility(False, "login")
    if _LOGIN_WORDS.search(text) and not mailing_list:
        return Eligibility(False, "login")
    if form.type == FormType.VERIFICATION:
        return Eligibility(False, "verification")
    if form.type == FormType.CONTACT and not _is_shopify_newsletter(form):
        return Eligibility(False, "contact")
    if _ORDER_WORDS.search(text):
        return Eligibility(False, "order_lookup")
    if _LEAD_WORDS.search(text) and not mailing_list:
        return Eligibility(False, "lead_form")
    if captcha is not None and captcha.visible:
        return Eligibility(False, "interactive_captcha")
    return Eligibility(True, None)


def form_text(form: FormBS, limit: int = 300) -> str:
    """Visible text of the form without <option> lists (e.g. long country selects)."""
    parts = []
    for s in form.tag.strings:
        parent = getattr(s, "parent", None)
        if parent is not None and parent.name in ("option", "script", "style"):
            continue
        text = s.strip()
        if text:
            parts.append(text)
    return " ".join(parts)[:limit]


def capture_kind(form: FormBS) -> str:
    strings = [
        x
        for x in (
            form_text(form),
            get_attr(form.tag, "id"),
            get_attr(form.tag, "name"),
            get_attr(form.tag, "class"),
            get_attr(form.tag, "action"),
        )
        if x and not x.startswith(_INJECTED_ID_PREFIX)
    ]
    scores = keyword_score(
        _KIND_KEYWORDS, strings, match_keywords_lemmatized, form.lang, Config().MIN_KW_MATCH_LEN
    )
    kind, score = max(scores.items(), key=lambda x: x[1])
    if score > 0:
        return kind
    if form.type == FormType.NEWSLETTER:
        return "newsletter"
    return "other"


def vendor_hint(form: FormBS) -> Optional[str]:
    html = str(form.tag).lower()
    for needle, vendor in _VENDORS:
        if needle in html:
            return vendor
    return None


def _field_name(inp: InputBS) -> str:
    name = get_attr(inp.element, "name")
    if name:
        return name
    if inp.id and not inp.id.startswith(_INJECTED_ID_PREFIX):
        return inp.id
    return ""


def field_summary(form: FormBS) -> list[dict[str, Any]]:
    return [
        {
            "type": i.estimated_type.name,
            "html_type": i.direct_type.name,
            "name": _field_name(i),
            "required": bool(i.required),
            "visible": i.visible,
            "label": (i.label or "")[:80],
        }
        for i in form.inputs
        if i.direct_type not in _CONTROL_TYPES
    ]


def signature(form: FormBS) -> str:
    """Stable across page loads: ignores the random ids the crawler injects."""
    fields = sorted(
        (_field_name(i), i.direct_type.name, (i.label or "")[:40])
        for i in form.inputs
        if i.direct_type not in _CONTROL_TYPES
    )
    action = (get_attr(form.tag, "action") or "").strip()
    return hashlib.sha1(json.dumps([action, fields]).encode("utf-8")).hexdigest()


def to_db(
    form: FormBS,
    url: str,
    website_crawl_id: int,
    page_html: Optional[str] = None,
    trigger: str = "inline",
) -> DBCaptureForm:
    captcha = captcha_info(form, page_html)
    result = eligibility(form, captcha, url)
    return DBCaptureForm(
        website_crawl_id=website_crawl_id,
        url=url,
        kind=capture_kind(form),
        eligible=result.eligible,
        reject_reason=result.reject_reason,
        trigger=trigger,
        visible=is_visible(form),
        vendor_hint=vendor_hint(form),
        fields=field_summary(form),
        captcha_type=captcha.type if captcha else None,
        captcha_visible=captcha.visible if captcha else None,
        signature=signature(form),
        frame_path=form.location_json(),
        html=str(form.tag),
    )
