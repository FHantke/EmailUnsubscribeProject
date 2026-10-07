"""
contains a single reg element (a child tag of a form tag, can be select, input or textarea)
"""
from __future__ import annotations

import itertools
import logging
import re
import typing
import uuid
from typing import Optional, Sequence

from bs4.element import Tag, PageElement

# Imports from the enfbots library
from enfbots_crawler.helper import get_attr, filter_none
from enfbots_crawler.languages import KeywordType

from enfbots_crawler.config import Config

# Imports from this crawler implementation
from enfbots_crawler import InputType
from enfbots_crawler.keyword_matching import match_keywords_lemmatized, keyword_score, keyword_classify

if typing.TYPE_CHECKING:
    from enfbots_crawler.form_bs import FormBS

logger = logging.getLogger("enfbots_crawler")

input_autocomplete_mapping = {
    "name": InputType.FULL_NAME,
    "honorific-prefix": InputType.HONORIFIC_PREFIX,
    "given-name": InputType.FIRST_NAME,
    "additional-name": InputType.MIDDLE_NAME,
    "family-name": InputType.LAST_NAME,
    "email": InputType.MAIL,
    "username": InputType.USERNAME,
    "new-password": InputType.PASSWORD,
    "current-password": InputType.PASSWORD,
    "organizational-title": InputType.TITLE,
    "organization": InputType.ORGANIZATION,
    "street-address": InputType.STREET_FULL,
    "address-line1": InputType.STREET_FULL,
    "country": InputType.COUNTRY,
    "country-name": InputType.COUNTRY,
    "postal-code": InputType.ZIP,
    "bday": InputType.BIRTH_FULL,
    "bday-day": InputType.BIRTH_DAY,
    "bday-month": InputType.BIRTH_MONTH,
    "bday-year": InputType.BIRTH_YEAR,
    "sex": InputType.SEX,
    "tel": InputType.PHONE,
    "address-level-2": InputType.CITY,
}

text_keyword_mapping = {
    InputType.MAIL: KeywordType.MAIL_INPUT,
    InputType.CAPTCHA_INPUT: KeywordType.CAPTCHA_INPUT,
    InputType.USERNAME: KeywordType.USER_INPUT,
    InputType.PASSWORD: KeywordType.PW_INPUT,
    InputType.PHONE: KeywordType.PHONE_INPUT,
    InputType.TITLE: KeywordType.TITLE_INPUT,
    InputType.FIRST_NAME: KeywordType.FIRSTNAME_INPUT,
    InputType.LAST_NAME: KeywordType.LASTNAME_INPUT,
    InputType.FULL_NAME: KeywordType.NAME_INPUT,
    InputType.STREET: KeywordType.STREET_INPUT,
    InputType.STREET_NR: KeywordType.STREET_NR_INPUT,
    InputType.STREET_FULL: KeywordType.STREET_FULL_INPUT,
    InputType.CITY: KeywordType.CITY_INPUT,
    InputType.ZIP: KeywordType.ZIP_INPUT,
    InputType.COUNTRY: KeywordType.COUNTRY_INPUT,
    InputType.FULL_ADDRESS: KeywordType.FULL_ADDRESS_INPUT,
    InputType.BIRTH_DAY: KeywordType.BIRTH_DAY_INPUT,
    InputType.BIRTH_MONTH: KeywordType.BIRTH_MONTH_INPUT,
    InputType.BIRTH_YEAR: KeywordType.BIRTH_YEAR_INPUT,
    InputType.BIRTH_FULL: KeywordType.BIRTH_FULL_INPUT,
    InputType.VERIFY_CODE: KeywordType.VERIFICATION_CODE,
    InputType.SEARCH: KeywordType.SEARCH_INPUT,
    InputType.ORGANIZATION: KeywordType.ORGANIZATION_INPUT,
    InputType.AGE: KeywordType.AGE_INPUT,
    InputType.HONEYPOT: KeywordType.HONEYPOT_INPUT,
}

checkbox_keyword_mapping: dict[InputType, KeywordType | Sequence[KeywordType]] = {
    InputType.CHECKBOX_EMAIL: KeywordType.CHECKBOX_EMAIL,
    InputType.CHECKBOX_PP: KeywordType.CHECKBOX_PP,
    InputType.CHECKBOX_TOS: KeywordType.CHECKBOX_TOS,
    InputType.CHECKBOX_AGE: KeywordType.AGE_INPUT,
}

button_keyword_mapping = {
    InputType.BUTTON_LOGIN: KeywordType.LOGIN,
    InputType.BUTTON_REGISTRATION: KeywordType.REGISTRATION,
    InputType.BUTTON_CONTACT: KeywordType.CONTACT,
    InputType.BUTTON_SUBSCRIBE: KeywordType.NEWSLETTER,
}

