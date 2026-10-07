"""
The tests within this file actually send an email to infsec-server.inf.ethz.ch.
We expect the user to have the email flask_app@infsec-server.inf.ethz.ch
"""

import pytest
from hyperlink import URL

from enfbots_crawler import Config, RegistrationStatus, SessionLocal
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.website import WebSite

from pytest_mock import MockerFixture

from tests.apps.flask_app import flask_email  # type: ignore


@pytest.fixture
def real_email_creds(mocker: MockerFixture):
    creds = Credentials.get()
    # This must exist as a claim in the database
    creds.email = "flask_app@infsec-server.inf.ethz.ch"
    mocker.patch.object(Credentials, "get", return_value=creds)


def run_local_email_testcase(browser, flask_email_function) -> WebSite:
    site = WebSite(browser, flask_email_function)
    site.crawl()

    assert site.credentials
    assert site.credentials.username in flask_email.USERS
    expected = site.credentials
    actual = flask_email.USERS[expected.username]
    assert expected.username == actual.username
    assert expected.password == actual.password
    assert expected.email == actual.email

    return site


def test_local_email(browser, flask_email_function, real_email_creds, db_memory):
    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"
    Config().CREATE_ACCOUNT = True
    Config().USE_CLASSIFIER = False

    site = run_local_email_testcase(browser, flask_email_function)

    assert site


def test_db_content(browser, flask_email_function, real_email_creds, db_memory):
    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"
    Config().CREATE_ACCOUNT = True
    Config().USE_CLASSIFIER = False

    site = run_local_email_testcase(browser, flask_email_function)
    _, db_website = site.get_db_entity()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(db_website)

        assert len(db_website.cookies) == 1
        assert db_website.username == site.credentials.username
        assert len(db_website.forms) == 1
        reg_url = flask_email_function.child("register").to_text()
        assert db_website.forms[0].urls == str(list([reg_url]))
        # print("status: " + str(db_website.forms[0].reg_status))
        assert (
            db_website.forms[0].reg_status == RegistrationStatus.SUCCESS_KEYWORDS
        )  # Actually we should follow another link and then have RegistrationStatus.VERIFICATION_CODE_REQUESTED
        assert db_website.reg_url == reg_url
        assert db_website.reg_status == RegistrationStatus.SUCCESS_KEYWORDS
        assert db_website.tc_urls[0].tc_url.url == flask_email_function.child("terms").to_text()
        assert db_website.pp_urls[0].pp_url.url == flask_email_function.child("policy").to_text()

        # TODO: This test should find the link in the email.
