"""
Wrapper for selenium driver
"""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from threading import Thread
from contextlib import contextmanager
import time

import base64
import logging
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Optional, NamedTuple, Any, List, TypeVar, Callable, cast, Generator
from urllib.parse import urldefrag

import psutil
from psutil import Process
from bs4 import BeautifulSoup
from hyperlink import URL, URLParseError
from numpy import random
import undetected_chromedriver as uc

from selenium.common.exceptions import (
    NoAlertPresentException,
    TimeoutException,
    WebDriverException,
    JavascriptException,
    UnexpectedAlertPresentException,
)
from selenium.webdriver import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.expected_conditions import staleness_of
from selenium.webdriver.support.wait import WebDriverWait
from pyvirtualdisplay.display import XvfbDisplay

from selenium_stealth import stealth

from seleniumwire import webdriver
from seleniumwire.request import Request, Response
from seleniumwire.utils import decode

from enfbots_crawler.languages import Language
from enfbots_crawler.captcha_solver import classify_captcha_url
from enfbots_crawler.enums import PageState
from enfbots_crawler.config import Config
from enfbots_crawler.form_bs import FormBS

logger = logging.getLogger("enfbots_crawler")


class CookieTuple(NamedTuple):
    name: str
    value: str
    path: str
    domain: str
    secure: bool
    http_only: bool
    expiry: int
    same_site: str


FuncT = TypeVar("FuncT", bound=Callable[..., Any])

CHROME_WIDTH=1920
CHROME_HEIGHT=1080

# The pointer leaving the viewport at the top: mouseout/mouseleave with no related target
_EXIT_INTENT_JS = """
const options = {bubbles: true, cancelable: true, view: window, clientX: 200, clientY: -5,
                 relatedTarget: null};
for (const target of [document, document.documentElement, document.body]) {
    if (!target) continue;
    target.dispatchEvent(new MouseEvent("mouseout", options));
    target.dispatchEvent(new MouseEvent("mouseleave", {...options, bubbles: false}));
}
window.dispatchEvent(new MouseEvent("mouseout", options));
"""

# Allows the sign-up vendors' domains for the browser session, outranking uBlock's filter
# lists (a higher priority wins within one extension); runs on one of uBlock's own pages
_UNBLOCK_RULE_ID = 7_000_001
_UNBLOCK_JS = """
const [domains, ruleId, done] = arguments;
if (!(window.chrome && chrome.declarativeNetRequest)) {
    done("declarativeNetRequest is not available on this page");
    return;
}
const resourceTypes = ["main_frame", "sub_frame", "stylesheet", "script", "image", "font",
                       "xmlhttprequest", "ping", "media", "websocket", "other"];
chrome.declarativeNetRequest.updateSessionRules({
    removeRuleIds: [ruleId],
    addRules: [{id: ruleId, priority: 1000000, action: {type: "allow"},
                condition: {requestDomains: domains, resourceTypes: resourceTypes}}],
}).then(() => chrome.declarativeNetRequest.getSessionRules())
  .then((rules) => {
      const rule = rules.find((r) => r.id === ruleId);
      done(rule ? rule.condition.requestDomains.length : "the rule is missing after adding it");
  })
  .catch((e) => done(String(e)));
"""

# Switches uBlock Origin Lite to "No filtering" for all sites with the message its dashboard
# sends (uBOL 2024.2.26, js/settings.js). uBOL then adds an allowAllRequests rule and removes
# its cosmetic filters; the rule is read back to confirm
_NO_FILTERING_JS = """
const done = arguments[arguments.length - 1];
if (!(window.chrome && chrome.runtime && chrome.declarativeNetRequest)) {
    done("the extension APIs are not available on this page");
    return;
}
chrome.runtime.sendMessage({what: "setDefaultFilteringMode", level: 0})
  .then((level) => chrome.declarativeNetRequest.getDynamicRules().then((rules) => {
      const allowAll = rules.some((r) => r.action.type === "allowAllRequests"
                                         && !r.condition.requestDomains);
      done({level: level, allowAll: allowAll});
  }))
  .catch((e) => done(String(e)));
"""

# Find all href tags
# JavaScript efficient implementation
GET_LINK_JS = (Path(__file__).parent / "js/get_links.js").read_text()

def post_load_routine(func: FuncT, browser_init: Optional["Browser"] = None) -> FuncT:
    """
    Collects cookies and dismisses alert windows after the decorated function is run
    """

    def func_wrapper(*args: Any, **kwargs: Any) -> None:
        ret = func(*args, **kwargs)

        # check if self (Browser) is the first argument
        browser = args[0]
        if not isinstance(browser, Browser):
            if browser_init:
                browser = browser_init
            else:
                logger.error("Browser not provided to the post_routine decorator")
                return ret

        logger.debug("executing post function routine")
        browser.dismiss_dialogs()
        return ret

    return cast(FuncT, func_wrapper)


