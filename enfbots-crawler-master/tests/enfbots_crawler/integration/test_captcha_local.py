from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest
from pytest_mock import MockerFixture
from selenium.webdriver.common.by import By

import enfbots_crawler
from enfbots_crawler import Config
from enfbots_crawler.browser import EnfbotsBrowser
from enfbots_crawler.captcha_solver import CaptchaSolverStub
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_selenium import FormSelenium

from tests.apps.flask_app import flask_app  # type: ignore
from PIL import Image


def assert_images_equal(base_image: str, img_file: Path):
    img1 = Image.open(BytesIO(base64.b64decode(base_image)))
    img2 = Image.open(img_file)

    # Convert to same mode and size for comparison
    img2 = img2.convert(img1.mode)
    img2 = img2.resize(img1.size)

    sum_sq_diff = np.sum((np.asarray(img1).astype("float") - np.asarray(img2).astype("float")) ** 2)

    if sum_sq_diff == 0:
        # Images are exactly the same
        pass
    else:
        normalized_sum_sq_diff = sum_sq_diff / np.sqrt(sum_sq_diff)
        assert normalized_sum_sq_diff < 0.001


@pytest.mark.parametrize(
    "captcha_type, scenario",
    [
        ("recaptcha_v2", "auto"),
        ("recaptcha_v2", "onload"),
        ("recaptcha_v2", "onload_var"),
        ("recaptcha_v2", "invisible_auto"),
        ("recaptcha_v2", "invisible_onload"),
        ("recaptcha_v3", "auto"),
        ("recaptcha_v3", "listener"),
        ("recaptcha_v3", "onclick"),
        ("recaptcha_v3", "external"),
        ("hcaptcha", "auto"),
        ("hcaptcha", "auto_compat"),
        ("hcaptcha", "onload"),
        ("hcaptcha", "onload_compat"),
        ("hcaptcha", "onload_var"),
        ("hcaptcha", "invisible_auto"),
        ("hcaptcha", "invisible_onload"),
    ],
)
def test_captcha_detection(
    captcha_keys, browser: EnfbotsBrowser, flask_app_function, captcha_type: str, scenario: str
) -> None:
    flask_app.app.config["site_key"] = captcha_keys[captcha_type].site_key
    Config().CAPTCHA_BACKEND = "debug"

    browser.load_page(flask_app_function.child(captcha_type, scenario))
    captcha_solver = enfbots_crawler.captcha_solver.create_solver(browser)
    captcha_solver.detect()

    assert captcha_solver.captcha_type == captcha_keys[captcha_type].type
    assert captcha_solver.invisible == ("invisible" in scenario)
    assert captcha_solver.site_key == captcha_keys[captcha_type].site_key

    if captcha_type == "recaptcha_v3":
        browser.driver.find_element(By.ID, "fake-button").click()
        time.sleep(0.1)
        assert captcha_solver._get_action_queue() == ["fake_action"]


@pytest.mark.parametrize(
    "captcha_type, scenario",
    [
        ("recaptcha_v2", "auto"),
        ("recaptcha_v2", "onload"),
        ("recaptcha_v2", "onload_var"),
        ("recaptcha_v2", "invisible_auto"),
        ("recaptcha_v2", "invisible_onload"),
        ("recaptcha_v3", "auto"),
        ("recaptcha_v3", "listener"),
        ("recaptcha_v3", "onclick"),
        ("recaptcha_v3", "external"),
        ("hcaptcha", "auto"),
        ("hcaptcha", "auto_compat"),
        ("hcaptcha", "onload"),
        ("hcaptcha", "onload_compat"),
        ("hcaptcha", "onload_var"),
        ("hcaptcha", "invisible_auto"),
        ("hcaptcha", "invisible_onload"),
    ],
)
def test_captcha_submit(
    captcha_keys,
    mocker: MockerFixture,
    browser: EnfbotsBrowser,
    flask_app_function,
    captcha_type: str,
    scenario: str,
) -> None:
    flask_app.app.config["site_key"] = captcha_keys[captcha_type].site_key
    Config().CAPTCHA_BACKEND = "debug"

    browser.load_page(flask_app_function.child(captcha_type, scenario))
    forms = browser.find_forms()
    form_selenium = FormSelenium.from_bs(browser, forms[0])

    submit_re = mocker.patch.object(
        CaptchaSolverStub, "_submit_recaptcha", return_value=f"mocked-{captcha_type}-response"
    )
    submit_h = mocker.patch.object(
        CaptchaSolverStub, "_submit_hcaptcha", return_value=f"mocked-{captcha_type}-response"
    )

    form_selenium.fill_form(Credentials.get(), False)
    form_selenium.submit_form()

    assert form_selenium.captcha_solver.captcha_type == captcha_keys[captcha_type].type
    assert form_selenium.captcha_solver.invisible == ("invisible" in scenario)
    assert form_selenium.captcha_solver.site_key == captcha_keys[captcha_type].site_key

    if captcha_type == "hcaptcha":
        submit_h.assert_called_once_with()
    elif captcha_type == "recaptcha_v3":
        submit_re.assert_called_once_with(action="submit_action")
    else:
        submit_re.assert_called_once_with(action=None)

    # on successful verification we are redirected to index
    assert browser.current_url.normalize() == flask_app_function.normalize()


def test_captcha_image(
    mocker: MockerFixture,
    browser: EnfbotsBrowser,
    flask_app_function,
) -> None:
    browser.load_page(flask_app_function.child("image_captcha"))
    Config().CAPTCHA_BACKEND = "debug"

    forms = browser.find_forms()
    form_selenium = FormSelenium.from_bs(browser, forms[0])

    submit = mocker.patch.object(CaptchaSolverStub, "solve_image_captcha", return_value="tqatps")

    form_selenium.fill_form(Credentials.get(), False)
    form_selenium.submit_form()

    submit.assert_called_once()
    assert_images_equal(
        submit.call_args[0][0], Config().root_dir / "tests/apps/flask_app/static/captcha.png"
    )
    # on successful verification we are redirected to index
    assert browser.current_url.normalize() == flask_app_function.normalize()
