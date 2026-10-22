"""Selenium actions: driver setup, page scanning, capture.

One driver per site (Selenium has no cheap per-context isolation the way
Playwright does), so every site starts from a clean profile. `SeErr` is caught
around every browser call: one failing page or frame must never stop a crawl.
"""

import logging
import time
from urllib.parse import urldefrag, urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException as SeErr
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By

from crawler.config import (
    BLOCKED_URL_PATTERNS, DEFAULT_FORM_TYPE, DESKTOP_VIEWPORT, DETECT_BUDGET_MS, DETECT_PATTERNS,
    FORM_TYPES, LINK_BLACKLIST, LOAD_SETTLE_MS, MAX_SHADOW_SCAN, PAINT_SETTLE_MS, SCRIPT_TIMEOUT_S,
    SCROLL_BUDGET_MS, SKIP_EXTENSIONS, TARGET_FORM_TYPE, URL_BLACKLIST,
)
from crawler.js import DETECT_JS, EXIT_INTENT_JS, LINKS_JS, SCROLL_JS
from crawler.util import form_signature, link_tier, now, same_site, short, slug


log = logging.getLogger(__name__)

# Our page scripts are arrow functions, which execute_script will not call on its
# own: it runs a statement list. These wrap one into a call that returns its value.
def _call(js, n_args=0):
    """`js` as a call expression, reading arguments[0..n-1]."""
    args = ", ".join(f"arguments[{i}]" for i in range(n_args))
    return f"return ({js.strip()})({args});"


def _call_async(js):
    """Same, for an async arrow function: execute_async_script appends a done
    callback as the last argument, and the script must call it when finished."""
    return ("const done = arguments[arguments.length - 1];"
            f"({js.strip()})(arguments[0]).then(() => done(null), e => done(String(e)));")


def detect_options(prefix="ux"):
    """The settings DETECT_JS needs, all from config.py. `prefix` starts every
    data-ux-form-id the run writes into the page."""
    return {"prefix": prefix, "budget": DETECT_BUDGET_MS, "maxShadowScan": MAX_SHADOW_SCAN,
            "patterns": DETECT_PATTERNS, "defaultFormType": DEFAULT_FORM_TYPE,
            "targetFormType": TARGET_FORM_TYPE,
            "formTypes": [dict(rules, name=name) for name, rules in FORM_TYPES]}


def make_driver(args):
    """A fresh Chrome for one site, set up to match the measurement regime.

    The viewport is forced through CDP rather than --window-size, which sizes the
    whole window: only this gives the exact DESKTOP_VIEWPORT the recorded widths
    and viewport_coverage are measured against. --hide-scrollbars matters for the
    same reason, or a classic scrollbar takes 15px out of the layout width.
    """
    o = Options()
    if args.headless:
        o.add_argument("--headless=new")
    o.add_argument("--hide-scrollbars")
    o.add_argument("--lang=en-US")
    o.add_argument("--accept-lang=en-US,en")
    if args.user_agent:
        o.add_argument(f"--user-agent={args.user_agent}")
    o.set_capability("acceptInsecureCerts", True)   # == Playwright ignore_https_errors
    o.page_load_strategy = "eager"                  # == wait_until="domcontentloaded"

    driver = webdriver.Chrome(options=o)
    driver.set_page_load_timeout(args.timeout)
    # Bounds every execute_script. Playwright has no equivalent, which is why a
    # page with a wedged main thread used to hang a whole shard indefinitely.
    driver.set_script_timeout(SCRIPT_TIMEOUT_S)
    try:
        driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride",
                               {"width": DESKTOP_VIEWPORT["width"], "height": DESKTOP_VIEWPORT["height"],
                                "deviceScaleFactor": 1, "mobile": False})
        driver.execute_cdp_cmd("Network.enable", {})
        # Service workers would serve cached responses around the URL blocking below.
        driver.execute_cdp_cmd("Network.setBypassServiceWorker", {"bypass": True})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": list(BLOCKED_URL_PATTERNS)})
    except SeErr as e:
        log.warning(f"  CDP setup failed ({short(e)}); viewport and media blocking may be off")
    return driver


