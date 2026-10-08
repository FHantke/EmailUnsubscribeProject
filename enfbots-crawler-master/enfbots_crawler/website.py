"""
All browsing activities of the enfbots_crawler are defined here
"""

from __future__ import annotations

import base64
import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Optional, cast, List, Tuple, TypeVar, NamedTuple, Any, Iterator
import json
import hashlib
import urllib
from pathlib import Path
from collections import defaultdict
import glob
import shutil
from importlib.metadata import version
from enfbots_crawler.exceptions import CrawlerException, WebsiteException

from sortedcontainers import SortedSet
from tldextract import tldextract
from bs4 import BeautifulSoup
from pdfminer.high_level import extract_text as extract_text_from_pdf
from urllib3.exceptions import HTTPError

# Libs
try:
    import pycld2
    pycld_avail = True
except ImportError:
    # Ignore in dev; This package has difficulties building on my machine
    pycld_avail = False

from hyperlink import URL

if pycld_avail:
    from polyglot.detect import Detector
    from polyglot.detect.base import UnknownLanguage

from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
    NoSuchElementException,
    InvalidSessionIdException,
)

# Imports from the enfbots library
from enfbots_crawler import store, SessionLocal, const, DBJob
from enfbots_crawler.enums import PageType

from enfbots_crawler.modules.classifier import (
    ClassifierAbstr,
    ClassifierAsAService,
    ClassificationException,
)
from enfbots_crawler.languages import (
    KeywordType,
    get_supported_languages,
    Language,
)
from enfbots_crawler.text_helper import (
    extract_content_from_html,
    get_all_emails,
    remove_bad_chars_for_polyglot,
    extract_text_only_from_html,
)
from enfbots_crawler.lang_helper import detect_language
from enfbots_crawler.modules.stat_collector import StatCollector, CollectType
from enfbots_crawler.keyword_matching import keyword_classify, match_keywords

# Imports from this crawler implementation
from enfbots_crawler import (
    Config,
    database,
    EmailVerificationStatus,
    PageState,
    State,
    RegistrationStatus,
    FormType,
    InputType,
    ConsiderationBasis,
)
from enfbots_crawler.browser import EnfbotsBrowser, LinkTuple, Browser
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.database import (
    DBWebsite,
    DBWebsiteCrawl,
    DBURL,
    CrawlToPrivacyPolicy,
    CrawlToTermsAndConditions,
    CrawlToUSPrivacyNotice,
    get_website,
    get_urlcontent,
)
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.form_selenium import FormSelenium
from enfbots_crawler.reg_processor import RegProcessor
from enfbots_crawler.text_lib import extract_text_from_html

T = TypeVar("T", bound=Browser)

logger = logging.getLogger("enfbots_crawler")

_newsletter_map = (
    State.NEWSLETTER_FORM_FOUND,
    State.NEWSLETTER_SUCCESSFUL,
    State.NEWSLETTER_FAILED,
    State.NEWSLETTER_ERRORED,
)
_register_map = (
    State.REGISTER_FORM_FOUND,
    State.REGISTER_SUCCESSFUL,
    State.REGISTER_FAILED,
    State.REGISTER_ERRORED,
)


class Navigator(ABC):
    def __init__(self, base_url: str) -> None:
        self.base_domain = tldextract.extract(base_url)
        logger.info("Created navigator for base_domain %s", self.base_domain)

        self.links: SortedSet[UrlMatch] = SortedSet(key=self.sorting_key)
        self.other_links: set[UrlMatch] = set()

        # keep track of already visited pages
        self.visited: set[UrlMatch] = set()
        self.visited_counts: dict[PageType, int] = defaultdict(lambda: 0)

    def __iter__(self) -> Iterator[UrlMatch]:
        return self

    @abstractmethod
    def is_navigation_completed(self) -> bool: ...

    @abstractmethod
    def is_type_overused(self, page_type: PageType) -> bool: ...

    @abstractmethod
    def is_type_needed(self, t: PageType) -> bool: ...

    def __next__(self) -> UrlMatch:
        if len(self.visited) > 20 or self.is_navigation_completed():
            logging.getLogger("enfbots_lib").info("Visited enough pages")
            raise StopIteration()

        while self.links:
            match = self.links.pop()
            if self.is_type_needed(match.type) and not self.is_type_overused(match.type):
                self.visited.add(match)
                self.visited_counts[match.type] += 1
                return match

        # we have no pages left to queue
        logging.getLogger("enfbots_lib").info("All links visited.")
        raise StopIteration()

    @staticmethod
    def domain_legal(url: URL) -> bool:
        domain = tldextract.extract(str(url))
        return f"{domain.domain}.{domain.suffix}" not in const.FORBIDDEN_DOMAINS

    def domain_matches(self, url: URL) -> bool:
        domain = tldextract.extract(str(url))
        return domain.registered_domain == self.base_domain.registered_domain

    def sorting_key(self, k: UrlMatch) -> float:
        # Idea is: k.type.value is the TYPE of the link (INDEX & OTHER are the lowest)  which we multiply with 10 to add some spacing between the page types. Then add the score which is usually in the inverval [0, 5]
        sort_value = k.type.value * 10 + k.score

        # When the domain is the same we add 10%
        if self.domain_matches(k.url) or k.url.host == "iubenda.com":
            sort_value *= 1.1

        return sort_value

    def add(self, match: UrlMatch) -> None:
        if match not in self.visited and self.domain_legal(match.url):
            if self.is_type_needed(match.type):
                self.links.add(match)
            else:
                logging.getLogger("enfbots_navigator").debug(
                    "Url is ignored as type %s is no longer needed: %s", match.type.name, match.url
                )


