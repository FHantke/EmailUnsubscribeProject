from __future__ import annotations

import datetime
import logging
import re
import time
from typing import Optional, cast, Any, List, Dict
from email.utils import getaddresses

import requests
from hyperlink import URL, URLParseError
from lxml import etree

# pylint: disable=no-name-in-module
from lxml.etree import _Element, _ElementUnicodeResult

try:
    from polyglot.detect import Detector
    from polyglot.detect.base import UnknownLanguage
except ImportError:
    pass

from tldextract import tldextract

# Imports from the enfbots library
from enfbots_crawler.languages import KeywordType, Language, LocaleNotFoundException

# Imports from this crawler implementation
from enfbots_crawler.database import MailType, DBWebsiteCrawl, SessionLocal
from enfbots_crawler import Config
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.text_lib import extract_content_from_html
from enfbots_crawler.text_helper import remove_bad_chars_for_polyglot

logger = logging.getLogger("enfbots_crawler")


# https://stackoverflow.com/questions/6038061/regular-expression-to-find-urls-within-a-string
URL_REGEX = r"((https?)://)([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:/~+#-]*[\w@?^=%&/~+#-])?"
CODE_REGEX = r"(code|token|.*OTP[^0-9a-f]*|password):?.*?\n?([0-9a-f]{4,})\s*"


class SybilException(Exception):
    pass


class EmailParsingException(Exception):
    pass


class EmptyException(Exception):
    pass


class Mail:
    def __init__(
        self,
        intid: Optional[int],
        mail_id: str,
        subject: str,
        from_addr: str,
        from_name: Optional[str],
        to_addr: str,
        to_name: Optional[str],
        body: str,
        headers: Optional[str],
        date: datetime.datetime | None,
        domain: Optional[str] = None,
        language: Optional[str] = None,
        skip_processing: bool = False,
    ):
        self.to_name = to_name
        self.from_name = from_name
        self.from_str = from_addr
        self.from_addr = from_addr
        self.body = body.replace("\x00", "\uFFFD")
        self.headers = headers.replace("\x00", "\uFFFD") if headers else headers
        self.to_addr = to_addr
        self.subject = subject
        self.intid = intid
        self.mail_id = mail_id
        self.date = date

        try:
            self.tree = etree.HTML(self.body)
        except ValueError:
            try:
                logging.info("Failed to parse body HTML by simple method, trying .encode()")
                self.tree = etree.HTML(self.body.encode())
            except ValueError:
                logging.exception("Failed to parse body HTML")
        if language:
            self.lang = Language.get(Config().language_dir, language)
        else:
            self.lang = self._extract_language(ignore_body=True)

        self.domain = domain
        if not domain and "@" in self.from_addr:
            # problems with encoding here
            # Unicode strings with encoding declaration are not supported.
            # Please use bytes input or XML fragments without declaration.
            self.domain = tldextract.extract(self.from_addr.split("@")[1]).registered_domain

        if not skip_processing:
            self.has_code = self._has_code()
            self.is_verification = self._verification_in_subject()
            self.verification_code = self._extract_code()
            self.activation_link = self._extract_activation_link()
            self.simple_type = self._simple_classification()

    def _simple_classification(self) -> MailType:
        if not self.is_verification:
            return MailType.MARKETING
        elif self.has_code or self.activation_link:
            return MailType.SERVICING_OPT_IN
        else:
            return MailType.SERVICING_CONFIRMATION

    def _extract_language(self, ignore_body: bool = False) -> Language:
        threshold = Config().MIN_CONFIDENCE_LANGUAGE_DETECTION
        content = self.subject
        if not ignore_body:
            body = extract_content_from_html(self.body, clean=True)
            if body:
                content += " " + body

        # Remove bad characters because of https://github.com/aboSamoor/polyglot/issues/71
        content = remove_bad_chars_for_polyglot(content)

        if content:
            try:
                lang_detector = Detector(content, quiet=True).language
                mail_lang = (
                    str(lang_detector.locale) if lang_detector.confidence > threshold else "en"
                )
                ret = self._get_website_lang()
                website_lang = ret if ret else "en"

                if mail_lang == website_lang:
                    return Language.get(Config().language_dir, mail_lang)
                else:
                    return Language.get(Config().language_dir, mail_lang, second=website_lang)
            except (UnknownLanguage, LocaleNotFoundException):
                pass

        return Language.get(Config().language_dir, "en")

    def _get_website_lang(self) -> Optional[str]:
        email_addr = self.to_addr.lower()
        session = SessionLocal()
        with session.begin():
            query = session.query(DBWebsiteCrawl.lang).filter(DBWebsiteCrawl.email == email_addr)
            res = query.first()
            if res:
                return res[0]
            logger.warning(f"Website with this email addr not found: {email_addr}")
            return None

    def _verification_in_subject(self) -> bool:
        return any(
            s.text in self.subject for s in self.lang.get_keywords(KeywordType.CONFIRMATION_EMAIL)
        )

    def _has_code(self) -> bool:
        return any(
            s.text in self.body.lower()
            for s in self.lang.get_keywords(KeywordType.VERIFICATION_CODE)
        )

    def _extract_code(self) -> Optional[str]:
        """
        extract verification code via regex pattern
        :return: code
        """

        pattern = re.compile(CODE_REGEX)
        m = pattern.search(_get_text(self.tree))
        if m:
            code = m.group(2)
            if len(code) >= 4:
                return code
        return None

    def _matches_domain(self, url: URL) -> bool:
        link_domain = tldextract.extract(str(url)).registered_domain
        return link_domain == self.domain

    def _is_unsubscribe_link(self, link: _Element) -> bool:
        """Check if the text around the link talks about unsubscribing"""
        text = _to_string(link).lower()
        return any(s.text.lower() in text for s in self.lang.get_keywords(KeywordType.UNSUBSCRIBE))

    def _is_activation_link(self, link: _Element) -> bool:
        """Check if the text around the link talks about confirming"""
        text = _to_string(link).lower()
        return any(
            k.text.lower() in text for k in self.lang.get_keywords(KeywordType.CONFIRMATION_LINK)
        )

    @staticmethod
    def process_text(text: _ElementUnicodeResult, candidate_map: dict[str, _Element]) -> None:
        """
        Checks the text for potential verification links and sets
        candidate_map at key to the text element.
        """
        logging.debug("Mail process_text for activation link: " + text)
        s = str(text)
        url_regex = re.compile(URL_REGEX)
        parent = text.getparent()
        if parent is not None:
            matches = url_regex.finditer(s)
            for match in matches:
                href = match.group(0)
                try:
                    if href not in candidate_map:
                        el = etree.Element("a")
                        el.set("href", href)
                        el.set("lowprio", "true")
                        el.text = _get_text(parent)
                        candidate_map[href] = el
                except EmptyException:
                    logger.warning(f"Got no text for {href}")

    def _extract_activation_link(self) -> Optional[URL]:
        """
        extract activation link
        1. check all href tags containing keywords
        2. find links via text tags (e.g. links following text such as "activation link")
        3. find activation directly via keywords in the url of the links
        """

        # Extracts all links and check if the link contains some unsubscribe keywords
        candidates = cast(list[_Element], self.tree.xpath("//a[@href]"))
        candidate_map: dict[str, _Element] = {c.get("href", ""): c for c in candidates}

        # try to find link via text context (html)
        candidate_strings = _get_texts(self.tree)
        for string in candidate_strings:
            Mail.process_text(string, candidate_map)

        best_candidate = None
        best_score = 0
        for href, candidate in candidate_map.items():
            if not href:
                continue
            try:
                url = URL.from_text(href)
            except URLParseError:
                continue
            except ValueError:
                continue
            score = 0
            if candidate.get("lowprio"):
                score -= 1
            if self._is_unsubscribe_link(candidate):
                score = -3
            if self._is_activation_link(candidate):
                score += 3
            if self._matches_domain(url):
                score += 2
            if "http" not in url.scheme:
                score -= 100
            url_arg_len = len(
                "".join(url.path) + "".join(str(x) + str(y) for x, y in url.query) + url.fragment
            )
            if url_arg_len < 4:
                score -= 20
            if url_arg_len < 6:
                score -= 2

            if score > best_score:
                logging.debug(f"Best link {best_candidate} with score {best_score}")
                best_score = score
                best_candidate = url

        if best_candidate:
            logging.info(f"Activation link found {best_candidate}")
            return best_candidate

        return None


