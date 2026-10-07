"""
contains the regform class as well as some form tag related procedures
"""
from __future__ import annotations

import logging
from collections import Counter

# Const
from typing import Optional

from bs4.element import Tag, ResultSet

# Imports from the enfbots library
from enfbots_crawler.helper import get_attr, filter_none
from enfbots_crawler.languages import KeywordType, Language

# Imports from this crawler implementation
from enfbots_crawler import InputType, FormType, Config
from enfbots_crawler.input_bs import InputBS
from enfbots_crawler.keyword_matching import match_keywords_lemmatized, keyword_classify

logger = logging.getLogger("enfbots_crawler")

form_keyword_mapping = {
    FormType.LOGIN: KeywordType.LOGIN,
    FormType.REGISTER: KeywordType.REGISTRATION,
    FormType.NEWSLETTER: KeywordType.NEWSLETTER,
    FormType.CONTACT: KeywordType.CONTACT,
}


class FormBS:
    def __init__(
        self,
        tag: Tag,
        lang: Language = Language.get(Config().language_dir, "en"),
        input_info: dict[str, bool] | None = None,
    ) -> None:
        self.tag = tag
        self.lang = lang
        self.id: Optional[str] = get_attr(tag, "id")
        self.uuid: Optional[str] = get_attr(tag, "data-enfbots-uuid")

        self.input_info = input_info
        self.input_tags = self._get_input_tags()
        self.rejected_labels: set[str] = set()

        self.inputs: list[InputBS] = []
        self.hidden_inputs: list[InputBS] = []

        for i in self.input_tags:
            input_bs = InputBS(self, i)
            if input_bs.direct_type == InputType.HIDDEN:
                self.hidden_inputs.append(input_bs)
            else:
                self.inputs.append(input_bs)

        for inp in self.inputs:
            if inp.uuid in self.rejected_labels:
                inp.label = None
                inp.estimate_type()

        self.input_counts = Counter([e.estimated_type for e in self.inputs if e.visible])
        self.type = self.classify_form()

    def __str__(self) -> str:
        return f"FormBS [id={self.id}, type={self.type.name}]"

    def classify_form(
        self, allow_mailless: bool = False, allow_verification: bool = False
    ) -> FormType:
        """
        second_pass allows forms not to contain emails and classifies verifications codes
        """
        return self._classify_decision_tree(allow_mailless, allow_verification)

    def equality_score(self, other: FormBS) -> int:
        score = 0
        if self.uuid and self.uuid == other.uuid:
            # this is true up to UUID uniqueness
            score -= 10000

        # if they have different natural ids
        has_natural_id = self.uuid != self.id
        if has_natural_id and self.id != other.id:
            score += 3

        if self.type != other.type:
            score += 2

        if get_attr(self.tag, "action") != get_attr(other.tag, "action"):
            score += 1

        if get_attr(self.tag, "name") != get_attr(other.tag, "name"):
            score += 1

        other_classes = get_classes(other.tag)
        for cls in get_classes(self.tag):
            if cls not in other_classes:
                score += 1

        for typ, count in self.input_counts.items():
            score += abs(count - other.input_counts[typ])

        return score

    def _get_input_tags(self) -> ResultSet:
        return self.tag.find_all(["input", "textarea", "select", "button"])

    def _match_form_type(self) -> FormType:
        e = self.tag

        strings = filter_none((get_attr(e, "name"), get_attr(e, "id"), get_attr(e, "class")))

        possible_types = keyword_classify(
            form_keyword_mapping,
            strings,
            match_keywords_lemmatized,
            self.lang,
            Config().MIN_KW_MATCH_LEN,
        )

        if len(possible_types) == 0:
            return FormType.OTHER
        return max(possible_types, key=lambda x: x[1])[0]

    def _is_in_footer(self) -> bool:
        level: Optional[Tag] = self.tag
        while level is not None and level.name != "body" and level.name != "html":
            if (
                level.name == "footer"
                or "footer" in get_attr(level, "class", "")
                or "footer" in get_attr(level, "id", "")
            ):
                return True
            level = level.parent
        return False

    def _classify_decision_tree(self, allow_mailless: bool, allow_verification: bool) -> FormType:
        # TODO this is where machine learning sounds amazeballs
        counts = self.input_counts
        keyword_type = self._match_form_type()

        if counts[InputType.VERIFY_CODE] > 0 and allow_verification:
            return FormType.VERIFICATION

        if (
            counts[InputType.PASSWORD] == 0
            and counts[InputType.MAIL] == 0
            and counts[InputType.SEARCH] > 0
        ):
            return FormType.SEARCH

        # tags that are most common in registration and not in other forms
        common_tags = [
            InputType.PHONE,
            InputType.TITLE,
            InputType.FULL_NAME,
            InputType.BIRTH_FULL,
            InputType.BIRTH_MONTH,
            InputType.BIRTH_DAY,
            InputType.BIRTH_YEAR,
            InputType.CITY,
            InputType.FULL_ADDRESS,
            InputType.STREET,
            InputType.STREET_FULL,
            InputType.STREET_NR,
        ]
        common_count = sum(self.input_counts[t] for t in common_tags)

        if counts[InputType.PASSWORD] > 0:
            if (counts[InputType.PASSWORD]) > 1:
                return FormType.REGISTER
            if common_count >= 2:
                return FormType.REGISTER
            if counts[InputType.PASSWORD] == 1 and (
                (counts[InputType.MAIL] == 1) != (counts[InputType.USERNAME] == 1)
            ):
                if common_count <= 1:
                    # allow at most one "reg input" for login
                    # if there is just one username/email field and a password field its probably a login button
                    if (
                        counts[InputType.BUTTON_LOGIN] == 0
                        and counts[InputType.BUTTON_REGISTRATION] > 0
                    ):
                        if not keyword_type or keyword_type == FormType.REGISTER:
                            return FormType.REGISTER

                    return FormType.LOGIN
            return FormType.REGISTER

        if counts[InputType.MAIL] > 0 or allow_mailless:
            if self._is_in_footer():
                return FormType.NEWSLETTER

            # multistep forms
            if keyword_type in (FormType.OTHER, FormType.REGISTER) and (
                common_count >= 3 or counts[InputType.USERNAME] > 0
            ):
                return FormType.REGISTER

            if counts[InputType.BUTTON_CONTACT] > 0 or keyword_type == FormType.CONTACT:
                return FormType.CONTACT

            # another low prio form, most common when multistep is possible
            # cannot use keyword match since most keywords would also match newsletter
            if counts[InputType.BUTTON_REGISTRATION] > 0:
                return FormType.REGISTER

            return FormType.NEWSLETTER

        if counts[InputType.SEARCH] > 0:
            return FormType.SEARCH

        return FormType.OTHER


def get_classes(tag: Tag) -> list[str]:
    clazz = get_attr(tag, "class")
    if clazz:
        return [c.strip() for c in clazz.split(" ")]
    return []