class Browser(ABC):
    driver: uc.Chrome | webdriver.Firefox

    """
    Abstracts driver for Selenium

    :ivar driver: automated browser driver
    :ivar post_function_armed: if the service routing should be executed or not
          (prevents capturing cookies when everything is already dumped into DB)
    :ivar cookie_tracker: a list collecting all the detected cookies during crawl
    """

    def __init__(
        self,
        allow_screenshot: bool,
        timeout: float,
        seconds_before_processing_page: float,
        proxy: Optional[str] = None,
    ) -> None:
        """This implements an abstract basic browser which provides some common settings (screenshots, proxy, timeout and the seconds_before_processing_page).
        And also dumping logic, link collecion and other shared logic.

        Args:
            allow_screenshot (bool): Defines if we take a screenshot when full_dump is called.
            timeout (float): Timeout for a page to load.
            seconds_before_processing_page (float): Seconds to wait before determining the status of a page.
            proxy (Optional[str], optional): Proxy url. Defaults to None.
        """

        # Contains a dictionary from all URLs of loaded resources to their state
        self._load_status: dict[str, PageState] = {}

        self.last_loaded_url: Optional[URL] = None
        self.allow_screenshot = allow_screenshot

        self.proxy = proxy
        self.timeout = timeout
        self.seconds_before_processing_page = seconds_before_processing_page

        # Needs to also have enfbots_ prefix as this is also deleted
        # via 'run-crawler.sh' in case the crawler crashes.
        self.temp_download_directory = tempfile.TemporaryDirectory(prefix="enfbots_download_dir_")

    @property
    @abstractmethod
    def requests(self) -> list[Any]: ...

    @abstractmethod
    def __enter__(self) -> Browser: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        logger.info("Exiting selenium driver")
        # noinspection PyBroadException
        try:
            self._press_key(Keys.ESCAPE)
            logger.info("During the crawl %s HTTP requests were performed.", len(self.requests))
            self.driver.quit()
        except Exception as e:
            # some errors (like KeyboardInterrupt) might crash Selenium and we cannot quit it like this
            logger.warning("Driver failed to quit gracefully, due to %s", e)

    def dismiss_dialogs(self) -> None:
        # try to dismiss alert windows
        try:
            while True:
                self.driver.switch_to.alert.dismiss()
                logger.debug("Dismissed alert")
                time.sleep(0.5)
        except (NoAlertPresentException, TimeoutException):
            pass

    @property
    def user_agent(self) -> str:
        agent = self.execute_script("return navigator.userAgent;")
        if agent:
            return agent
        logging.warning("Browser returned no user agent!")
        return "Mozilla/5.0 (X11; Linux x86_64; rv:94.0) Gecko/20100101 Firefox/94.0"

    @property
    def current_url(self) -> URL:
        try:
            # Even though the type from driver.current_url says it can never be None
            # it sometimes is and we have to handle this case here
            return URL.from_text(self.driver.current_url)
        except TypeError:
            return URL.from_text("")

    @post_load_routine
    def load_page(self, url: URL, timeout: Optional[float] = None) -> PageState:
        timeout = self.seconds_before_processing_page if timeout is None else timeout

        # this function is NOT thread safe
        # selenium wire will add a trailing slash, so we add it before to be able to match requests later
        # adds a trailing slash if it does not exist

        if not url.path:
            url = url.child("")

        logger.debug("Loading page %s", url)
        self.last_loaded_url = url
        error = None
        try:
            str_url = str(url)
            logger.info("Calling driver.get %s", str_url)
            self.driver.get(str_url)
        except TimeoutException:
            logging.warning("Timeout on: %s", url)
            return PageState.TIMEOUT
        except WebDriverException as e:
            if "net::ERR_NAME_NOT_RESOLVED" in str(e.msg):
                return PageState.DNS_ERROR
            # other exceptions in Chrome.
            # actual error is in load status
            error = e

        # this may add up to 40 s to the whole crawl execution
        if timeout == 0:
            timeout = 0.8 + random.random() * 1.2
        logger.info("Waiting for %0.2f seconds", timeout)
        time.sleep(timeout)

        if str_url in self._load_status:
            logger.info("load status is: %s", self._load_status[str_url])
            return self._load_status[str_url]
        else:
            logger.info("NO load status found for %s", str_url)

        # Escape closes modals; email-capture mode is looking for exactly those (pop-up sign-ups)
        if not Config().EMAIL_CAPTURE_ONLY:
            try:
                logger.info("Pressing escape")
                self._press_key(Keys.ESCAPE)
            except (UnexpectedAlertPresentException, WebDriverException, TimeoutException) as e:
                logger.exception(e)
                # Also continue

        if str(url) in self._load_status:
            tries = 3
            while tries > 0:
                try:
                    status = self._load_status[str(url)]
                    if status == PageState.REDIRECT:
                        return self._load_status[str(self.last_loaded_url)]
                    return status
                except KeyError:
                    pass
                tries -= 1
            # End of tries
            logger.error("No status for URL: %s", url)
            return PageState.UNKNOWN_ERROR
        if error:
            # an error on get without extra
            logger.error("Unknown error occurred on page load.", exc_info=error)
            return PageState.UNKNOWN_ERROR

        # this indicates the list was probably an anchor and no reload happened (e.g. SPA)
        return PageState.OK

    def full_dump(self, output_dir: Path, name: str) -> None:
        path = output_dir / "dump_urls.txt"
        with path.open("a") as file:
            print(f"{name}: {self.current_url.to_text()}", file=file)

        if self.allow_screenshot:
            self.take_screenshot(output_dir, name)
        self.dump_html(output_dir, name)

    def take_screenshot(self, output_dir: Path, name: str) -> None:
        # use firefox driver specific method
        logger.debug("Taking screenshot: %s", name)

        # Ensure the output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

        # Take only a screenshot of the visible part
        # self.driver.save_screenshot(str(path))

        for i, window_handle in enumerate(self.driver.window_handles):
            path = output_dir / f"{name}_window_{i}.png"

            logger.debug("\t taking screenshot of window: %s", window_handle)
            png = self._get_screenshot_as_png(window_handle)
            try:
                with path.open("wb") as file:
                    file.write(png)
            finally:
                del png

    @abstractmethod
    def _get_screenshot_as_png(self, window_handle: str) -> bytes: ...

    def dump_html(self, output_dir: Path, name: str) -> Path:
        """
        Save page as html. Returns the filename of the stored file.
        :param output_dir: storage path
        :param name: file name
        """
        current_url = self.current_url
        logger.info("Dumping HTML: %s on page: %s", name, current_url)

        if str(current_url).strip().lower().endswith(".pdf"):
            logger.error("Dumping html on pdf page %s", current_url)

        content = self.get_html()
        file_name = output_dir / f"{name}.html"

        # Write out
        output_dir.mkdir(parents=True, exist_ok=True)
        with file_name.open("w") as out_file:
            out_file.write(content)
        return file_name

    def get_html(self) -> str:
        return str(self.driver.page_source)

    def get_soup(self) -> BeautifulSoup:
        """
        Parse the content of the web page
        :return: BeautifulSoup of the page content
        """
        soup = BeautifulSoup(self.driver.page_source, "html.parser", multi_valued_attributes=None)
        for nos in soup.find_all("noscript"):
            nos.decompose()
        return soup

    def get_links(self) -> list[LinkTuple]:
        """
        For currently loaded page, locate all links and their accompanying text
        """

        links = self.execute_script(GET_LINK_JS)

        if links is None:
            return []

        current_url = self.current_url

        results = []
        for item in links:
            if item is None:
                continue

            if "href" in item:
                if item["href"]:
                    href = item["href"].strip()
                    try:
                        url = URL.from_text(urldefrag(href).url)
                    except URLParseError:
                        logger.warning("Badly formatted url encountered %s", href)
                        continue
                    except ValueError:
                        logger.warning("Badly formatted url encountered, other ValueError %s", href)
                        continue
                    # check for valid scheme (not mailto...)
                    if url.scheme not in ("http", "https", ""):
                        continue
                    if not url.absolute:
                        try:
                            url = current_url.click(url)
                        except NotImplementedError as e:
                            logger.warning(
                                "NotImplementedError when clicking: %s on link %s", e, url
                            )
                            continue

                    path_only = url.replace(scheme=None, host=None, port=None).to_text()
                    test_str = [item["text"], path_only, item["alt_text"]]
                    results.append(LinkTuple(url, test_str))
            else:
                logger.error("Strange link found: %s", item)
        return results

    @post_load_routine
    def activate(self, el: WebElement) -> None:
        """
        Using this function, one is also able to click on partially hidden html elements, which would otherwise cause
        an exception when trying to simulate a click on it :param el: element to make active
        """
        self.driver.execute_script("arguments[0].click();", el)

    @post_load_routine
    def execute_script(self, script: str, *args: Any, raise_exception: bool = False) -> Any:
        """
        Wrapper of browser execute_script. Raises JavascriptException
        """
        logger.debug("Executing JS code in selenium: %s", script)
        try:
            res = self.driver.execute_script(script, *args)
            logger.debug("> Result was: %s", res)
            return res
        except JavascriptException as e:
            if raise_exception:
                raise e
            else:
                logger.exception("JavaScript exception encountered")

    @post_load_routine
    def _press_key(self, key: Any) -> None:
        """
        Operate the browser via keyboard.
        :param key: keyboard keys to press
        """
        actions = ActionChains(self.driver)
        actions.send_keys(key)
        actions.perform()

    def scroll_through_page(self, steps: int = 8, pause: float = 0.4) -> None:
        """Scrolls to the bottom in steps, firing scroll events like a reader would, then back."""
        for i in range(1, steps + 1):
            self.driver.execute_script(
                "window.scrollTo(0, document.documentElement.scrollHeight * arguments[0]);",
                i / steps,
            )
            time.sleep(pause)
        self.driver.execute_script("window.scrollTo(0, 0);")

    def simulate_exit_intent(self) -> None:
        """
        Moves the mouse up to the top edge, then fires the events exit-intent scripts listen
        for when the pointer leaves the window towards the tabs or address bar. The events are
        synthetic (isTrusted is false), so scripts that check for real input won't react.
        """
        actions = ActionBuilder(self.driver)
        actions.pointer_action.move_to_location(200, 300)
        actions.pointer_action.move_to_location(200, 5)
        actions.perform()
        self.driver.execute_script(_EXIT_INTENT_JS)

    @post_load_routine
    def input_value(self, tag: WebElement, value: str) -> None:
        """
        Fill in an input form using javascript
        :param tag: tag which should be modified
        :param value: value which should be set
        """

        if (
            tag.tag_name == "textarea"
            or tag.get_attribute("type") in ("text", "password", "email", "tel", "number", "search")
            and tag.is_displayed()
        ):
            self.fill_text_elem(tag, value)
        else:
            self.set_attribute(tag, "value", value)

    @staticmethod
    def fill_text_elem(tag: WebElement, value: str) -> None:
        """
        Fill a single input element, such as text, password, or textarea
        :param tag: tag which should be modified
        :param value: value which should be set
        """
        tag.clear()
        if tag.tag_name != "textarea":
            value = value.replace("\n", " ")

        for letter, timeout in zip(str(value), random.uniform(0.02, 0.1, len(value))):
            tag.send_keys(letter)
            time.sleep(timeout)

    @post_load_routine
    def set_attribute(self, tag: WebElement, attr: str, value: str) -> None:
        """
        Fill in an input form using javascript
        :param tag: tag which should be modified
        :param attr: name of the attribute to change
        :param value: value which should be set
        """
        self.driver.execute_script(f"arguments[0].{attr} = '{value}'", tag)

    @abstractmethod
    def get_image_as_base64(self, nearest_image: WebElement) -> Optional[str]: ...

    @abstractmethod
    def get_screenshot(self) -> bytes:
        """
        Returns the screenshot as bytes in png format.
        """

