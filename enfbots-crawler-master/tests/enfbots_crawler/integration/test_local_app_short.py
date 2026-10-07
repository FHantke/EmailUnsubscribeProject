from enfbots_crawler import Config, ConsiderationBasis
from enfbots_crawler.website import WebSite

from enfbots_crawler.database import SessionLocal


def crawl_this(browser, flask_app_pdf):
    Config().CREATE_ACCOUNT = False
    site = WebSite(browser, flask_app_pdf)
    site.crawl()

    return site


def test_short_pp(browser, flask_app_function_short, db_memory):
    Config().USE_CLASSIFIER = False

    site = crawl_this(browser, flask_app_function_short)
    _, db_website = site.get_db_entity()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(db_website)

        assert len(db_website.pp_urls) == 1
        assert not db_website.pp_urls[0].considered
        assert db_website.pp_urls[0].consideration_basis == ConsiderationBasis.TOO_SHORT_TEXT

        # TC is not too short in that case
        assert len(db_website.tc_urls) == 1
        assert db_website.tc_urls[0].considered
        assert db_website.tc_urls[0].tc_url.url == flask_app_function_short.child("terms").to_text()


def test_short_pp_and_tc(browser, flask_app_function_short_tc, db_memory):
    Config().USE_CLASSIFIER = False

    site = crawl_this(browser, flask_app_function_short_tc)
    _, db_website = site.get_db_entity()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(db_website)

        assert len(db_website.pp_urls) == 1
        assert not db_website.pp_urls[0].considered
        assert db_website.pp_urls[0].consideration_basis == ConsiderationBasis.TOO_SHORT_TEXT

        # TC is too short in that case; There are two links: popular path and the one found with too
        # short content
        assert len(db_website.tc_urls) == 2

        assert not db_website.tc_urls[0].considered
        assert not db_website.tc_urls[1].considered

        assert (
            db_website.tc_urls[0].consideration_basis == ConsiderationBasis.TOO_SHORT_TEXT
            and db_website.tc_urls[1].consideration_basis == ConsiderationBasis.TOO_SHORT_TEXT
        )
        assert (
            db_website.tc_urls[0].tc_url.url == flask_app_function_short_tc.child("terms").to_text()
            and db_website.tc_urls[1].tc_url.url
            == flask_app_function_short_tc.child("terms").to_text()
        )
