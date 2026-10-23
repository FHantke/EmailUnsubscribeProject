#!/usr/bin/env python3

"""
Class for automatically solving captchas, using the AZCaptcha/ImageTyperz API.

Author: Patrice Kast, <kastpa@inf.ethz.ch>
"""

from __future__ import annotations

import logging
import re
import time
import typing

from time import sleep
from typing import Optional, Any

from hyperlink import URL
from selenium.webdriver.common.by import By
from twocaptcha import TwoCaptcha, SolverExceptions
from twocaptcha.api import ApiException

# Imports from this crawler implementation
from enfbots_crawler import Config, CaptchaType
from enfbots_crawler.libs.imagetyperzapi import ImageTyperzAPI

logger = logging.getLogger("enfbots_crawler")

if typing.TYPE_CHECKING:
    from enfbots_crawler.browser import EnfbotsBrowser


class CaptchaSolverError(Exception):
    pass


class CaptchaAccountBalanceException(CaptchaSolverError):
    pass


class CaptchaParamNotFoundError(CaptchaSolverError):
    pass


def classify_captcha_url(url: URL) -> Optional[str]:
    if "hcaptcha" in url.host and "api.js" in url.path:
        return "hcaptcha"
    if ("recaptcha" in url.host or "recaptcha" in url.path) and (
        "api.js" in url.path or "enterprise.js" in url.path
    ):
        return "recaptcha"
    if url.host == "challenges.cloudflare.com" and "turnstile" in url.path:
        return "turnstile"
    return None


