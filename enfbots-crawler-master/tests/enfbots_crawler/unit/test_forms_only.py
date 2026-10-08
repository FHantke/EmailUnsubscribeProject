from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from hyperlink import URL

from enfbots_crawler import Config
from enfbots_crawler.enums import PageType
from enfbots_crawler.website import EnfbotsNavigator, UrlMatch, WebSite

BASE = URL.from_text("https://shop.example.com/")
LEGAL_TYPES = (PageType.POLICY, PageType.TERMS, PageType.US_PN, PageType.GDPR)


@pytest.fixture
def forms_only(monkeypatch):
    monkeypatch.setattr(Config(), "COLLECT_LEGAL_TEXTS", False)


def _navigator() -> EnfbotsNavigator:
    # Bypass WebSite.__init__ (browser, database); the navigator only reads these attributes
    website = SimpleNamespace(base_url=BASE, states=set(), newsletter_url=None)
    return EnfbotsNavigator(website)  # type: ignore[arg-type]


def test_forms_only_visits_only_newsletter_pages(forms_only):
    nav = _navigator()

    assert nav.is_type_needed(PageType.NEWSLETTER)
    for t in LEGAL_TYPES + (PageType.REGISTER, PageType.LOGIN, PageType.OTHER):
        assert not nav.is_type_needed(t)


def test_forms_only_does_not_queue_policy_or_account_links(forms_only):
    nav = _navigator()
    nav.add(UrlMatch(BASE.child("privacy"), PageType.POLICY, 3.0))
    nav.add(UrlMatch(BASE.child("register"), PageType.REGISTER, 3.0))
    nav.add(UrlMatch(BASE.child("login"), PageType.LOGIN, 3.0))
    nav.add(UrlMatch(BASE.child("newsletter"), PageType.NEWSLETTER, 1.0))

    assert [m.type for m in nav.links] == [PageType.NEWSLETTER]


def test_forms_only_stops_once_a_newsletter_form_is_seen(forms_only):
    nav = _navigator()
    assert not nav.is_navigation_completed()

    nav.website.newsletter_url = BASE.child("newsletter")
    assert nav.is_navigation_completed()


def test_forms_only_stops_when_newsletter_pages_are_exhausted(forms_only):
    nav = _navigator()
    nav.visited_counts[PageType.NEWSLETTER] = 3
    assert not nav.is_navigation_completed()

    nav.visited_counts[PageType.NEWSLETTER] = 4
    assert nav.is_navigation_completed()


def test_default_mode_still_collects_legal_pages():
    assert Config().COLLECT_LEGAL_TEXTS
    nav = _navigator()

    for t in LEGAL_TYPES + (PageType.LOGIN, PageType.NEWSLETTER):
        assert nav.is_type_needed(t)
    # A newsletter form alone does not end a legal crawl
    nav.website.newsletter_url = BASE.child("newsletter")
    assert not nav.is_navigation_completed()


def _site(mocker) -> WebSite:
    # Bypass __init__ (browser, database); _process_site only needs these
    site = WebSite.__new__(WebSite)
    site.navigator = MagicMock()
    site.navigator.domain_matches.return_value = True
    site.br = MagicMock()
    site.br.get_html.return_value = "<html><body>Contact: hello@shop.example.com</body></html>"
    site.emails = []
    mocker.patch.object(site, "_process_links")
    mocker.patch.object(site, "_process_forms")
    return site


def test_forms_only_page_skips_text_extraction_but_processes_forms(forms_only, mocker):
    extract = mocker.patch("enfbots_crawler.website.extract_content_from_html")
    site = _site(mocker)

    site._process_site(BASE, PageType.INDEX, 0.0)

    extract.assert_not_called()
    site._process_links.assert_called_once()
    site._process_forms.assert_called_once()
    assert ("hello", "shop.example.com", "INDEX", str(BASE)) in site.emails


def test_default_mode_page_still_extracts_text(mocker):
    extract = mocker.patch(
        "enfbots_crawler.website.extract_content_from_html", return_value="page text"
    )
    site = _site(mocker)

    site._process_site(BASE, PageType.INDEX, 0.0)

    extract.assert_called_once()
    site._process_forms.assert_called_once()


def test_forms_only_without_submitting_skips_newsletter_reload(forms_only, mocker, monkeypatch):
    monkeypatch.setattr(Config(), "CREATE_ACCOUNT", False)
    site = _site(mocker)
    site.newsletter_url = BASE.child("newsletter")

    site.process_newsletter_registration()

    site.br.load_page.assert_not_called()