class EnfbotsNavigator(Navigator):
    def __init__(self, website: WebSite) -> None:
        super(EnfbotsNavigator, self).__init__(str(website.base_url))
        # this is a reference to website's states
        self.states = website.states
        self.website = website

    def is_navigation_completed(self) -> bool:
        if not Config().COLLECT_LEGAL_TEXTS:
            # Forms only: done once a newsletter form is seen, or no newsletter page is left to try
            return self.website.newsletter_url is not None or self.is_type_overused(
                PageType.NEWSLETTER
            )
        return (
            (State.REGISTER_FORM_FOUND in self.states or self.is_type_overused(PageType.REGISTER))
            and (
                State.POLICY_CONTENT_FOUND in self.states or self.is_type_overused(PageType.POLICY)
            )
            and (State.TERMS_CONTENT_FOUND in self.states or self.is_type_overused(PageType.TERMS))
        )

    def is_type_overused(self, page_type: PageType) -> bool:
        maxes = {
            PageType.SUSPICIOUS: 10,
            PageType.REGISTER: 3,
            PageType.LOGIN: 3,
            PageType.US_PN: 3,
            PageType.GDPR: 3,
            PageType.TERMS: 3,
            PageType.POLICY: 3,
            PageType.NEWSLETTER: 3,
            PageType.OTHER: 15,
        }
        return self.visited_counts[page_type] > maxes[page_type]

    def is_type_needed(self, t: PageType) -> bool:
        if not Config().COLLECT_LEGAL_TEXTS:
            # Forms only: newsletter pages; account registration and login pages are not needed
            return t == PageType.NEWSLETTER
        return (
            (
                State.REGISTER_FORM_FOUND not in self.states
                and (t == PageType.REGISTER or t == PageType.LOGIN)
            )
            or (t == PageType.TERMS)
            or (t == PageType.NEWSLETTER)
            or (t == PageType.POLICY)
            or (t == PageType.US_PN)
            or (t == PageType.GDPR)
        )


class BaseWebsite(ABC):
    def __init__(self, browser: T, url: URL, output_path: Path, log_to_output_path: bool) -> None:
        """_summary_

        Args:
            browser (Browser): Browser
            url (URL): Base URL of the Website
            output_path (Path): Output path to folder which should contain all data dumped from this website
            log_to_output_path (bool): If we should create a log inside the output_path with the log output of this website
        """
        # 6 char dump ID so we can crawl the same page multiple times
        self.dump_uuid = base64.urlsafe_b64encode(os.urandom(6)).decode()

        self.base_url = url
        self.br = browser

        # folder in which we dump our gathered data
        self.output_path = output_path / f"{self.base_url.host}_{self.dump_uuid}"
        self.log_to_output_path = log_to_output_path

        # Ensure output_path exists
        self.output_path.mkdir(exist_ok=True, parents=True)

        if self.log_to_output_path:
            self.output_log_filehandler = logging.FileHandler(self.output_path / "crawler.log")
            self._prepare_logging()
            logging.info(
                "Crawling %s with enfbots-crawler version %s",
                self.base_url.to_text(),
                version("enfbots-crawler"),
            )

    @abstractmethod
    def crawl(self) -> None: ...

    def _prepare_logging(self) -> None:
        root_logger = logging.getLogger()
        log_formatter = logging.Formatter(
            fmt=const.LOG_FORMAT_INFO,
            datefmt="%Y-%m-%d:%H:%M:%S",
        )
        self.output_log_filehandler.setFormatter(log_formatter)
        root_logger.addHandler(self.output_log_filehandler)

    def __del__(self) -> None:
        """
        Always called when an object is destroyed.
        """
        if self.log_to_output_path:
            if self.output_log_filehandler in logging.getLogger().handlers:
                logging.getLogger().removeHandler(self.output_log_filehandler)
            else:
                logging.getLogger().error("Missing output_log_filehandler in the handlers")