class CaptchaSolverStub:
    """
    Handler of the captcha solving

    :ivar captcha_type: detected CaptchaType
    :ivar site_key: captcha ID for site
    :ivar invisible: is used captcha invisible
    :ivar enterprise: is used captcha enterprise
    :ivar browser: instance of Selenium controlled browser
    :ivar solve_start_time: solving time holder var
    :ivar ita: instance of ImageTyperz API with our access token
    :ivar solver_2captcha: instance of 2captcha API with our access token
    :ivar response_cache: cache of solution until form submission
    """

    def __init__(self, browser: EnfbotsBrowser) -> None:
        self.captcha_type = CaptchaType.NONE
        self.site_key: Optional[str] = None
        self.invisible = False
        self.enterprise = False
        self.browser = browser
        self.solve_start_time: float = 0
        self.stub_exists = False

        self.ita: ImageTyperzAPI = ImageTyperzAPI(Config().ITA_ACCESS_TOKEN)
        self.solver_2captcha = TwoCaptcha(Config().TWOCAPTCHA_ACCESS_TOKEN)

        # until the form is refreshed we can reuse the response cache (submission might have been blocked by JS)
        # once the form has been submitted the token is invalid
        self.response_cache: dict[str, str] = dict()

    def detect(self) -> None:
        """
        Main function for complete preparing
        """

        logger.info("Detecting CAPTCHAs")
        self._detect_type()
        if self.stub_exists:
            self._collect_parameters()

    def pre_submit_solve(self) -> None:
        """
        Main function for complete solving if sitekey is found
        """

        if self.captcha_type in (CaptchaType.HCaptcha, CaptchaType.ReCAPTCHAv2):
            cache_key = f"{self.site_key}"
            if cache_key in self.response_cache:
                response = self.response_cache[cache_key]
            else:
                response = self._submit_captcha()
                self.response_cache[cache_key] = response
            self._set_response(response)

    def post_submit_solve(self) -> bool:
        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            queue = self._get_action_queue()
            if queue is None:
                return False
            action_queue = set(queue)
            if not action_queue:
                # this means not action has been triggered yet,
                # maybe wrong button, maybe captcha is just not being checked
                return False

            for action in action_queue:
                # there might be more than one action stored up, lets solve them all
                # it is inefficient but fortunately shouldn't happen very often
                # TODO submit multiple then wait for all
                cache_key = f"{self.site_key}::{action}"
                if cache_key in self.response_cache:
                    response = self.response_cache[cache_key]
                else:
                    response = self._submit_recaptcha(action=action)
                    self.response_cache[cache_key] = response
                self._set_response(response, action)

        return True

    def _submit_captcha(self, action: Optional[str] = None) -> str:
        if Config().CAPTCHA_BACKEND == "ita":
            # TODO implement for 2captcha
            if float(self.ita.account_balance()[1:]) <= 0.0:
                raise CaptchaAccountBalanceException()

        if Config().CAPTCHA_BACKEND == "twocaptcha":
            if float(self.solver_2captcha.balance()) <= 0.0:
                raise CaptchaAccountBalanceException()

        if not self.site_key:
            raise CaptchaParamNotFoundError("sitekey")

        if self.captcha_type == CaptchaType.HCaptcha:
            return self._submit_hcaptcha()
        elif self.captcha_type in (CaptchaType.ReCAPTCHAv3, CaptchaType.ReCAPTCHAv2):
            return self._submit_recaptcha(action=action)

        raise CaptchaSolverError("Captcha type without implemented submit")

    def _detect_type(self) -> None:
        """
        Detect which Captcha System is used, if any
        """
        # Scan for Scripts loaded, which are Recaptcha Plugins
        if self.browser.execute_script("return window?.captcha_stub?.stub;"):
            self.stub_exists = True
            if self.browser.execute_script("return window.captcha_stub.type;") == "recaptcha":
                if self.browser.execute_script("return window.captcha_stub.version;") == "v3":
                    self.captcha_type = CaptchaType.ReCAPTCHAv3
                else:
                    self.captcha_type = CaptchaType.ReCAPTCHAv2
            else:
                self.captcha_type = CaptchaType.HCaptcha
            logger.info(f"{self.captcha_type.name} mock detected")

    def _get_action_queue(self) -> list[str]:
        # does not support nested executes yet
        return self.browser.execute_script("return window.grecaptcha.get_action_queue();")

    def _submit_recaptcha(self, action: Optional[str] = None) -> str:
        if self.captcha_type == CaptchaType.ReCAPTCHAv3 and not action:
            raise CaptchaParamNotFoundError("action")

        if Config().CAPTCHA_BACKEND == "ita":
            return self._submit_recaptcha_ita(action)
        else:
            return self._submit_recaptcha_2cap(action)

    def _submit_recaptcha_ita(self, action: Optional[str] = None) -> str:
        """
        Submit ReCAPTCHA v3 using AZCaptcha System
        """

        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            type_id = 3
            if not action:
                raise CaptchaParamNotFoundError("action")
            if self.enterprise:
                type_id = 5
        elif self.captcha_type == CaptchaType.ReCAPTCHAv2:
            if self.enterprise:
                type_id = 4
            elif self.invisible:
                type_id = 2
            else:
                type_id = 1
        else:
            raise CaptchaSolverError("submit recaptcha called on a non recaptcha solver")

        captcha_params: dict[str, Any] = {
            "page_url": str(self.browser.current_url),
            "sitekey": self.site_key,
            "type": type_id,
            "user_agent": self.browser.user_agent,
        }

        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            captcha_params["v3_min_score"] = 0.3
            captcha_params["v3_action"] = action

        logger.info(f"Starting recaptcha solving Imagetyperz with {captcha_params}")

        ita_id = self.ita.submit_recaptcha(captcha_params)
        return self._poll_imagetyperz(ita_id)

    def _submit_recaptcha_2cap(self, action: Optional[str] = None) -> str:
        captcha_params: dict[str, Any] = {
            "url": self.browser.current_url.to_text(),
            "sitekey": self.site_key,
            "userAgent": self.browser.user_agent,
            "enterprise": "1" if self.enterprise else "0",
        }
        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            captcha_params["version"] = "v3"
            captcha_params["action"] = action
        else:
            captcha_params["version"] = "v2"
            captcha_params["invisible"] = 1 if self.invisible else 0

        logger.info(f"Starting recaptcha solving 2captcha with {captcha_params}")
        self.solve_start_time = time.time()
        try:
            result = self.solver_2captcha.recaptcha(**captcha_params)
            logger.info(f"2Captcha api responded with {result}")

            return result["code"]
        except SolverExceptions:
            raise CaptchaSolverError("Captcha solving failed")
        except ApiException as e:
            raise CaptchaSolverError("Failed to solve captcha: " + str(e))

    def _submit_hcaptcha(self) -> str:
        if Config().CAPTCHA_BACKEND == "ita":
            return self._submit_hcaptcha_ita()
        else:
            return self._submit_hcaptcha_2cap()

    def _submit_hcaptcha_2cap(self) -> str:
        captcha_params: dict[str, Any] = {
            "url": self.browser.current_url.to_text(),
            "sitekey": self.site_key,
            "userAgent": self.browser.user_agent,
            "invisible": 1 if self.invisible else 0,
        }

        logger.info(f"Starting hcaptcha solving 2captcha with {captcha_params}")
        self.solve_start_time = time.time()
        try:
            result = self.solver_2captcha.hcaptcha(**captcha_params)
            logger.info(f"2Captcha api responded with {result}")
            return result["code"]
        except SolverExceptions:
            raise CaptchaSolverError("Captcha solving failed")

    def _submit_hcaptcha_ita(self) -> str:
        """
        Submit hCaptcha using AZCaptcha System
        """

        captcha_params: dict[str, Any] = {
            "page_url": self.browser.current_url,
            "sitekey": self.site_key,
            "user_agent": self.browser.user_agent,
        }

        if self.invisible:
            captcha_params["invisible"] = True

        logger.info(f"Starting hCaptcha solving with {captcha_params}")
        self.solve_start_time = time.time()
        ita_id = self.ita.submit_hcaptcha(captcha_params)
        return self._poll_imagetyperz(ita_id)

    def solve_image_captcha(self, img_base64: str) -> str:
        """
        Solve image captchas and return string
        """
        self.captcha_type = CaptchaType.IMAGE
        if Config().CAPTCHA_BACKEND == "ita":
            return self._solve_image_captcha_ita(img_base64)
        else:
            return self._solve_image_captcha_2cap(img_base64)

    def _solve_image_captcha_ita(self, img_base64: str) -> str:
        ita_id = self.ita.submit_image(img_base64.encode("utf-8"), True)
        return self._poll_imagetyperz(ita_id)

    def _solve_image_captcha_2cap(self, img_base64: str) -> str:
        logger.info("Submitting image captcha to 2captcha")
        try:
            result = self.solver_2captcha.normal(img_base64)
            logger.info(f"2Captcha api responded with {result}")
            return result["code"]
        except SolverExceptions:
            raise CaptchaSolverError("Captcha solving failed")

    def _set_response(self, response: str, action: Optional[str] = None) -> None:
        self.browser.execute_script(
            "window.captcha_stub.setResponse(arguments[0], arguments[1]);", response, action
        )

    def _collect_parameters(self) -> None:
        captcha_parameters = self.browser.execute_script(
            "return window.captcha_stub.collect_parameters();"
        )
        if captcha_parameters:
            if "sitekey" in captcha_parameters:
                self.site_key = captcha_parameters["sitekey"]
            if "size" in captcha_parameters:
                if captcha_parameters["size"] == "invisible":
                    self.invisible = True

    def _poll_imagetyperz(self, captcha_id: str) -> str:
        """
        Solve a crawled captcha by using the imagetyperz solving service
        """

        logger.info("Querying captcha service")
        for i in range(24):
            try:
                response = self.ita.retrieve_response(captcha_id)
                if response:
                    logger.info(f"Captcha service responded with {response}")
                    return response["Response"]
            except Exception as e:
                raise CaptchaSolverError(f"Error while waiting for Imagetyperz response {e}")
            sleep(5)
        raise CaptchaSolverError("Timeout while waiting for Imagetyperz response")


