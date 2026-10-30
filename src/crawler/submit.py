"""Filling in and submitting the forms a crawl found.

The only module in the project that types into a page or clicks anything. A
crawl never reaches it: it runs from --submit, over a run that is already in
the database, so detection and submission stay separate phases and the forms
can be reviewed before anything real is sent.

Per site it takes the top-ranked subscription form, reopens the page it was
found on, replays the stimuli that made the form appear, fills it in, saves the
filled form, clicks submit, and records what came back. One site is submitted
to at most once, ever.

Submitting creates real subscriptions, and sometimes real accounts, on real
sites, which detection-only crawling does not. Ethics/IRB sign-off for that is
still an open question - see CLAUDE.md.
"""

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from selenium.common.exceptions import NoAlertPresentException
from selenium.common.exceptions import WebDriverException as SeErr
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

from crawler.browser import (_call, _call_async, _enter_frame_path, capture, detect_options,
                             make_driver, simulate_exit_intent)
from crawler.config import (DETECT_PATTERNS, LOAD_SETTLE_MS, PAINT_SETTLE_MS, SCROLL_BUDGET_MS,
                            SITE_TIME_LIMIT_PER_PAGE_S, STOP, SUBMIT_DISMISS, SUBMIT_FILL,
                            SUBMIT_FILL_DEFAULT, SUBMIT_REFUSE, SUBMIT_SETTLE_MS, SUBMIT_SMS,
                            SUBSCRIBE_FAILURE_KEYWORDS, SUBSCRIBE_SUCCESS_KEYWORDS,
                            TARGET_FORM_TYPE)
from crawler.jobs import SiteWatchdog, install_stop_handler
from crawler.js import DETECT_JS, FIELD_INFO_JS, OBSERVE_JS, SCROLL_JS
from crawler.output import Output, submission_targets
from crawler.util import form_signature, now, short, slug, strip_www

log = logging.getLogger(__name__)

# Chrome's own error page, e.g. ERR_HTTP2_PROTOCOL_ERROR when the form's
# endpoint did not load. Only one that is new after the click counts.
_PAGE_ERROR = re.compile(r"\berr_[a-z0-9_]+\b")
# Curly quotes and non-breaking spaces, so "You're in." matches "you're in".
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "\xa0": " "})


# ---------------------------------------------------------------------------
# Finding the form again
# ---------------------------------------------------------------------------

def _look(driver, path, want_sig):
    """Depth-first through this frame and its children for the wanted form.

    On a hit the driver is left standing in the form's frame, which is where it
    has to be to fill it in. Returns (cand, frame_path, frame_url) or None.
    """
    try:
        cands = driver.execute_script(_call(DETECT_JS, 1), detect_options(with_elements=True))
        frame_url = driver.execute_script("return location.href")
        n_frames = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
    except SeErr:
        return None
    for cand in cands:
        if form_signature(cand, frame_url) == want_sig:
            return cand, path, frame_url
    for i in range(n_frames):
        if _enter_frame_path(driver, path + (i,)):
            hit = _look(driver, path + (i,), want_sig)
            if hit:
                return hit          # leave the driver where the form is
        _enter_frame_path(driver, path)
    return None


def _find_target(driver, target, args):
    """Reopen the target's page and wait for its form to come back.

    Replays the same stimuli scan_page() uses, in the same order, and stops at
    the first phase where the form's signature reappears - a delayed popup or
    an exit-intent bar needs the same prompting the second time.
    """
    driver.get(target["page_url"])
    deadline = time.monotonic() + LOAD_SETTLE_MS / 1000
    while time.monotonic() < deadline:
        if driver.execute_script("return document.readyState") == "complete":
            break
        time.sleep(0.1)
    time.sleep(PAINT_SETTLE_MS / 1000)

    for phase in ["on_load", "after_delay", "after_scroll", "after_exit_intent"]:
        driver.switch_to.default_content()
        try:
            if phase == "after_delay":
                time.sleep(args.popup_wait)
            elif phase == "after_scroll":
                driver.execute_async_script(_call_async(SCROLL_JS), SCROLL_BUDGET_MS)
            elif phase == "after_exit_intent":
                simulate_exit_intent(driver)
        except SeErr as e:
            log.debug(f"  {phase}: {short(e)}")
        driver.switch_to.default_content()
        hit = _look(driver, (), target["form_sig"])
        if hit:
            log.info(f"  found again at {phase}")
            return hit
    return None


