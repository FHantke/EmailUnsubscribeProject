from __future__ import annotations

from enum import Enum, IntEnum, auto


class PageType(IntEnum):
    """Type of the pages, values are important for sorting in the Navigator.
    The bigger the number, the higher the importance"""

    INDEX = 99
    OTHER = 100
    SUSPICIOUS = 101
    TERMS = 102
    US_PN = 103
    GDPR = 104
    POLICY = 105
    NEWSLETTER = 106
    LOGIN = 107
    REGISTER = 108


class PageState(Enum):
    """
    Enum to represent state of index page
    """

    # When the domain name cannot be resolved
    DNS_ERROR = 15

    # Everything OK
    OK = 0
    REDIRECT = 2
    TIMEOUT = 3
    BAD_CONTENT_TYPE = 11
    HTTP_ERROR = 12
    TCP_ERROR = 13
    UNKNOWN_ERROR = 14


class DomainStatus(Enum):
    DNS_ERROR = auto()
    OK = auto()
    BLACKLISTED = auto()
    UNSAFE = auto()
    OK_RUSSIAN = auto()
    LOCATION_BLOCKED = auto()


class ConsiderationBasis(Enum):
    """
    Enum to classify on what basis we can say that this URL is (or is not) of the
    given type.
    """

    # Decided via the classifier
    CLASSIFIER = auto()

    # Decided because the keyword matching score was high enough
    KEYWORD_MATCHING = auto()

    KEYWORD_MATCHING_CLASSIFIER = auto()

    # Found via duckduckgo
    SEARCH = auto()

    SEARCH_CLASSIFIER = auto()

    KEYWORD_MATCHING_SEARCH = auto()

    # The text is too short
    TOO_SHORT_TEXT = auto()

    # No basis for this decision. Needed to gather some true negatives
    NONE = auto()

    # Unknown. Currently not used.
    UNKNOWN = auto()

    # It's a popular path
    POPULAR = auto()

    POPULAR_CLASSIFIER = auto()

    # Previously found and now only checked if it is still existing
    CACHED = auto()

    def __add__(self, other: ConsiderationBasis) -> ConsiderationBasis:
        assert not (other == ConsiderationBasis.POPULAR and self == ConsiderationBasis.SEARCH)
        assert not (self == ConsiderationBasis.POPULAR and other == ConsiderationBasis.SEARCH)

        if self == other:
            return self

        if self == ConsiderationBasis.NONE:
            return other

        # If it is cached we keep the consideration basis of cached
        if self == ConsiderationBasis.CACHED and other == ConsiderationBasis.KEYWORD_MATCHING:
            return self

        if self == ConsiderationBasis.CLASSIFIER:
            if other == ConsiderationBasis.KEYWORD_MATCHING:
                return ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER
            if other == ConsiderationBasis.SEARCH:
                return ConsiderationBasis.SEARCH_CLASSIFIER
            if other == ConsiderationBasis.POPULAR:
                return ConsiderationBasis.POPULAR_CLASSIFIER
        if other == ConsiderationBasis.CLASSIFIER:
            if self == ConsiderationBasis.KEYWORD_MATCHING:
                return ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER
            if self == ConsiderationBasis.SEARCH:
                return ConsiderationBasis.SEARCH_CLASSIFIER
            if self == ConsiderationBasis.POPULAR:
                return ConsiderationBasis.POPULAR_CLASSIFIER

        if self == ConsiderationBasis.KEYWORD_MATCHING:
            if other == ConsiderationBasis.SEARCH:
                return ConsiderationBasis.KEYWORD_MATCHING_SEARCH
            if other == ConsiderationBasis.POPULAR:
                return ConsiderationBasis.POPULAR

        if other == ConsiderationBasis.KEYWORD_MATCHING:
            if self == ConsiderationBasis.SEARCH:
                return ConsiderationBasis.KEYWORD_MATCHING_SEARCH
            if self == ConsiderationBasis.POPULAR:
                return ConsiderationBasis.POPULAR

        if self == ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER:
            if other == ConsiderationBasis.CLASSIFIER:
                return ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER
        if self == ConsiderationBasis.CLASSIFIER:
            if other == ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER:
                return ConsiderationBasis.KEYWORD_MATCHING_CLASSIFIER

        if (self == ConsiderationBasis.SEARCH and other == ConsiderationBasis.POPULAR) or (
            other == ConsiderationBasis.SEARCH and self == ConsiderationBasis.POPULAR
        ):
            raise RuntimeError("This cannot happen. SEARCH and POPULAR")

        if (
            self == ConsiderationBasis.POPULAR_CLASSIFIER and other == ConsiderationBasis.CLASSIFIER
        ) or (
            other == ConsiderationBasis.POPULAR_CLASSIFIER and self == ConsiderationBasis.CLASSIFIER
        ):
            return ConsiderationBasis.POPULAR_CLASSIFIER

        raise RuntimeError(f"Missing case: {self} and other {other}")


