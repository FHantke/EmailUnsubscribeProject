import logging
import threading
from contextlib import contextmanager

from hyperlink import URL
import pytest

from enfbots_crawler import Config
from enfbots_crawler.website import WebSite
from enfbots_crawler.enums import ConsiderationBasis

from tests.apps.flask_app_popular import flask_app  # type: ignore


@contextmanager
def create_flask_app_popular():
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
    with create_flask_app_popular() as u:
        yield u


def crawl_this(browser, flask_app_popular_function):
    Config().CREATE_ACCOUNT = False
    site = WebSite(browser, flask_app_popular_function)
    site.crawl()

    return site


def test_popular_url(browser, flask_app_function, db_memory):
    Config().USE_CLASSIFIER = False

    Config().POPULAR_PP_PATHS += ",secret-link"

    site = crawl_this(browser, flask_app_function)
    _, db_website = site.get_db_entity()

    # PP url is not referenced from index and is found via the popular list
    assert len(site.pp_urls) == 1
    assert len(site.tc_urls) == 1

    # TODO; create POPULAR_* consideration basis
    assert site.pp_urls[0].consideration_basis == ConsiderationBasis.POPULAR
    assert site.tc_urls[0].consideration_basis != ConsiderationBasis.POPULAR