# ---------------------------------------------------------------------------
# Filling it in
# ---------------------------------------------------------------------------

def _hints(info):
    """The words describing one field: its name, placeholder and label."""
    return " ".join([info["name"], info["placeholder"], info["label"]]).replace("_", " ")


def _is_email_field(info):
    """A second email box - "confirm your email" - gets the alias too, not a name."""
    return info["type"] == "email" or bool(
        re.search(DETECT_PATTERNS["email"], _hints(info), re.I)
        and not re.search(DETECT_PATTERNS["not_email"], _hints(info), re.I))


def _is_sms_box(info):
    """A text-message opt-in. Never ticked, and unticked if the site pre-ticked it."""
    return bool(re.search(SUBMIT_SMS, _hints(info), re.I))


def _refuses(info):
    """Why the study will not fill this field in, or None if it will."""
    hay = _hints(info)
    for pattern, reason in SUBMIT_REFUSE:
        if re.search(pattern, hay, re.I):
            return reason
    return None


def _fill_value(info):
    """What to type into one required field, from SUBMIT_FILL in config.py."""
    hay = _hints(info)
    for pattern, value in SUBMIT_FILL:
        if re.search(pattern, hay, re.I):
            return value
    return SUBMIT_FILL_DEFAULT


def _type(driver, el, value):
    """Type into one field, replacing whatever is in it."""
    try:
        el.clear()
    except SeErr:
        pass                        # readonly or managed by a framework; type anyway
    el.send_keys(value)