class EnfbotsBrowser(Browser):
    def __init__(self, seconds_before_processing_page: float, proxy: Optional[str] = None) -> None:
        super().__init__(
            Config().ALLOW_SCREENSHOTS,
            Config().TIMEOUT_SHORT,
            seconds_before_processing_page,
            proxy,
        )
        self.captcha_apis: list[URL] = []

        self.cookie_tracker: set[CookieTuple] = set()

    def find_forms(
        self, lang: Language = Language.get(Config().language_dir, "en")
    ) -> list[FormBS]:
        form_info = self.load_form_info()
        soup = self.get_soup()
        return [FormBS(f, lang, form_info) for f in soup.find_all("form")]

    def load_page(self, url: URL, timeout: Optional[float] = None) -> PageState:
        ps = super().load_page(url, timeout)
        if str(url) in self._load_status:
            self.collect_cookies()
        return ps

    def collect_cookies(self) -> None:
        cookies = self.driver.get_cookies()

        if cookies is None:
            return

        for cookie in cookies:
            my_cookie = CookieTuple(
                cookie.get("name"),
                cookie.get("value"),
                cookie.get("path"),
                cookie.get("domain"),
                cookie.get("secure"),
                cookie.get("httpOnly"),
                cookie.get("expiry"),
                cookie.get("sameSite"),
            )
            # the tuple is  hashable nicely so the set should work
            if my_cookie not in self.cookie_tracker:
                self.cookie_tracker.add(my_cookie)

    def load_form_info(self) -> dict[str, bool]:
        # give all forms and inputs unique IDs for matching between Selenium and bs4
        return self.execute_script(
            """
            return (function () {
                const UUIDGen = () =>
                    ([1e7] + -1e3 + -4e3 + -8e3 + -1e11).replace(/[018]/g, c =>
                        (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16)
                    );

                const isVisible = (elem) => {
                    while (elem.parentNode && elem.parentNode.getBoundingClientRect) {
                        const elemComputedStyle = window.getComputedStyle(elem);
                        if (elemComputedStyle.display === 'none' ||
                            elemComputedStyle.visibility !== 'visible' ||
                            parseFloat(elemComputedStyle.opacity, 10) <= 0) {
                            return false
                        }
                        elem = elem.parentNode;
                    }
                    return true;
                };

                const results = {};
                for (const e of document.querySelectorAll("form, input, textarea, select, button")) {
                    const id = 'crawleruuid-' + UUIDGen();
                    if (!e.hasAttribute('id')) {
                        e.id = id;
                    }
                    if (!e.hasAttribute("data-enfbots-uuid")) {
                        e.setAttribute("data-enfbots-uuid", id);
                        results[id] = isVisible(e);
                    } else {
                        results[e.getAttribute("data-enfbots-uuid")] = isVisible(e);
                    }

                }
                return results;
            })();
            """
        )


