import datetime
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from hyperlink import URL
from selenium.common.exceptions import WebDriverException

from enfbots_crawler import DomainStatus, main
from enfbots_crawler.database import DBTestCase, DBWebsiteCrawl, SessionLocal
from enfbots_crawler.exceptions import WebsiteException
from enfbots_crawler.study import create_test_cases
from enfbots_crawler.subscribe import SubscribeResult
from enfbots_crawler.website import WebSite

from test_study import db, discovery  # noqa: F401  pylint: disable=unused-import


@pytest.fixture
def case_id(discovery):  # noqa: F811
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        cases = create_test_cases(session, "disc", "subscribe-1")
        session.flush()
        shop = next(c for c in cases if c.capture_form.url.startswith("https://shop.example"))
        return shop.id


def _site() -> WebSite:
    # Bypass __init__ (browser, output folder); subscribe needs only these before signup.run
    site = WebSite.__new__(WebSite)
    site.base_url = URL.from_text("https://shop.example")
    site.crawl_stat_collector = MagicMock()
    site.db_websitecrawl = DBWebsiteCrawl()
    return site


def _case(case_id):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        return session.get(DBTestCase, case_id)


def test_subscribe_stores_the_result(case_id, mocker):
    now = datetime.datetime(2026, 10, 20, 12, 0)
    run = mocker.patch(
        "enfbots_crawler.website.signup.run",
        return_value=SubscribeResult(
            "success_text", {"filled": ["alias:mail"]}, "https://shop.example/", now
        ),
    )

    _site().subscribe(case_id)

    target = run.call_args.args[1]
    case = _case(case_id)
    assert target.alias == case.alias and target.url == "https://shop.example/"
    assert (case.submit_status, case.submit_detail, case.submitted_at) == (
        "success_text",
        {"filled": ["alias:mail"]},
        now,
    )


def test_a_submitted_test_case_is_never_submitted_again(case_id, mocker):
    run = mocker.patch(
        "enfbots_crawler.website.signup.run",
        return_value=SubscribeResult("form_gone", {}, None, datetime.datetime.now()),
    )
    _site().subscribe(case_id)
    _site().subscribe(case_id)

    assert run.call_count == 1


def test_browser_error_is_recorded_and_the_job_left_open(case_id, mocker):
    crash = WebDriverException("tab crashed")
    mocker.patch("enfbots_crawler.website.signup.run", side_effect=crash)

    with pytest.raises(WebsiteException):
        _site().subscribe(case_id)

    case = _case(case_id)
    assert case.submit_status == "error" and case.submitted_at is None


def test_run_domain_runs_subscribe_jobs_instead_of_crawling(monkeypatch):
    monkeypatch.setattr(main.Config(), "CREATE_ACCOUNT", True)
    monkeypatch.setattr(main.Config(), "EMAIL_CAPTURE_ONLY", True)  # no Sybilmail checks
    monkeypatch.setattr(main, "domain_status", lambda *_a, **_k: DomainStatus.OK)
    monkeypatch.setattr(main, "assemble_url", lambda h: URL.from_text(f"https://{h}/"))
    browser_args = {}

    @contextmanager
    def browser(**kwargs):
        browser_args.update(kwargs)
        yield MagicMock()

    monkeypatch.setattr(main, "create_browser", browser)
    site = MagicMock(index_redirect_url=None)
    monkeypatch.setattr(main, "WebSite", lambda *_a: site)
    monkeypatch.setattr(main, "SessionLocal", MagicMock())
    job = MagicMock(test_case_id=7)

    main.run_domain("shop.example", stat_collector=MagicMock(), job=job)

    site.subscribe.assert_called_once_with(7)
    site.crawl.assert_not_called()
    # No network interception (CAPTCHA stub) in email-capture mode
    assert browser_args["intercept_network"] is False