def _click(driver, el):
    """Click, falling back to the page's own click when something covers it."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", el)
        time.sleep(0.2)
        el.click()
        return True
    except SeErr:
        pass
    try:
        # A consent box behind a styled label, or a button under a cookie
        # banner, cannot be clicked at its coordinates but still responds here.
        driver.execute_script("arguments[0].click()", el)
        return True
    except SeErr:
        return False


def _freeze(driver, form_el):
    """Write what was typed into the markup, so the saved HTML shows it.

    Typing sets a field's value *property*; outerHTML serializes its
    *attributes*, which still hold the empty page as it was served. Copying one
    to the other is what makes the saved filled form a record rather than a
    blank. It changes nothing about what is submitted, which reads the
    properties.
    """
    try:
        driver.execute_script(r"""
            for (const f of arguments[0].querySelectorAll('input, textarea, select')) {
              const t = (f.getAttribute('type') || '').toLowerCase();
              if (t === 'checkbox' || t === 'radio') f.toggleAttribute('checked', f.checked);
              else if (f.tagName === 'SELECT') {
                for (const o of f.options) o.toggleAttribute('selected', o.selected);
              } else if (f.value) f.setAttribute('value', f.value);
            }
        """, form_el)
    except SeErr as e:
        log.debug(f"  could not freeze values into the markup: {short(e)}")


def _typed_value(driver, el):
    """What a field actually holds now, read back from the page."""
    try:
        return driver.execute_script("return arguments[0].value || ''", el) or ""
    except SeErr:
        return ""


def _describe(driver, els):
    """Name, type, required, label and current value of each field, in one call."""
    if not els:
        return []
    return driver.execute_script(_call(FIELD_INFO_JS, 1), els) or []


def _fill(driver, cand, email):
    """Fill the form in. Returns (fields_filled, n_ticked, refused).

    `refused` names the kind of personal data the form requires and the study
    does not invent (SUBMIT_REFUSE); the caller then skips the form instead of
    submitting it. "no_email_field" means there was nowhere to put the address.

    Otherwise only required fields are touched, and only unchecked required
    checkboxes are ticked: a form's optional fields and the default state of its
    consent boxes are themselves part of what is studied. The exception is a
    pre-ticked SMS box, which is unticked - the study signs up for email, and
    gives no phone number for anyone to text.
    """
    email_el = cand.get("email_el")
    if email_el is None:
        return [], 0, "no_email_field"
    _type(driver, email_el, email)
    filled = [f"{cand.get('email_name') or cand.get('email_id') or 'email'}={email}"]

    others = [e for e in (cand.get("text_els") or []) if e != email_el]
    described = _describe(driver, others)
    # Refusals first, over every required field, so nothing is typed into a form
    # that is going to be skipped anyway.
    for info in described:
        if info["required"] and not _is_email_field(info):
            reason = _refuses(info)
            if reason:
                return filled, 0, reason
    for el, info in zip(others, described):
        if not info["required"] or info["value"].strip():
            continue
        if info["type"] == "select":
            choice = next((o for o in info["options"] if o.strip()), "")
            if choice:
                Select(el).select_by_value(choice)
                filled.append(f"{info['name'] or 'select'}={choice}")
            continue
        # A "confirm your email" box takes the address, not a name.
        value = email if _is_email_field(info) else _fill_value(info)
        _type(driver, el, value)
        filled.append(f"{info['name'] or info['type']}={value}")

    ticked = 0
    boxes = cand.get("checkbox_els") or []
    for el, info in zip(boxes, _describe(driver, boxes)):
        sms = _is_sms_box(info)
        if sms and info["checked"]:
            if _click(driver, el):
                filled.append(f"{info['name'] or 'checkbox'}=unticked_sms")
            continue
        if sms or info["checked"] or not info["required"]:
            continue
        if _click(driver, el):
            ticked += 1
            filled.append(f"{info['name'] or 'checkbox'}=checked")
    return filled, ticked, None


# ---------------------------------------------------------------------------
# Submitting, and judging what happened
# ---------------------------------------------------------------------------

def _submit_controls(cand):
    """The form's submit buttons, best first, as (element, text).

    DETECT_JS counts any <button> as submit-like whatever its text says, which
    is right for detection and wrong here: a popup's "No thanks" is a button
    too, and clicking it dismisses the form instead of sending it. Dismiss
    wording and menu-openers are dropped, and anything hidden is tried last.
    """
    pairs = list(zip(cand.get("submit_els") or [], cand.get("submit_info") or []))
    usable = [(el, i) for el, i in pairs
              if not i["toggle"] and not re.search(SUBMIT_DISMISS, (i["text"] or "").strip(), re.I)]
    # Visible ones first, each group in page order; a hidden submit input is
    # still worth a scripted click if nothing on screen works.
    return ([(el, i["text"]) for el, i in usable if i["displayed"]]
            + [(el, i["text"]) for el, i in usable if not i["displayed"]])


def _do_submit(driver, cand, email_el):
    """Click the form's submit button; failing that, press Enter in the email box.

    Never form.submit(), which skips the site's own handlers and can send an
    AJAX form twice. Returns how it was submitted, or "" if nothing worked.
    """
    for el, text in _submit_controls(cand):
        if _click(driver, el):
            return f"button:{(text or '')[:40]}"
        log.debug(f"  submit button {text!r} would not click")
    try:
        email_el.send_keys(Keys.ENTER)
        return "enter"
    except SeErr as e:
        log.debug(f"  Enter not possible: {short(e)}")
    return ""


def _take_alert(driver):
    """Accept a JavaScript alert the submit opened, returning its text.

    An open alert blocks every later driver call, so this has to run before
    anything else reads the page.
    """
    try:
        alert = driver.switch_to.alert
        text = alert.text or ""
        alert.accept()
        return text
    except NoAlertPresentException:
        return ""
    except SeErr as e:
        log.debug(f"  could not read an alert: {short(e)}")
        return ""


def _plain(text):
    """Page text as the keyword lists are written: lower case, straight quotes."""
    return (text or "").translate(_QUOTES).lower()


def _observe(driver, cand):
    """The page state the verdict is read from."""
    state = {}
    try:
        state = driver.execute_script(
            _call(OBSERVE_JS, 1), [cand.get("form_el"), cand.get("email_el")]) or {}
    except SeErr as e:
        # A form that navigated away - the ordinary case for a non-AJAX one -
        # leaves its elements stale, and passing one to the page raises before
        # the script runs. Read what is on screen now without them, or the
        # thank-you page would go unread and every such submit look like a bare
        # redirect.
        log.debug(f"  the form's elements are gone, reading the page itself: {short(e)}")
        try:
            driver.switch_to.default_content()
            state = {"text": driver.execute_script(
                "return document.body ? document.body.innerText : ''")}
        except SeErr as e2:
            log.debug(f"  could not observe the page: {short(e2)}")
    try:
        url = driver.current_url
    except SeErr:
        url = ""
    return {"url": url, "text": _plain(state.get("text")),
            "form_visible": bool(state.get("form_visible")),
            "email_value": state.get("email_value") or "",
            "form_valid": state.get("form_valid")}


def _observe_new_tab(driver, handle):
    """The result of a submit that opened a tab, as Mailchimp's target=_blank
    embeds do. Reads it, then closes it and goes back."""
    original = driver.current_window_handle
    try:
        driver.switch_to.window(handle)
        return {"url": driver.current_url,
                "text": _plain(driver.execute_script(
                    "return document.body ? document.body.innerText : ''")),
                "form_visible": False, "email_value": "", "form_valid": None}
    except SeErr as e:
        log.debug(f"  could not read the new tab: {short(e)}")
        return {"url": "", "text": "", "form_visible": False,
                "email_value": "", "form_valid": None}
    finally:
        try:
            driver.close()
            driver.switch_to.window(original)
        except SeErr:
            pass


def _new_keywords(keywords, before, after):
    """Only what appeared. A success message is usually in the page, hidden,
    before the click, so its mere presence afterwards proves nothing."""
    return [k for k in keywords if k in after and k not in before]


def classify_outcome(before, after):
    """What the click appears to have achieved, from the page either side of it.

    A heuristic for triage, like form_type: spot-check it against the result
    screenshots before reporting any of it.
    """
    success = _new_keywords(SUBSCRIBE_SUCCESS_KEYWORDS, before["text"], after["text"])
    failure = _new_keywords(SUBSCRIBE_FAILURE_KEYWORDS, before["text"], after["text"])
    errors = [e for e in _PAGE_ERROR.findall(after["text"]) if e not in before["text"]]
    email_kept = after["email_value"] == before["email_value"]
    detail = {"success_keywords": success, "failure_keywords": failure,
              "form_visible_after": after["form_visible"], "email_kept": email_kept,
              "form_valid_after": after["form_valid"]}
    if errors:
        return "page_error", detail
    if success:
        return "success_text", detail
    if failure:
        return "failed", detail
    # The browser itself refused the form. A form that hid or emptied itself is
    # invalid too, but because it took the address, so both are checked here.
    if after["form_valid"] is False and after["form_visible"] and email_kept:
        return "failed", detail
    if after["url"] != before["url"]:
        return "redirect", detail
    if not after["form_visible"]:
        return "form_gone", detail
    if not email_kept:
        return "form_reset", detail        # many AJAX forms clear on success
    return "no_change", detail


# ---------------------------------------------------------------------------
# One site
# ---------------------------------------------------------------------------

def _blank_row(target, args):
    """An empty submissions row for this target, for any outcome to fill in."""
    return {"timestamp": now(), "site": target["site"], "form_sig": target["form_sig"],
            "page_url": target["page_url"], "frame_url": target["frame_url"],
            "form_type": target["form_type"], "rank_on_page": target["rank_on_page"],
            "email_used": "", "dry_run": args.submit_dry_run, "outcome": "",
            "fields_filled": [], "n_checkboxes_ticked": 0, "submit_text_used": "",
            "screenshot_filled": "", "context_screenshot_filled": "", "html_filled": "",
            "final_url": "", "http_status_after": None, "result_heading": "", "result_text": "",
            "screenshot_after": "", "context_screenshot_after": "", "html_after": "", "error": ""}


def _alias(target, pattern):
    """The address this site gets. {site} becomes its hostname, so a later leak
    or sale can be traced back to the site that received the address."""
    host = urlparse(target["page_url"]).hostname or target["site"]
    return pattern.replace("{site}", slug(strip_www(host)))


def _result(driver, path, cand, sig, site, output):
    """What the page shows once the click has settled."""
    out = {}
    shots = capture(driver, path, cand, sig, site, output,
                    suffix="_after", el=cand.get("form_el"))
    out.update(screenshot_after=shots["screenshot"],
               context_screenshot_after=shots["context_screenshot"],
               html_after=shots["html_file"])
    try:
        driver.switch_to.default_content()
        out["final_url"] = driver.current_url
        status = driver.execute_script(
            "const n = performance.getEntriesByType('navigation')[0];"
            "return n && n.responseStatus ? n.responseStatus : '';")
        out["http_status_after"] = int(status) if status else None
        out["result_heading"] = driver.execute_script(
            "const h = document.querySelector('h1, h2');"
            "return h ? h.innerText.trim().slice(0, 200) : '';") or ""
        out["result_text"] = driver.execute_script(
            "return (document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 600);") or ""
    except SeErr as e:
        out["error"] = short(e)
    return out


def _submit_one(driver, target, args, output):
    """Find, fill, capture, submit and record one form. Returns the outcome."""
    site, sig = target["site"], target["form_sig"]
    row = _blank_row(target, args)

    hit = _find_target(driver, target, args)
    if hit is None:
        row["outcome"] = "not_found"
        output.submission(row)
        return row["outcome"]
    cand, path, frame_url = hit
    row["frame_url"] = frame_url
    row["email_used"] = email = _alias(target, args.submit_email)

    filled, ticked, refused = _fill(driver, cand, email)
    row["fields_filled"], row["n_checkboxes_ticked"] = filled, ticked
    if refused:
        # A form wanting data the study does not invent is left alone, not filled
        # with something made up. Nothing has been sent, so it stays eligible.
        row["outcome"] = refused if refused == "no_email_field" else f"skipped_{refused}"
        log.info(f"  skipped: the form requires {refused.replace('_', ' ')}")
        output.submission(row)
        return row["outcome"]

    # The address really has to be in the box: a popup stealing focus mid-typing
    # would otherwise submit a half-typed address and subscribe a stranger.
    typed = _typed_value(driver, cand.get("email_el"))
    if typed != email:
        _type(driver, cand.get("email_el"), email)
        typed = _typed_value(driver, cand.get("email_el"))
    if typed != email:
        row.update(outcome="failed_fill", error=f"email box holds {typed[:80]!r}")
        log.warning(f"  the address did not go in: {typed[:80]!r}")
        output.submission(row)
        return row["outcome"]

    # The filled form, before anything is clicked: the record of exactly what
    # was typed and which boxes were ticked at the moment of submission.
    _freeze(driver, cand.get("form_el"))
    shots = capture(driver, path, cand, sig, site, output,
                    suffix="_filled", el=cand.get("form_el"))
    row.update(screenshot_filled=shots["screenshot"],
               context_screenshot_filled=shots["context_screenshot"],
               html_filled=shots["html_file"])

    controls = _submit_controls(cand)
    row["submit_text_used"] = controls[0][1] if controls else ""
    if not controls:
        row["outcome"] = "no_submit_button"
        output.submission(row)
        return row["outcome"]
    if args.submit_dry_run:
        row["outcome"] = "filled_only"
        output.submission(row)
        return row["outcome"]

    # Written before the click. The watchdog can kill the browser mid-submit,
    # so a row has to exist already or a real subscription would go unrecorded.
    row["outcome"] = "submitting"
    output.submission(row)

    before = _observe(driver, cand)
    tabs = set(driver.window_handles)
    how = _do_submit(driver, cand, cand.get("email_el"))
    if not how:
        output.update_submission(site, sig, outcome="click_failed")
        return "click_failed"
    time.sleep(SUBMIT_SETTLE_MS / 1000)

    # An open alert blocks every driver call, so it has to be taken first.
    alert = _take_alert(driver)
    opened = [h for h in driver.window_handles if h not in tabs]
    after = _observe_new_tab(driver, opened[0]) if opened else _observe(driver, cand)
    if alert:
        after["text"] = f"{after['text']} {_plain(alert)}"
    result, detail = classify_outcome(before, after)
    output.update_submission(
        site, sig, outcome="submitted", submit_text_used=how, result=result,
        alert_text=alert[:500], new_tab_url=after["url"] if opened else "",
        **detail, **_result(driver, path, cand, sig, site, output))
    log.info(f"  {result}" + (f" ({', '.join(detail['success_keywords'])})"
                              if detail["success_keywords"] else ""))
    return "submitted"


def _record_error(output, target, args, err, outcome="error"):
    """Note a failure, keeping whatever the attempt had already recorded: an
    error after the form was filled must not erase what was filled in."""
    if output.update_submission(target["site"], target["form_sig"],
                                outcome=outcome, error=short(err)):
        return
    row = _blank_row(target, args)
    row.update(outcome=outcome, error=short(err))
    output.submission(row)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def submit_run(args):
    """Submit to one form on each site of the run named by --out."""
    out_dir = Path(args.out)
    targets = submission_targets(out_dir)
    output = Output(out_dir)
    try:
        already = set() if args.submit_again else output.submitted_sites()
        todo = [t for t in targets if t["site"] not in already]
        n_skipped = len(targets) - len(todo)
        if args.submit_limit:
            todo = todo[: args.submit_limit]
        if not todo:
            log.info(f"nothing to submit: {len(targets)} {TARGET_FORM_TYPE} form(s) in run "
                     f"'{output.run}', {n_skipped} site(s) already submitted to")
            return
        if n_skipped:
            log.info(f"{n_skipped} site(s) skipped: already submitted to")
        log.warning("%s %d form(s) as %s%s",
                    "Would submit to" if args.submit_dry_run else "SUBMITTING to",
                    len(todo), args.submit_email,
                    "" if args.submit_dry_run else ". This creates real subscriptions.")

        install_stop_handler()
        watchdog = SiteWatchdog()
        limit = args.site_time_limit or SITE_TIME_LIMIT_PER_PAGE_S * args.max_pages
        counts = {}
        for n, target in enumerate(todo, 1):
            if STOP["now"]:
                break
            if n > 1:
                time.sleep(args.submit_delay)   # a submission is a write: pace it harder
            log.info(f"[{n}/{len(todo)}] {target['site']}")
            watchdog.start(target["site"], limit)
            driver = outcome = None
            try:
                driver = make_driver(args)
                outcome = _submit_one(driver, target, args, output)
            except Exception as e:              # keep going on any per-site failure
                outcome = "site_timeout" if watchdog.fired else "error"
                log.error(f"  failed: {short(e)}")
                _record_error(output, target, args, e, outcome)
            finally:
                watchdog.stop()
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
            counts[outcome] = counts.get(outcome, 0) + 1
            log.info(f"  {outcome}")
        log.info("Submission run: " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))
    finally:
        output.close()