class Firefox(EnfbotsBrowser):

    class ErrorInterceptorAddon:
        def __init__(self, browser: EnfbotsBrowser):
            self.browser = browser

        def error(self, flow: Any) -> None:
            if not hasattr(flow.request, "id"):
                # Request was not stored by seleniumwire
                return
            url = URL.from_text(flow.request.url)
            if url == self.browser.last_loaded_url:
                logger.debug("Failed to load %s. TCPError: %s", url.to_text(), flow.error.msg)
                self.browser._load_status[flow.request.url] = PageState.TCP_ERROR

    def _response_interceptor(self, request: Request, response: Response) -> None:
        url = URL.from_text(request.url)
        captcha_type = classify_captcha_url(url)
        if captcha_type:
            self.captcha_apis.append(url)
            # The stub only imitates the reCAPTCHA/hCaptcha APIs, not Turnstile
            if Config().CAPTCHA_ALLOW_STUB and captcha_type in ("recaptcha", "hcaptcha"):
                enterprise = "true" if "enterprise.js" in url.path else "false"
                stub = (Config().code_dir / "js/captcha_stub.js").read_text()
                query_dict = dict(url.query)
                stub = (
                    stub.replace("{{render}}", query_dict.get("render") or "")
                    .replace("{{onload}}", query_dict.get("onload") or "")
                    .replace("{{hl}}", query_dict.get("hl") or "")
                    .replace("{{type}}", captcha_type)
                    .replace("{{enterprise}}", enterprise)
                )
                stub_bytes = stub.encode("utf-8")
                del response.headers["Content-Type"]
                del response.headers["Content-Encoding"]
                del response.headers["Content-Length"]
                response.headers["Content-Type"] = "text/javascript; charset=UTF-8"
                response.headers["Content-Length"] = str(len(stub_bytes))
                response.body = stub_bytes

        if url == self.last_loaded_url:
            location = response.headers["Location"]
            content_type = response.headers["Content-Type"]
            if 300 <= response.status_code < 400 and location:
                loc = URL.from_text(location)
                if not loc.absolute:
                    loc = url.click(loc)
                self.last_loaded_url = loc
                self._load_status[str(url)] = PageState.REDIRECT
            elif not is_content_type_accepted(content_type):
                # we tried to load a page that will probably trigger a download instead
                # this will reject the load
                self._load_status[str(url)] = PageState.BAD_CONTENT_TYPE
                response.status_code = 500
                del response.headers["Content-Type"]
                del response.headers["Content-Encoding"]
                del response.headers["Content-Length"]
                response.headers["Content-Type"] = "text/html; charset=UTF-8"
                response.body = "<html>Content blocked</html>".encode("utf-8")
                response.headers["Content-Length"] = str(len(response.body))
                logger.warning("Blocking the load of a non html page at %s", request.url)
            elif response.status_code >= 400:
                logger.error("HTTP status_code %s and response: %s", response.status_code, response)
                self._load_status[str(url)] = PageState.HTTP_ERROR
            else:
                self._load_status[str(url)] = PageState.OK
                logger.debug(
                    "Fetched the page %s with status %s and content type %s",
                    request.url,
                    response.status_code,
                    content_type,
                )

    def __enter__(self) -> Firefox:
        logger.info("Starting Firefox browser")

        wire_options: dict[str, Any] = {
            "verify_ssl": True,
        }
        if self.proxy:
            wire_options["proxy"] = {"http": self.proxy, "https": self.proxy}

        options = FirefoxOptions()
        options.set_preference("profile", str(Config().FIREFOX_PROFILE_PATH))
        options.set_preference("intl.accept_languages", Config().BROWSER_LANGUAGE)
        options.set_preference("extensions.lastAppBuildId", "20211118224727")

        # if driver is not installed at the given path, try to use a global one from PATH
        if Config().GECKO_DRIVER_PATH.exists():
            gecko_path = str(Config().GECKO_DRIVER_PATH)
        else:
            gecko_path = "geckodriver"

        service = FirefoxService(executable_path=gecko_path, log_path=str(Config().GECKO_LOG_PATH))

        self.driver = webdriver.Firefox(
            options=options, service=service, seleniumwire_options=wire_options
        )

        self.driver.backend.master.addons.add(self.ErrorInterceptorAddon(self))
        self.driver.response_interceptor = self._response_interceptor
        self.driver.set_page_load_timeout(40)

        return self

    @property
    def requests(self) -> list[Any]:
        return self.driver.requests

    def get_image_as_base64(self, nearest_image: WebElement) -> Optional[str]:
        src: str = nearest_image.get_attribute("src")
        for req in reversed(self.requests):
            if req.url == src and req.response and req.response.body:
                body = decode(
                    req.response.body,
                    req.response.headers.get("Content-Encoding", "identity"),
                )
                return base64.b64encode(body).decode("ascii")

        # noinspection PyBroadException
        try:
            return nearest_image.screenshot_as_base64
        # pylint: disable=broad-exception-caught
        except Exception:
            logger.warning("Unable to screenshot image captcha")
            return None

    def _get_screenshot_as_png(self, window_handle: str) -> bytes:
        # TODO: activate correct window_handle
        return self.driver.get_full_page_screenshot_as_png()


    def get_screenshot(self) -> bytes:
        """
        Returns the screenshot as bytes in png format.
        """
        return self.driver.get_full_page_screenshot_as_png("not-used")