def simulate_exit_intent(driver):
    """Sweep the mouse to the top edge and dispatch mouseout/mouseleave, which is
    what exit-intent popups listen for. Moves only; never clicks.
    """
    x = DESKTOP_VIEWPORT["width"] // 2
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        (ActionChains(driver)
         .move_to_element_with_offset(body, x, DESKTOP_VIEWPORT["height"] // 2)
         .move_to_element_with_offset(body, x, 1)
         .perform())
    except SeErr:
        pass            # the synthetic events below are what popups actually listen for
    driver.execute_script(_call(EXIT_INTENT_JS))
    time.sleep(2.5)


def rank_links(driver, base, visited):
    """Same-site, visible, unvisited links that match a LINK_TIERS tier, best tier first.

    Skips LINK_BLACKLIST link text and URL_BLACKLIST addresses (so "unsubscribe" is
    never followed, by its words or its address) and file downloads
    (SKIP_EXTENSIONS). Links matching no tier are dropped.
    """
    try:
        links = driver.execute_script(_call(LINKS_JS))
    except SeErr:
        return []
    scored = {}
    for link in links:
        href, _ = urldefrag(link["href"])
        p = urlparse(href)
        if p.scheme not in ("http", "https") or not link["visible"]:
            continue
        if not same_site(p.hostname, base) or SKIP_EXTENSIONS.search(p.path):
            continue
        if href in visited:
            continue
        text = link["text"].lower()
        if any(b in text for b in LINK_BLACKLIST) or any(b in href.lower() for b in URL_BLACKLIST):
            continue
        tier = link_tier(text, href.lower())
        if tier is not None and (href not in scored or tier < scored[href]):
            scored[href] = tier
    return [h for h, _ in sorted(scored.items(), key=lambda kv: kv[1])]


def _enter_frame_path(driver, path):
    """Switch from the top document down to the frame at `path` (indices into each
    level's iframe list). Returns True if the whole path still resolves."""
    driver.switch_to.default_content()
    for i in path:
        frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        if i >= len(frames):
            return False
        driver.switch_to.frame(frames[i])
    return True


def capture(driver, path, cand, sig, site, output):
    """Save one form's outerHTML, element screenshot and viewport screenshot.

    Runs with the driver already switched into the form's frame (`path`), and
    leaves it switched back there. Returns the row fields, with paths relative to
    --out. A step that fails leaves its field empty rather than failing the form.
    """
    files = {"screenshot": "", "context_screenshot": "", "html_file": ""}
    shot_dir = output.out / "screens" / slug(site)
    html_dir = output.out / "html" / slug(site)
    shot_dir.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    selector = f'[data-ux-form-id="{cand["dom_id"]}"]'

    try:
        el = driver.find_element(By.CSS_SELECTOR, selector)
    except SeErr:
        return files
    try:
        html = driver.execute_script("return arguments[0].outerHTML", el)
        path_html = html_dir / f"{sig}.html"
        path_html.write_text(html[:500_000], encoding="utf-8")
        files["html_file"] = output.rel(path_html)
    except SeErr:
        pass
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'center'})", el)
        time.sleep(0.3)                       # let the scroll settle before the shot
        png = shot_dir / f"{sig}.png"
        png.write_bytes(el.screenshot_as_png)
        files["screenshot"] = output.rel(png)
    except SeErr:
        pass
    try:
        # The whole window, so the form can be seen in context. Only the top
        # document can be screenshotted, so step out and then back into the frame.
        driver.switch_to.default_content()
        ctx_png = shot_dir / f"{sig}_context.png"
        ctx_png.write_bytes(driver.get_screenshot_as_png())
        files["context_screenshot"] = output.rel(ctx_png)
    except SeErr:
        pass
    finally:
        _enter_frame_path(driver, path)
    return files


