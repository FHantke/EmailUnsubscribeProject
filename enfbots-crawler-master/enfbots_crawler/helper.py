from __future__ import annotations

import gzip
import io
import json
import lzma
import subprocess
from typing import IO, TypeVar, Optional, overload, Sequence, Dict, Any, List
import logging
import base64
from pathlib import Path
from collections import Counter
import time
import random

from packaging import version
import tldextract

import hyperlink
import requests

from hyperlink import URL, URLParseError, DecodedURL

import alembic.config
import alembic.command

import numpy as np

from bs4.element import Tag
from sqlalchemy import text, inspect

from enfbots_crawler.database import SessionLocal
from enfbots_crawler.exceptions import TablesMissingException, OutdatedDatabaseException

logger = logging.getLogger("helper.py")


class Singleton(type):
    _instances: Dict[Singleton, Singleton] = {}

    def __call__(cls, *args: Any, **kwargs: Any) -> Singleton:
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


@overload
def get_attr(element: Tag, attr: str, default: str) -> str: ...


@overload
def get_attr(element: Tag, attr: str, default: None = None) -> Optional[str]: ...


def get_attr(element: Tag, attr: str, default: Optional[str] = None) -> Optional[str]:
    result = element.get(attr, default)
    if isinstance(result, list):
        result = " ".join(result)
    return result


T = TypeVar("T")


def filter_none(seq: Sequence[T | None]) -> list[T]:
    return list(filter(None, seq))


def assemble_url(hostname: str) -> URL:
    # if protocol is already defined, take it as is
    if hostname.startswith("https://") or hostname.startswith("http://"):
        url = hyperlink.parse(hostname)
    else:
        # Else try https first
        url = hyperlink.parse("https://" + hostname)

    if isinstance(url, DecodedURL):
        url = url.encoded_url

    try:
        response = requests.head(str(url), allow_redirects=False, timeout=60)
        if 300 <= response.status_code < 400:
            if "Location" in response.headers:
                redirect_url = URL.from_text(response.headers["Location"])
                if redirect_url.scheme == "http":
                    url = url.replace(scheme="http", port=redirect_url.port)
                    logger.info("Detected redirect to HTTP %s", redirect_url.to_text())
            logger.info("Valid HTTPS url detected %s", url.to_text())
        return url
    except (requests.exceptions.RequestException, ValueError, URLParseError):
        # this will throw on connection errors but not on HTTP errors
        # default to http
        try:
            url = hyperlink.parse("http://" + hostname)
            logger.info("HTTPS unavailable. Falling back to %s", url.to_text())
            if isinstance(url, DecodedURL):
                url = url.encoded_url
        except (requests.exceptions.RequestException, ValueError, URLParseError):
            logger.error("Unable to parse url: http://%s", hostname)
            url = hyperlink.parse(hostname)
            if isinstance(url, DecodedURL):
                url = url.encoded_url
            return url

    return url


def domain_suffix_to_location(suffix: str) -> str:
    """
    Translate URL suffix to country code
    Implements https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2
    """
    if "." in suffix:
        if suffix.split(".")[1] == "uk":
            return "gb"
        else:
            return suffix.split(".")[1]
    elif suffix in ("com", "net", "org", "co", "biz"):
        return "us"
    elif suffix == "el":
        return "gr"
    else:
        return suffix


def ns_lookup(domain: str, record_type: Optional[str] = None) -> list[str]:
    command = ["dig", "+short", domain]
    if record_type:
        command.append(record_type)

    pipe = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=None).communicate()
    return pipe[0].decode("utf-8").splitlines()


def is_google_unsafe(*urls: str, google_api_key: str) -> bool:
    data = {
        "client": {"clientId": "enfbots.inf.ethz.ch", "clientVersion": "1.0.0"},
        "threatInfo": {
            "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING"],
            "platformTypes": ["LINUX"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url} for url in urls],
        },
    }

    num_tries = 5
    for i in range(num_tries):
        try:
            response = requests.post(
                f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={google_api_key}",
                json.dumps(data),
                timeout=60,
            ).json()
            break
        except Exception as e:
            time.sleep(10 + random.randint(0, 20))
            if i == num_tries - 1:
                raise e
    return bool(response)


def _execute_query(path: Path, **params: Any) -> str:
    with open(path, "r", encoding="utf-8") as file:
        query = file.read()

        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            res = session.execute(text(query).bindparams(**params)).scalar()

            if res is None:
                raise RuntimeError(f"Unexpected result when running {path}: {res}")

            return res


def get_progress(code_dir: Path, crawl_id: str) -> float:
    """
    Returns the progress of the given crawl_id in the configured database as a fraction.
    """
    progress_query_file = code_dir / "../queries/progress.sql"

    return float(_execute_query(progress_query_file, crawl_id=crawl_id))


