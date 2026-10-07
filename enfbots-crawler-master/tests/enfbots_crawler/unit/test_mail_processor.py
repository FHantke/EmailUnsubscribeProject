from hyperlink import URL
from lxml import etree

from enfbots_crawler import Config
from enfbots_crawler.languages import Language
from enfbots_crawler.mail_processor import Mail, _get_texts

EMAIL = """<html><body>
<style>.x { color: red }</style>
<p>View this email in your browser: https://shop.example.com/view?id=987654</p>
<p>Please confirm your subscription: https://shop.example.com/confirm?token=abc123</p>
<p>No longer interested? Unsubscribe at https://shop.example.com/unsub?id=987654</p>
<script>var tracking = 1;</script>
</body></html>"""


def test_get_texts_is_relative_to_element():
    first_paragraph = etree.HTML(EMAIL).xpath("//p")[0]

    assert [t.strip() for t in _get_texts(first_paragraph)] == [
        "View this email in your browser: https://shop.example.com/view?id=987654"
    ]


def test_get_texts_on_root_skips_style_and_script():
    text = " ".join(_get_texts(etree.HTML(EMAIL)))

    assert "confirm your subscription" in text
    assert "Unsubscribe" in text
    assert "color" not in text
    assert "tracking" not in text


def test_activation_link_scored_by_its_own_paragraph():
    # Bypass __init__, which loads a spaCy model; _extract_activation_link only reads these
    mail = Mail.__new__(Mail)
    mail.tree = etree.HTML(EMAIL)
    mail.lang = Language(Config().language_dir, "en")
    mail.domain = "example.com"

    # With whole-document context every bare URL scored the same and the first one won
    assert mail._extract_activation_link() == URL.from_text(
        "https://shop.example.com/confirm?token=abc123"
    )