def detect_in_all_frames(driver, prefix="ux"):
    """Every form candidate in the page and all its frames, as one flat list.

    For callers that only want the candidates and capture nothing; the crawl
    itself uses _scan_frame(), which also screenshots each form in its own frame.
    Leaves the driver on the top document.
    """
    found = []

    def walk(path):
        try:
            found.extend(driver.execute_script(_call(DETECT_JS, 1), detect_options(prefix)))
            n = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
        except SeErr:
            return
        for i in range(n):
            if _enter_frame_path(driver, path + (i,)):
                walk(path + (i,))
            _enter_frame_path(driver, path)

    driver.switch_to.default_content()
    walk(())
    driver.switch_to.default_content()
    return found


def _scan_frame(driver, path, phase, page_url, site, output, seen):
    """Detect and record forms in the frame at `path`, then recurse into its own
    frames. The driver is already switched into that frame; it is left there."""
    new = 0
    try:
        cands = driver.execute_script(_call(DETECT_JS, 1), detect_options())
        frame_url = driver.execute_script("return location.href")
    except SeErr:
        return 0
    for cand in cands:
        sig = form_signature(cand, frame_url)
        if sig in seen:
            continue
        seen.add(sig)
        files = capture(driver, path, cand, sig, site, output)
        output.form({
            "timestamp": now(), "site": site, "page_url": page_url,
            "frame_url": frame_url, "form_sig": sig, "first_seen_phase": phase,
            "in_iframe": bool(path), "source": "browser",
            **cand, **files,
        })
        new += 1
        log.info(f"    {phase}: {cand['placement_guess']} form ({cand['detection_method']})")

    try:
        n_frames = len(driver.find_elements(By.CSS_SELECTOR, "iframe, frame"))
    except SeErr:
        return new
    for i in range(n_frames):
        if not _enter_frame_path(driver, path + (i,)):
            continue
        try:
            new += _scan_frame(driver, path + (i,), phase, page_url, site, output, seen)
        except SeErr:
            pass
        _enter_frame_path(driver, path)      # back to this level for the next sibling
    return new


def scan_page(driver, url, site, args, output, seen):
    """Load one URL and detect forms in every frame after each phase.

    Phases run in order: on_load, after_delay (--popup-wait), after_scroll,
    after_exit_intent. A form not in `seen` is captured and written immediately
    with the phase it first appeared in. Always writes one pages.csv row and
    returns the number of new forms.
    """
    row = {"timestamp": now(), "site": site, "page_url": url, "final_url": "",
           "http_status": "", "status": "ok", "n_new_forms": 0, "error": ""}
    try:
        driver.get(url)                       # page_load_strategy "eager": returns at DOMContentLoaded
        deadline = time.monotonic() + LOAD_SETTLE_MS / 1000
        while time.monotonic() < deadline:    # then give the load event a bounded chance
            if driver.execute_script("return document.readyState") == "complete":
                break
            time.sleep(0.1)
        time.sleep(PAINT_SETTLE_MS / 1000)
        row["final_url"] = driver.current_url
        row["http_status"] = driver.execute_script(
            "const n = performance.getEntriesByType('navigation')[0];"
            "return n && n.responseStatus ? n.responseStatus : '';") or ""
    except SeErr as e:
        row.update(status="load_error", error=short(e))
        output.page(row)
        return 0

    page_url = row["final_url"]
    new = 0
    for phase in ["on_load", "after_delay", "after_scroll", "after_exit_intent"]:
        driver.switch_to.default_content()
        try:
            if phase == "after_delay":
                time.sleep(args.popup_wait)
            elif phase == "after_scroll":
                err = driver.execute_async_script(_call_async(SCROLL_JS), SCROLL_BUDGET_MS)
                if err:
                    row["error"] = f"{phase}: {err[:200]}"
            elif phase == "after_exit_intent":
                simulate_exit_intent(driver)
        except SeErr as e:
            row["error"] = f"{phase}: {short(e)}"

        driver.switch_to.default_content()
        try:
            new += _scan_frame(driver, (), phase, page_url, site, output, seen)
        except SeErr as e:
            row["error"] = f"{phase}: {short(e)}"
        driver.switch_to.default_content()

    row["n_new_forms"] = new
    output.page(row)
    return new