class WebSite(BaseWebsite):
    def __init__(
        self, browser: EnfbotsBrowser, url: URL, credentials: Optional[Credentials] = None
    ) -> None:
        super().__init__(browser, url, Config().OUTPUT_PATH, Config().OUTPUT_LOG)
        # url we are currently processing
        self.current: URL

        # Classifier used to determine if a page is terms & conditions or a privacy policy
        self.classifier: Optional[ClassifierAbstr]

        if Config().USE_CLASSIFIER:
            if Config().CLASSIFY_SERVICE_ENDPOINT != "":
                logger.info("Using classifier service at %s", Config().CLASSIFY_SERVICE_ENDPOINT)
                self.classifier = ClassifierAsAService(
                    Config().CLASSIFY_SERVICE_ENDPOINT,
                    Config().CLASSIFY_SERVICE_USER,
                    Config().CLASSIFY_SERVICE_TOKEN,
                    Config().DEV_VERIFY_SSL,
                )
            else:
                logger.error("Local classifier not supported")
                raise CrawlerException(
                    "Local classifier not supported. Please configure CLASSIFY_SERVICE_* or do not use classification"
                )

        self.states: set[State] = set()
        self.index_status: Optional[PageState] = None
        self.navigator = EnfbotsNavigator(self)

        self.reg_status: Optional[RegistrationStatus] = None

        self.email_verification_status: Optional[EmailVerificationStatus] = None

        self.real_lang_code: Optional[str] = None
        self.lang = Language.get(Config().language_dir, "en")

        self.pp_urls: List[CrawlToPrivacyPolicy] = []
        self.tc_urls: List[CrawlToTermsAndConditions] = []

        self.login_url: Optional[URL] = None
        self.index_redirect_url: Optional[URL] = None
        self.newsletter_url: Optional[URL] = None

        self.dumped_htmls: List[Path] = []  # List of filenames of dumped html files

        # List of tuples containing (address_local_part, address_domain, pagetype, url)
        self.emails: List[Tuple[str, str, str, str]] = list()

        self.reg_processors: list[RegProcessor] = []

        # Credentials used for registration forms
        self.credentials = credentials or Credentials.get()

        # Credentials for newsletter registration
        self.newsletter_credentials = Credentials.get()
        self.newsletter_registered = False

        # Gathers the stats over this single crawl
        self.crawl_stat_collector = StatCollector(CollectType.SINGLE_CRAWL)

        self.db_websitecrawl: DBWebsiteCrawl = DBWebsiteCrawl()

        self.next_gdpr_id: int = 0

        self.search_provider = "duckduckgo.com"
        # self.search_provider = "startpage.com"

        self.dump_id = 0

    def download_page(self, page_url: URL, output_file: Path) -> bool:
        """
        This downloads a page (defined by page_url) of a website (defined by the url from the Website constructor) and stores it as markdown at output_file.

        Args:
            page_url (str): Url of the page to download the content from
            output_file: File into which the content is stored (as markdown text)

        Returns:
            bool: True if successful
        """
        # Get page and convert to markdown
        if page_url.scheme == "":
            raise RuntimeError("URL needs a scheme (http or https)")
        status = self.br.load_page(page_url)

        if status != PageState.OK:
            logger.warning("Failed to load page %s. State %s", page_url, status)
            return False
        markdown = extract_content_from_html(self.br.get_html(), str(page_url))

        if markdown:
            output_file.open("w").write(markdown)
        else:
            logger.warning("No markdown was extracted.")

        return True

    def load_index_page(self) -> bool:
        """
        Loads the index page defined by self.base_url

        Returns:
            bool: True if the site was successfully loaded, else False.
        """
        tries = 3
        delay = self.br.seconds_before_processing_page
        for i in range(tries):
            try:
                self.index_status = self.br.load_page(self.base_url, delay)
                logger.info("Loaded index page")
                return True
            except (InvalidSessionIdException, WebDriverException) as e:
                logger.error("Failed when loading page: %s", self.base_url)
                delay *= 2
                if i == tries - 1:
                    logger.exception(e)
                    self.index_status = PageState.UNKNOWN_ERROR
                    return False
        return False

    def crawl(self) -> None:
        try:
            logger.info("Starting the crawl from %s", self.base_url)
            self.crawl_stat_collector.start()

            # Do this in crawl(); This creates the rows in the database
            website = get_website(self.base_url)
            self.db_websitecrawl.website_id = website.id

            # pylint: disable=no-member
            with SessionLocal.begin() as session:
                session.add(self.db_websitecrawl)

            logger.info("Loading page...")
            if not self.load_index_page():
                logger.warning("Failed to load index page %s", self.base_url)
                return

            if Config().ALLOW_SCREENSHOTS:
                png_bytes = self.br.get_screenshot()
                did =  self.dump_id
                self.dump_id += 1
                (self.output_path / f"{did}_index.png").write_bytes(png_bytes)

            self.crawl_stat_collector.page_loaded()
            if self.index_status not in (PageState.OK, PageState.REDIRECT):
                logger.warning(
                    "Failed to load index page %s. State %s", self.base_url, self.index_status
                )
                self.states.add(State.INDEX_LOAD_FAILED)
                return
            # |> index_status == PageState.OK or REDIRECT

            did = self.dump_id
            self.dump_id += 1
            self.br.dump_html(self.output_path, f"{did}_index")

            if not self.navigator.domain_matches(self.br.current_url):
                logger.warning(
                    "Index page %s redirected us to a different domain %s. Aborting crawl",
                    self.base_url,
                    self.br.current_url,
                )
                self.index_redirect_url = self.br.current_url
                self.states.add(State.INDEX_DOMAIN_REDIRECT)
                return

            # Try to detect the language of the website
            try:
                self.real_lang_code, self.lang = self.setup_language()
            except NoLanguageDetectedException as e:
                self.states.add(State.NO_LANGUAGE_DETECTED)
                logger.error(e)
                return
            except UnsupportedLanguageException as e:
                self.states.add(State.UNSUPPORTED_LANGUAGE)
                logger.error(e)
                return
            except pycld2.error as e:
                logger.error(e)
                self.states.add(State.NO_LANGUAGE_DETECTED)
                return

            self._process_site(self.base_url, PageType.INDEX, 0.0)
            self.crawl_stat_collector.page_loaded()

            # Print links in order of visit (see self.navigator.sorting_key)
            logger.info("Interesting links on this page:")
            for link in list(reversed(self.navigator.links))[:16]:
                logger.info("\t%s", link.url)

            run_newsletter_first = Config().NEWSLETTER_FIRST

            if run_newsletter_first:
                logger.info("Processing forms on the current page first (newsletter first)...")
                self.categorize_forms_on_current_page()
                self.process_newsletter_registration()

            logging.info("Checking found links via navigator...")
            # This iterator goes in reverse over self.navigator.links
            for url, page_type, score in self.navigator:
                logger.info("Loading page %s of type %s (score: %.4f)", url, page_type.name, score)

                status = self.br.load_page(url)
                logger.info("Loaded page %s (dump_id: %d)", url, self.dump_id)

                did = self.dump_id
                self.dump_id += 1

                # store screenshot
                if Config().ALLOW_SCREENSHOTS:
                    png_bytes = self.br.get_screenshot()
                    (self.output_path / f"{did}_{page_type.name.lower()}.png").write_bytes(png_bytes)

                self.crawl_stat_collector.page_loaded()

                if status == PageState.OK:
                    if page_type == PageType.LOGIN:
                        self.login_url = url
                        self.states.add(State.LOGIN_PAGE_FOUND)
                    elif page_type == PageType.REGISTER:
                        self.states.add(State.REGISTER_PAGE_FOUND)
                    elif page_type == PageType.SUSPICIOUS:
                        self.states.add(State.SUSPICIOUS_PAGE_FOUND)
                    elif page_type == PageType.NEWSLETTER and self.newsletter_registered:
                        # Skip already registered newsletter pages
                        continue

                    self._process_site(url, page_type, score)
                else:
                    logger.info("Page is not OK: %s as it is %s", url, status.name)

            # Processes the newsletter registration, if applicable
            if not run_newsletter_first and State.REGISTER_FORM_FOUND not in self.states:
                self.states.add(State.REGISTER_FORM_NOT_FOUND)
                self.process_newsletter_registration()

            if not Config().COLLECT_LEGAL_TEXTS:
                # Forms only: search and popular paths below only serve PP/TC discovery
                return

            # Search if configured
            if Config().USE_SEARCH.lower() == "always" or (
                not self.has_pp() and Config().USE_SEARCH.lower() == "missing"
            ):
                self.search(KeywordType.POLICY, PageType.POLICY)

            if Config().USE_SEARCH.lower() == "always" or (
                not self.has_tc() and Config().USE_SEARCH.lower() == "missing"
            ):
                self.search(KeywordType.TERMS, PageType.TERMS)

            # Try popular paths if no PP/TC was found
            if not self.has_pp():
                for path in Config().POPULAR_PP_PATHS.split(",") + self.lang.get_popular_paths(
                    KeywordType.POPULAR_PP_PATH
                ):
                    url = URL.from_text(str(self.base_url) + "/" + path)
                    logger.info("Trying popular path %s", url)

                    status = self.br.load_page(url)
                    logger.info("Loaded page %s", url)

                    if status == PageState.OK:
                        self.crawl_stat_collector.page_loaded()
                        self._process_site(
                            url=url,
                            page_type=PageType.POLICY,
                            score=0.0,
                            is_popular=True,
                            consideration_basis=ConsiderationBasis.POPULAR,
                        )

                    if self.has_pp():
                        break

            if not self.has_tc():
                for path in Config().POPULAR_TC_PATHS.split(",") + self.lang.get_popular_paths(
                    KeywordType.POPULAR_TC_PATH
                ):
                    url = URL.from_text(str(self.base_url) + "/" + path)
                    logger.info("Trying popular path %s", url)

                    status = self.br.load_page(url)
                    logger.info("Loaded page %s", url)

                    if status == PageState.OK:
                        self.crawl_stat_collector.page_loaded()
                        self._process_site(
                            url=url,
                            page_type=PageType.TERMS,
                            score=0.0,
                            is_popular=True,
                            consideration_basis=ConsiderationBasis.POPULAR,
                        )
                    if self.has_tc():
                        break
        except (WebDriverException, TimeoutError, InvalidSessionIdException, HTTPError) as e:
            # This is catched as else we abort the crawl, WebDriverExceptions only indicate an issue
            # with the current website
            # Throw WebsiteException to not set 'ended_at'
            raise WebsiteException(e)
        finally:
            self.crawl_stat_collector.stop()
            logger.info("Finished crawl of %s:%s", self.base_url, self.crawl_stat_collector)

    def process_newsletter_registration(self) -> None:
        """
        If no registration form was found, but a newsletter URL is known, try to register there.
        """
        if not Config().COLLECT_LEGAL_TEXTS and not Config().CREATE_ACCOUNT:
            # Forms only without submitting: reloading the page would only serve the submission
            return

        if (
                self.newsletter_url
                and self.navigator.domain_legal(self.newsletter_url)
            ):

            # Check if newsletter url is forbidden
            visit = True
            for x in Config().FORBIDDEN_NEWSLETTER_DOMAINS.split(","):
                if x.strip() in str(self.newsletter_url):
                    visit = False
                    break

            if not visit:
                logger.info(
                        "Not visiting newsletter page as it's in our forbidden list %s",
                        self.newsletter_url,
                    )
            else:
                logger.info("Loading stored newsletter page %s", self.newsletter_url)
                status = self.br.load_page(self.newsletter_url)
                logger.info("Loaded newsletter url %s", self.newsletter_url)
                self.crawl_stat_collector.page_loaded()
                if status == PageState.OK:
                    try:
                        self._process_forms(try_newsletter=True)
                        self.newsletter_registered = True
                    except WebDriverException:
                        logger.exception(
                                f"Unknown Webdriver error occurred while processing forms: {self.newsletter_url.to_text()}"
                            )
        else:
            logging.info("No newsletter URL known or registration form already found; skipping newsletter processing. (in_states: %s, newsletter_url: %s)", self.states, self.newsletter_url)


    def has_pp(self) -> bool:
        if len(self.pp_urls) == 0:
            return False

        for p in self.pp_urls:
            if p.considered:
                return True
        return False

    def has_tc(self) -> bool:
        if len(self.tc_urls) == 0:
            return False

        for t in self.tc_urls:
            if t.considered:
                return True
        return False

    def search(self, kw_type: KeywordType, pagetype: PageType) -> None:
        """
        Searches for the given kw_type on the search provider
        """
        policy_in_native = self.lang.get_keywords(kw_type)[0].text

        site = tldextract.extract(str(self.base_url))
        searchterm = f"site:{site.domain}.{site.suffix} {policy_in_native}"

        logger.info('SEARCH: [lang: %s] Doing a request for "%s"', self.real_lang_code, searchterm)
        try:
            self.crawl_stat_collector.search_performed()

            if self.search_provider == "startpage.com":
                search_url = (
                    f"https://startpage.com/do/search?query={urllib.parse.quote(searchterm)}"
                )
            elif self.search_provider == "duckduckgo.com":
                search_url = f"https://duckduckgo.com/?q={urllib.parse.quote(searchterm)}&ia=web"
            else:
                raise CrawlerException("Unknown search provider: " + self.search_provider)

            surl = URL.from_text(search_url)
            status = self.br.load_page(surl)

            if status is PageState.OK:
                self._process_site(surl, PageType.INDEX, 0.0, is_search=True)
                for url, page_type, score in list(self.navigator)[:4]:
                    istatus = self.br.load_page(url)

                    if istatus is PageState.OK and page_type == pagetype:
                        self._process_site(url, page_type, score, is_search=True)
                    else:
                        logger.info(
                            "SEARCH: Found url is no match for type %s: %s [status: %s, pagetype: %s]",
                            pagetype.name,
                            url,
                            istatus,
                            page_type.name,
                        )

                    # Abort search if we already have what we searched for
                    if pagetype == PageType.POLICY and self.has_pp():
                        return
                    if pagetype == PageType.TERMS and self.has_tc():
                        return

        except Exception as e:
            logger.error("Unable to search %s", searchterm)
            logger.error(e)

    def validation_crawl(self, pp_url: URL, tc_url: URL, prev_lang_code: str) -> None:
        logger.info("Doing a cached crawl.")

        website = get_website(self.base_url)
        self.db_websitecrawl.website = website

        self.real_lang_code = prev_lang_code
        self.lang = Language.get(Config().language_dir, self.real_lang_code)

        # check PP link
        status = self.br.load_page(pp_url)

        if status == PageState.OK:
            self._process_site(
                pp_url, PageType.POLICY, score=None, consideration_basis=ConsiderationBasis.CACHED
            )
        else:
            logger.info("Page is not OK: %s as it is %s", pp_url, status.name)
            self.crawl()
            return

        # check TC link
        status = self.br.load_page(tc_url)
        if status == PageState.OK:
            self._process_site(
                tc_url, PageType.TERMS, score=None, consideration_basis=ConsiderationBasis.CACHED
            )
        else:
            logger.info("Page is not OK: %s as it is %s", pp_url, status.name)
            self.crawl()
            return

        self.db_websitecrawl.validation_run = True
        store(self.db_websitecrawl)

    def _process_site(
        self,
        url: URL,
        page_type: PageType,
        score: Optional[float],
        is_popular: bool = False,
        consideration_basis: ConsiderationBasis = ConsiderationBasis.NONE,
        is_search: bool = False,
    ) -> None:
        # to prevent recursive crawling
        if consideration_basis != ConsiderationBasis.CACHED:
            if self.navigator.domain_matches(url) or is_search:
                logger.info("Processing links")
                self._process_links(is_search)
        # Classify this page
        if is_popular:
            consideration_basis += ConsiderationBasis.POPULAR

        if is_search:
            consideration_basis = ConsiderationBasis.SEARCH

        if score is None:
            score = 0.0

        html_str = self.br.get_html()
        found_email_addresses = get_all_emails(html_str)

        if not Config().COLLECT_LEGAL_TEXTS:
            # Forms only: no text extraction, PDF download or PP/TC classification
            self._finish_page(url, page_type, consideration_basis, found_email_addresses)
            return

        # Indicates that the current page is a pdf
        is_pdf = False

        try:
            markdown: Optional[str] = None

            # PDFs are downloaded usually, so we simply check if the timestamp
            # of the most recent downloaded file is close enough and assume this
            # is the pdf that we just visited
            most_recent_downloaded: Optional[str] = None

            if str(url).strip().lower().endswith(".pdf") or str(
                self.br.current_url
            ).strip().lower().endswith(".pdf"):
                is_pdf = True

                max_wait = 60
                waited = 0
                while len(glob.glob(self.br.temp_download_directory.name + "/*.crdownload")) > 0:
                    time.sleep(1)
                    waited += 1
                    if waited > max_wait:
                        break

                files = glob.glob(self.br.temp_download_directory.name + "/*.pdf")

                if len(files) == 0:
                    logger.error("Did not get pdf from: %s", url)
                    return

                # If the file is less than 5 seconds old we assume it's the file
                current_time = time.time()
                most_recent_downloaded = max(files, key=os.path.getctime)

                if (
                    current_time - os.path.getctime(most_recent_downloaded)
                    < 5 + self.br.seconds_before_processing_page
                ):
                    try:
                        markdown = extract_text_from_pdf(most_recent_downloaded)
                    except Exception as e:
                        logger.exception(e)
                        markdown = f"Failed due to {e}"
                        logger.error("Failed to get text from pdf at %s", most_recent_downloaded)
                else:
                    markdown = f"Unable to download pdf: {str(url)}"
                    logger.error(
                        "Unable to download pdf %s. See log for more info as latest file is too old.",
                        url,
                    )
            else:
                markdown = extract_content_from_html(html_str, str(url))

            if markdown is None:
                logging.warning("Unable to get markdown from site: %s", url)
                markdown = f"Unable to get markdown from site {str(url)}"

            # Extract all emails
            text_without_formatting = extract_text_only_from_html(html_str)

            if text_without_formatting is not None:
                found_email_addresses = found_email_addresses.union(
                    get_all_emails(text_without_formatting)
                )

            probability = -1.0

            # If this url is considered to be the type in 'page_type'
            considered: Optional[bool] = None

            if consideration_basis == ConsiderationBasis.CACHED:
                considered = True

            initial_page_type = page_type

            if page_type == PageType.TERMS:
                # Check if content is too short; Store consideration_basis as TOO_SHORT_TEXT for this link
                if len(markdown) < Config().MIN_CHARS_DOCUMENT:
                    self.store_terms(
                        ConsiderationBasis.TOO_SHORT_TEXT,
                        considered=False,
                        is_pdf=is_pdf,
                        markdown=markdown,
                        most_recent=most_recent_downloaded,
                        page_type=page_type,
                        score=score,
                        url=url,
                        probability=None,
                    )
                    return

                if Config().USE_CLASSIFIER:
                    assert self.classifier is not None  # Constructor provides this

                    start = time.time()
                    class_result = self.classifier.is_terms_conditions(markdown)
                    end = time.time()

                    if not class_result.result:
                        page_type = PageType.OTHER
                        logger.info(
                            "Not a TC due to CLASSIFIER: %s",
                            url,
                        )

                    # We always consider the result of the classifier
                    consideration_basis += ConsiderationBasis.CLASSIFIER
                    considered = class_result.result
                    if class_result.probability:
                        probability = class_result.probability

                    # Store some crawling statistics
                    if class_result.error:
                        self.crawl_stat_collector.error()
                    self.crawl_stat_collector.classified(end - start)
                else:  # no classifier
                    if consideration_basis != ConsiderationBasis.CACHED:
                        considered = score >= Config().MIN_SCORE_KEYWORD_CLASSIFY_TC
                        consideration_basis += ConsiderationBasis.KEYWORD_MATCHING

            if page_type == PageType.POLICY:
                # Check if content is long enough
                if len(markdown) < Config().MIN_CHARS_DOCUMENT:
                    self.store_pp(
                        ConsiderationBasis.TOO_SHORT_TEXT,
                        considered=False,
                        is_pdf=is_pdf,
                        markdown=markdown,
                        most_recent=most_recent_downloaded,
                        page_type=page_type,
                        score=score,
                        url=url,
                        probability=probability,
                    )
                    return

                # Calculate classification
                if Config().USE_CLASSIFIER:
                    assert self.classifier is not None  # Constructor provides this

                    start = time.time()
                    class_result = self.classifier.is_privacy_policy(markdown)
                    end = time.time()

                    # Only change page_type if score is too low
                    if score < Config().MIN_SCORE_KEYWORD_CLASSIFY_PP:
                        if not class_result.result:
                            page_type = PageType.OTHER
                            logger.info(
                                "Not a PP due to CLASSIFIER: %s",
                                url,
                            )
                        consideration_basis += ConsiderationBasis.CLASSIFIER

                    # Always take the result from the classifier as the consideration_basis
                    consideration_basis += ConsiderationBasis.CLASSIFIER
                    considered = class_result.result
                    if class_result.probability:
                        probability = class_result.probability

                    # Store some crawling statistics
                    if class_result.error:
                        self.crawl_stat_collector.error()
                    self.crawl_stat_collector.classified(end - start)
                else:  # no classifier
                    if consideration_basis != ConsiderationBasis.CACHED:
                        considered = score >= Config().MIN_SCORE_KEYWORD_CLASSIFY_PP
                        consideration_basis += ConsiderationBasis.KEYWORD_MATCHING

            if page_type == PageType.US_PN:
                considered = (
                    score >= Config().MIN_SCORE_KEYWORD_CLASSIFY_PP
                )  # This is intentional as US_PN have a lower score and TCs too

            if page_type == PageType.GDPR:
                considered = score >= Config().MIN_SCORE_KEYWORD_CLASSIFY_PP

            # Store the link if it has a specific page_type
            if PageType.TERMS in (page_type, initial_page_type):
                self.store_terms(
                    consideration_basis,
                    considered,
                    is_pdf,
                    markdown,
                    most_recent_downloaded,
                    page_type,
                    score,
                    url,
                    probability=probability,
                )
                return

            if PageType.POLICY in (page_type, initial_page_type):
                self.store_pp(
                    consideration_basis,
                    considered,
                    is_pdf,
                    markdown,
                    most_recent_downloaded,
                    page_type,
                    probability,
                    score,
                    url,
                )
                return

            if PageType.US_PN in (page_type, initial_page_type):
                logger.info("US Privacy Notice found at %s", url)

                # pylint: disable=no-member
                with SessionLocal.begin() as session:
                    hash_str = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
                    db_content = get_urlcontent(hash_str, markdown)
                    db_url = DBURL(url=str(url), content=db_content)
                    crawl_has_us_pn = CrawlToUSPrivacyNotice(
                        us_pn_url=db_url,
                        us_pn_kw_score=score,
                        consideration_basis=consideration_basis,
                        considered=considered,
                        website_crawl_id=self.db_websitecrawl.id,
                    )
                    session.add(crawl_has_us_pn)

                if is_pdf:
                    assert most_recent_downloaded

                    shutil.move(
                        most_recent_downloaded,
                        self.output_path / f"us_privacy_notice_{db_url.id}.pdf",
                    )
                else:
                    dumped_fn = self.br.dump_html(self.output_path, "us_privacy_notice")
                    self.dumped_htmls.append(dumped_fn)

                if Config().STORE_MARKDOWN:
                    (self.output_path / f"url_{db_url.id}_US_privacy_notice.md").open("w").write(
                        markdown
                    )

                self.states.add(State.US_PN_CONTENT_FOUND)
                return

            if PageType.GDPR in (page_type, initial_page_type):
                logger.info("GDPR found at %s", url)

                if is_pdf:
                    assert most_recent_downloaded

                    shutil.move(
                        most_recent_downloaded, self.output_path / f"url_{self.next_gdpr_id}"
                    )
                else:
                    dumped_fn = self.br.dump_html(self.output_path, f"url_{self.next_gdpr_id}_gdpr")
                    self.dumped_htmls.append(dumped_fn)

                if Config().STORE_MARKDOWN:
                    (self.output_path / f"url_{self.next_gdpr_id}_gdpr.md").open("w").write(
                        markdown
                    )

                self.states.add(State.GDPR_CONTENT_FOUND)

        except ClassificationException as e:
            logger.error("Unable to classify %s: %s", url, e)
            self.crawl_stat_collector.error()
            page_type = PageType.OTHER
        finally:
            self._finish_page(url, page_type, consideration_basis, found_email_addresses)

    def _finish_page(
        self,
        url: URL,
        page_type: PageType,
        consideration_basis: ConsiderationBasis,
        found_email_addresses: set[tuple[str, str]],
    ) -> None:
        logger.info(
            "Finished processing page %s and classified as %s on basis %s",
            url,
            page_type.name,
            consideration_basis,
        )

        # Now that we know the page_type
        for address_local_part, domain in found_email_addresses:
            self.emails.append((address_local_part, domain, page_type.name, str(url)))

        try:
            self._process_forms()
        except WebDriverException:
            logger.exception(
                "Unknown Webdriver error occurred while processing forms on %s", url.to_text()
            )

    def store_pp(
        self,
        consideration_basis: ConsiderationBasis,
        considered: Optional[bool],
        is_pdf: bool,
        markdown: str,
        most_recent: Optional[str],
        page_type: PageType,
        probability: Optional[float],
        score: float,
        url: URL,
    ) -> None:
        if page_type == PageType.POLICY:
            logger.info("Policy page found at %s", url)
        else:
            logger.info("Page that is not considered a PP found at %s", url)
        hash_str = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        db_content = get_urlcontent(hash_str, markdown)
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            db_url = DBURL(url=str(url).replace("\x00", ""), content=db_content)

            session.add(db_url)
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            crawl_has_pp = CrawlToPrivacyPolicy(
                pp_url_id=db_url.id,
                pp_kw_score=score,
                consideration_basis=consideration_basis,
                considered=considered,
                pp_probability=probability,
                website_crawl_id=self.db_websitecrawl.id,
            )
            session.add(crawl_has_pp)
        if Config().STORE_MARKDOWN:
            (self.output_path / f"privacy_policy_{db_url.id}.md").open("w").write(markdown)
        if is_pdf:
            assert most_recent

            shutil.move(most_recent, self.output_path / f"privacy_policy_{db_url.id}.pdf")
        else:
            dumped_fn = self.br.dump_html(self.output_path, f"privacy_policy_{db_url.id}")
            self.dumped_htmls.append(dumped_fn)
        self.states.add(State.POLICY_CONTENT_FOUND)
        self.pp_urls.append(crawl_has_pp)

    def store_terms(
        self,
        consideration_basis: ConsiderationBasis,
        considered: Optional[bool],
        is_pdf: bool,
        markdown: str,
        most_recent: Optional[str],
        page_type: PageType,
        score: float,
        url: URL,
        probability: Optional[float],
    ) -> None:
        if page_type == PageType.TERMS:
            logger.info("TC page found at %s", url)
        else:
            logger.info("Page that is not considered a TC found at %s", url)
        db_url: DBURL
        hash_str = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        db_content = get_urlcontent(hash_str, markdown)
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            db_url = DBURL(url=str(url).replace("\x00", ""), content=db_content)

            session.add(db_url)
        with SessionLocal.begin() as session:
            crawl_has_tc = CrawlToTermsAndConditions(
                tc_url_id=db_url.id,
                tc_kw_score=score,
                consideration_basis=consideration_basis,
                considered=considered,
                tc_probability=probability,
                website_crawl_id=self.db_websitecrawl.id,
            )
            session.add(crawl_has_tc)
        if Config().STORE_MARKDOWN:
            (self.output_path / f"terms_of_use_{db_url.id}.md").open("w").write(markdown)
        if is_pdf:
            assert most_recent

            shutil.move(most_recent, self.output_path / f"terms_of_use_{db_url.id}.pdf")
        else:
            html_fn = self.br.dump_html(self.output_path, f"terms_of_use_{db_url.id}")
            self.dumped_htmls.append(html_fn)
        self.states.add(State.TERMS_CONTENT_FOUND)
        self.tc_urls.append(crawl_has_tc)

    def _process_links(self, remove_startpage_results: bool = False) -> None:
        # TODO also detect clickable buttons with same keywords
        # we can use selenium 4.0.0 devtools
        # https://stackoverflow.com/questions/34204449/access-geteventlisteners-from-chrome-webdriver-python

        logger.info("Processing links found on page using keyword matching")

        try:
            links = self.br.get_links()
            logger.info("Found %s links", len(links))
        except WebDriverException:
            logger.warning("Processing links on page %s failed.", self.br.current_url.to_text())
            return

        if remove_startpage_results:

            def filter_func(x: LinkTuple) -> bool:
                return (self.search_provider + "/") not in x.url.asText()

            links = list(filter(filter_func, links))

        # Classify found links and also follow them
        for link in links:
            possible_types = keyword_classify(
                page_type_keyword_map,
                link.texts,
                match_keywords,
                self.lang,
                Config().MIN_KW_MATCH_LEN,
            )
            if len(possible_types) == 0:
                possible_types = [(PageType.OTHER, 1)]
            for type, score in possible_types:
                self.navigator.add(UrlMatch(link.url, type, score))
        logger.info("Finished processing and classifying links")

    def _process_forms(self, try_newsletter: bool = False) -> None:
        """

        try_newsletter: bool
            Try to subscribe to the newsletter nevertheless of other forms found.
        """
        logger.info("Looking for form found on page %s", self.br.current_url)

        by_type = self.categorize_forms_on_current_page()

        # Process depending on which types of forms were found

        # Register account if possible
        if State.REGISTER_FORM_FOUND not in self.states and by_type[FormType.REGISTER]:
            if len(by_type[FormType.REGISTER]) > 1:
                logger.info("Multiple registration forms found")
                self.states.add(State.MULTIPLE_REGISTRATION_FORMS)

            best_form = max(by_type[FormType.REGISTER], key=lambda x: sum(x.input_counts.values()))
            if Config().CREATE_ACCOUNT:
                self._process_form(best_form)

        # Consider subscribing to newsletter
        if ((try_newsletter and not self.newsletter_registered) or (State.REGISTER_FORM_NOT_FOUND in self.states)) and by_type[FormType.NEWSLETTER]:
            best_form = max(
                by_type[FormType.NEWSLETTER], key=lambda x: sum(x.input_counts.values())
            )
            if Config().CREATE_ACCOUNT:
                self._process_form(best_form)
        logger.info("Finished processing forms.")

    def categorize_forms_on_current_page(self) -> defaultdict[FormType, list[FormBS]]:
        by_type: defaultdict[FormType, list[FormBS]] = defaultdict(list)

        for f in cast(EnfbotsBrowser, self.br).find_forms(self.lang):
            logger.debug("Found a form of type %s", f.type.name)
            by_type[f.type].append(f)

        if by_type[FormType.NEWSLETTER] and self.newsletter_url is None:
            self.newsletter_url = self.br.current_url
            logger.info(
                "Detected newsletter form. Storing it for later usage. URL: %s", self.newsletter_url
            )

        return by_type

    def _process_form(self, best_form: FormBS) -> None:
        if best_form.type == FormType.NEWSLETTER:
            found_state, success_state, fail_state, error_state = _newsletter_map
        else:
            found_state, success_state, fail_state, error_state = _register_map

        self.states.add(found_state)

        if self.newsletter_registered and best_form.type is FormType.NEWSLETTER:
            logger.info(
                "Skipping newsletter registration as we are already registered."
            )
            return

        logger.info("Detected a form of type %s. Will try to submit.", best_form.type.name)
        logger.info(
            "Detected inputs: %s",
            [
                inp.estimated_type.name
                for inp in best_form.inputs
                if inp.direct_type != InputType.HIDDEN
            ],
        )

        try:
            reg_form = FormSelenium.from_bs(cast(EnfbotsBrowser, self.br), best_form)

            # The action attribute of the registration form is the form-handler, which can be a URL or javascript
            form_handler = str(reg_form.action)

            is_insecure: Optional[bool]
            if form_handler.strip().startswith("http://"):
                is_insecure = True
            elif form_handler.strip().startswith("https://"):
                is_insecure = False
            else:
                is_insecure = None

        except NoSuchElementException:
            self.states.add(State.FORM_ID_MISMATCH)
            logger.exception(
                "Selenium and BS forms could not be matched. Likely due to an unexpected reload of the page"
            )
            return

        reg_processor = RegProcessor(
            cast(EnfbotsBrowser, self.br),
            self.lang,
            self.credentials if best_form.type is not FormType.NEWSLETTER else self.newsletter_credentials,
            self.output_path,
            len(self.reg_processors),
            is_insecure,
        )
        self.reg_processors.append(reg_processor)

        # load form state and fill what is already in the forms
        try:
            logging.info("Handling registration form submission for type %s. (email: %s)", best_form.type.name, reg_processor.credentials.email)
            self.reg_status = reg_processor.handle_registration(reg_form)
            if Config().AWAIT_VERIFY_EMAIL or (
                Config().VERIFY_EMAIL_ON_REQUEST
                and RegistrationStatus.VERIFICATION_CODE_REQUESTED in reg_processor.states
            ):
                self.email_verification_status = reg_processor.verify_email()
        except StaleElementReferenceException:
            logger.exception("Probably an attempt to fill form before full load")
            self.states.add(error_state)
            self.states.add(State.FORM_STALE_ERROR)
        except WebDriverException:
            logger.exception("Unknown exception happened while submitting the form")
            self.states.add(State.FORM_UNKNOWN_ERROR)

    def setup_language(self) -> Tuple[str, Language]:
        """
        Detects the language of the current website and returns the lang_code and the associated Language.
        :throws:
        """
        lang_code = self._setup_language()
        return (lang_code, Language.get(Config().language_dir, lang_code))

    def _setup_language(self) -> str:
        lang_code = self._extract_language(Config().MIN_CONFIDENCE_LANGUAGE_DETECTION)
        if not lang_code:
            raise NoLanguageDetectedException(
                f"No language found for this website: {str(self.br.current_url)}"
            )
        if lang_code and self._language_supported(lang_code):
            logger.info("Detected language as: %s", lang_code)
            return lang_code

        self.states.add(State.UNSUPPORTED_LANGUAGE)
        raise UnsupportedLanguageException(f"Page language is not supported: {lang_code}")

    @staticmethod
    def _language_supported(lang: str) -> bool:
        return lang in get_supported_languages()

    def _extract_language(self, min_confidence: float) -> Optional[str]:
        """
        Tries to extract the language from the current website.
        :param min_confidence: minimal confidence to accept it as the language
        :return: Language code of the detected language or None
        """
        html_content = self.br.get_html()

        # filter out numbers as they have no influence on a language
        html_content = "".join([i for i in html_content if not i.isdigit()])

        content = extract_text_from_html(
            BeautifulSoup(html_content, "html.parser", multi_valued_attributes=None)
        )

        # Remove bad characters because of https://github.com/aboSamoor/polyglot/issues/71
        content = remove_bad_chars_for_polyglot(content)

        # Remove invalid utf-8 characters
        content = content.encode("utf-8", "ignore").decode("utf-8", "ignore")

        # First try to get the language with polyglot which is very fast. Else
        # we use detect_language which uses gcld3 (slower but better)
        if content:
            try:
                lang_detector = Detector(content, quiet=True).language
                if lang_detector.confidence > min_confidence:
                    return str(lang_detector.locale)
            except UnknownLanguage:
                pass
        else:
            logger.warning("No content to extract the language on %s", self.br.current_url)
            return None

        return detect_language(content)

    def get_db_entity(self, job: Optional[DBJob] = None) -> Tuple[str, DBWebsiteCrawl]:
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            session.add(self.db_websitecrawl)

            if job:
                self.db_websitecrawl.job_id = job.id

            url = self.base_url.to_text()

            self.db_websitecrawl.lang = self.real_lang_code
            self.db_websitecrawl.index_status = self.index_status if self.index_status else None
            self.db_websitecrawl.newsletter_url = (
                self.newsletter_url.to_text() if self.newsletter_url else None
            )

            if Config().CREATE_ACCOUNT:
                self.db_websitecrawl.username = self.credentials.username
                self.db_websitecrawl.password = self.credentials.password
                self.db_websitecrawl.email = self.credentials.email

            if self.newsletter_registered:
                self.db_websitecrawl.newsletter_email = self.newsletter_credentials.email
                self.db_websitecrawl.newsletter_username = self.newsletter_credentials.username
                self.db_websitecrawl.newsletter_password = self.newsletter_credentials.password

            self.db_websitecrawl.dump_uuid = self.dump_uuid

            if len(self.db_websitecrawl.tc_urls) > 0:
                logger.info("FOUND TCs:")
                for x in self.db_websitecrawl.tc_urls:
                    logger.info(
                        "\t[considered: %s, basis: %s]: %s, content: [%s]",
                        x.considered,
                        x.consideration_basis,
                        x.tc_url.url,
                        x.tc_url.content.content[:20].replace("\n", ""),
                    )
            else:
                logger.info("FOUND no TCs")

            if len(self.db_websitecrawl.pp_urls) > 0:
                logger.info("FOUND PPs:")
                for y in self.db_websitecrawl.pp_urls:
                    logger.info(
                        "\t[considered: %s, basis: %s]: %s, content [%s]",
                        y.considered,
                        y.consideration_basis,
                        y.pp_url.url,
                        y.pp_url.content.content[:20].replace("\n", ""),
                    )
            else:
                logger.info("FOUND no PPs")

            if len(self.db_websitecrawl.us_pn_urls) > 0:
                logger.info("FOUND US PNs:")
                for z in self.db_websitecrawl.us_pn_urls:
                    logger.info(
                        "[considered: %s, basis: %s]: %s, content [%s]",
                        z.considered,
                        z.consideration_basis,
                        z.us_pn_url.url,
                        z.us_pn_url.content.content[:20].replace("\n", ""),
                    )
            else:
                logger.info("FOUND no US PNs")

            if len(self.emails) > 0:
                logger.info("Found emails: ")
                for address_local, address_domain, page_type, url in self.emails:
                    logger.info(
                        "\tEmail %s@%s on pagetype %s (%s)",
                        address_local,
                        address_domain,
                        page_type,
                        url,
                    )
                self.db_websitecrawl.found_emails = json.dumps(self.emails)
            # store some additional info of the first encountered form
            if self.reg_processors:
                # check the last one
                r = self.reg_processors[-1]
                self.db_websitecrawl.reg_status = r.registration_status
                self.db_websitecrawl.email_verification_status = r.email_verification_status
                self.db_websitecrawl.reg_url = r.base_url.to_text() if r.base_url else None
            else:
                self.db_websitecrawl.reg_status = RegistrationStatus.FAILURE_NOT_FOUND
                self.db_websitecrawl.email_verification_status = EmailVerificationStatus.UNKNOWN

            states = [s.name for s in self.states]
            self.db_websitecrawl.states = json.dumps(states)

            for cookie in cast(EnfbotsBrowser, self.br).cookie_tracker:
                db_cookie = database.DBCookie(
                    name=cookie.name,
                    value=cookie.value,
                    domain=cookie.domain,
                    path=cookie.path,
                    exp=cookie.expiry,
                    is_secure=cookie.secure,
                    is_httponly=cookie.http_only,
                    same_site=cookie.same_site,
                )
                self.db_websitecrawl.cookies.append(db_cookie)

            forms = [processor.get_db_form() for processor in self.reg_processors]
            for f in forms:
                session.add(f)
                f.website_crawl = self.db_websitecrawl
            self.db_websitecrawl.forms = forms
            return url, self.db_websitecrawl


page_type_keyword_map = {
    PageType.REGISTER: KeywordType.REGISTRATION,
    PageType.LOGIN: KeywordType.LOGIN,
    PageType.POLICY: KeywordType.POLICY,
    PageType.TERMS: KeywordType.TERMS,
    PageType.US_PN: KeywordType.US_PN,
    PageType.GDPR: KeywordType.GDPR,
    PageType.NEWSLETTER: KeywordType.NEWSLETTER,
}


class NoLanguageDetectedException(Exception):
    """
    Indicates that our detection was unable to find a language for the content on the INDEX page.
    """


class UnsupportedLanguageException(Exception):
    pass


class UrlMatch(NamedTuple):
    url: URL
    type: PageType
    score: float

    def __hash__(self) -> int:
        return hash((self.url, self.type))

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, UrlMatch) and self.url == other.url and self.type == other.type
