"""
contains a single reg element (a child tag of a form tag, can be select, input or textarea)
"""
from __future__ import annotations

import logging
import typing
import re
from time import sleep

from datetime import date
from typing import Any, cast, List

import rstr
from babel import UnknownLocaleError
from babel.dates import format_date
from selenium.common.exceptions import WebDriverException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.select import Select

# Imports from the enfbots library
from enfbots_crawler.languages import Keyword, Language, KeywordType, MatchString

# Imports from this crawler implementation
from enfbots_crawler import InputType, input_bs, FormType, Config
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.input_bs import InputBS

from enfbots_crawler.keyword_matching import match_keywords_lemmatized

from enfbots_crawler.browser import EnfbotsBrowser

logger = logging.getLogger("enfbots_crawler")


class InputSelenium:
    """
    Class representing single WebElement of the registration form
    """

    def __init__(self, elem: WebElement, browser: EnfbotsBrowser, bs: InputBS) -> None:
        self.br = browser
        self.elem = elem
        self.bs = bs

        self.required = bs.required
        # For text based assumption if input is required
        self.half_required = False

        self.prechecked = bs.prechecked
        self.type = bs.estimated_type

        if self.type in (
            InputType.CHECKBOX_PP,
            InputType.CHECKBOX_TOS,
            InputType.CHECKBOX_PP_TOS,
            InputType.CHECKBOX_AGE,
            InputType.CHECKBOX_PP_TOS_EMAIL,
        ) or (bs.form.type == FormType.NEWSLETTER and self.type == InputType.CHECKBOX_EMAIL):
            self.half_required = True

        self.direct_type = bs.direct_type

        self.html_tag: str = elem.tag_name.lower()
        self.html_type: str = elem.get_attribute("type")
        self.html_name: str = elem.get_attribute("name")

        try:
            max_l = elem.get_attribute("maxlength")
            self.max_length = None if (max_l is None or max_l == "") else int(max_l)
            min_l = elem.get_attribute("minlength")
            self.min_length = None if (min_l is None or min_l == "") else int(min_l)
            max_s = elem.get_attribute("max")
            self.max = None if (max_s is None or max_s == "") else int(max_s)
            min_s = elem.get_attribute("min")
            self.min = None if (min_s is None or min_s == "") else int(min_s)
        except ValueError:
            self.max_length = None
            self.min_length = None
            self.min = None
            self.max = None

        self.pattern = elem.get_attribute("pattern")
        self.id = elem.get_attribute("id")
        self.filled_in = False
        self.content: typing.Optional[str] = None
        self.lang = bs.lang

    def __str__(self) -> str:
        return f"[tag={self.html_tag}, type={self.type}]"

    @staticmethod
    def from_bs(browser: EnfbotsBrowser, input_bs_: InputBS) -> InputSelenium:
        """Constructs the class from InputBS, might raise NoSUchElementException"""
        tag = browser.driver.find_element(By.ID, input_bs_.id)
        return InputSelenium(tag, browser, input_bs_)

    @staticmethod
    def input_creds_mapping(creds: Credentials) -> dict:
        return {
            InputType.VERIFY_CODE: creds.verify_code,
            InputType.MAIL: creds.email,
            InputType.USERNAME: creds.username,
            InputType.PASSWORD: creds.password,
            InputType.PHONE: creds.phone,
            InputType.TITLE: creds.title,
            InputType.FIRST_NAME: creds.first_name,
            InputType.LAST_NAME: creds.last_name,
            InputType.FULL_NAME: creds.full_name,
            InputType.STREET: creds.street,
            InputType.STREET_NR: creds.street_nr,
            InputType.STREET_FULL: creds.street,
            InputType.CITY: creds.city,
            InputType.ZIP: creds.postal_code,
            InputType.COUNTRY: creds.country,
            InputType.FULL_ADDRESS: creds.full_address,
            InputType.BIRTH_DAY: creds.birth_day,
            InputType.BIRTH_MONTH: creds.birth_month,
            InputType.BIRTH_YEAR: creds.birth_year,
            InputType.BIRTH_FULL: creds.birthdate,
            InputType.ORGANIZATION: creds.organization,
        }

    def fill(self, creds: Credentials, fill_all: bool) -> bool:
        self.filled_in = True
        mapping = self.input_creds_mapping(creds)

        if self.direct_type in input_bs.textual_types and self.type in mapping:
            value = mapping[self.type]
            new_value = self.validate_text(value)
            if new_value != value:
                # store login info, other modifications can be ignored
                if self.type == InputType.USERNAME:
                    creds.username = new_value
                elif self.type == InputType.PASSWORD:
                    creds.password = new_value

            self.fill_text(new_value)
            logger.debug("input filled %s with %s", self, new_value)
            return True
        elif self.direct_type in input_bs.textual_types and (fill_all or self.required):
            random_text = self.validate_text("Ignore this automated message1")
            self.fill_text(random_text)
            return True
        elif self.direct_type == InputType.CHECKBOX_OTHER:
            value = self.required or self.half_required or fill_all
            if value:
                self.select_checkbox()
                return True
        elif self.direct_type == InputType.SELECT_OTHER:
            self.filled_in = True
            values: List[Keyword] = cast(List[Keyword], list())
            if self.type == InputType.COUNTRY:
                values = cast(
                    List[Keyword],
                    Language.get(Config().language_dir, "de", load_model=False).get_keywords(
                        KeywordType.LANGUAGE
                    ),
                )
            if self.type in mapping:
                if self.type == InputType.BIRTH_MONTH:
                    b_date = creds.birthdate
                    try:
                        for fmt in ["MMMM", "MMM"]:
                            values.append(
                                Keyword(
                                    format_date(b_date, fmt, locale=self.lang.code),
                                    self.lang,
                                    None,
                                    False,
                                    False,
                                )
                            )  # TODO: enable kw_syntax
                            values.append(
                                Keyword(
                                    format_date(b_date, fmt, locale="en"),
                                    self.lang,
                                    None,
                                    False,
                                    True,
                                )
                            )  # TODO: enable kw_syntax
                    except UnknownLocaleError:
                        pass
                values.append(
                    Keyword(str(mapping[self.type]), self.lang, None, False, True)
                )  # TODO: enable kw_syntax
            self.fill_select(values)
            return True

        self.filled_in = False
        return False

    def validate_text(self, value: Any) -> str:
        if self.type in (InputType.MAIL, InputType.PHONE):
            return str(value)

        if isinstance(value, date):
            if self.html_type == "date":
                # format required by browsers
                return value.strftime("%Y-%m-%d")
            else:
                try:
                    return format_date(value, locale=self.lang.code, format="short")
                except UnknownLocaleError:
                    pass
                return format_date(value, locale="de", format="short")

        if self.pattern:
            # do this only if the input field type is not very describing and there exists a pattern attribute
            try:
                value = str(value)
                if not re.match(f"^{self.pattern}$", value):
                    new_val = rstr.xeger(self.pattern)
                    # not normal to ask a user to make a regex based input longer then 40 chars
                    if len(new_val) > 40:
                        new_val = new_val[0:40]
                    value = new_val
                return value
            except Exception as e:
                logger.exception(e)
                pass

        if self.direct_type == InputType.NUMBER_OTHER:
            if isinstance(value, str):
                value = "".join(s for s in value if s.isdigit())
            try:
                value = int(value)
            except ValueError:
                value = 11
            if self.max is not None and value > self.max:
                value = self.max
            if self.min is not None and value < self.min:
                value = self.min
            return str(value)

        value = str(value)
        # check extracted input constraints
        if self.min_length is not None and len(value) < self.min_length:
            # just repeat last character
            value = value + value[-1] * (self.min_length - len(value))
        if self.max_length is not None and len(value) > self.max_length:
            value = value[: self.max_length - 1]

        return value

    def fill_text(self, value: str) -> None:
        self.content = value
        self.br.input_value(self.elem, value)

    def select_checkbox(self) -> None:
        self.content = "selected"
        if not self.elem.is_selected():
            self.br.activate(self.elem)

    def fill_select(self, keywords: List[Keyword]) -> None:
        """
        For a single select tag, fill the first valid value
        """

        tries = 3
        for i in range(tries):
            try:
                sel = Select(self.elem)
                break
            except StaleElementReferenceException as e:
                if i == tries - 1:
                    logger.error("Exception when filling a select tag: %s", e)
                    return
                sleep(5)

        options = sel.options
        best_score: float = 0
        best_option = -1
        backup_option = -1

        for i, option in enumerate(options):
            value = option.get_attribute("value") or ""
            text = option.get_attribute("innerText") or ""
            if not option.get_attribute("disabled") and value.strip() and text.strip():
                backup_option = i
                if keywords and (value or text):
                    matches = list((MatchString(value, self.lang), MatchString(text, self.lang)))
                    score = match_keywords_lemmatized(matches, keywords, Config().MIN_KW_MATCH_LEN)
                    if score > best_score:
                        best_score = score
                        best_option = i

        if best_option == -1:
            best_option = backup_option

        if best_option != -1:
            self.content = options[best_option].get_attribute("value")
            sel.select_by_index(best_option)

    def click(self) -> bool:
        btn = self.elem
        if btn.is_displayed():
            try:
                btn.click()
                logger.info("button %s clicked", self)
                return True
            except WebDriverException:
                logger.warning(f"unable to click button {self} due to selenium exception")
        return False
