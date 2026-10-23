"""
Sign-ups that are not a plain <form> in the page: an email field without a <form>, a form in an
iframe, in an open shadow root, and behind a two-step pop-up. Discovery finds them and
subscribe.py signs up to them. Needs Chrome (Docker dev image).
"""

import json

import pytest

from enfbots_crawler import Config, capture
from enfbots_crawler import subscribe as signup
from enfbots_crawler.website import WebSite
from tests.apps.flask_app import flask_app  # type: ignore

ALIAS = "news1234567890@study.example"


@pytest.fixture
def capture_mode(monkeypatch, output_directory):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)
    monkeypatch.setattr(Config(), "SUBSCRIBE_WAIT_SEC", 1.0)
    monkeypatch.setattr(Config(), "POPUP_TEASER_WAIT_SEC", 0.5)
    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", ["teaser"])
    flask_app.NEWSLETTER_SIGNUPS.clear()


def _page(flask_app_function, variant):
    return flask_app_function.child("static", "capture_variants.html").set("v", variant)


def _captures(browser):
    return [f for f in browser.find_forms() if capture.is_capture_candidate(f)]


@pytest.mark.parametrize(
    "variant, where",
    [
        ("formless", {"formless": True}),
        ("shadow", {"shadow_hosts": ["signup-popup"]}),
    ],
)
def test_discovery_finds_formless_and_shadow_forms(flask_app_function, browser, capture_mode, variant, where):
    browser.load_page(_page(flask_app_function, variant))
    forms = _captures(browser)

    assert len(forms) == 1
    assert capture.is_visible(forms[0]) and capture.eligibility(forms[0]).eligible
    assert json.loads(forms[0].location_json()) == where


def test_discovery_finds_the_form_in_an_iframe(flask_app_function, browser, capture_mode):
    browser.load_page(_page(flask_app_function, "iframe"))
    forms = _captures(browser)

    assert len(forms) == 1 and forms[0].frame["src"].endswith("/static/capture_frame.html")
    assert capture.is_visible(forms[0])


def test_discovery_clicks_the_teaser_of_a_two_step_popup(flask_app_function, browser, capture_mode):
    browser.load_page(_page(flask_app_function, "teaser"))
    assert _captures(browser) == []

    assert browser.click_popup_teaser() == "Claim my discount"
    assert len(_captures(browser)) == 1
    # Nothing more to click once the email step shows
    assert browser.click_popup_teaser() is None


def _target(site: WebSite, url) -> signup.SubscribeTarget:
    # What discovery would have stored for the form (after the teaser step, if any)
    site.br.load_page(url)
    forms = _captures(site.br)
    if not forms:
        site.br.click_popup_teaser()
        forms = _captures(site.br)
    form = forms[0]
    return signup.SubscribeTarget(ALIAS, "us_jordan", str(url), capture.signature(form), str(form.tag))


@pytest.mark.parametrize("variant", ["formless", "iframe", "shadow", "teaser"])
def test_signs_up_to_each_variant(flask_app_function, browser, capture_mode, variant):
    url = _page(flask_app_function, variant)
    site = WebSite(browser, url)
    target = _target(site, url)

    result = signup.run(site, target)

    assert result.status == "success_text", result.detail
    assert flask_app.NEWSLETTER_SIGNUPS == [{"email": ALIAS, "source": variant}]
