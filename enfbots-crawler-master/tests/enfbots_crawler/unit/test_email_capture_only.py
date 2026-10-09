import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from hyperlink import URL

from enfbots_crawler import Config
from enfbots_crawler.browser import LinkTuple
from enfbots_crawler.enums import PageType
from enfbots_crawler.languages import Language
from enfbots_crawler.website import EnfbotsNavigator, UrlMatch, WebSite, page_key

BASE = URL.from_text("https://shop.example.com/")
LEGAL_TYPES = (PageType.POLICY, PageType.TERMS, PageType.US_PN, PageType.GDPR)
EN = Language.get(Path("enfbots_crawler/languages"), "en")


@pytest.fixture
def capture_only(monkeypatch):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)


def _navigator() -> EnfbotsNavigator:
    # Bypass WebSite.__init__ (browser, database); the navigator only reads these attributes
    website = SimpleNamespace(
        base_url=BASE, states=set(), newsletter_url=None, eligible_capture_found=False
    )
    return EnfbotsNavigator(website)  # type: ignore[arg-type]


def test_capture_only_visits_only_newsletter_pages(capture_only):
    nav = _navigator()

    assert nav.is_type_needed(PageType.NEWSLETTER)
    for t in LEGAL_TYPES + (PageType.REGISTER, PageType.LOGIN, PageType.OTHER):
        assert not nav.is_type_needed(t)


def test_capture_only_does_not_queue_policy_or_account_links(capture_only):
    nav = _navigator()
    nav.add(UrlMatch(BASE.child("privacy"), PageType.POLICY, 3.0))
    nav.add(UrlMatch(BASE.child("register"), PageType.REGISTER, 3.0))
    nav.add(UrlMatch(BASE.child("login"), PageType.LOGIN, 3.0))
    nav.add(UrlMatch(BASE.child("newsletter"), PageType.NEWSLETTER, 1.0))

    assert [m.type for m in nav.links] == [PageType.NEWSLETTER]


def test_capture_only_stops_once_a_newsletter_form_is_seen(capture_only):
    nav = _navigator()
    assert not nav.is_navigation_completed()

    nav.website.newsletter_url = BASE.child("newsletter")
    assert nav.is_navigation_completed()


def test_capture_only_stops_when_newsletter_pages_are_exhausted(capture_only):
    nav = _navigator()
    nav.visited_counts[PageType.NEWSLETTER] = 3
    assert not nav.is_navigation_completed()

    nav.visited_counts[PageType.NEWSLETTER] = 4
    assert nav.is_navigation_completed()


def test_default_mode_still_collects_legal_pages():
    assert not Config().EMAIL_CAPTURE_ONLY
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


def test_capture_only_page_skips_text_extraction_but_processes_forms(capture_only, mocker):
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


def test_capture_only_skips_newsletter_reload_without_submitting(capture_only, mocker, monkeypatch):
    monkeypatch.setattr(Config(), "CREATE_ACCOUNT", False)
    site = _site(mocker)
    site.newsletter_url = BASE.child("newsletter")

    site.process_newsletter_registration()

    site.br.load_page.assert_not_called()


def test_discovery_stops_only_at_an_eligible_capture(capture_only, monkeypatch):
    monkeypatch.setattr(Config(), "CREATE_ACCOUNT", False)
    nav = _navigator()

    # A newsletter-looking form alone (e.g. one that requires a phone number) is not enough
    nav.website.newsletter_url = BASE.child("newsletter")
    assert not nav.is_navigation_completed()

    nav.website.eligible_capture_found = True
    assert nav.is_navigation_completed()


OFFSITE_ARTICLE = URL.from_text("https://www.ciodive.com/news/shop-example-loyalty/123/")
SUBSTACK = URL.from_text("https://shopexample.substack.com/")


def _newsletter_link(url: URL) -> UrlMatch:
    return UrlMatch(url, PageType.NEWSLETTER, 1.0)