class CaptchaSolverScanning:  # pragma: no cover
    _response_cache: dict[str, str] = dict()

    def __init__(self, browser: EnfbotsBrowser) -> None:
        self.captcha_type = CaptchaType.NONE
        self.init_options: dict[str, str] = {}
        self.site_key: Optional[str] = None
        self.invisible = False  # only used in reCAPTCHA v2
        self.g_action: Optional[str] = None  # only used in reCAPTCHA v3
        self.callback_func: Optional[str] = None
        self.browser = browser
        self.solve_start_time: float = 0

        self.ita: ImageTyperzAPI = ImageTyperzAPI(Config().ITA_ACCESS_TOKEN)
        self.captcha_id: Optional[str] = None
        logger.debug("CaptchaSolver initialized.")

    def _scan_html(self) -> None:
        if self.captcha_type in (CaptchaType.ReCAPTCHAv2, CaptchaType.ReCAPTCHAv3):
            self._scan_key_recaptcha()
        elif self.captcha_type == CaptchaType.HCaptcha:
            self._scan_key_hcaptcha()

    def _get_action_queue(self) -> list[str]:
        # does not support nested executes yet
        if self.g_action:
            return [self.g_action]
        return []

    def detect(self) -> None:
        """
        Main function for complete preparing
        """

        logger.info("Detecting CAPTCHAs")
        self._scan_scripts()
        self._scan_html()

    def pre_submit_solve(self) -> None:
        """
        Main function for complete solving if sitekey is found
        """

        if self.captcha_type in (CaptchaType.HCaptcha, CaptchaType.ReCAPTCHAv2):
            cache_key = f"{self.site_key}"
            if cache_key in self._response_cache:
                rc_response = self._response_cache[cache_key]
            else:
                ita_id = self._submit_captcha()
                rc_response = self._poll_imagetyperz([ita_id])[ita_id]
                self._response_cache[cache_key] = rc_response
            self._solve_captcha(rc_response)

    def _solve_captcha(self, token: str) -> None:
        if self.captcha_type == CaptchaType.ReCAPTCHAv2:
            self._solve_recaptcha_v2(token)
        elif self.captcha_type == CaptchaType.ReCAPTCHAv3:
            self._solve_recaptcha_v3(token)
        elif self.captcha_type == CaptchaType.HCaptcha:
            self._solve_hcaptcha(token)

    def _submit_captcha(self, action: Optional[str] = None) -> str:
        if float(self.ita.account_balance()[1:]) == 0:
            raise CaptchaAccountBalanceException()

        if self.captcha_type == CaptchaType.HCaptcha:
            return self._submit_hcaptcha()
        elif self.captcha_type in (CaptchaType.ReCAPTCHAv3, CaptchaType.ReCAPTCHAv2):
            return self._submit_recaptcha(action=action)

        raise CaptchaSolverError("Captcha type without implemented submit")

    def post_submit_solve(self) -> bool:
        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            action = self.g_action
            cache_key = f"{self.site_key}::{action}"
            if cache_key not in self._response_cache:
                ita_id = self._submit_captcha(action=action)
                rc_response = self._poll_imagetyperz([ita_id])[ita_id]
                self._response_cache[cache_key] = rc_response
            else:
                rc_response = self._response_cache[cache_key]
            self._solve_recaptcha_v3(rc_response)

        return True

    def _evaluate_expression(self, val: str) -> Any:
        return self.browser.execute_script(
            f"""
            if(typeof {val} !== 'undefined') {{
                const obj = {val};
                if (obj !== null && typeof obj.toString === 'function') {{ return obj.toString() }}
                return obj;
            }}"""
        )

    def _scan_scripts(self) -> None:
        """
        Detect which Captcha System is used, if any
        """
        script_url = self.browser.captcha_apis[-1]
        if "api.js" in script_url.path and "hcaptcha.com" in script_url.host:
            logger.info("hCaptcha found")
            self.captcha_type = CaptchaType.HCaptcha
            return

        if "recaptcha" in script_url.path:
            # default to recaptchav2
            self.captcha_type = CaptchaType.ReCAPTCHAv2

            for key, item in script_url.query:
                if item is not None:
                    self.init_options[key] = item
            logger.info(self.init_options)

            if "onload" in self.init_options:
                # A custom init function is used
                logger.info("Google ReCAPTCHA custom init function found")
                init_f_name = self.init_options["onload"]
                init_f_str = self._evaluate_expression(init_f_name)

                logger.info(f"Custom init function converted to string: {init_f_str}")

                # Does it contain a sitekey?
                match = js_key_regex("sitekey", init_f_str)
                if match:
                    # try to evaluate the site key variable in case its an expression
                    site_key = self._evaluate_expression(match)
                    if site_key:
                        logger.info(f"Sitekey found: {site_key}")
                        self.site_key = site_key

                # Does it contain a callback?
                match = js_key_regex("callback", init_f_str)
                if match:
                    self.callback_func = match
                    logger.info("Callback function found: " + self.callback_func)

                # Does it contain a size?
                match = js_key_regex("size", init_f_str)
                if match:
                    size = self._evaluate_expression(match)
                    if size == "invisible":
                        self.invisible = True
                        logger.info("Hidden Recaptchav2 detected")

            if "render" in self.init_options:
                # render onload and explicit indicate v2 which is default anyway
                if len(self.init_options["render"]) == 40:
                    # render is an Attribute with sitekey containing only used in v3
                    logger.info("Render site_key detected. Google ReCAPTCHA v3 found.")
                    self.captcha_type = CaptchaType.ReCAPTCHAv3
                    self.site_key = self.init_options["render"]
            # indication of a recaptcha v3
            elif (
                self.browser.execute_script(
                    "if(typeof ___grecaptcha_cfg != 'undefined') { ___grecaptcha_cfg.clients }"
                )
                and int(self.browser.execute_script("Object.keys(___grecaptcha_cfg.clients)[0]"))
                > 9
            ):
                self.captcha_type = CaptchaType.ReCAPTCHAv3
                logger.info(
                    "___grecaptcha_cfg Object with value 1000 detected, Google ReCAPTCHA v3 found."
                )

        if self.captcha_type == CaptchaType.NONE:  # if no captcha found, leave def
            logger.info("captcha_solver: No captcha found.")
        else:
            logger.info("captcha_solver: Found captcha type %s", self.captcha_type)

    def _scan_key_recaptcha(self) -> None:
        """
        Get Recaptcha v2 Parameters for Solving
        """
        logger.info("Google ReCAPTCHA information scanning...")

        # scan for the google recaptcha initialisation object (Way A to initialize recaptcha)
        for g_obj in self.browser.driver.find_elements(By.CLASS_NAME, "g-recaptcha"):
            site_key = g_obj.get_attribute("data-sitekey")
            if not self.site_key and site_key:
                self.site_key = site_key

            callbac_func = g_obj.get_attribute("data-callback")
            if not self.callback_func and callbac_func:
                self.callback_func = callbac_func

            # option to set recaptcha to v2 hidden
            data_size = g_obj.get_attribute("data-size")
            if data_size and data_size.lower() == "invisible":
                self.invisible = True
                logger.info("Hidden Flag found")

            data_action = g_obj.get_attribute("data-action")
            if data_action:
                self.g_action = data_action
                self.captcha_type = CaptchaType.ReCAPTCHAv3
                logger.info(f"v3 action found: {self.g_action}")

        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            self._scan_recaptcha_v3_execute()

    def _solve_recaptcha_v2(self, rc_response: str) -> None:
        """
        Solve ReCAPTCHA v2 using AZCaptcha System
        """
        logger.info("ReCAPTCHAv2 Answer ready.")

        # enter recaptcha response
        self.browser.execute_script(
            'if(document.getElementById("g-recaptcha-response")) '
            '{document.getElementById("g-recaptcha-response").innerHTML = "' + rc_response + '";}'
        )

        logger.info("ReCAPTCHAv2 solved.")

        # If callback function found, use it to submit form
        if self.callback_func:
            self.browser.execute_script(self.callback_func + '("' + rc_response + '");')
            logger.info("Custom callback function executed to submit form.")

    def _scan_recaptcha_v3_execute(self) -> None:
        """
        Get Recaptcha v3 Parameters for Solving
        """
        logger.info("Google ReCAPTCHA v3 executre scanning...")

        match = re.search(
            r"grecaptcha\.execute\s*?\([\"|\']([^\"\']*)[\"|\'].*?action:\s*?[\"|\']([^\"\']*?)[\"|\'].*?"
            r"then\s*?\(\s*?function\s*?\((.*?)\)(.*?})\s*?\)\s*?;",
            self.browser.driver.page_source,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            self.site_key = match.group(1)
            self.g_action = match.group(2)
            self.browser.execute_script(
                "window.mySubmitFssssunctionReg = (" + match.group(3) + ") => " + match.group(4)
            )
            self.callback_func = "mySubmitFssssunctionReg"
            logger.info(
                f"Sitekey, action and callback function found: "
                f"{self.site_key}, {self.g_action}, {self.callback_func}"
            )

    def _submit_recaptcha(self, action: Optional[str] = None) -> str:
        """
        Submit ReCAPTCHA v3 using AZCaptcha System
        """

        logger.info("Starting ReCAPTCHA solving...")

        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            type_id = 3
            if not action:
                raise CaptchaParamNotFoundError("action")
        elif self.captcha_type == CaptchaType.ReCAPTCHAv2:
            if self.invisible:
                type_id = 2
            else:
                type_id = 1
        else:
            raise CaptchaSolverError("submit recaptcha called on a non recaptcha solver")

        if not self.site_key:
            raise CaptchaParamNotFoundError("sitekey")

        captcha_params = {
            "page_url": str(self.browser.current_url),
            "sitekey": self.site_key,
            "type": type_id,
            "user_agent": self.browser.user_agent,
        }

        if self.captcha_type == CaptchaType.ReCAPTCHAv3:
            captcha_params["v3_min_score"] = 0.3
            captcha_params["v3_action"] = action

        self.solve_start_time = time.time()
        return self.ita.submit_recaptcha(captcha_params)

    def _solve_recaptcha_v3(self, rc_response: str) -> None:
        """
        Solve ReCAPTCHA v3 using AZCaptcha System
        """

        logger.info("ReCAPTCHAv3 Answer ready.")

        # enter recaptcha response
        self.browser.execute_script(
            'if(document.getElementById("g-recaptcha-response")) '
            '{document.getElementById("g-recaptcha-response").innerHTML = "' + rc_response + '";}'
        )
        self.browser.execute_script(
            'if(document.getElementById("g-recaptcha-response-100000")) '
            '{document.getElementById("g-recaptcha-response-100000").innerHTML = "'
            + rc_response
            + '";}'
        )

        logger.info("ReCAPTCHAv3 solved.")

        # If callback function found, use it to submit form
        if self.callback_func:
            self.browser.execute_script(self.callback_func + '("' + rc_response + '");')
            logger.info("Custom callback function exre.searchecuted to submit form.")

    def solve_image_captcha(self, img_base64: str) -> str:
        """
        Solve image captchas and return string
        """
        logger.info("Submitting image captcha for solving...")
        self.captcha_type = CaptchaType.IMAGE

        result = self.ita.submit_image(img_base64, True)
        logger.info(f"Captcha result received: {result}")
        return result

    def _scan_key_hcaptcha(self) -> None:
        """
        Get HCaptcha v3 Parameters for Solving
        """
        logger.info("hCaptcha information scanning...")

        for g_obj in self.browser.driver.find_elements(By.CLASS_NAME, "h-captcha"):
            if g_obj.get_attribute("data-sitekey"):
                self.site_key = g_obj.get_attribute("data-sitekey")
                logger.info(f"Sitekey found: {self.site_key}")

    def _submit_hcaptcha(self) -> str:
        """
        Submit hCaptcha using AZCaptcha System
        """
        logger.info("Starting hCaptcha solving...")

        captcha_params = {
            "page_url": self.browser.current_url,
            "sitekey": self.site_key,
            "user_agent": "Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/60.0",
        }
        self.solve_start_time = time.time()
        return self.ita.submit_hcaptcha(captcha_params)

    def _solve_hcaptcha(self, rc_response: str) -> None:
        """
        Solve hCaptcha using AZCaptcha System
        """
        logger.info("hCaptcha Answer ready.")

        # enter recaptcha response
        self.browser.execute_script(
            'if(document.querySelector("[name=g-recaptcha-response]")) '
            '{document.querySelector("[name=g-recaptcha-response]").innerText = "'
            + rc_response
            + '";}'
        )
        self.browser.execute_script(
            'if(document.querySelector("[name=h-captcha-response]")) '
            '{document.querySelector("[name=h-captcha-response]").innerText = "'
            + rc_response
            + '";}'
        )

        logger.info("hCaptcha solved.")

    def _poll_imagetyperz(self, captcha_ids: list[str]) -> dict[str, str]:
        """
        Solve a crawled captcha by using the imagetyperz solving service
        """
        response_map: dict[str, str] = dict()
        queue = captcha_ids

        logger.info(f"Querying captcha service")
        attempts = 0
        while queue and attempts < 24:
            attempts += 1
            sleep(5)
            for key in queue:
                # need a try except, since sometimes, an error is returned by api in an invalid json object
                try:
                    response = self.ita.retrieve_response(key)
                    if response:
                        response_map[key] = response
                        queue.remove(key)
                except Exception:
                    response_map[key] = "captcha_error"
                    queue.remove(key)
                    logger.info("Captcha solving api failed, leaving out captcha")
        for key in queue:
            # these have timed out
            response_map[key] = "captcha_error"

        logger.info(f"Captcha service responded with {response_map}")
        return response_map


# Live check for a displayed challenge (image grid etc.); the frames exist hidden beforehand
# Name of the visible challenge on the page ('' if none): CAPTCHA challenge frames, a reCAPTCHA
# checkbox that is not the invisible badge, and bot-protection challenges (DataDome, HUMAN)
_CHALLENGE_SHOWN_JS = r"""
const shown = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width <= 50 || r.height <= 50) return false;
    for (let x = e; x; x = x.parentElement) {
        const s = getComputedStyle(x);
        if (s.visibility === 'hidden' || s.display === 'none' || parseFloat(s.opacity) === 0) {
            return false;
        }
    }
    return true;
};
const kinds = [
    [/recaptcha\/(api2|enterprise)\/bframe/, 'recaptcha'],
    [/recaptcha\/(api2|enterprise)\/anchor(?!.*size=invisible)/, 'recaptcha_checkbox'],
    [/hcaptcha\.com.*challenge/, 'hcaptcha'],
    [/challenges\.cloudflare\.com/, 'turnstile'],
    [/captcha-delivery\.com/, 'datadome'],
    [/px-cdn\.net|px-cloud\.net|perimeterx/, 'human'],
];
for (const f of document.querySelectorAll('iframe')) {
    const kind = kinds.find(([re]) => re.test(f.src || ''));
    if (kind && shown(f)) return kind[1];
}
const px = document.querySelector('#px-captcha');
return px && shown(px) ? 'human' : '';
"""


class CaptchaRecorder:
    """
    Records CAPTCHAs instead of solving them (CAPTCHA_BACKEND="none"). Never calls a paid
    service: invisible CAPTCHAs run in the real browser, and visible challenges are only noted.
    """

    def __init__(self, browser: EnfbotsBrowser) -> None:
        self.browser = browser
        self.captcha_type = CaptchaType.NONE
        # Finer than CaptchaType, e.g. "turnstile" or "recaptcha_v2_invisible"
        self.captcha_name: Optional[str] = None
        self.captcha_visible: Optional[bool] = None

    def detect(self) -> None:
        # Imported here: capture imports this module (classify_captcha_url)
        # pylint: disable=import-outside-toplevel
        from enfbots_crawler import capture

        info = capture.captcha_in(self.browser.get_soup()) or capture.page_captcha(
            self.browser.get_html()
        )
        if info is None:
            return
        self.captcha_name, self.captcha_visible = info.type, info.visible
        if info.type.startswith("recaptcha_v3"):
            self.captcha_type = CaptchaType.ReCAPTCHAv3
        elif info.type.startswith("recaptcha"):
            self.captcha_type = CaptchaType.ReCAPTCHAv2
        elif info.type.startswith("hcaptcha"):
            self.captcha_type = CaptchaType.HCaptcha
        logger.info("CAPTCHA detected (not solved): %s, visible=%s", info.type, info.visible)

    def pre_submit_solve(self) -> None:
        pass

    def post_submit_solve(self) -> bool:
        return True

    def solve_image_captcha(self, img_base64: str) -> str:
        self.captcha_type = CaptchaType.IMAGE
        self.captcha_name, self.captcha_visible = "image", True
        logger.warning("Image CAPTCHA left unsolved (CAPTCHA_BACKEND=none)")
        return ""

    def challenge_name(self) -> str:
        """The visible challenge after a submit, e.g. "hcaptcha" or "datadome"; '' if none."""
        return str(self.browser.execute_script(_CHALLENGE_SHOWN_JS) or "")

    def challenge_shown(self) -> bool:
        return bool(self.challenge_name())


def js_key_regex(name: str, string: str) -> Optional[str]:
    """Regex to find the value of a key from JS object source code"""
    matches = re.search(r"[\"|']?" + name + r"[\"|']?\s*:\s*([^,}\n]*)", string, re.IGNORECASE)
    if matches and matches.group(1):
        return matches.group(1)
    return None


CaptchaSolver = typing.Union[CaptchaSolverStub, CaptchaSolverScanning, CaptchaRecorder]


def create_solver(*args: Any, **kwargs: Any) -> CaptchaSolver:
    if Config().CAPTCHA_BACKEND == "none":
        return CaptchaRecorder(*args, **kwargs)
    if Config().CAPTCHA_ALLOW_STUB:
        return CaptchaSolverStub(*args, **kwargs)
    else:
        return CaptchaSolverScanning(*args, **kwargs)