def get_speed(code_dir: Path, crawl_id: str) -> float:
    """
    Returns the speed of the given crawl_id in crawls per minute of the last hour.
    """
    progress_query_file = code_dir / "../queries/speed.sql"

    return float(_execute_query(progress_query_file, crawl_id=crawl_id))


def get_jobs_todo(code_dir: Path, crawl_id: str) -> int:
    """
    Returns the amount of jobs todo.
    """
    return int(_execute_query(code_dir / "../queries/jobs_todo.sql", crawl_id=crawl_id))


def set_log_formatter(fmt: str, date_format: str) -> None:
    """
    Sets the given format for the root logger and all its handlers.
    The handlers may be to a file or to console. It also ensures that
    at least one console handler exists.
    """
    root_logger = logging.getLogger()
    log_formatter = logging.Formatter(
        fmt=fmt,
        datefmt=date_format,
    )
    # Set the log_formatter from above for all and ensure
    # that at lest one handler is present
    for handler in root_logger.handlers:
        handler.setFormatter(log_formatter)
    if len(root_logger.handlers) == 0:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)
        root_logger.addHandler(console_handler)


def full_stack() -> str:
    """
    Creates the current full stacktrace and returns it as a string

    Returns:
        str: Stacktrace as string
    """
    import traceback, sys

    exc = sys.exc_info()[0]
    stack = traceback.extract_stack()[:-1]  # last one would be full_stack()
    if exc is not None:  # i.e. an exception is present
        del stack[-1]  # remove call of full_stack, the printed exception
        # will contain the caught exception caller instead
    trc = "Traceback (most recent call last):\n"
    stackstr = trc + "".join(traceback.format_list(stack))
    if exc is not None:
        # pylint: disable=bad-str-strip-call
        stackstr += "  " + traceback.format_exc().lstrip(trc)
    return stackstr


def open_text(path: Path | str) -> IO[str]:
    """
    Opens a UTF-8 text file for reading, decompressing .xz and .gz files transparently.
    """
    path = Path(path)
    if path.suffix == ".xz":
        return lzma.open(path, "rt", encoding="utf-8")
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def is_in_blocklist(blocklist_path: Path, domain: str) -> bool:
    if blocklist_path.exists():
        tld = tldextract.extract(domain)

        with blocklist_path.open() as f:
            for line in f:
                tld2 = tldextract.extract(line)
                if tld2.domain == tld.domain and tld2.suffix == tld.suffix:
                    return True
    return False


def get_spoken_languages_of_tld(tld: str) -> List[str]:
    """Accepts the TLD and returns a string with spoken languages (the ISO 639-1 code) in this TLD .
    If there are multiple they are split with commas ',' and if it's international we say it's english
    """
    mapping = dict(
        {
            "al": "sq",  # Albania
            "ad": "ca",  # Andorra
            "am": "hy",  # Armenia
            "հայ": "hy",  # Armenia
            "at": "de",  # Austria
            "az": "az",  # Azerbaijan
            "by": "be,ru,yi",  # Belarus
            "бел": "be,ru,yi",  # Belarus
            "be": "nl,fr,de",  # Belgium
            "ba": "bs,hr,sr",  # Bosnia and Herzegovina
            "bg": "bg",  # Bulgaria
            "бг": "bg",  # Bulgaria
            "hr": "hr",  # Croatia
            "cy": "el,tr,hy",  # Cyprus
            "cn": "zh",  # China
            "中国": "zh",  # China (IDN)
            "中國": "zh",  # China (IDN Traditional)
            "cz": "cs",  # Czech Republic
            "dk": "da,de",  # Denmark
            "ee": "et",  # Estonia
            "eu": "en,de,fr",  # EU TLD; I simply used some of the most common languages
            "fi": "fi,sv",  # Finland
            "fr": "fr",  # France, French Republic
            "ge": "ka,ab",  # Georgia
            "de": "de",  # Germany, Federal Republic of Germany
            "gr": "el",  # Greece, Hellenic Republic
            "ελ": "el",  # Greece
            "hu": "hu",  # Hungary
            "is": "is",  # Iceland
            "in": "hi,en",  # India
            "भारत": "hi,en",  # India (IDN)
            "ie": "en,ga",  # Ireland
            "im": "en",  # Isle of Man
            "it": "it",  # Italy
            "je": "en",  # Jersey
            "kz": "kk,ru",  # Kazakhstan
            "қаз": "kk,ru",  # Kazakhstan
            "jp": "ja",  # Japan
            "日本": "ja",  # Japan (IDN)
            "xk": "sq,sr",  # Kosovo
            "lv": "lv",  # Latvia
            "li": "de",  # Liechtenstein
            "lt": "lt",  # Lithuania
            "lu": "lb,de,fr",  # Luxembourg
            "mt": "mt,it,en",  # Malta
            "md": "ro,ru,be,bg,de,pl,uk",  # Moldova
            "mc": "fr,it",  # Monaco
            "me": "sq,bs,hr,sr",  # Montenegro
            "nl": "nl,de",  # Netherlands
            "mk": "mk,sq,tr,sr,bs",  # North Macedonia
            "мкд": "mk,sq,tr,sr,bs",  # North Macedonia
            "no": "no",  # Norway
            "pl": "pl",  # Poland
            "pt": "pt",  # Portugal
            "ro": "ro",  # Romania
            "ru": "ru",  # Russia
            "sm": "it",  # San Marino
            "rs": "sr",  # Serbia
            "срб": "sr",  # Serbia
            "sk": "sk",  # Slovakia
            "si": "sl,it,hu",  # Slovenia
            "es": "es,ca,gl",  # Spain
            "se": "sv,fi,yi",  # Sweden
            "ch": "de,fr,it,rm",  # Switzerland
            "swiss": "de,fr,it,rm",  # Switzerland
            "tr": "tr",  # Turkey
            "kr": "ko",  # South Korea
            "한국": "ko",  # South Korea (IDN)
            "ua": "uk",  # Ukraine
            "укр": "uk",  # Ukraine
            "uk": "en,cy,gd",  # United Kingdom
            "za": "en,af,zu,xh",  # South Africa
            "va": "it,la",  # Vatican City
            "com": "en",  # company -> english?
            "org": "en",
            "gb": "en",
        }
    )

    if tld in mapping:
        return mapping[tld].split(",")
    logger.warning("Unknown TLD %s", tld)
    return []