class MailType(Enum):
    """
    Classification of emails
    """

    CONFIRMATION = 0
    MARKETING = 1
    OTHER = 2
    MARKETING_NOTIFICATION = 3
    MARKETING_NEWSLETTER = 4
    MARKETING_SURVEY = 5
    MARKETING_SPAM = 6
    SERVICING_OPT_IN = 7
    SERVICING_CONFIRMATION = 8
    SERVICING_UPDATES = 9


class CaptchaType(Enum):
    """
    Enum to represent the different Captchas
    """

    NONE = auto()
    ReCAPTCHAv2 = auto()
    ReCAPTCHAv3 = auto()
    HCaptcha = auto()
    IMAGE = auto()


class UserSkipped(Enum):
    """
    Mark, if user skipped the website and if so, from what reason?
    """

    NOT = 0
    LANG = 1
    PAYMENT = 2
    INAPPROPRIATE = 3
    REPEATED = 4
    NO_REG = 5
    OTHER = 6


class InputType(Enum):
    """
    Enum to represent the different form element types
    """

    UNKNOWN = auto()
    OTHER = auto()
    MAIL = auto()
    USERNAME = auto()
    PASSWORD = auto()
    PHONE = auto()
    TITLE = auto()
    FIRST_NAME = auto()
    LAST_NAME = auto()
    FULL_NAME = auto()
    STREET = auto()
    STREET_NR = auto()
    STREET_FULL = auto()
    CITY = auto()
    ZIP = auto()
    COUNTRY = auto()
    FULL_ADDRESS = auto()
    BIRTH_DAY = auto()
    BIRTH_MONTH = auto()
    BIRTH_YEAR = auto()
    BIRTH_FULL = auto()
    AGE = auto()
    HONORIFIC_PREFIX = auto()
    MIDDLE_NAME = auto()
    ORGANIZATION = auto()
    SEX = auto()
    NUMBER_OTHER = auto()

    CHECKBOX_OTHER = auto()
    CHECKBOX_PP = auto()
    CHECKBOX_TOS = auto()
    CHECKBOX_PP_TOS = auto()
    CHECKBOX_PP_TOS_EMAIL = auto()
    CHECKBOX_EMAIL = auto()
    CHECKBOX_SMS = auto()
    CHECKBOX_AGE = auto()

    RADIO_OTHER = auto()

    SELECT_OTHER = auto()

    TEXT_OTHER = auto()

    COLOR = auto()
    FILE = auto()
    HIDDEN = auto()
    IMAGE = auto()
    RANGE = auto()
    RESET = auto()
    SEARCH = auto()
    URL = auto()

    CAPTCHA_INPUT = auto()
    VERIFY_CODE = auto()
    HONEYPOT = auto()

    BUTTON_OTHER = auto()
    BUTTON_SUBMIT = auto()
    BUTTON_LOGIN = auto()
    BUTTON_REGISTRATION = auto()
    BUTTON_CONTACT = auto()
    BUTTON_SUBSCRIBE = auto()