class Sybil:
    def __init__(self, time_format: str = "%A, %d. %B %Y %I:%M%p") -> None:
        self.base_url = Config().SYBIL_URL
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"basicToken {Config().SYBIL_AUTH_TOKEN}",
        }
        self.inbox: Optional[List[Dict[str, Any]]] = None
        self.time_format = time_format
        self.language: Optional[str] = None

    def poll(self, creds: Credentials, language: Optional[str] = None) -> list[Mail]:
        if language:
            self.language = language
        logger.info("Polling Sybil for new emails....")
        timeout_start = time.time()
        timeout = Config().EMAIL_VERIFY_TIMEOUT
        interval = Config().EMAIL_VERIFY_POLL_INTERVAL

        while time.time() < timeout_start + timeout:
            emails = self.get_emails(creds)
            if emails:
                return emails
            time.sleep(interval)
        return []

    def create_mail_address(self, creds: Credentials) -> None:
        """
        Query Sybilmail for a unique email address and put it into the credentials object
        """
        if not creds.email:
            url = self.base_url.child("claim", creds.username)
            response = self._send_request(url, "post")
            if "email" in response:
                creds.email = response["email"]
            else:
                raise SybilException("Sybil response did not contain a valid email")

    def get_emails(self, creds: Credentials) -> list[Mail]:
        if not creds.email:
            raise SybilException("This set of credentials does not have an email yet")
        self.inbox = self._load_inbox_for_address(creds.email)
        results: list[Mail] = []
        if not self.inbox:
            return results
        for mail in self.inbox:
            m = self.process_mail(mail)
            if m:
                results.append(m)
        return results

    def process_mail(self, mail: dict) -> Mail | None:
        try:
            to_addr, to_name = _parse_addr_header(mail["to"], sybil=True)
            from_addr, from_name = _parse_addr_header(mail["from"])

            return Mail(
                intid=int(mail["intid"]),
                mail_id=mail["id"],
                subject=mail["subject"],
                from_name=from_name,
                from_addr=from_addr,
                to_name=to_name,
                to_addr=to_addr,
                date=datetime.datetime.strptime(mail["date"], self.time_format),
                body=self._body_fetch(mail["id"]),
                headers=str(self._headers_fetch(mail["id"])),
                language=self.language,
            )
        except Exception:
            logger.exception(f'Extracting email {mail["intid"]} data failed')
        return None

    def _send_request(self, url: URL, method: str = "get", query: Optional[dict] = None) -> Any:
        tries = 3
        for i in range(tries):
            try:
                resp = requests.request(
                    method,
                    url.to_text(),
                    headers=self.headers,
                    params=query,
                    timeout=120,
                    verify=Config().DEV_VERIFY_SSL,
                )
                if resp.status_code != 200:
                    num_retries = 3
                    while num_retries > 0 and (resp.status_code == 504 or resp.status_code == 423):
                        num_retries -= 1
                        logger.warning(
                            f"Sybilmail timed out, wait to let it reboot. Retry {num_retries} more times"
                        )
                        time.sleep(
                            90
                        )  # sleep to let sybilmail workers reboot, it takes about 65s to reboot
                        # retry
                        resp = requests.request(
                            method,
                            url.to_text(),
                            headers=self.headers,
                            params=query,
                            timeout=120,
                            verify=Config().DEV_VERIFY_SSL,
                        )
                    if resp.status_code != 200:
                        raise SybilException(
                            f"Sybil mail server failed with status {resp}, {resp.content!r}"
                        )
                return resp.json()
            except requests.RequestException as e:
                if i == tries - 1:
                    logger.error(f"Unable to send request after {tries}")
                    logger.exception(e)
                    raise SybilException(f"Error connecting to Sybil at {self.base_url}")
                time.sleep(30)

        raise SybilException(f"Error connecting to Sybil at {self.base_url}")

    def _load_inbox_for_address(self, addr: str) -> Any:
        url = Config().SYBIL_URL.child("emails").add("address", addr)
        t = datetime.datetime.now() - datetime.timedelta(hours=4)
        query = {"after": t.strftime("%Y-%m-%dT%H:%M:%SZ")}
        return self._send_request(url, query=query)

    def load_inbox(self, hours: int = 4) -> list[dict[str, str]]:
        url = Config().SYBIL_URL.child("emails")
        t = datetime.datetime.now() - datetime.timedelta(hours=hours)
        query = {"after": t.strftime("%Y-%m-%dT%H:%M:%SZ")}
        return self._send_request(url, query=query)

    def _body_fetch(self, mail_id: str) -> str:
        """
        Query Sybilmail for the body of a given mail.
        :return: mail body
        """
        url = Config().SYBIL_URL.child("email", mail_id)
        return self._send_request(url)

    def _headers_fetch(self, mail_id: str) -> dict[str, str]:
        """
        Query Sybilmail for the headers of a given mail
        :return: dict of mail headers
        """
        url = Config().SYBIL_URL.child("headers", mail_id)
        return self._send_request(url)


