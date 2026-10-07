import logging
import tempfile
import os

from typing import Iterable, Optional, Set, Tuple

import requests
import regex
from urllib3.exceptions import ReadTimeoutError
from bs4 import BeautifulSoup
import cyrtranslit

from pdfminer.pdfparser import PDFSyntaxError
from pdfminer.high_level import extract_text

from readabilipy import simple_json_from_html_string
from html2text import HTML2Text

from enfbots_crawler.const import email_pattern

RE_BAD_POLYGLOT_CHARS = regex.compile(r"[\p{Cc}\p{Cs}]+")


def coerce_cyrillic(text: str, lang_code: str = "ru") -> str:
    if lang_code not in cyrtranslit.supported():
        lang_code = "ru"

    return cyrtranslit.to_latin(text, lang_code)


def full_split(s: str) -> list[str]:
    return [
        i.lower().strip()
        for j in special_character_split(s)
        for i in camel_case_split(j)
        if i.strip()
    ]


def extract_content_from_html(html: str, url: str) -> Optional[str]:
    """
    Extract markdown text from HTML code
    :param html: page source as html string
    :return: markdown string
    """
    try:
        html_content = simple_json_from_html_string(html, use_readability=True)["content"]
    except Exception as e:
        logger = logging.getLogger("text_helper.py")
        logger.error("Readability failed to extract text of PP/ToS, %s", e)
        return None

    # happens when page is not html but e.g. pdf
    if html_content is None:
        logger = logging.getLogger("text_helper.py")
        logger.error("Readability failed to extract text of PP/ToS, html_content is None")
        return None

    formatter = HTML2Text()
    formatter.ignore_images = True
    return formatter.handle(html_content)


def extract_text_only_from_html(html: str) -> Optional[str]:
    try:
        formatter = HTML2Text()
        formatter.ignore_images = True
        formatter.ignore_emphasis = True
        return formatter.handle(html)
    except Exception as e:
        logging.exception(e)
        return None


def extract_text_from_html(bs_html: BeautifulSoup) -> str:
    """
    Text extraction
    """
    content_filtered = ""
    blacklist = [
        "[document]",
        "noscript",
        "header",
        "html",
        "meta",
        "head",
        "input",
        "script",
        "base",
        "link",
        "meta",
        "style",
    ]

    for t in bs_html.find_all(string=True):
        if t.parent.name not in blacklist:
            content_filtered += f"{t} "

    return content_filtered


def special_character_split(s: str) -> Iterable[str]:
    """
    Preprocess string:
    1. split
    2. to lower
    :param s: text to split and change to lower
    :return: result
    """
    return [x for x in regex.split(r"[^\p{L}0-9']+", s) if x]


def remove_special_characters(s: str) -> str:
    return regex.sub(r"[^\p{L}0-9' \n]+", "", s)


def camel_case_split(s: str) -> Iterable[str]:
    """
    Source: https://stackoverflow.com/a/58996565/1761879
    :param s: string to split.
    :return: split string
    """
    # Skip camel case splitting for non-Latin scripts (they don't have case)
    # Check if string contains any Latin characters with case
    has_latin_case = any(c.isalpha() and ord(c) < 128 and (c.isupper() or c.islower()) for c in s)
    if not has_latin_case:
        # For non-Latin scripts, return the string as-is
        return [s] if s else []

    idx = list(map(str.isupper, s))
    # mark change of case
    l = [0]
    for i, (x, y) in enumerate(zip(idx, idx[1:])):
        if x and not y:  # "Ul"
            l.append(i)
        elif not x and y:  # "lU"
            l.append(i + 1)
    l.append(len(s))
    # for "lUl", index of "U" will pop twice, have to filer it
    return [s[x:y] for x, y in zip(l, l[1:]) if x < y]


def get_all_emails(input: str) -> Set[Tuple[str, str]]:
    result = email_pattern.findall(input)

    ret: Set[Tuple[str, str]] = set()
    for local_part, domain in result:
        lower_end = str(domain).rstrip().lower()

        # filter out some common cases of wrong detections
        if lower_end.endswith(".jpg"):
            continue
        if lower_end.endswith(".png"):
            continue

        ret.add((local_part, domain))

    return ret


def remove_bad_chars_for_polyglot(text: str) -> str:
    return RE_BAD_POLYGLOT_CHARS.sub("", text)
