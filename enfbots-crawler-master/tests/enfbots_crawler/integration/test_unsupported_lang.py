import json
import logging
import threading
from contextlib import contextmanager

from hyperlink import URL
import pytest

from enfbots_crawler import Config, website as website_module
from enfbots_crawler.website import WebSite

from tests.apps.flask_app_chinese import flask_app  # type: ignore


@contextmanager
def create_flask_app():
    """
    Creates a flask app which mocks emails and other functionalities.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    server, port = flask_app.create_server()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield URL.from_text(f"http://localhost:{port}")
    server.shutdown()


@pytest.fixture
def flask_app_function():
    with create_flask_app() as u:
        yield u


def crawl_this(browser, flask_app_pdf_function):
    Config().CREATE_ACCOUNT = False
    site = WebSite(browser, flask_app_pdf_function)
    site.crawl()

    return site


def test_chinese_supported(browser, flask_app_function):
    site = crawl_this(browser, flask_app_function)
    _, db_website = site.get_db_entity()

    states = json.loads(str(db_website.states))
    assert "UNSUPPORTED_LANGUAGE" not in states
    assert db_website.lang == "zh"


def test_unsupported_language_state(monkeypatch, browser, flask_app_function):
    def fake_extract_language(self, min_confidence):
        return "xx"

    monkeypatch.setattr(website_module.WebSite, "_extract_language", fake_extract_language)

    site = crawl_this(browser, flask_app_function)
    _, db_website = site.get_db_entity()

    states = json.loads(str(db_website.states))
    assert "UNSUPPORTED_LANGUAGE" in states