textual_types = {
    InputType.TEXT_OTHER,
    InputType.MAIL,
    InputType.PASSWORD,
    InputType.PHONE,
    InputType.NUMBER_OTHER,
}


class InputBS:
    def __init__(self, form: FormBS, element: Tag) -> None:
        self.element = element
        self.form = form
        self.lang = form.lang
        self.id = get_attr(element, "id")

        # force an id for label matching
        self.uuid: Optional[str] = get_attr(element, "data-enfbots-uuid")

        self.visible = True
        if self.uuid and form.input_info and self.uuid in form.input_info:
            self.visible = form.input_info[self.uuid] is True

        if not self.uuid:
            self.uuid = uuid.uuid4().hex
            self.element["data-enfbots-uuid"] = self.uuid

        self.direct_type = self._get_direct_type()
        self.label = self._get_label()
        self.required = self._get_is_required()
        self.prechecked = self._get_is_prechecked()

        self.tag_name = self.element.name
        self.estimated_type: InputType = self.direct_type
        self.match_string: Optional[str] = None

        self.estimate_type()

    def estimate_type(self) -> None:
        if self.direct_type in textual_types or self.direct_type is InputType.SELECT_OTHER:
            if self.direct_type == InputType.SELECT_OTHER:
                pass
            kw_type = self._match_text_type()
            if self.direct_type not in (
                InputType.TEXT_OTHER,
                InputType.NUMBER_OTHER,
                InputType.SELECT_OTHER,
            ):
                # who wins when type is specific but keywords don't support the evidence?
                self.estimated_type = self.direct_type
            else:
                self.estimated_type = kw_type
        elif (
            self.direct_type is InputType.CHECKBOX_OTHER
            or self.direct_type is InputType.RADIO_OTHER
        ):
            self.estimated_type = self._match_box_type()
        elif (
            self.direct_type is InputType.BUTTON_OTHER
            or self.direct_type is InputType.BUTTON_SUBMIT
        ):
            self.estimated_type = self._match_button_type()

    def __str__(self) -> str:
        return f"[tag={self.tag_name}, html_type={self.direct_type}, estimated_type={self.estimated_type}]"

    def __repr__(self) -> str:
        return str(self)

    def _blacklist_label(self, tag: Tag, count: int = 0) -> bool:
        regex = re.compile("[0-9]+::.*")
        used_labels = tag.find_all(attrs={"data-enfbots-label": regex})
        if regex.match(get_attr(tag, "data-enfbots-label", "")):
            used_labels.append(tag)

        for u in used_labels:
            parts = u.get("data-enfbots-label").split("::")
            count_other, uuid_other = int(parts[0]), parts[1]
            if count_other > count:
                self.form.rejected_labels.add(uuid_other)
            else:
                return False
        tag["data-enfbots-label"] = f"{count}::{self.uuid}"
        return True

    def _get_label(self) -> Optional[str]:
        if self.direct_type is InputType.HIDDEN:
            return None

        # should only be called once per input (it modifies the blacklist attrs)
        # try to find a label using the for attribute
        if self.id:
            label = typing.cast(Tag, self.form.tag.find("label", attrs={"for": self.id}))
            if label:
                self._blacklist_label(label, count=0)
                return self._extract_strings(label, assert_length=False)

        # TODO could add rules for matching the closest text on the page, would need a selenium attribute instead of bs4

        # try to find the closes label in the hierarchy
        # go through a few levels prioritizing previous sibilings over next sibilings
        # label should be between 4 characters and 3 lines, reject others
        level = self.element

        parent_label: Optional[Tag] = None
        if level.parent and level.parent.name == "label":
            parent_label = level.parent

        queue = itertools.chain(
            (
                parent_label,
                level,
            ),
            level.find_previous_siblings(True),
            (None,),
            level.find_next_siblings(True),
        )
        count = 0
        for i in range(3):
            for e in queue:
                if e is None:
                    count += 1

                if isinstance(e, Tag):
                    count += 2
                    strings = self._extract_strings(e)
                    if strings and self._blacklist_label(e, count):
                        return strings
            if level.parent and level.parent.name != "form":
                level = level.parent
                queue = itertools.chain((level,), level.previous_siblings, level.next_siblings)
            else:
                break
        return None

    def _get_is_required(self) -> bool:
        """
        Load required attribute of this class
        """
        return (
            self.element.get("required") is not None
            or self.element.get("aria-required") == "true"
            or (self.label and "*" in self.label)
            or self.element.get("data-validation") == "required"
        )

    def _get_is_prechecked(self) -> bool:
        """
        Load required attribute of this class
        """
        return self.element.get("checked") is not None

    def _get_direct_type(self) -> InputType:
        """
        Get HTML type of an input
        """

        tag_name = self.element.name
        html_type = self.element.get("type", "").lower()  # type: ignore

        if tag_name == "button":
            if html_type == "submit":
                return InputType.BUTTON_SUBMIT
            return InputType.BUTTON_OTHER
        elif tag_name == "select":
            return InputType.SELECT_OTHER
        elif tag_name == "textarea":
            return InputType.TEXT_OTHER

        if html_type == "button":
            return InputType.BUTTON_OTHER
        if html_type == "color":
            return InputType.COLOR
        if html_type == "file":
            return InputType.FILE
        if html_type == "hidden":
            return InputType.HIDDEN
        if html_type == "image":
            return InputType.IMAGE
        if html_type == "range":
            return InputType.RANGE
        if html_type == "reset":
            return InputType.RESET
        if html_type == "search":
            return InputType.SEARCH
        if html_type == "submit":
            return InputType.BUTTON_SUBMIT
        if html_type == "url":
            return InputType.URL
        if html_type == "radio":
            return InputType.RADIO_OTHER
        if html_type == "checkbox":
            return InputType.CHECKBOX_OTHER
        if html_type == "email":
            return InputType.MAIL
        if html_type == "password":
            return InputType.PASSWORD
        if html_type == "tel":
            return InputType.PHONE
        if html_type == "number":
            return InputType.NUMBER_OTHER

        return InputType.TEXT_OTHER

    def _match_text_type(self) -> InputType:
        e = self.element

        # try to match the autocomplete attribute
        autocomplete = get_attr(e, "autocomplete")
        if autocomplete and autocomplete in input_autocomplete_mapping:
            return input_autocomplete_mapping[autocomplete]

        # class attribute is sometimes a string and sometimes a list, this is safer
        clazz = get_attr(e, "class")
        strings = filter_none(
            (
                self.label,
                get_attr(e, "placeholder"),
                get_attr(e, "title"),
                get_attr(e, "name"),
                self.id if not self.id == self.uuid else None,
                get_attr(e, "value"),
                clazz,
            )
        )
        # TODO can match select on the basis of options

        self.match_string = " ".join([i if i else "" for i in strings])
        possible_types = keyword_classify(
            text_keyword_mapping,
            strings,
            match_keywords_lemmatized,
            self.lang,
            Config().MIN_KW_MATCH_LEN,
        )

        if len(possible_types) == 0:
            return self.direct_type
        return max(possible_types, key=lambda x: x[1])[0]

    def _match_box_type(self) -> InputType:
        e = self.element
        # class attribute is sometimes a string and sometimes a list, this is safer
        clazz = get_attr(e, "class")
        strings = filter_none(
            (self.label, get_attr(e, "name"), get_attr(e, "id"), get_attr(e, "title"), clazz)
        )
        self.match_string = " ".join([i if i else "" for i in strings])

        scores = keyword_score(
            checkbox_keyword_mapping,
            strings,
            match_keywords_lemmatized,
            self.lang,
            Config().MIN_KW_MATCH_LEN,
        )
        pp_tos = scores[InputType.CHECKBOX_PP] + scores[InputType.CHECKBOX_TOS]
        pp_tos_email = pp_tos + scores[InputType.CHECKBOX_EMAIL]

        max_type, max_score = max(scores.items(), key=lambda x: x[1])
        if pp_tos_email > pp_tos > max_score:
            return InputType.CHECKBOX_PP_TOS_EMAIL
        if pp_tos > max_score:
            return InputType.CHECKBOX_PP_TOS

        if max_score == 0:
            return self.direct_type

        return max_type

    def _match_button_type(self) -> InputType:
        e = self.element
        clazz = get_attr(e, "class")
        strings = filter_none(
            (
                self.label,
                get_attr(e, "name"),
                get_attr(e, "id"),
                get_attr(e, "title"),
                get_attr(e, "value"),
                clazz,
            )
        )
        self.match_string = " ".join([i if i else "" for i in strings])

        possible_types = keyword_classify(
            button_keyword_mapping,
            strings,
            match_keywords_lemmatized,
            self.lang,
            Config().MIN_KW_MATCH_LEN,
        )

        if len(possible_types) == 0:
            return self.direct_type
        return max(possible_types, key=lambda x: x[1])[0]

    @staticmethod
    def _extract_strings(e: PageElement, assert_length: bool = True) -> Optional[str]:
        strings = []

        for s in e.strings:  # type: ignore
            if s.parent and s.parent.name == "option":
                continue
            t = s.strip()
            if t:
                strings.append(t)

        if assert_length:
            n = sum(len(s) for s in strings)
            if n > 50 or (n > 30 and len(strings) > 4):
                # we have gone too far probably
                return None
            if n <= 3:
                return None

        return " ".join(strings)
