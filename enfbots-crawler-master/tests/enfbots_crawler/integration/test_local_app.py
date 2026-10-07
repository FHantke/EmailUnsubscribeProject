import datetime
from typing import Optional

import pytest

from hyperlink import URL
from pytest_mock import MockerFixture
import json

from sqlalchemy import select

from enfbots_crawler import State, const
from enfbots_crawler import Config, RegistrationStatus, EmailVerificationStatus, PageState, FormType
from enfbots_crawler.database import DBWebsiteCrawl, SessionLocal
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.mail_processor import Sybil, Mail
from enfbots_crawler.website import WebSite

from tests.apps.flask_app import flask_app  # type: ignore
from tests.enfbots_crawler.integration.test_classifier import ENDPOINT_PASSWORD, ENDPOINT_PATH, ENDPOINT_USER


def run_local_app(browser, flask_app_function):
    """
    Run the crawler on the local domain

    Args:
        browser (_type_): browser to use
        flask_app_function (_type_): pytest fixture for the flask app

    Returns:
        Website: Crawled website
    """
    Config().CREATE_ACCOUNT = True
    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"
    site = WebSite(browser, flask_app_function)
    site.crawl()

    assert site.credentials
    assert site.credentials.username in flask_app.USERS
    expected = site.credentials
    actual = flask_app.USERS[expected.username]
    assert expected.username == actual.username
    assert expected.password == actual.password
    assert expected.email == actual.email
    return site


def test_local_app(browser, flask_app_function, email_creds, db_memory):
    Config().CREATE_ACCOUNT = True
    Config().CLASSIFY_SERVICE_ENDPOINT = ENDPOINT_PATH
    Config().CLASSIFY_SERVICE_USER = ENDPOINT_USER
    Config().CLASSIFY_SERVICE_TOKEN = ENDPOINT_PASSWORD
    run_local_app(browser, flask_app_function)


def test_db_content(browser, flask_app_function, email_creds, db_memory):
    Config().CREATE_ACCOUNT = True
    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"

    site = run_local_app(browser, flask_app_function)
    _, db_website = site.get_db_entity()

    assert len(db_website.cookies) == 1
    assert db_website.username == site.credentials.username
    assert len(db_website.forms) == 1
    reg_url = flask_app_function.child("register").to_text()
    print(db_website.forms[0].urls)
    assert db_website.forms[0].urls == str(list([reg_url]))
    assert db_website.forms[0].reg_status == RegistrationStatus.SUCCESS_REDIRECT
    assert db_website.reg_url == reg_url
    assert db_website.reg_status == RegistrationStatus.SUCCESS_REDIRECT
    assert db_website.tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()
    assert db_website.pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()


def _create_email(body, data):
    return Mail(
        123,
        "test_id",
        "Verify your email",
        "test@example.com",
        "Test Accounts",
        "myemail@example.com",
        "Me",
        body.replace("{{data}}", data),
        "headers",
        datetime.datetime.now(),
        "localhost",
    )