def _to_string(element: _Element) -> str:
    return etree.tostring(element, encoding="unicode")


def _get_text(element: _Element) -> str:
    return " ".join(_get_texts(element))


def _get_texts(element: _Element) -> list[_ElementUnicodeResult]:
    # ugly with casts but necessary to keep mypy happy
    # Relative to element (incl. itself); a leading // would search the whole document
    texts = element.xpath("descendant-or-self::*[not(self::style) and not(self::script)]/text()")
    if texts is None:
        raise EmptyException()
    results = cast(list[_ElementUnicodeResult], texts)
    return [x for x in results if x.strip()]


def _parse_addr_header(header: str, sybil: bool = False) -> tuple[str, str]:
    if not header:
        return "", ""
    addr, name = "", ""
    parsed_addresses = getaddresses([header])
    if len(parsed_addresses) == 0:
        logging.error(f"No address in : {header}")
        raise EmailParsingException(f"No address in : {header}")
    elif len(parsed_addresses) == 1:
        [(name, addr)] = parsed_addresses
    else:
        logging.warning(f"Parsed multiple addresses: {parsed_addresses}")
        for tuple_addr in parsed_addresses:
            name = tuple_addr[0]
            addr = tuple_addr[1]

            if sybil:
                substring = "@" + Config().SYBIL_MAIL_DOMAIN
            else:
                substring = "@"
            if substring in addr:
                logging.warning(f"Using: {addr}")
                break
    return addr, name
