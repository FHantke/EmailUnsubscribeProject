"""Email-capture form finding in browser.py: forms without <form>, shadow roots, iframes (mocked)."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    NoSuchFrameException,
)

from selenium.webdriver.remote.webelement import WebElement

from enfbots_crawler import Config, capture
from enfbots_crawler import browser as browser_module
from enfbots_crawler.browser import Chrome, find_tagged
from enfbots_crawler.languages import Language

EN = Language.get(Path("enfbots_crawler/languages"), "en")

PAGE = """<html><body>
<form id="f1" data-enfbots-uuid="f1"><input type="email" name="email" data-enfbots-uuid="e1">
  <button type="submit">Join</button></form>
<div id="box" data-enfbots-uuid="box" data-enfbots-formless="1">
  <input type="email" placeholder="enter email address" data-enfbots-uuid="e2">
  <button>I'm In</button></div>
</body></html>"""
FRAME = """<html><body><form data-enfbots-uuid="f9"><input type="email" name="email"
  data-enfbots-uuid="e9"><button type="submit">Continue</button></form></body></html>"""
SHADOW = {
    "hosts": ["h1"],
    "tags": ["wisepops-root"],
    "html": '<form data-enfbots-uuid="f3"><input type="email" name="email" data-enfbots-uuid="e3">'
    "<button>Subscribe</button></form>",
}


class FakeFrame(WebElement):
    # pylint: disable=super-init-not-called
    # A plain attribute instead of WebElement's read-only property
    size: dict = {}
    def __init__(self, name, src, width=400, height=300, shown=True):
        self.name, self.src, self.size, self.shown = name, src, {"width": width, "height": height}, shown

    def get_attribute(self, attr):
        return self.src if attr == "src" else None

    def is_displayed(self):
        return self.shown


class FakeDriver:
    """The page and its iframes; scripts answered per context."""

    def __init__(self, pages, frames, shadow=()):
        self.pages, self.frames, self.shadow = pages, frames, list(shadow)
        self.context = "top"
        self.switch_to = SimpleNamespace(frame=self._frame, default_content=self._top)
        self.current_url = "https://shop.example/"
        self.scripts = []

    def _frame(self, frame):
        self.context = frame.name

    def _top(self):
        self.context = "top"

    @property
    def page_source(self):
        return self.pages[self.context]

    def execute_script(self, js, *args):
        self.scripts.append((self.context, js, args))
        if js == browser_module._TAG_FORMS_JS:
            return {}
        if js == browser_module._SHADOW_FORMS_JS:
            return self.shadow if self.context == "top" else []
        return None

    def find_elements(self, _by, _value):
        return self.frames if self.context == "top" else []


def _chrome(mocker, driver) -> Chrome:
    # Bypass __init__/__enter__ (profile copy, real browser)
    chrome = Chrome.__new__(Chrome)
    chrome.driver = driver
    chrome.dismissed_alerts = []
    mocker.patch.object(Chrome, "dismiss_dialogs")
    return chrome


@pytest.fixture
def capture_mode(monkeypatch):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)


def test_capture_mode_finds_forms_formless_containers_and_shadow_forms(mocker, capture_mode):
    driver = FakeDriver({"top": PAGE}, [], shadow=[SHADOW])
    forms = _chrome(mocker, driver).find_forms(EN)

    assert [f.tag.name for f in forms] == ["form", "div", "form"]
    assert all(capture.is_capture_candidate(f) for f in forms)
    formless, shadow = forms[1], forms[2]
    assert json.loads(formless.location_json()) == {"formless": True}
    assert shadow.shadow_hosts == ["h1"]
    assert json.loads(shadow.location_json()) == {"shadow_hosts": ["wisepops-root"]}
    assert forms[0].location_json() is None
    # The tagging script ran in capture mode (shadow roots, formless containers)
    assert ("top", browser_module._TAG_FORMS_JS, (True,)) in driver.scripts


def test_other_crawls_find_only_form_tags(mocker, monkeypatch):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", False)
    driver = FakeDriver({"top": PAGE}, [FakeFrame("vendor", "https://creatives.attn.tv/x")], [SHADOW])
    forms = _chrome(mocker, driver).find_forms(EN)

    assert [f.uuid for f in forms] == ["f1"]
    assert ("top", browser_module._TAG_FORMS_JS, (False,)) in driver.scripts


def test_iframes_of_sign_up_vendors_are_scanned_ads_and_tiny_ones_not(mocker, capture_mode):
    frames = [
        FakeFrame("ad", "https://googleads.g.doubleclick.net/pagead/ads?x=1"),
        FakeFrame("pixel", "https://creatives.attn.tv/tiny", width=1, height=1),
        FakeFrame("hidden", "https://creatives.attn.tv/hidden", shown=False),
        FakeFrame("attentive", "https://creatives.attn.tv/creative?token=abc"),
    ]
    driver = FakeDriver({"top": PAGE, "attentive": FRAME}, frames)

    forms = _chrome(mocker, driver).find_forms(EN)

    in_frame = [f for f in forms if f.frame]
    assert [f.uuid for f in in_frame] == ["f9"]
    assert in_frame[0].frame == {"index": 3, "src": "https://creatives.attn.tv/creative"}
    assert {ctx for ctx, _, _ in driver.scripts} == {"top", "attentive"}
    assert driver.context == "top"


def test_iframes_written_by_the_page_or_from_its_own_site_are_scanned(mocker, capture_mode):
    frames = [FakeFrame("blank", ""), FakeFrame("own", "https://forms.shop.example/signup")]
    driver = FakeDriver({"top": "<html></html>", "blank": FRAME, "own": FRAME}, frames)

    forms = _chrome(mocker, driver).find_forms(EN)

    assert [f.frame["index"] for f in forms] == [0, 1]


def test_enter_frame_by_position_then_by_src(mocker):
    frames = [FakeFrame("a", "https://x.example/a"), FakeFrame("b", "https://creatives.attn.tv/c?t=1")]
    driver = FakeDriver({}, frames)
    chrome = _chrome(mocker, driver)

    chrome.enter_frame({"index": 1, "src": "https://creatives.attn.tv/c"})
    assert driver.context == "b"
    # The iframes moved: found by src
    chrome.enter_frame({"index": 0, "src": "https://creatives.attn.tv/c"})
    assert driver.context == "b"
    chrome.enter_frame(None)
    assert driver.context == "top"
    with pytest.raises(NoSuchFrameException):
        chrome.enter_frame({"index": 0, "src": "https://gone.example/"})


def _context(found):
    """An element context answering find_elements by CSS selector."""
    context = MagicMock()
    context.find_elements.side_effect = lambda _by, css: list(found.get(css, []))
    return context


def test_find_tagged_prefers_the_uuid_to_repeated_or_empty_ids():
    go, country = MagicMock(), MagicMock()
    context = _context({'[data-enfbots-uuid="u-go"]': [go], '[id="Button_button-default"]': [country, go]})
    assert find_tagged(context, "u-go", "Button_button-default") is go
    # No such uuid in the page (InputBS made one up): the id
    assert find_tagged(context, "u-missing", "Button_button-default") is country
    with pytest.raises(NoSuchElementException):
        find_tagged(context, None, "")


def test_find_tagged_escapes_quotes_in_ids():
    elem = MagicMock()
    context = _context({'[id="say \\"hi\\""]': [elem]})
    assert find_tagged(context, None, 'say "hi"') is elem


def test_teaser_click_in_the_page(mocker):
    chrome = _chrome(mocker, MagicMock())
    button = MagicMock()
    chrome.driver.execute_script.return_value = [button, "Spin to win"]

    assert chrome.click_popup_teaser() == "Spin to win"
    button.click.assert_called_once()

    # Covered by the overlay itself: a JavaScript click
    button.click.side_effect = ElementClickInterceptedException("covered")
    assert chrome.click_popup_teaser() == "Spin to win"
    chrome.driver.execute_script.assert_called_with("arguments[0].click();", button)


def test_no_teaser_anywhere(mocker):
    driver = FakeDriver({"top": PAGE}, [FakeFrame("attentive", "https://creatives.attn.tv/x")])
    chrome = _chrome(mocker, driver)

    assert chrome.click_popup_teaser() is None
    assert [(ctx, args) for ctx, js, args in driver.scripts if js == browser_module._TEASER_JS] == [
        ("top", (False,)),
        ("attentive", (True,)),
    ]
    assert driver.context == "top"


def test_raw_references_among_the_iframes_are_skipped(mocker, capture_mode):
    # abc27.com, belk.com, wfla.com: the driver returned dicts, and the crawl ended
    raw = {"element-6066-11e4-a52e-4f735466cecf": "f.1"}
    frames = [raw, FakeFrame("attentive", "https://creatives.attn.tv/creative")]
    driver = FakeDriver({"top": PAGE, "attentive": FRAME}, frames)

    forms = _chrome(mocker, driver).find_forms(EN)

    assert [f.frame["index"] for f in forms if f.frame] == [1]


def test_a_failing_iframe_scan_keeps_the_pages_own_forms(mocker, capture_mode):
    driver = FakeDriver({"top": PAGE}, [])
    chrome = _chrome(mocker, driver)
    mocker.patch.object(Chrome, "_capture_frames", side_effect=TypeError("odd driver answer"))

    assert [f.uuid for f in chrome.find_forms(EN)] == ["f1", "box"]
    assert chrome.click_popup_teaser() is None
