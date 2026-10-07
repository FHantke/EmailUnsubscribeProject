import pytest
from hyperlink import URL
from pyngrok import ngrok
from pytest_mock import MockFixture

from enfbots_crawler import Config
from enfbots_crawler.browser import EnfbotsBrowser
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_selenium import FormSelenium


@pytest.fixture(scope="session")
def ngrok_flask_app(flask_app_session):
    ngrok.set_auth_token(Config().NGROK_AUTH_TOKEN)
    http_tunnel = ngrok.connect(flask_app_session.port)
    yield URL.from_text(http_tunnel.public_url)
    ngrok.disconnect(http_tunnel.public_url)


@pytest.mark.parametrize(
    "captcha_type, scenario",
    [
        ("recaptcha_v2", "auto"),
        ("recaptcha_v2", "invisible_auto"),
        ("recaptcha_v3", "auto"),
        ("hcaptcha", "auto"),
        ("hcaptcha", "invisible_onload"),
    ],
)
def test_captcha_submit(
    captcha_keys,
    native,
    browser: EnfbotsBrowser,
    ngrok_flask_app: URL,
    captcha_type: str,
    scenario: str,
    mocker: MockFixture,
) -> None:
    Config().CAPTCHA_ALLOW_STUB = True

    browser.load_page(ngrok_flask_app.child(captcha_type, scenario))
    forms = browser.find_forms()
    form_selenium = FormSelenium.from_bs(browser, forms[0])
    spy = mocker.spy(form_selenium.captcha_solver, "_submit_recaptcha_2cap")

    form_selenium.fill_form(Credentials.get(), False)
    form_selenium.submit_form()

    assert form_selenium.captcha_solver.captcha_type == captcha_keys[captcha_type].type
    assert form_selenium.captcha_solver.invisible == ("invisible" in scenario)
    assert form_selenium.captcha_solver.site_key == captcha_keys[captcha_type].site_key

    if captcha_type == "recaptcha_v3":
        spy.assert_called_once_with(action="submit_action")

    # on successful verification we are redirected to index
    assert browser.current_url.normalize() == ngrok_flask_app.normalize()


def test_captcha_image(
    browser: EnfbotsBrowser,
    flask_app_function,
) -> None:
    browser.load_page(flask_app_function.child("image_captcha"))

    forms = browser.find_forms()
    form_selenium = FormSelenium.from_bs(browser, forms[0])

    form_selenium.fill_form(Credentials.get(), False)
    form_selenium.submit_form()

    # on successful verification we are redirected to index
    assert browser.current_url.normalize() == flask_app_function.normalize()
