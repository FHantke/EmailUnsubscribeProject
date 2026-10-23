import time
from unittest.mock import MagicMock, call

import pytest
from hyperlink import URL
from selenium.common.exceptions import WebDriverException

from enfbots_crawler import Config, PageState
from enfbots_crawler import browser as browser_module
from enfbots_crawler.browser import Chrome
from enfbots_crawler.website import WebSite


@pytest.fixture
def no_sleep(monkeypatch):
    # website and browser share the time module; records how long each sleep would have been
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def _site(mocker, tmp_path) -> WebSite:
    # Bypass __init__ (browser, database); _reveal_popups only needs these
    site = WebSite.__new__(WebSite)
    site.br = MagicMock()
    site.br.get_screenshot.return_value = b"png"
    site.output_path = tmp_path
    site.dump_id = 3
    site._index_loaded_at = time.monotonic() - 5
    mocker.patch.object(site, "categorize_forms_on_current_page")
    return site


def test_reveal_popups_runs_each_trigger_then_rescans(mocker, tmp_path, no_sleep, monkeypatch):
    monkeypatch.setattr(Config(), "ALLOW_SCREENSHOTS", True)
    site = _site(mocker, tmp_path)
    site.br.click_popup_teaser.return_value = "Spin to win"

    site._reveal_popups()

    assert site.categorize_forms_on_current_page.call_args_list == [
        call("delay"),
        call("scroll"),
        call("exit_intent"),
        call("teaser"),
    ]
    site.br.scroll_through_page.assert_called_once()
    site.br.simulate_exit_intent.assert_called_once()
    # "delay" waits until POPUP_WAIT_SEC after the homepage loaded (5 s ago here)
    assert Config().POPUP_WAIT_SEC - 6 < no_sleep[0] <= Config().POPUP_WAIT_SEC - 5
    assert no_sleep[1:] == [Config().POPUP_STEP_WAIT_SEC] * 2 + [Config().POPUP_TEASER_WAIT_SEC]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "3_popup_delay.png",
        "4_popup_scroll.png",
        "5_popup_exit_intent.png",
        "6_popup_teaser.png",
    ]


def test_teaser_step_without_a_two_step_popup_scans_nothing(mocker, tmp_path, no_sleep, monkeypatch):
    monkeypatch.setattr(Config(), "ALLOW_SCREENSHOTS", True)
    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", ["teaser"])
    site = _site(mocker, tmp_path)
    site.br.click_popup_teaser.return_value = None

    site._reveal_popups()

    site.categorize_forms_on_current_page.assert_not_called()
    assert no_sleep == [] and list(tmp_path.iterdir()) == []


def test_reveal_popups_keeps_going_when_a_trigger_fails(mocker, tmp_path, no_sleep):
    site = _site(mocker, tmp_path)
    site.br.scroll_through_page.side_effect = WebDriverException("page went away")
    site.br.click_popup_teaser.return_value = None

    site._reveal_popups()

    assert site.categorize_forms_on_current_page.call_args_list == [
        call("delay"),
        call("exit_intent"),
    ]


def test_popup_triggers_are_configurable(mocker, tmp_path, no_sleep, monkeypatch):
    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", ["exit_intent", "unknown"])
    site = _site(mocker, tmp_path)

    site._reveal_popups()

    assert site.categorize_forms_on_current_page.call_args_list == [call("exit_intent")]
    site.br.scroll_through_page.assert_not_called()

    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", [])
    site._reveal_popups()
    assert site.categorize_forms_on_current_page.call_count == 1


def _chrome(mocker) -> Chrome:
    # Bypass __init__/__enter__ (profile copy, real browser)
    chrome = Chrome.__new__(Chrome)
    chrome.driver = MagicMock()
    chrome.seconds_before_processing_page = 0
    chrome._load_status = {}
    chrome.last_loaded_url = None
    mocker.patch.object(Chrome, "dismiss_dialogs")
    mocker.patch.object(Chrome, "_press_key")
    return chrome


@pytest.mark.parametrize("capture_only, escape_presses", [(True, 0), (False, 1)])
def test_escape_is_not_pressed_in_email_capture_mode(
    mocker, monkeypatch, capture_only, escape_presses
):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", capture_only)
    chrome = _chrome(mocker)

    assert chrome.load_page(URL.from_text("https://shop.example.com/"), 0.01) == PageState.OK
    assert chrome._press_key.call_count == escape_presses