bodies = {
    "plain_body": """Please click the activation link at {{data}}""",
    "html_body": """<!DOCTYPE html> <html> <head> <title></title> <meta http-equiv="Content-Type" content="text/html; charset=utf-8" /> <meta name="viewport" content="width=device-width, initial-scale=1"> <meta http-equiv="X-UA-Compatible" content="IE=edge" /> </head> <body style="background-color: #f4ssf4f4; margin: 0 !important; padding: 0 !important;"> <!-- HIDDEN PREHEADER TEXT --> <div style="display: none; font-size: 1px; color: #fefefe; line-height: 1px; font-family: 'Lato', Helvetica, Arial, sans-serif; max-height: 0px; max-width: 0px; opacity: 0; overflow: hidden;"> We're thrilled to have you here! Get ready to dive into your new account. </div> <table border="0" cellpadding="0" cellspacing="0" width="100%"> <!-- LOGO --> <tr> <td bgcolor="#FFA73B" align="center"> <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;"> <tr> <td align="center" valign="top" style="padding: 40px 10px 40px 10px;"> </td> </tr> </table> </td> </tr> <tr> <td bgcolor="#FFA73B" align="center" style="padding: 0px 10px 0px 10px;"> <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;"> <tr> <td bgcolor="#ffffff" align="center" valign="top" style="padding: 40px 20px 20px 20px; border-radius: 4px 4px 0px 0px; color: #111111; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 48px; font-weight: 400; letter-spacing: 4px; line-height: 48px;"> <h1 style="font-size: 48px; font-weight: 400; margin: 2;">Welcome!</h1> <img src=" https://img.icons8.com/clouds/100/000000/handshake.png" width="125" height="120" style="display: block; border: 0px;" /> </td> </tr> </table> </td> </tr> <tr> <td bgcolor="#f4f4f4" align="center" style="padding: 0px 10px 0px 10px;"> <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;"> <tr> <td bgcolor="#ffffff" align="left" style="padding: 20px 30px 40px 30px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <p style="margin: 0;">We're excited to have you get started. First, you need to confirm your account. Just press the button below.</p> </td> </tr> <tr> <td bgcolor="#ffffff" align="left"> <table width="100%" border="0" cellspacing="0" cellpadding="0"> <tr> <td bgcolor="#ffffff" align="center" style="padding: 20px 30px 60px 30px;"> <table border="0" cellspacing="0" cellpadding="0"> <tr> <td align="center" style="border-radius: 3px;" bgcolor="#FFA73B"><a href="{{data}}" target="_blank" style="font-size: 20px; font-family: Helvetica, Arial, sans-serif; color: #ffffff; text-decoration: none; color: #ffffff; text-decoration: none; padding: 15px 25px; border-radius: 2px; border: 1px solid #FFA73B; display: inline-block;">Confirm Account</a></td> </tr> </table> </td> </tr> </table> </td> </tr> <!-- COPY --> <tr> <td bgcolor="#ffffff" align="left" style="padding: 0px 30px 0px 30px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <p style="margin: 0;">If that doesn't work, copy and paste the following link in your browser:</p> </td> </tr> <!-- COPY --> <tr> <td bgcolor="#ffffff" align="left" style="padding: 20px 30px 20px 30px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <p style="margin: 0;"><a href="#" target="_blank" style="color: #FFA73B;">{{data}}</a></p> </td> </tr> <tr> <td bgcolor="#ffffff" align="left" style="padding: 0px 30px 20px 30px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <p style="margin: 0;">If you have any questions, just reply to this email—we're always happy to help out.</p> </td> </tr> <tr> <td bgcolor="#ffffff" align="left" style="padding: 0px 30px 40px 30px; border-radius: 0px 0px 4px 4px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <p style="margin: 0;">Cheers,<br>BBB Team</p> </td> </tr> </table> </td> </tr> <tr> <td bgcolor="#f4f4f4" align="center" style="padding: 30px 10px 0px 10px;"> <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;"> <tr> <td bgcolor="#FFECD1" align="center" style="padding: 30px 30px 30px 30px; border-radius: 4px 4px 4px 4px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 400; line-height: 25px;"> <h2 style="font-size: 20px; font-weight: 400; color: #111111; margin: 0;">Need more help?</h2> <p style="margin: 0;"><a href="#" target="_blank" style="color: #FFA73B;">We&rsquo;re here to help you out</a></p> </td> </tr> </table> </td> </tr> <tr> <td bgcolor="#f4f4f4" align="center" style="padding: 0px 10px 0px 10px;"> <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px;"> <tr> <td bgcolor="#f4f4f4" align="left" style="padding: 0px 30px 30px 30px; color: #666666; font-family: 'Lato', Helvetica, Arial, sans-serif; font-size: 14px; font-weight: 400; line-height: 18px;"> <br> <p style="margin: 0;">If these emails get annoying, please feel free to <a href="#" target="_blank" style="color: #111111; font-weight: 700;">unsubscribe</a>.</p> </td> </tr> </table> </td> </tr> </table> </body> </html>""",
}


@pytest.fixture
def verify_always():
    Config().AWAIT_VERIFY_EMAIL = True
    yield
    Config().AWAIT_VERIFY_EMAIL = False


@pytest.mark.parametrize("body_name", ["plain_body", "html_body"])
def test_mail_verification_link(
    db_memory,
    browser,
    flask_app_function,
    mocker: MockerFixture,
    body_name,
    verify_always,
    email_creds,
    request,
):
    Config().CREATE_ACCOUNT = True

    body = bodies[body_name]

    activation_url = URL.from_text("https://verify.local/verify")

    email = _create_email(body, activation_url.to_text())

    assert email.activation_link == activation_url

    mocker.patch.object(Sybil, "get_emails", return_value=[email])

    og = browser.load_page

    def side_effect(url: str, timeout: Optional[float] = None):
        if url == activation_url:
            browser.load_page(flask_app_function.child("verify"), None)
            return PageState.OK
        else:
            return og(url, None)

    loader = mocker.patch.object(browser, "load_page", side_effect=side_effect)

    site = run_local_app(browser, flask_app_function)

    loader.assert_has_calls([mocker.call(activation_url)])
    assert (
        site.reg_processors[0].email_verification_status
        == EmailVerificationStatus.SUCCESS_ACTIVATION
    )


code_body = "Verification code for your account is: {{data}}"


def test_mail_verification_form(
    db_memory, browser, flask_app_function, mocker: MockerFixture, verify_always, email_creds
):
    Config().CREATE_ACCOUNT = True

    verification_code = "13781"
    flask_app.app.config["verification_code"] = verification_code

    email = _create_email(code_body, verification_code)
    assert email.verification_code == verification_code
    mocker.patch.object(Sybil, "get_emails", return_value=[email])
    site = run_local_app(browser, flask_app_function)

    assert (
        site.reg_processors[0].email_verification_status
        == EmailVerificationStatus.SUCCESS_VERIFICATION_CODE
    )
    flask_app.app.config["verification_code"] = None


