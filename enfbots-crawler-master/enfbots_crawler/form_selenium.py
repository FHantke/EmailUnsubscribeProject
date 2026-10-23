"""
contains the regform class as well as some form tag related procedures
"""

from __future__ import annotations

import base64
import logging
from collections import defaultdict
from typing import Optional

from hyperlink import URL
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.wait import WebDriverWait

# Imports from the enfbots library
from enfbots_crawler.helper import get_attr

# Imports from this crawler implementation
from enfbots_crawler import captcha_solver, CaptchaType, Config, InputType, FormStatus, ExtraStatus
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.input_selenium import InputSelenium
from enfbots_crawler.browser import EnfbotsBrowser, find_tagged, wait_for_page_load

logger = logging.getLogger("enfbots_crawler")


class FormSelenium:
    def __init__(self, browser: EnfbotsBrowser, reg_form: WebElement, form_bs: FormBS) -> None:
        self.br = browser
        self.tag = reg_form
        self.html = reg_form.get_attribute("outerHTML")
        self.form_type = form_bs.type
        self.form_bs = form_bs

        self.inputs: list[InputSelenium] = []
        self.radio_groups: defaultdict[str, list[InputSelenium]] = defaultdict(list)
        for input_bs in form_bs.inputs:
            input_sel = InputSelenium.from_bs(browser, input_bs, reg_form)
            name = get_attr(input_bs.element, "name")
            if input_bs.direct_type == InputType.RADIO_OTHER and name:
                self.radio_groups[name].append(input_sel)
            else:
                self.inputs.append(input_sel)

        self.url: URL = browser.current_url

        # for later form identification
        self.id = reg_form.get_attribute("id")
        self.selenium_id = reg_form.get_attribute("id")
        self.classes = []
        clazz = reg_form.get_attribute("class")
        if clazz:
            for c in clazz.split(" "):
                if c.strip():
                    self.classes.append(c.strip())
        self.name = reg_form.get_attribute("name")
        self.action = reg_form.get_attribute("action")

        self.captcha_solver = captcha_solver.create_solver(browser)

    def __str__(self) -> str:
        return f"Form [id={self.id}, type={self.form_type.name}]"

    @staticmethod
    def from_bs(browser: EnfbotsBrowser, form_bs: FormBS) -> FormSelenium:
        # A form inside shadow DOM is found through its hosts (the iframe, if any, must already
        # be the current frame: browser.enter_frame)
        tag = find_tagged(browser.search_context(form_bs.shadow_hosts), form_bs.uuid, form_bs.id)
        form = FormSelenium(browser, tag, form_bs)
        return form

    def fill_form(self, creds: Credentials, fill_all_inputs: bool) -> None:
        """
        :param creds: credentials used for registration
        :param fill_all_inputs: if maybe required inputs should also be filled out

        Fill:
        1. select tags (first valid option)
        2. checkboxes (only those which seems required
        3. input tags
          a) detect detailed type
          b) fill corresponding credentials value
          c) modify if the value is not accepted
        """
        if fill_all_inputs:
            logger.info("Filling in form with all the inputs and checkboxes.")
        else:
            logger.info("Filling in form with just the required inputs.")

        for tag in self.inputs:
            if tag.type != InputType.CAPTCHA_INPUT and (
                tag.type != InputType.VERIFY_CODE or creds.verify_code
            ):
                tag.fill(creds, fill_all_inputs)

        for item in self.radio_groups.items():
            self._fill_radio_group(*item)

        for inp in self.inputs:
            # non default handling of input elements
            if inp.type == InputType.CAPTCHA_INPUT or (
                inp.type == InputType.VERIFY_CODE and creds.verify_code
            ):
                if self.captcha_solver.captcha_type in (CaptchaType.NONE, CaptchaType.IMAGE):
                    # probably no one is using image + recaptcha
                    self._solve_image_captcha(inp)

    @staticmethod
    def _fill_radio_group(_: str, inputs: list[InputSelenium]) -> None:
        # Do we ever care about those
        for inp in inputs:
            value = inp.elem.get_attribute("value") or ""
            if not inp.elem.get_attribute("disabled") and value.strip():
                inp.click()
                break

    def _solve_image_captcha(self, inp: InputSelenium) -> None:
        # locate nearest embedded image in form and extract as base64

        logger.info("searching for image captchas as img elements...")
        nearest_image: WebElement = self.br.execute_script(
            """let search_obj = arguments[0]; 
               let levels = 0;
               while (search_obj.parentElement != null && levels < 4) {
                    levels += 1;
                    let nearest_imgs = search_obj.getElementsByTagName("img");
                    let max_area = 0;
                    let max_image = null;
                    for (const img of nearest_imgs) {
                            // sane image size conditions, if more images match take the biggest
                            if(img.height > 50 && img.height < 300 && img.width > 100 && img.width < 600) {
                                const area = img.height * img.width;
                                if (area > max_area) {
                                    max_image = img;
                                    max_area = area;
                                }
                            }
                    }
                    if (max_image !== null) {
                        return max_image;
                    }

                    search_obj = search_obj.parentElement;
                }
                """,
            inp.elem,
        )
        if nearest_image:
            src: str = nearest_image.get_attribute("src")
            image_base64: Optional[str]
            if src.startswith("data:"):
                header, data = src[5:].split(";", 1)
                if "base64" in header:
                    image_base64 = data
                else:
                    image_base64 = base64.b64encode(data.encode("utf-8")).decode("ascii")
            else:
                image_base64 = self.br.get_image_as_base64(nearest_image)

            if image_base64:
                logger.info("Captcha img element converted to base64")
                img_result = self.captcha_solver.solve_image_captcha(image_base64)
                inp.fill_text(img_result)
            else:
                logger.warning("Possible captcha image but no content was found in seleniumwire")
        else:
            logger.warning("Possible captcha input detected but not image is close by")

    def submit_form(self, js_submit: bool = False) -> set[FormStatus]:
        """
        Function tries to submit a target form on different ways and also tries to detect if submit was successful
        prior of trying other submit ways
        """

        logger.info("submitting %s", self)

        self.captcha_solver.detect()
        self.captcha_solver.pre_submit_solve()

        submitted = False
        states: set[FormStatus] = set()

        by_type: dict[InputType, list[InputSelenium]] = defaultdict(list)
        for inp in self.inputs:
            # prioritize submit buttons
            if inp.direct_type == InputType.BUTTON_SUBMIT:
                by_type[inp.direct_type].append(inp)
            by_type[inp.type].append(inp)

        # click submit buttons or any other submit-able inputs
        for inp in (
            by_type[InputType.BUTTON_SUBMIT]
            + by_type[InputType.BUTTON_REGISTRATION]
            + by_type[InputType.BUTTON_OTHER]
            + by_type[InputType.BUTTON_LOGIN]
            + by_type[InputType.BUTTON_SUBSCRIBE]
            + by_type[InputType.BUTTON_CONTACT]
        ):
            if inp.click():
                states.add(ExtraStatus.SUBMIT_BUTTON)
                self.captcha_solver.post_submit_solve()
                submitted = True
                break

        stale = False
        if submitted:
            try:
                WebDriverWait(self.br.driver, Config().TIMEOUT_SHORT).until(staleness_of(self.tag))
                stale = True
            except TimeoutException:
                pass

        # if we did not submit or the form did not go stale after 5 seconds we submit using JS
        if (not submitted or not stale) and js_submit:
            with wait_for_page_load(self.br, timeout=Config().TIMEOUT_SHORT):
                states.add(ExtraStatus.SUBMIT_JS)
                self.br.execute_script(
                    'if(typeof arguments[0].submit === "function"){arguments[0].submit();}',
                    self.tag,
                )
                self.captcha_solver.post_submit_solve()
                logger.info("fallback js submit used")

        return states
