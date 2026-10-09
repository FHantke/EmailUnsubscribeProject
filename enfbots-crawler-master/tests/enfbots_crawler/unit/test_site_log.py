import logging
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from hyperlink import URL

from enfbots_crawler import CrawlerException, DomainStatus, main
from enfbots_crawler.website import BaseWebsite

logger = logging.getLogger("enfbots_crawler")


class _Site(BaseWebsite):
    def crawl(self) -> None:
        pass


@pytest.fixture(autouse=True)
def no_package_version(monkeypatch):
    # The crawler is not installed as a package in the dev environment
    monkeypatch.setattr("enfbots_crawler.website.version", lambda _: "test")


def _site(tmp_path, host: str) -> _Site:
    return _Site(MagicMock(), URL.from_text(f"https://{host}/"), tmp_path, True)


def _log(site: _Site) -> str:
    return (site.output_path / "crawler.log").read_text(encoding="utf-8")


def test_closed_log_receives_nothing_from_the_next_website(tmp_path):
    first = _site(tmp_path, "first.example")
    logger.warning("line from the first website")
    first.close_log()

    second = _site(tmp_path, "second.example")
    logger.warning("line from the second website")
    second.close_log()

    assert "line from the first website" in _log(first)
    assert "line from the second website" not in _log(first)
    assert "line from the second website" in _log(second)
    assert "line from the first website" not in _log(second)


def test_close_log_detaches_the_handler_and_can_be_called_twice(tmp_path):
    site = _site(tmp_path, "first.example")
    handler = site.output_log_filehandler
    assert handler in logging.getLogger().handlers

    site.close_log()
    site.close_log()
    site.__del__()

    assert handler not in logging.getLogger().handlers


def test_close_log_without_a_website_log(tmp_path):
    site = _Site(MagicMock(), URL.from_text("https://first.example/"), tmp_path, False)
    site.close_log()


@contextmanager
def _browser(**_kwargs):
    yield MagicMock()


@pytest.fixture
def run_domain_offline(monkeypatch):
    # Everything in run_domain that touches the network or a real browser; no Sybil checks
    monkeypatch.setattr(main.Config(), "CREATE_ACCOUNT", False)
    monkeypatch.setattr(main, "domain_status", lambda *_args, **_kwargs: DomainStatus.OK)
    monkeypatch.setattr(main, "assemble_url", lambda host: URL.from_text(f"https://{host}/"))
    monkeypatch.setattr(main, "create_browser", _browser)
    site = MagicMock()
    monkeypatch.setattr(main, "WebSite", lambda *_args: site)
    return site


def test_run_domain_closes_the_website_log(run_domain_offline):
    main.run_domain("first.example", stat_collector=MagicMock())

    run_domain_offline.close_log.assert_called_once()


def test_run_domain_closes_the_website_log_when_the_crawl_fails(run_domain_offline):
    run_domain_offline.crawl.side_effect = RuntimeError("crawl failed")

    with pytest.raises(CrawlerException, match="crawl failed"):
        main.run_domain("first.example", stat_collector=MagicMock())

    run_domain_offline.close_log.assert_called_once()