def is_content_type_accepted(content_type: str) -> bool:
    return content_type is None or (
        content_type.strip().startswith("text/html")
        or content_type.strip().startswith("application/pdf")
        or content_type.strip().startswith("application/xhtml+xml")
    )


def _process_tree(pid: Optional[int]) -> list[Process]:
    """The process and all its descendants; empty if it is already gone."""
    if pid is None:
        return []
    try:
        root = Process(pid)
        return [root] + root.children(recursive=True)
    except psutil.Error:
        return []


def _is_alive(p: Process) -> bool:
    """
    A zombie has exited and writes nothing, so it counts as gone. Reaps it when it is our
    child: in Docker the crawler is often PID 1 and inherits Chrome's orphaned helpers.
    """
    try:
        if p.status() != psutil.STATUS_ZOMBIE:
            return True
        p.wait(timeout=0)
    except psutil.Error:
        pass
    return False


def _alive_after(processes: list[Process], timeout: float) -> list[Process]:
    deadline = time.monotonic() + timeout
    alive = [p for p in processes if _is_alive(p)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = [p for p in alive if _is_alive(p)]
    return alive


def _wait_for_exit(processes: list[Process], timeout: float = 10) -> None:
    """Waits for the processes to exit; kills those still running after timeout seconds."""
    alive = _alive_after(processes, timeout)
    if not alive:
        return
    logger.info("Killing %s browser processes still running", len(alive))
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    _alive_after(alive, timeout)


def _cleanup_temp_dir(temp_dir: tempfile.TemporaryDirectory[str], tries: int = 3) -> None:
    """Removes the directory, retrying shortly if a file appeared while it was removed."""
    for i in range(tries):
        try:
            temp_dir.cleanup()
            return
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(0.5)


class Chrome(EnfbotsBrowser):
    def __init__(
        self,
        seconds_before_processing_page: float,
        languages: List[str] = [],
        use_temp: bool = True,
        intercept_network: bool = True,
        headless: bool = True,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """
        Creates a EnfbotsBrowser using Chrome via the webdriver.

        Args:
            languages (List[str]): Languages in descending priority order and their code according to ISO 639-1. They are sent in the "Accepted-Languages" Header.
            use_temp (bool, optional): If a temporary directory should be used for the profile data which will be altered. Defaults to True.
        """
        super().__init__(seconds_before_processing_page=seconds_before_processing_page)
        self._requests: list[Any] = []
        self.use_temp = use_temp
        self.languages = languages
        self.intercept_network = intercept_network

        # By default we use a temporary directory to always have a fresh chrome profile
        if self.use_temp:
            self._temp_dir = tempfile.TemporaryDirectory(prefix="enfbots_")
            self.profile_path = Path(self._temp_dir.name) / "chrome_profile"

            if (Config().CHROME_PROFILE_PATH / "SingletonLock").exists():
                (Config().CHROME_PROFILE_PATH / "SingletonLock").unlink()
            if (Config().CHROME_PROFILE_PATH / "SingletonCookie").exists():
                (Config().CHROME_PROFILE_PATH / "SingletonCookie").unlink()
            if (Config().CHROME_PROFILE_PATH / "SingletonSocket").exists():
                (Config().CHROME_PROFILE_PATH / "SingletonSocket").unlink()

            # copy profile to the temporary directory
            shutil.copytree(
                Config().CHROME_PROFILE_PATH, self.profile_path, ignore_dangling_symlinks=True
            )

        else:
            self.profile_path = Config().CHROME_PROFILE_PATH
        self.headless = headless

    @property
    def requests(self) -> list[Any]:
        return self._requests

    def __enter__(self) -> Chrome:
        driver_path: Optional[Path] = None

        if Config().CHROME_DRIVER_PATH.exists():
            driver_path = Config().CHROME_DRIVER_PATH
        chrome_path: Optional[Path] = None

        if Config().CHROME_BROWSER_PATH.exists():
            chrome_path = Config().CHROME_BROWSER_PATH
        else:
            raise RuntimeError(f"Where is {Config().CHROME_BROWSER_PATH}")

        logger.info(
            "Instantiating chrome [%s] using chromedriver [%s] with profile_path %s",
            chrome_path,
            driver_path,
            self.profile_path,
        )

        options = uc.ChromeOptions()

        # required in docker (no X11 context)
        # More info on flags: https://peter.sh/experiments/chromium-command-line-switches/
        options.add_argument("--no-sandbox")
        options.add_argument(f"--window-size={CHROME_WIDTH},{CHROME_HEIGHT}")

        if len(self.languages) > 0:
            options.add_argument("--accept-lang=" + ",".join(self.languages))
            options.add_argument("--lang=" + ",".join(self.languages))
            logging.info("Preferring languages: %s", ",".join(self.languages))

        # just some options passing in to skip annoying popups
        options.add_argument("--no-first-run")
        options.add_argument("--no-service-autorun")
        options.add_argument("--password-store=basic")
        if self.proxy:
            options.add_argument(f"--proxy-server={self.proxy}")

        if Config().CHROME_DISABLE_SHM:
            options.add_argument("--disable-dev-shm-usage")

        prefs = {
            "download_restrictions": 0,  # Allows the browser to download all content; https://chromeenterprise.google/policies/?policy=DownloadRestrictions
            "download.default_directory": self.temp_download_directory.name,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "profile.default_content_settings.popups": False,
            "plugins.always_open_pdf_externally": True,
            "excludeSwitches": ["enable-automation"],
            "useAutomationExtension": False,
        }
        options.add_experimental_option("prefs", prefs)

        options.add_argument("--kiosk-printing")

        # adding argument to disable the AutomationControlled flag
        options.add_argument("--disable-blink-features=AutomationControlled")

        # For debugging
        # options.add_argument("--enable-logging")
        # options.add_argument("--v=1")

        # headless=True will send --headless=new after version 108
        # options.headless = self.headless
        options.headless = False # always false! we use Xvfb instead if not display is available

        self.display: XvfbDisplay | None = None
        if self.headless:
            logging.info("Using Xvfb")
            self.display = XvfbDisplay(size=(CHROME_WIDTH, CHROME_HEIGHT))
            self.display.start()
        else:
            logging.info("Not using Xvfb")
            self.display = None

        options.page_load_strategy = "normal"

        self.driver = uc.Chrome(
            options=options,
            driver_executable_path=str(driver_path),
            browser_executable_path=str(chrome_path),
            headless=self.headless,
            version_main=143,
            user_data_dir=self.profile_path,
            enable_cdp_events=True,
        )

        stealth(
            self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        # Time to wait when calling driver.get
        self.driver.set_page_load_timeout(Config().PAGE_TIMEOUT_SEC)

        # changing the property of the navigator value for webdriver to undefined
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        if self.intercept_network:
            self._intercept_network()

        self.driver.add_cdp_listener("Network.responseReceived", self._handle_cdp_response_received)

        if Config().EMAIL_CAPTURE_ONLY:
            self.configure_ublock()

        return self

    def configure_ublock(self) -> None:
        """Applies CAPTURE_UBLOCK_MODE to uBlock Origin Lite (email-capture mode)."""
        mode = Config().CAPTURE_UBLOCK_MODE
        if mode == "none":
            self.disable_ublock_filtering()
        elif mode == "allowlist":
            self.unblock_capture_vendors()
        elif mode != "default":
            logger.warning("Unknown CAPTURE_UBLOCK_MODE %s; uBlock left unchanged", mode)

    def _run_on_ublock_page(self, script: str, *args: Any) -> Any:
        # uBlock's extension APIs are only reachable from its own pages, e.g. its dashboard
        self.driver.get(f"chrome-extension://{Config().UBLOCK_EXTENSION_ID}/dashboard.html")
        return self.driver.execute_async_script(script, *args)

    def disable_ublock_filtering(self) -> None:
        """
        Switches uBlock Origin Lite to "No filtering": it stays installed and running, as for
        a user who turned it off, but blocks and hides nothing, so every pop-up vendor loads.
        """
        try:
            result = self._run_on_ublock_page(_NO_FILTERING_JS)
        except WebDriverException as e:
            logger.warning("Could not switch off uBlock Origin Lite filtering: %s", e.msg)
            return
        if isinstance(result, dict) and result.get("level") == 0 and result.get("allowAll"):
            logger.info("uBlock Origin Lite filtering switched off (No filtering mode)")
        else:
            logger.warning("Could not switch off uBlock Origin Lite filtering: %s", result)

    def unblock_capture_vendors(self) -> None:
        """
        Lifts uBlock Origin Lite's blocking for CAPTURE_UNBLOCK_DOMAINS only, so pop-up and
        sign-up vendors load while its other filtering stays on.
        """
        domains = Config().CAPTURE_UNBLOCK_DOMAINS
        if not domains:
            return
        try:
            result = self._run_on_ublock_page(_UNBLOCK_JS, domains, _UNBLOCK_RULE_ID)
        except WebDriverException as e:
            logger.warning("Could not unblock sign-up vendors in uBlock Origin Lite: %s", e.msg)
            return
        if isinstance(result, int):
            logger.info("Unblocked %d sign-up vendor domains in uBlock Origin Lite", result)
        else:
            logger.warning("Could not unblock sign-up vendors in uBlock Origin Lite: %s", result)

    def _handle_cdp_response_received(self, data: Any) -> None:
        """
        This function is analogous to _process_intercepted_request but is directly called
        from undetected-chromedriver instead of using node to communicate with the CDP endpoint.
        The javascript is still used for captcha solving.

        This handles the response and adds usefull information to self._load_status.
        """
        if data["method"] == "Network.responseReceived":
            url = data["params"]["response"]["url"]
            http_status = data["params"]["response"]["status"]

            if http_status == 404:
                self._load_status[url] = PageState.HTTP_ERROR  # TODO : add pagestate HTTP_404?
            if 200 <= http_status < 300:
                self._load_status[url] = PageState.OK

    def _process_intercepted_request(self, data: Any) -> None:
        self.requests.append(data)
        url = URL.from_text(data["request"]["url"])
        response = data["response"]
        if url == self.last_loaded_url:
            error = response.get("error_reason")
            if error:
                logger.warning("Load of page %s was interrupted with status %s.", url, error)
                # Failed, Aborted, TimedOut, AccessDenied, ConnectionClosed, ConnectionReset,
                # ConnectionRefused, ConnectionAborted, ConnectionFailed, NameNotResolved,
                # InternetDisconnected, AddressUnreachable, BlockedByClient, BlockedByResponse
                if error == "NameNotResolved":
                    self._load_status[str(url)] = PageState.DNS_ERROR
                elif error == "TimedOut":
                    self._load_status[str(url)] = PageState.TIMEOUT
                else:
                    self._load_status[str(url)] = PageState.TCP_ERROR
            else:
                headers = response["headers"]
                status_code = response["http_status"]
                location = headers.get("Location")
                content_type = headers.get("Content-Type")
                if 300 <= status_code < 400 and location:
                    loc = URL.from_text(location)
                    if not loc.absolute:
                        loc = url.click(loc)
                    self.last_loaded_url = loc
                    self._load_status[str(url)] = PageState.REDIRECT
                elif status_code >= 400:
                    logger.error(
                        "On %s: HTTP status_code %s and response: %s", url, status_code, response
                    )
                    logger.error("Data: %s", data)
                    self._load_status[str(url)] = PageState.HTTP_ERROR
                elif not is_content_type_accepted(content_type):
                    # actually block done by download_restriction parameter
                    self._load_status[str(url)] = PageState.BAD_CONTENT_TYPE
                else:
                    self._load_status[str(url)] = PageState.OK
                    logger.debug(
                        "Fetched the page %s with status %s and content type %s",
                        url,
                        status_code,
                        content_type,
                    )

    def _spawn_network_interceptor(self) -> None:
        logger.info("Starting Node network interceptor")
        interceptor_workdir = Config().root_dir / "interceptor"
        interceptor = interceptor_workdir / "index.js"

        debug_addr = self.driver.capabilities["goog:chromeOptions"]["debuggerAddress"]

        command = ["node", str(interceptor), debug_addr]
        if Config().CAPTCHA_ALLOW_STUB:
            command.append(str(Config().code_dir / "js" / "captcha_stub.js"))

        logger.info("Executing %s", command)
        self._interceptor_process = subprocess.Popen(command, stdout=subprocess.PIPE)

        # Poll process for new output until finished
        assert self._interceptor_process.stdout
        for line in iter(self._interceptor_process.stdout.readline, b""):
            data = json.loads(line.decode("utf-8"))
            self._process_intercepted_request(data)

        self._interceptor_process.wait()
        logger.info("Network interceptor exited with: %s", self._interceptor_process.returncode)

    def _intercept_network(self) -> None:
        self._interceptor_thread = Thread(target=self._spawn_network_interceptor)
        self._interceptor_thread.start()
        time.sleep(0.5)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:

        if self.intercept_network:
            self._interceptor_process.terminate()
            self._interceptor_thread.join()

        # Chrome's helper processes (network service, GPU, zygote, ...) can outlive the main
        # browser process and keep writing into the profile; collect them before quitting
        browser_processes = _process_tree(self.driver.browser_pid)

        super().__exit__(exc_type, exc_val, exc_tb)

        try:
            # Ensure chrome is no longer running before removing _temp_dir
            if self.display:
                self.display.stop()

            _wait_for_exit(browser_processes)

            if self.use_temp:
                _cleanup_temp_dir(self._temp_dir)
            if self.temp_download_directory:
                self.temp_download_directory.cleanup()
            print("Exited browser")
        except Exception as e:
            logger.warning("Unable to remove the temporary directory", stack_info=False)
            logger.exception(e)

    def get_image_as_base64(self, nearest_image: WebElement) -> Optional[str]:
        # noinspection PyBroadException
        try:
            return nearest_image.screenshot_as_base64
        except Exception:
            logger.warning("Unable to screenshot image captcha")
            return None

    def _get_screenshot_as_png(self, window_handle: str) -> bytes:
        """
        Creates a screenshot of the window defined by the handle of the entire page
        (not only the visible area of the browser)
        """
        page_rect = self.driver.execute_cdp_cmd("Page.getLayoutMetrics", {})

        self.driver.switch_to.window(window_handle)
        logger.debug(
            "Chrome screenshot of %s and window %s", self.driver.current_url, window_handle
        )

        screenshot = self.driver.execute_cdp_cmd(
            "Page.captureScreenshot",
            {
                "format": "png",
                "captureBeyondViewport": True,
                "clip": {
                    "width": page_rect["contentSize"]["width"],
                    "height": page_rect["contentSize"]["height"],
                    "x": 0,
                    "y": 0,
                    "scale": 1,
                },
            },
        )

        return base64.urlsafe_b64decode(screenshot["data"])


    def get_screenshot(self) -> bytes:
        return self.driver.get_screenshot_as_png()


def create_browser(*args: Any, **kwargs: Any) -> EnfbotsBrowser:
    if Config().BROWSER == "chrome":
        return Chrome(*args, **kwargs)
    return Firefox(*args, **kwargs)


class LinkTuple(NamedTuple):
    url: URL
    texts: list[str]


@contextmanager
def wait_for_page_load(browser: Browser, timeout: float) -> Generator[None, None, None]:
    """
    Context manager waiting for the page to load.
    If raise exception is true it raises a TimeoutException
    """
    old_page = browser.driver.find_element(By.TAG_NAME, "html")
    yield
    try:
        WebDriverWait(browser.driver, timeout).until(staleness_of(old_page))
        time.sleep(1)
    except TimeoutException:
        logger.warning("Timeout waiting for the page %s to load", browser.current_url)
