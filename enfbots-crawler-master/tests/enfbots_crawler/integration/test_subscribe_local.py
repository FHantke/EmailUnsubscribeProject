"""Study sign-ups (subscribe.py) against the local Flask app; needs Chrome (Docker dev image)."""

import pytest

from enfbots_crawler import Config, capture
from enfbots_crawler import subscribe as signup
from enfbots_crawler.website import WebSite
from tests.apps.flask_app import flask_app  # type: ignore

ALIAS = "news1234567890@study.example"


@pytest.fixture
def study(monkeypatch, output_directory):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)
    monkeypatch.setattr(Config(), "SUBSCRIBE_WAIT_SEC", 1.0)
    monkeypatch.setattr(Config(), "POPUP_TRIGGERS", [])
    flask_app.NEWSLETTER_SIGNUPS.clear()


def _target(site: WebSite, url) -> signup.SubscribeTarget:
    # What discovery would have stored for the form
    site.br.load_page(url)
    form = next(f for f in site.br.find_forms(site.lang) if capture.is_capture_candidate(f))
    return signup.SubscribeTarget(
        ALIAS, "us_jordan", str(url), capture.signature(form), str(form.tag)
    )


def test_signs_up_with_the_alias_and_required_fields_only(flask_app_function, browser, study):
    url = flask_app_function.child("newsletter")
    site = WebSite(browser, url)

    result = signup.run(site, _target(site, url))

    assert result.status == "success_text"
    assert result.submitted_at is not None
    # Required first name filled, optional last name and phone left empty, honeypot untouched,
    # privacy box ticked, pre-ticked SMS box unticked (unticked boxes are not sent)
    assert flask_app.NEWSLETTER_SIGNUPS == [
        {
            "email": ALIAS,
            "first_name": "Jordan",
            "last_name": "",
            "phone": "",
            "privacy": "yes",
            "comment": "",
        }
    ]
    assert not result.detail["submitted_by"].startswith("button:No thanks")


def test_dry_run_fills_but_never_submits(flask_app_function, browser, study, monkeypatch):
    monkeypatch.setattr(Config(), "SUBSCRIBE_DRY_RUN", True)
    url = flask_app_function.child("newsletter")
    site = WebSite(browser, url)

    result = signup.run(site, _target(site, url))

    assert result.status == "dry_run" and result.submitted_at is None
    assert flask_app.NEWSLETTER_SIGNUPS == []


def test_missing_form_is_skipped(flask_app_function, browser, study):
    url = flask_app_function.child("newsletter")
    site = WebSite(browser, url)
    target = signup.SubscribeTarget(ALIAS, "us_jordan", str(url), "no-such-form", None)

    assert signup.run(site, target).status == "skipped_form_not_found"
    assert flask_app.NEWSLETTER_SIGNUPS == []
