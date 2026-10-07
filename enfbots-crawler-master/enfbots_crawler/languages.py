from __future__ import annotations

import logging
from pathlib import Path
from enum import Enum, auto
from typing import Optional, Any, List, cast
from unidecode import unidecode

import lemmagen3
import yaml

import spacy
from spacy.tokens import Doc
from spacy import Vocab

# Imports from the enfbots library
from enfbots_crawler.text_helper import coerce_cyrillic, full_split


class KeywordType(Enum):
    POLICY = auto()
    TERMS = auto()
    REGISTRATION = auto()
    LOGIN = auto()
    MAIL_INPUT = auto()
    USER_INPUT = auto()
    PW_INPUT = auto()
    PHONE_INPUT = auto()
    FIRSTNAME_INPUT = auto()
    LASTNAME_INPUT = auto()
    NAME_INPUT = auto()
    STREET_INPUT = auto()
    STREET_NR_INPUT = auto()
    STREET_FULL_INPUT = auto()
    CITY_INPUT = auto()
    ZIP_INPUT = auto()
    COUNTRY_INPUT = auto()
    FULL_ADDRESS_INPUT = auto()
    BIRTH_DAY_INPUT = auto()
    BIRTH_MONTH_INPUT = auto()
    BIRTH_YEAR_INPUT = auto()
    BIRTH_FULL_INPUT = auto()
    CHECKBOX_EMAIL = auto()
    CHECKBOX_PP = auto()
    CHECKBOX_TOS = auto()
    SUBMIT = auto()
    SUBMIT_SUCCESS = auto()
    SUBMIT_FAILURE = auto()
    CONFIRM_SUCCESS = auto()
    CONFIRM_FAILURE = auto()
    LANGUAGE = auto()
    NEWSLETTER = auto()
    CONTACT = auto()
    VERIFICATION_CODE = auto()
    CONFIRMATION_EMAIL = auto()
    CONFIRMATION_LINK = auto()
    UNSUBSCRIBE = auto()
    CAPTCHA_INPUT = auto()
    SEARCH_INPUT = auto()
    TITLE_INPUT = auto()
    ORGANIZATION_INPUT = auto()
    AGE_INPUT = auto()
    HONEYPOT_INPUT = auto()
    US_PN = auto()
    GDPR = auto()
    POPULAR_PP_PATH = auto()
    POPULAR_TC_PATH = auto()


logger = logging.getLogger("enfbots_lib")


class LocaleNotFoundException(Exception):
    def __init__(self, locale: str, *args: Any) -> None:
        self.locale = locale
        super().__init__(f"Locale '{locale}' not found", *args)


_supported_languages = [
    "en",
    "de",
    "cs",
    "fr",
    "pl",
    "sq",
    "eu",
    "bs",
    "bg",
    "ca",
    "hr",
    "da",
    "nl",
    "et",
    "fi",
    "gl",
    "el",
    "hu",
    "is",
    "it",
    "lv",
    "lt",
    "lb",
    "mk",
    "mt",
    "no",
    "pt",
    "ro",
    "ru",
    "sr",
    "sk",
    "sl",
    "es",
    "sv",
    "tr",
    "uk",
    "cy",
    "hi",
    "ja",
    "ko",
    "xh",
    "zh",
    "zu",
]

_non_latin_script_codes = {"ru", "bg", "mk", "hi", "ja", "ko", "zh"}


def get_supported_languages() -> list[str]:
    return _supported_languages.copy()


class MatchString:
    def __init__(
        self, text: str, lang: Language, weight: Optional[float] = None, lemmatize: bool = True
    ):
        self.text = text
        self.words: list[str] = full_split(text)

        # Serbian uses cyrillic and latin, we coerce all text to latin before matching
        if lang.code == "sr":
            self.words = [coerce_cyrillic(w, lang.code) for w in self.words]

        self.lang = lang
        self.weight = weight

        self.lemmas: list[str] = []
        if lemmatize:
            self.lemmatize()

        # unidecode all latin-like scripts
        if not lang.should_preserve_script():
            self.text = unidecode(self.text)
            self.words = [unidecode(w) for w in self.words]
            self.lemmas = [unidecode(w) for w in self.lemmas]

    def lemmatize(self) -> None:
        for word in self.words:
            self.lemmas.extend(self.lang.lemmatize(word))

    def __repr__(self) -> str:
        return f"MatchString[{self.text}]"