def merge_languages_with_prio(priority_codes: List[str], lang_codes: List[str]) -> List[str]:
    out: List[str] = []

    for code in priority_codes:
        if code in lang_codes:
            lang_codes.remove(code)
        out.append(code)
    for rest in lang_codes:
        out.append(rest)

    return out


def check_database(alembic_root_dir: Path) -> bool:
    with SessionLocal() as session:
        result = session.execute(text("SELECT 42")).one()

        if result[0] != 42:
            logger.error("Unable to connect to the database")
            return False

        i = inspect(SessionLocal().get_bind())
        tables_exist = i.has_table("websites") and i.has_table("jobs")
        if not tables_exist:
            raise TablesMissingException()

    try:
        # Check revision
        # Get database head revision
        captured_current = io.StringIO()
        config = alembic.config.Config(
            file_=str(alembic_root_dir / "alembic.ini"), stdout=captured_current
        )
        config.set_main_option("script_location", str(alembic_root_dir / "alembic"))
        config.attributes["configure_logger"] = False
        alembic.command.current(config)

        current_rev = captured_current.getvalue().split(" ")[0].strip()

        # Get what this crawler has as head revision
        captured_head = io.StringIO()
        config = alembic.config.Config(
            file_=str(alembic_root_dir / "alembic.ini"), stdout=captured_head
        )
        config.set_main_option("script_location", str(alembic_root_dir / "alembic"))
        config.attributes["configure_logger"] = False
        alembic.command.show(config, "head")

        head_rev = captured_head.getvalue().removeprefix("Rev: ").split(" ")[0]

    except Exception as e:
        logger.error(e)
        return False

    if current_rev != head_rev:
        raise OutdatedDatabaseException(
            f"Database is outdated. Revision of the database is {current_rev} {captured_current.getvalue()}. Please update to {head_rev}"
        )

    return True


def check_classifier(endpoint: str, user: str, token: str) -> bool:
    if endpoint == "":
        logger.error("CRAWLER_CLASSIFY_SERVICE_ENDPOINT is not defined")
        return False
    user_token = user + ":" + token
    auth_string = (base64.encodebytes(user_token.encode("utf-8"))).decode("utf-8").strip()

    try:
        response = requests.get(
            url=endpoint + "/version",
            headers={"Authorization": f"Basic {auth_string}"},
            timeout=120,
        )
    except Exception as e:
        logger.error(e)
        return False

    if response.status_code >= 400:
        logger.error("Error code of the classifier at %s: %s", endpoint, response.status_code)
        return False

    ver = response.text
    logger.info("Classifier has version: %s", ver)

    return True


def check_sybilmail(sybil_url: URL, auth_token: str, verify_ssl: bool = True) -> bool:
    url = sybil_url.child("version")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"basicToken {auth_token}",
    }

    resp = requests.request("GET", url.to_text(), headers=headers, verify=verify_ssl, timeout=120)

    if resp.status_code != 200:
        logging.error("Sybilmail returned %s", resp)
        return False

    is_good = version.parse(resp.text) >= version.parse("0.2.5")

    if not is_good:
        logging.error("Sybilmail at %s response was %s with text: %s", url, resp, resp.text)
        return False
    return True


def get_non_unique_items(l: List[Any]) -> List[Any]:
    def low(x: Any) -> Any:
        return x.lower() if isinstance(x, str) else x

    c = Counter(l)
    return list(np.unique([x for x in l if c[low(x)] > 1]))
