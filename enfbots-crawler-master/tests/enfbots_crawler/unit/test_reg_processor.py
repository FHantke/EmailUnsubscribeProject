from unittest.mock import MagicMock

from bs4 import BeautifulSoup
from hyperlink import URL

from enfbots_crawler import Config, RegistrationStatus
from enfbots_crawler.languages import Language
from enfbots_crawler.reg_processor import RegProcessor

BEFORE_SUBMIT = """<html><body>
<form><input type="email" name="email"><button>Subscribe</button></form>
<p>We will send you a confirmation email.</p>
</body></html>"""


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _processor(mocker) -> RegProcessor:
    mocker.patch("enfbots_crawler.reg_processor.sleep")

    # Bypass __init__, which claims an address from Sybilmail
    proc = RegProcessor.__new__(RegProcessor)
    proc.br = MagicMock()
    proc.br.find_forms.return_value = []
    proc.br.current_url = URL.from_text("https://shop.example.com/newsletter")
    proc.handling_url = proc.br.current_url
    proc.lang = Language(Config().language_dir, "en")
    proc.blocked_submit_state_keywords = []

    proc.br.get_soup.return_value = _soup(BEFORE_SUBMIT)
    proc._load_submit_success_keywords()
    return proc


def test_success_word_already_on_page_is_ignored(mocker):
    proc = _processor(mocker)
    assert "confirmation" in proc.blocked_submit_state_keywords

    # Page unchanged after submit; before the fix "confirmation" counted as success
    status, _ = proc._check_submission_success(None)

    assert status == RegistrationStatus.UNKNOWN


def test_new_success_word_after_submit_counts(mocker):
    proc = _processor(mocker)
    proc.br.get_soup.return_value = _soup("<p>Success! You are subscribed.</p>")

    status, _ = proc._check_submission_success(None)

    assert status == RegistrationStatus.SUCCESS_KEYWORDS
