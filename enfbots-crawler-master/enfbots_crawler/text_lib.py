import logging
from typing import Optional, Iterable

from bs4 import BeautifulSoup
from readabilipy import simple_json_from_html_string
import regex

from enfbots_crawler.text_helper import extract_text_from_html

logger = logging.getLogger("enfbots_crawler")


def extract_content_from_html(html: str, clean: bool = True) -> Optional[str]:
    """
    Extract text from HTML code
    :param html: page source as BeautifulSoup
    :param clean: whether result should be completely without html
    :return: string
    """
    try:
        html_content = simple_json_from_html_string(html, use_readability=True)["content"]
    except TypeError as e:
        logger.error("Readability failed to extract text of PP/TC, %s", e)
        return None

    if not clean or not html_content:
        return html_content
    else:
        content = BeautifulSoup(html_content, "html.parser", multi_valued_attributes=None)

        return extract_text_from_html(content)


def special_character_split(s: str) -> Iterable[str]:
    """
    Preprocess string:
    1. split
    2. to lower
    :param s: text to split and change to lower
    :return: result
    """
    return [x for x in regex.split(r"[^\p{L}0-9']+", s) if x]


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