class FormType(Enum):
    """Type of a single form on the site"""

    SKIPPED = auto()
    NOT_ANNOTATED = auto()
    LOGIN = auto()
    REGISTER = auto()
    NEWSLETTER = auto()
    SEARCH = auto()
    OTHER = auto()
    CONTACT = auto()
    VERIFICATION = auto()


class State(Enum):
    LANGUAGE_SELECTED = auto()
    NEWSLETTER_FORM_FOUND = auto()
    NEWSLETTER_SUCCESSFUL = auto()
    NEWSLETTER_FAILED = auto()
    NEWSLETTER_ERRORED = auto()
    REGISTER_PAGE_FOUND = auto()
    REGISTER_FORM_NOT_FOUND = auto()
    REGISTER_FORM_FOUND = auto()
    REGISTER_SUCCESSFUL = auto()
    REGISTER_FAILED = auto()
    REGISTER_ERRORED = auto()
    LOGIN_PAGE_FOUND = auto()
    POLICY_PAGE_FOUND = auto()
    POLICY_CONTENT_FOUND = auto()
    TERMS_PAGE_FOUND = auto()
    TERMS_CONTENT_FOUND = auto()
    US_PN_CONTENT_FOUND = auto()
    GDPR_CONTENT_FOUND = auto()
    INDEX_LOAD_FAILED = auto()
    UNSUPPORTED_LANGUAGE = auto()
    NO_LANGUAGE_DETECTED = auto()
    FORM_ID_MISMATCH = auto()
    MULTIPLE_REGISTRATION_FORMS = auto()
    MULTIPLE_NEWSLETTERS_FORMS = auto()
    FORM_STALE_ERROR = auto()
    FORM_UNKNOWN_ERROR = auto()
    SUSPICIOUS_PAGE_FOUND = auto()
    SUBMITTING_HALF_REQUIRED = auto()
    MULTI_STAGE_FORM = auto()
    INDEX_DOMAIN_REDIRECT = auto()
    FORM_ML_SUCCESS = auto()
    FORM_ML_FAILED = auto()
    VIOLATIONS_DET_SUCCESS = auto()
    VIOLATIONS_DET_FAILED = auto()


class FormStatus(IntEnum):
    pass


class ExtraStatus(FormStatus):
    SUBMIT_HALF_REQUIRED = auto()
    SUBMIT_INPUT = auto()
    SUBMIT_BUTTON = auto()
    SUBMIT_JS = auto()


class RegistrationStatus(FormStatus):
    UNKNOWN = 0
    SUCCESS_REDIRECT = 1
    SUCCESS_KEYWORDS = 2
    VERIFICATION_CODE_REQUESTED = 3
    FAILURE_SAME_FORM = -1
    FAILURE_KEYWORDS = -2
    FAILURE_FALLBACK = -3
    FAILURE_NOT_FOUND = -4
    MULTI_STAGE_FORM = -5


class EmailVerificationStatus(FormStatus):
    UNKNOWN = 0
    SUCCESS_ACTIVATION = 1
    SUCCESS_VERIFICATION_CODE = 2
    SUCCESS_RECEIVED_EMAIL = 3
    FAILURE_ACTIVATION = -1
    FAILURE_VERIFICATION_CODE = -2
    FAILURE_NO_EMAIL = -3
    FAILURE_LINK_FAIL_KEYWORD = -4
    FAILURE_LINK_NO_KEYWORD = -5
    FAILURE_REACHING_SYBILMAIL = -6


class EmailOptIn(Enum):
    DOUBLE_OPT_IN = auto()
    SINGLE_OPT_IN = auto()
    NO_OPT_IN = auto()


class EmailPassword(Enum):
    USER_PASSWORD = auto()
    GENERATED_PASSWORD = auto()
    PASSWORD_SET_LINK = auto()
    NO_PASSWORD = auto()