class Keyword:
    def __init__(
        self,
        text: str,
        lang: Language,
        weight: Optional[float],
        kw_syntax: bool,
        lemmatize: bool,
    ):
        self.text = text
        parts = text.lower().split(" ")
        self.words: list[set[str]] = []
        if kw_syntax:
            for part in parts:
                if part.startswith("[") and part.endswith("]"):
                    self.words.append(set(part[1:-1].split("|")))
                else:
                    self.words.append({part})
        else:
            self.words = [{w} for w in full_split(text)]

        self.weight = weight if weight else 1

        self.lang = lang

        self.lemmas: list[set[str]] = []
        if lemmatize:
            self.lemmatize()

        # unidecode all latin-like scripts
        if not lang.should_preserve_script():
            self.text = unidecode(self.text)
            self.words = [{unidecode(w) for w in s} for s in self.words]
            self.lemmas = [{unidecode(w) for w in s} for s in self.lemmas]

    def lemmatize(self) -> None:
        for word_set in self.words:
            s = set()
            for word in word_set:
                try:
                    s.update(self.lang.lemmatize(word))
                except UnicodeDecodeError:
                    logger.exception(f"Lemmatizer failed for language {self.lang}, keyword {word}")
                    # Fixme: check if this bug is resolved: https://github.com/vpodpecan/lemmagen3/issues/2
            self.lemmas.append(s)

    def __repr__(self) -> str:
        return f"Keyword{self.words}"


class YourTokenizer:
    def __init__(self, vocab: Vocab) -> None:
        self.vocab = vocab

    def __call__(self, text: str) -> Doc:
        words = full_split(text)
        return Doc(self.vocab, words=words, spaces=[True] * len(words))


class Language:
    _instances: dict[str, Language] = dict()

    @staticmethod
    def get(
        language_dir: Path, code: str, load_model: bool = True, second: Optional[str] = None
    ) -> Language:
        if code in Language._instances:
            return Language._instances[code]
        lang = Language(language_dir, code, second=second)
        Language._instances[code] = lang
        if load_model:
            lang._load_model()
        return lang

    def __init__(self, language_dir: Path, code: str, second: Optional[str] = None) -> None:
        if code not in get_supported_languages():
            raise LocaleNotFoundException(code)

        self.language_dir = language_dir

        self.code = code
        self.cyrillic = code in ("ru", "bg", "mk")
        self._preserve_script = code in _non_latin_script_codes
        self.keywords = self._load_keywords()
        self._spacy: Optional[spacy.Language] = None
        self._lemmagen: Optional[lemmagen3.Lemmatizer] = None

        if code != "en":
            self.en = Language.get(self.language_dir, "en")
        self.second = Language.get(self.language_dir, second) if second else None

    def __eq__(self, o: object) -> bool:
        return isinstance(o, Language) and self.code == o.code

    def should_preserve_script(self) -> bool:
        return self._preserve_script

    def get_keywords(self, keyword_type: KeywordType) -> List[Keyword]:
        if keyword_type in self.keywords:
            words = self.keywords[keyword_type]
        else:
            words = cast(List[Keyword], list())

        if self.code == "en":
            return words

        en_words: List[Keyword] = self.en.get_keywords(keyword_type)
        snd_words: List[Keyword] = self.second.get_keywords(keyword_type) if self.second else []

        if "????" in words:
            logger.info("%s missing in language %s", keyword_type.name, self.code)
            return en_words + snd_words

        # always add english locale because many sites are coded in english
        return words + en_words + snd_words

    def get_popular_paths(self, type: KeywordType) -> List[str]:
        assert type in [KeywordType.POPULAR_PP_PATH, KeywordType.POPULAR_TC_PATH]

        if type in self.keywords:
            s: List[str] = []
            for path in self.keywords[type]:
                s.append(path.text)
            return s
        else:
            return []

    def _load_model(self) -> None:
        if self._spacy or self._lemmagen:
            return

        if self.code == "en":
            self._spacy = spacy.load("en_core_web_md", disable=["parser", "ner"])
        elif self.code == "de":
            self._spacy = spacy.load("de_core_news_md", disable=["parser", "ner"])
        elif self.code in lemmagen3.Lemmatizer.list_supported_languages():
            self._lemmagen = lemmagen3.Lemmatizer(self.code)

        if self._spacy:
            self._spacy.tokenizer = YourTokenizer(self._spacy.vocab)

        for kw_list in self.keywords.values():
            for kw in kw_list:
                kw.lemmatize()

    def lemmatize(self, word: str) -> list[str]:
        if self._spacy:
            document = self._spacy(word)
            return [w.lemma_ for w in document]

        if self._lemmagen:
            return [self._lemmagen.lemmatize(word)]

        return []

    def _load_keywords(self) -> dict[KeywordType, List[Keyword]]:
        path = self.language_dir / f"{self.code}.yaml"
        if not path.exists() or not path.is_file():
            raise LocaleNotFoundException(self.code)

        results: dict[KeywordType, List[Keyword]] = dict()
        with path.open() as file:
            try:
                parsed_yaml = yaml.safe_load(file)
                for key, value in parsed_yaml.items():
                    kws: List[Keyword] = list()
                    try:
                        typ = KeywordType[key.upper()]
                    except KeyError:
                        logger.warning("Unknown keyword type %s for language %s", key, self.code)
                        continue
                    if value:
                        try:
                            for text, weight in value.items():
                                kws.append(
                                    Keyword(
                                        text, self, weight=weight, lemmatize=False, kw_syntax=True
                                    )
                                )
                        except KeyError:
                            logger.warning(
                                "Unknown keyword type %s for language %s", key, self.code
                            )
                    results[typ] = kws
            except yaml.YAMLError as exc:
                raise RuntimeError(f"language file for {self.code} poorly formatted") from exc
        return results