# TODO add test that checks that we can insert code in https://verify.local/verify


def test_newsletter(browser, flask_app_function, email_creds, mocker: MockerFixture) -> None:
    Config().CREATE_ACCOUNT = True
    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"
    mocker.patch.object(FormBS, "classify_form", return_value=FormType.NEWSLETTER)
    site = WebSite(browser, flask_app_function)
    site.crawl()

    assert site.reg_processors[0].forms[0].form_type == FormType.NEWSLETTER
    assert State.NEWSLETTER_FORM_FOUND in site.states


def test_search_always(db_memory, browser, flask_app_function, mocker: MockerFixture) -> None:
    """
    Tests if Website.search is called even if both PP/TC links are found
    """
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_SEARCH = "always"
    Config().USE_CLASSIFIER = False

    import logging

    logging.basicConfig(level=logging.DEBUG)

    site = WebSite(browser, flask_app_function)

    search_fn = mocker.patch.object(WebSite, "search")
    site.crawl()

    search_fn.assert_called()
    assert search_fn.call_count == 2


def test_search_not_missing(db_memory, browser, flask_app_function, mocker: MockerFixture) -> None:
    """
    Tests that Website.search is NOT called when PP/TC are found.
    """
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_SEARCH = "missing"
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function)

    search_fn = mocker.patch.object(WebSite, "search")
    site.crawl()

    # Not called as PP/TC are found
    search_fn.assert_not_called()


def test_search_missing(
    db_memory, browser, flask_app_function_no_links, mocker: MockerFixture
) -> None:
    """
    Tests that Website.search is called when PP/TC are missing.
    """
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_SEARCH = "missing"
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function_no_links)

    search_fn = mocker.patch.object(WebSite, "search")
    site.crawl()

    search_fn.assert_called()
    assert search_fn.call_count == 2


def test_search_never(
    db_memory, browser, flask_app_function_no_links, mocker: MockerFixture
) -> None:
    """
    Tests that Website.search is called when PP/TC are missing.
    """
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_SEARCH = "never"
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function_no_links)

    search_fn = mocker.patch.object(WebSite, "search")
    site.crawl()

    search_fn.assert_not_called()


def test_email_found(
    db_memory, browser, flask_app_function_no_links, mocker: MockerFixture
) -> None:
    """
    Tests that email addresses are found
    """
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function_no_links)

    site.crawl()
    _, website_crawl = site.get_db_entity()

    found_emails = json.loads(website_crawl.found_emails)
    # print(type(website_crawl.found_emails))
    assert len(found_emails) == 4  # One on the index page and one on the login page

    assert [
        f"{prefix}@{website}"
        for (prefix, website, _, _) in found_emails
        if prefix == "email-prefix" and website == "web.site"
    ] != []

    assert [
        f"{prefix}@{website}"
        for (prefix, website, _, _) in found_emails
        if prefix == "email-prefix2" and website == "web.site2"
    ] != []


def test_normal(db_memory, browser, flask_app_function) -> None:
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function)

    site.crawl()
    _, website_crawl = site.get_db_entity()

    assert len(website_crawl.pp_urls) == 1
    assert len(website_crawl.tc_urls) == 1

    assert website_crawl.pp_urls[0].considered
    assert website_crawl.tc_urls[0].considered

    assert website_crawl.pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()
    assert website_crawl.tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()


def test_const_forbidden_domains(
    db_memory, browser, flask_app_function_external_forbidden_pp
) -> None:
    Config().CREATE_ACCOUNT = False
    Config().USE_SAFE_BROWSING_API = False
    Config().USE_CLASSIFIER = False

    site = WebSite(browser, flask_app_function_external_forbidden_pp)

    const.FORBIDDEN_DOMAINS += ("deepl.com",)  # type: ignore

    site.crawl()
    _, website_crawl = site.get_db_entity()

    with SessionLocal.begin() as session:
        session.add(website_crawl)
        assert len(website_crawl.tc_urls) == 1

        assert website_crawl.tc_urls[0].considered

        # Because no PP was found there are now the URLs that were tried via testing public links
        for link in website_crawl.pp_urls:
            assert link.considered == False

        assert (
            website_crawl.tc_urls[0].tc_url.url
            == flask_app_function_external_forbidden_pp.child("terms").to_text()
        )


def test_http_404_error(
    db_memory, browser, flask_app_function_missing_pp, mocker: MockerFixture
) -> None:
    """
    Tests that a privacy policy with a 404 http error is ignored.
    """
    Config().CREATE_ACCOUNT = False

    site = WebSite(browser, flask_app_function_missing_pp)

    site.crawl()

    _, db_website = site.get_db_entity()

    with SessionLocal.begin() as session:
        session.add(db_website)

        assert len(db_website.pp_urls) == 0