def test_capture_only_follows_newsletter_links_on_own_domain_and_signup_platforms(
    capture_only, caplog
):
    nav = _navigator()
    with caplog.at_level(logging.INFO, logger="enfbots_crawler"):
        nav.add(_newsletter_link(BASE.child("newsletter")))
        # Another subdomain of the same registered domain is still the same site
        nav.add(_newsletter_link(URL.from_text("https://news.example.com/signup")))
        nav.add(_newsletter_link(SUBSTACK))
        # The same unrelated site linked twice (e.g. from two pages) is logged once
        nav.add(_newsletter_link(OFFSITE_ARTICLE))
        nav.add(_newsletter_link(OFFSITE_ARTICLE))

    assert {m.url.host for m in nav.links} == {
        "shop.example.com",
        "news.example.com",
        "shopexample.substack.com",
    }
    messages = [r.getMessage() for r in caplog.records if "Off-site" in r.getMessage()]
    assert messages == [
        f"Off-site newsletter link allowed (sign-up platform): {SUBSTACK}",
        f"Off-site newsletter link skipped: {OFFSITE_ARTICLE}",
    ]


def test_capture_host_allowlist_is_configurable(capture_only, monkeypatch):
    monkeypatch.setattr(Config(), "CAPTURE_HOST_ALLOWLIST", ["ciodive.com"])
    nav = _navigator()
    nav.add(_newsletter_link(SUBSTACK))
    nav.add(_newsletter_link(OFFSITE_ARTICLE))

    assert [m.url for m in nav.links] == [OFFSITE_ARTICLE]


def test_page_key_ignores_trailing_slash_fragment_and_host_case():
    assert page_key(URL.from_text("https://Shop.Example.com/auth/login/#top")) == URL.from_text(
        "https://shop.example.com/auth/login"
    )
    assert page_key(URL.from_text("https://shop.example.com/")) == page_key(BASE.replace(path=()))


def test_capture_only_queues_a_page_once_with_or_without_trailing_slash(capture_only):
    nav = _navigator()
    nav.add(_newsletter_link(BASE.click("/auth/login")))
    nav.add(_newsletter_link(BASE.click("/auth/login/")))
    # A different query string is a different page
    nav.add(_newsletter_link(BASE.click("/auth/login?next=/newsletter")))

    queued = [m.url.to_text() for m in nav.links]
    assert len(queued) == 2
    assert set(queued) == {
        "https://shop.example.com/auth/login",
        "https://shop.example.com/auth/login?next=/newsletter",
    }


def test_default_mode_still_follows_offsite_links():
    nav = _navigator()
    nav.add(_newsletter_link(OFFSITE_ARTICLE))

    assert [m.url for m in nav.links] == [OFFSITE_ARTICLE]


def _links_site(*links: tuple[str, str]) -> WebSite:
    # Bypass __init__; _process_links needs the browser's links, the language and a navigator.
    # Like browser.get_links, each link is classified by its text, its path and its alt text.
    site = WebSite.__new__(WebSite)
    site.lang = EN
    site.br = MagicMock()
    site.br.get_links.return_value = [
        LinkTuple(BASE.click(path), [text, path, ""]) for text, path in links
    ]
    site.navigator = _navigator()
    return site


NEWS_AND_NEWSLETTER_LINKS = (
    ("News", "/news"),
    ("Club news", "/news/club-news-2026"),
    ("Newsletter", "/newsletter"),
    ("Subscribe to our news", "/signup"),
)


def test_capture_only_ignores_links_matched_only_by_weak_newsletter_keywords(capture_only):
    site = _links_site(*NEWS_AND_NEWSLETTER_LINKS)
    site._process_links()

    assert {m.url.path for m in site.navigator.links} == {("newsletter",), ("signup",)}
    assert {m.type for m in site.navigator.links} == {PageType.NEWSLETTER}


def test_weak_newsletter_keywords_are_configurable(capture_only, monkeypatch):
    monkeypatch.setattr(Config(), "WEAK_NEWSLETTER_KEYWORDS", [])
    site = _links_site(("News", "/news"))
    site._process_links()

    assert [m.url.path for m in site.navigator.links] == [("news",)]


def test_default_mode_still_follows_news_links():
    site = _links_site(*NEWS_AND_NEWSLETTER_LINKS)
    site._process_links()

    newsletter = {m.url.path for m in site.navigator.links if m.type == PageType.NEWSLETTER}
    assert ("news",) in newsletter
    assert ("newsletter",) in newsletter