def test_scroll_through_page_ends_back_at_the_top(mocker, no_sleep):
    chrome = _chrome(mocker)

    chrome.scroll_through_page(steps=4)

    scripts = [c.args for c in chrome.driver.execute_script.call_args_list]
    assert [args[1] for args in scripts[:4]] == [0.25, 0.5, 0.75, 1.0]
    assert scripts[-1] == ("window.scrollTo(0, 0);",)
    assert len(no_sleep) == 4


def test_unblock_capture_vendors_adds_the_allow_rule(mocker, monkeypatch):
    monkeypatch.setattr(Config(), "CAPTURE_UNBLOCK_DOMAINS", ["attn.tv", "privy.com"])
    chrome = _chrome(mocker)
    chrome.driver.execute_async_script.return_value = 2

    chrome.unblock_capture_vendors()

    chrome.driver.get.assert_called_once_with(
        f"chrome-extension://{Config().UBLOCK_EXTENSION_ID}/dashboard.html"
    )
    script, domains, rule_id = chrome.driver.execute_async_script.call_args.args
    assert "updateSessionRules" in script
    assert domains == ["attn.tv", "privy.com"]
    assert rule_id == browser_module._UNBLOCK_RULE_ID


@pytest.mark.parametrize(
    "outcome",
    [WebDriverException("ERR_BLOCKED_BY_CLIENT"), "declarativeNetRequest is not available"],
)
def test_unblock_capture_vendors_failure_does_not_stop_the_crawl(mocker, caplog, outcome):
    chrome = _chrome(mocker)
    if isinstance(outcome, Exception):
        chrome.driver.execute_async_script.side_effect = outcome
    else:
        chrome.driver.execute_async_script.return_value = outcome

    chrome.unblock_capture_vendors()

    assert "Could not unblock sign-up vendors" in caplog.text


def test_disable_ublock_filtering_switches_to_no_filtering(mocker, caplog):
    chrome = _chrome(mocker)
    chrome.driver.execute_async_script.return_value = {"level": 0, "allowAll": True}

    with caplog.at_level("INFO", logger="enfbots_crawler"):
        chrome.disable_ublock_filtering()

    chrome.driver.get.assert_called_once_with(
        f"chrome-extension://{Config().UBLOCK_EXTENSION_ID}/dashboard.html"
    )
    (script,) = chrome.driver.execute_async_script.call_args.args
    assert '"setDefaultFilteringMode", level: 0' in script
    assert "filtering switched off" in caplog.text


@pytest.mark.parametrize(
    "outcome",
    [
        WebDriverException("ERR_BLOCKED_BY_CLIENT"),
        "the extension APIs are not available on this page",
        {"level": 2, "allowAll": False},  # message not understood (other uBlock version)
        {"level": 0, "allowAll": False},
    ],
)
def test_disable_ublock_filtering_failure_does_not_stop_the_crawl(mocker, caplog, outcome):
    chrome = _chrome(mocker)
    if isinstance(outcome, Exception):
        chrome.driver.execute_async_script.side_effect = outcome
    else:
        chrome.driver.execute_async_script.return_value = outcome

    chrome.disable_ublock_filtering()

    assert "Could not switch off uBlock Origin Lite filtering" in caplog.text


@pytest.mark.parametrize(
    "mode, called",
    [
        ("none", "disable_ublock_filtering"),
        ("allowlist", "unblock_capture_vendors"),
        ("default", None),
        ("bogus", None),
    ],
)
def test_capture_ublock_mode_selects_the_action(mocker, monkeypatch, mode, called):
    monkeypatch.setattr(Config(), "CAPTURE_UBLOCK_MODE", mode)
    chrome = _chrome(mocker)
    actions = {
        name: mocker.patch.object(chrome, name)
        for name in ("disable_ublock_filtering", "unblock_capture_vendors")
    }

    chrome.configure_ublock()

    assert {name for name, m in actions.items() if m.called} == ({called} if called else set())


def test_teaser_that_leads_to_another_page_goes_back(mocker, tmp_path, no_sleep, monkeypatch):
    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", ["teaser"])
    site = _site(mocker, tmp_path)
    # The homepage before the click, the paywall page after it
    urls = iter([URL.from_text("https://shop.example/")])
    type(site.br).current_url = property(
        lambda _: next(urls, URL.from_text("https://shop.example/subscribe"))
    )
    site.br.click_popup_teaser.return_value = "Subscribe"

    site._reveal_popups()

    site.br.driver.back.assert_called_once()
    site.categorize_forms_on_current_page.assert_not_called()
