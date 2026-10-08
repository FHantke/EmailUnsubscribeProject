from pathlib import Path
from typing import Optional
import logging
import os

from hyperlink import URL

from enfbots_crawler.languages import get_supported_languages

from enfbots_crawler.helper import Singleton


class Config(metaclass=Singleton):
    """
    Configuration of the crawler. There can only exist ONE object
    of this Configuration.
    Be sure to call 'load()' before using an configuration through environment variables!
    """

    __metaclass__ = Singleton

    def __init__(self) -> None:
        super().__init__()
        self.reset()

    def reset(self) -> None:
        # default configuration
        self.code_dir = Path(__file__).parent
        self.root_dir = self.code_dir.parent

        # Contains the directory where the languages are stored
        # which are used to classify pages and input forms
        self.language_dir = Path(__file__).parent.joinpath("languages")

        self.ENV = "dev"
        self.LOG_LEVEL = logging.INFO

        # Crawl settings
        self.CRAWL_ID: str = ""

        self.BROWSER = "chrome"

        self.ALLOW_SCREENSHOTS = True

        # Firefox settings
        self.GECKO_DRIVER_PATH = self.root_dir / "resources/geckodriver"
        self.GECKO_LOG_PATH = self.root_dir / "geckodriver.log"
        self.FIREFOX_PROFILE_PATH = self.root_dir / "resources/firefox_profile"

        # Chrome settings
        self.CHROME_DRIVER_PATH = self.root_dir / "resources/chromedriver"
        self.CHROME_BROWSER_PATH = self.root_dir / "chrome"
        self.CHROME_PROFILE_PATH = self.root_dir / "resources/chrome_profile"
        # Disable SHM usage (Docker gitlab mostly)
        self.CHROME_DISABLE_SHM = False

        # Database settings
        # Supported values "sqlite" or "postgres"
        self.DB_TYPE: str = "sqlite"
        self.DB_PATH: str = str(self.root_dir / "crawl.sqlite")
        self.DB_HOST: str = ""
        self.DB_PORT: int = 5432
        self.DB_NAME: str = ""
        self.DB_USERNAME: str = ""
        self.DB_PASSWORD: str = ""

        # Name of this crawler implementation
        self.crawler_name = "enfbots"

        self.credentials_dir = Path(__file__).parent.joinpath("credentials")
        self.code_dir = Path(__file__).parent

        # If we should try to create an account
        self.CREATE_ACCOUNT = True

        # Intervall between the polls if a new email was received
        self.EMAIL_VERIFY_POLL_INTERVAL = 5
        # Total time in seconds to wait for a verification email
        self.EMAIL_VERIFY_TIMEOUT = 300

        # If we should await a verification email
        self.AWAIT_VERIFY_EMAIL = True
        self.VERIFY_EMAIL_ON_REQUEST = True

        # DEFAULT SETTINGS

        # First try to subscribe to a newsletter, before registering
        self.NEWSLETTER_FIRST = False

        # Collect privacy policies, terms, US privacy notices and GDPR pages. If False the crawler
        # only visits newsletter pages to find sign-up forms and skips all policy work.
        self.COLLECT_LEGAL_TEXTS = True

        # This is used to classify pages (their markdown content) as beeing a PP/TC or not.
        self.USE_CLASSIFIER: bool = False
        self.CLASSIFY_SERVICE_ENDPOINT: str = ""
        self.CLASSIFY_SERVICE_USER: str = ""
        self.CLASSIFY_SERVICE_TOKEN: str = ""

        # Minimum score a provacy policy page needs to be classified without using the classifier
        self.MIN_SCORE_KEYWORD_CLASSIFY_PP = 1.2

        # Minimum score a terms and conditions page needs to be classified without using the classifier
        self.MIN_SCORE_KEYWORD_CLASSIFY_TC = 0.8

        # Minimum amount of characters a PP/TC needs to be considered one
        self.MIN_CHARS_DOCUMENT = 60

        # One of faus / abela / "tielo" / "samsa"
        self.CREDENTIALS = "samsa"

        # If the last crawl is less days in the past than RECRAWL_AFTER_DAYS
        # the crawler will only validate the links of this latest crawl
        self.RECRAWL_AFTER_DAYS = 90

        self.LOG_PATH = self.root_dir / "enfbots_crawler.log"
        self.OUTPUT_LOG = (
            True  # If true we'll put separate log files into each website's output folder
        )
        self.DOMAIN_BLACKLIST: Optional[Path] = None
        self.BLACKLIST_RUSSIAN: bool = False
        self.BLACKLIST_LOCATIONS: list[str] = []

        # Time to wait for one page to load
        self.PAGE_TIMEOUT_SEC = 120

        # How long to wait for a get request to complete (in seconds)
        self.TIMEOUT_SHORT = 5

        self.PP_CLASSIFIER_PATH = self.root_dir / "resources/pp_classifier"

        # LibreTranslate
        self.LIBRE_TRANSLATE_ENDPOINT: str = ""

        # Language detection and PP text extraction
        # Minimal confidence for the language detection (in percent)
        self.MIN_CONFIDENCE_LANGUAGE_DETECTION = 75

        # Number of characters the extracted policy should contain at least
        self.MIN_LENGTH_POLICY_TEXT = 100

        # Keywords setup
        # minimal length of a match (to ignore 'ort' in 'passwort' or 'tel' in 'erstellen')
        # 3 filters 'tel' but keeps 'mail'
        self.MIN_KW_MATCH_LEN = 3

        # Storage configuration
        self.OUTPUT_PATH = self.root_dir / f"{self.crawler_name}_output"

        # If true we download relevant websites (PP, TC) as markdown to disk
        # It is always stored in the database
        self.STORE_MARKDOWN = True

        # Browsing language - independent of multilingual browsing
        # ATTENTION: This order indicates how preferable a language is (descending order) and has to be in ISO 639-1 format!
        self.BROWSER_LANGUAGE = ",".join(get_supported_languages())

        # Mail configuration
        self.SYBIL_URL: URL = URL.from_text("")
        self.SYBIL_MAIL_DOMAIN: str = ""
        self.SYBIL_ID: int = -1
        self.SYBIL_AUTH_TOKEN: str = ""

        # Whether the confirmation script should run from DB or path
        self.SYBIL_DB_LIVE: bool = True
        self.SYBIL_LOAD_FAST: bool = True

        # Mail confirmation script
        self.SYBIL_DB_EXPORT_PATH: str = ""
        # Skip delayed verification
        self.SYBIL_SKIP_LATER_VERIFICATION: bool = False

        # CaptchaSolver Settings
        self.CAPTCHA_ALLOW_STUB = True
        self.CAPTCHA_BACKEND = "twocaptcha"
        self.AZ_KEY: str = ""
        self.ITA_ACCESS_TOKEN: str = ""
        self.TWOCAPTCHA_ACCESS_TOKEN: str = ""

        self.DEV_VERIFY_SSL = True

        # Display backend xvfb/xephyr/native
        self.DISPLAY_BACKEND = "xvfb"

        # Email alerts
        self.ALERT_EMAIL_USERNAME: str = ""
        self.ALERT_EMAIL_PASSWORD: str = ""
        self.ALERT_EMAIL_RECIPIENTS: str = ""
        self.ALERT_EMAIL_SERVER: str = ""

        # Extra services
        self.NGROK_AUTH_TOKEN: str = ""

        # Search for the PP/TC via duckduckgo
        # valid: "always", "missing", "never"
        self.USE_SEARCH: str = "never"

        # Service to check if a website is safe according to
        # google
        self.USE_SAFE_BROWSING_API: bool = True
        self.GOOGLE_API_KEY: str = ""

        self.FORBIDDEN_NEWSLETTER_DOMAINS: str = ",".join(
            [
                "wordfence.com",
                "freewar.de",
                "rapidmail.de",
                "hotjar.com",
                "zoom.us",
                "gazeta.pl",
                "cookieyes.com",
                "hubit.de",
                "nabu.de",
                "myshopify.com",
                "leagueoflegends.com",
                "mailgun.com",
                "onet.pl",
                "cookiedatabase.org",
                "activecampaign.com",
                "uni-leipzig.de",
                "amazon.com",
                "ebay.com",
            ]
        )

        # The popolar paths are tried on all websites where no PP/TC is found.
        # In the language files are also paths that are tried when the language
        # of the given website matches and no PP/TC was found.
        self.POPULAR_PP_PATHS: str = ",".join(
            [
                "privacy",
                "privacy-policy",
            ]
        )

        self.POPULAR_TC_PATHS: str = ",".join(
            [
                "terms",
                "policies/terms-of-service",
                "terms-of-use",
            ]
        )

    def load(self) -> bool:
        """Loads the Config via loading all environment variables starting with CRAWLER_{setting}.

        Returns:
            bool: Success if configuration was loaded and else False (i.e. if configuration was made that does not exist)
        """
        # Override config using ENV variables (works for int, str, bool and Path)
        for k, v in os.environ.items():
            if k.startswith("CRAWLER_"):
                status = self.set(k[8:], v)
                if not status:
                    return False
        return True

    def get_db_url(self, informative: bool = False) -> str:
        """
        Get the database URL to connect to.

        Args:
            informative (bool, optional): If true the password will be censored. Defaults to False.
        """
        if self.DB_TYPE == "sqlite":
            return f"sqlite:///{self.DB_PATH}"
        elif self.DB_TYPE == "postgres" or self.DB_TYPE == "postgresql":
            if informative:
                return f"postgresql+psycopg2://{self.DB_USERNAME}:<REMOVED>@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            else:
                return f"postgresql+psycopg2://{self.DB_USERNAME}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        raise RuntimeError("Unsupported DB type: " + self.DB_TYPE)

    def set(self, key: str, new_value: str) -> bool:
        if not hasattr(self, key):
            logging.error("Tried to set unknown key %s to %s", key, new_value)
            return False

        current_value = getattr(self, key)
        logging.debug("Current value of %s is %s, will be set to %s", key, current_value, new_value)
        if callable(current_value) or key.startswith("_") or key[0].islower():
            logging.warning("Tried to set bad key %s to %s", key, new_value)
            return False

        if isinstance(current_value, str):
            setattr(self, key, new_value)
            return True
        if isinstance(current_value, bool):
            possible_true = ["true", "y", "yes", "1"]
            v = new_value.lower() in possible_true
            setattr(self, key, v)
            return True
        if isinstance(current_value, int):
            if key == "LOG_LEVEL":
                new_value = new_value.strip().upper()
                if new_value in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                    setattr(self, key, logging.getLevelName(new_value))
            else:
                setattr(self, key, int(new_value))
            return True
        if isinstance(current_value, float):
            setattr(self, key, float(new_value))
            return True
        if isinstance(current_value, Path) or key == "DOMAIN_BLACKLIST":
            path = Path(new_value)
            if not path.is_absolute():
                path = path.relative_to(self.code_dir)
            setattr(self, key, path)
            return True
        if isinstance(current_value, URL):
            url = URL.from_text(new_value)
            setattr(self, key, url)
            return True
        if isinstance(current_value, list):
            arr = [x.strip().lower() for x in new_value.split(",")]
            setattr(self, key, arr)
            return True

        logging.warning("Setting not found: %s", key)
        return False

    def __str__(self) -> str:
        s: str = "Configuration: {\n"
        for setting in sorted(self.__dict__):
            value = self.__dict__[setting]
            if (
                value != ""
                and not setting.__contains__("PASSWORD")
                and not setting.__contains__("TOKEN")
            ):
                s += "  " + setting + ": " + str(value) + "\n"
        s += "}"
        return s
