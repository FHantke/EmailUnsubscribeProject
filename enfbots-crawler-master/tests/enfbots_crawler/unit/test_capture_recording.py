from pathlib import Path
from unittest.mock import MagicMock

import bs4
import pytest
from hyperlink import URL
from sqlalchemy import select

from enfbots_crawler import Config
from enfbots_crawler.database import (
    DBCaptureForm,
    DBWebsiteCrawl,
    SessionLocal,
    get_website,
    initialize_base_db,
    store,
)
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.languages import Language
from enfbots_crawler.website import WebSite

EN = Language.get(Path("enfbots_crawler/languages"), "en")
BASE = URL.from_text("https://shop.example.com/")

FOOTER_NEWSLETTER = """<form id="crawleruuid-{n}"><label for="e">Newsletter</label>
  <input type="email" name="email" id="e"><button type="submit">Subscribe</button></form>"""
REGISTRATION = """<form action="/signup"><input type="email" name="email">
  <input type="password" name="password"><button type="submit">Create account</button></form>"""


def _form(html: str, input_info: dict[str, bool] | None = None) -> FormBS:
    return FormBS(bs4.BeautifulSoup(html, "html.parser").form, EN, input_info)


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "crawl.sqlite"
    monkeypatch.setenv("CRAWLER_DB_TYPE", "sqlite")
    monkeypatch.setenv("CRAWLER_DB_PATH", str(db_path))
    monkeypatch.setattr(Config(), "DB_TYPE", "sqlite")
    monkeypatch.setattr(Config(), "DB_PATH", str(db_path))
    initialize_base_db(
        db_url=f"sqlite:///{db_path}", alembic_root_dir=Config().code_dir, create=True
    )


@pytest.fixture
def discovery(monkeypatch):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)
    monkeypatch.setattr(Config(), "CREATE_ACCOUNT", False)


def _site() -> WebSite:
    # Bypass __init__ (browser, output folder); categorize_forms_on_current_page needs these
    site = WebSite.__new__(WebSite)
    site.br = MagicMock()
    site.br.get_html.return_value = "<html><body></body></html>"
    site.lang = EN
    site.newsletter_url = None
    site._capture_rows = {}
    site.eligible_capture_found = False
    site.db_websitecrawl = store(DBWebsiteCrawl(website_id=get_website(BASE).id))
    return site


def _visit(site: WebSite, path: str, *forms: str) -> None:
    site.br.current_url = BASE.child(path)
    site.br.find_forms.return_value = [_form(f) for f in forms]
    site.categorize_forms_on_current_page()


def _stored() -> list[DBCaptureForm]:
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        return list(session.scalars(select(DBCaptureForm).order_by(DBCaptureForm.id)))


def test_discovery_records_each_capture_once(db, discovery):
    site = _site()
    _visit(site, "", FOOTER_NEWSLETTER.format(n="a"))
    _visit(site, "account", FOOTER_NEWSLETTER.format(n="b"), REGISTRATION)

    rows = _stored()
    assert [(r.kind, r.eligible, r.reject_reason) for r in rows] == [
        ("newsletter", True, None),
        ("other", False, "password"),
    ]
    assert rows[0].url == str(BASE.child(""))
    assert rows[0].website_crawl_id == site.db_websitecrawl.id
    assert site.eligible_capture_found


def test_only_ineligible_capture_keeps_searching(db, discovery):
    site = _site()
    _visit(site, "", REGISTRATION)

    assert len(_stored()) == 1
    assert not site.eligible_capture_found


# A discount pop-up; its email input carries the id browser.load_form_info gives it
POPUP = """<form id="popup"><p>Get 15% off your first order</p>
  <input type="email" name="email" data-enfbots-uuid="popup-email">
  <button type="submit">Unlock offer</button></form>"""


def _scan(site: WebSite, trigger: str, *forms: FormBS) -> None:
    site.br.current_url = BASE
    site.br.find_forms.return_value = list(forms)
    site.categorize_forms_on_current_page(trigger)


def test_popup_is_recorded_with_the_trigger_that_showed_it(db, discovery):
    site = _site()
    _scan(site, "inline", _form(FOOTER_NEWSLETTER.format(n="a")))
    _scan(site, "delay", _form(FOOTER_NEWSLETTER.format(n="b")), _form(POPUP))

    rows = _stored()
    assert [(r.trigger, r.visible) for r in rows] == [("inline", True), ("delay", True)]


def test_hidden_popup_form_gets_the_trigger_that_reveals_it(db, discovery):
    site = _site()
    # The pop-up's form is in the page from the start, but hidden
    _scan(site, "inline", _form(POPUP, {"popup-email": False}))
    assert [(r.trigger, r.visible) for r in _stored()] == [("inline", False)]

    _scan(site, "delay", _form(POPUP, {"popup-email": False}))
    _scan(site, "scroll", _form(POPUP, {"popup-email": True}))
    _scan(site, "exit_intent", _form(POPUP, {"popup-email": True}))

    rows = _stored()
    assert [(r.trigger, r.visible) for r in rows] == [("scroll", True)]
    assert rows[0].fields[0]["visible"] is True


def test_nothing_recorded_outside_discovery(db, monkeypatch):
    monkeypatch.setattr(Config(), "EMAIL_CAPTURE_ONLY", True)
    monkeypatch.setattr(Config(), "CREATE_ACCOUNT", True)
    site = _site()
    _visit(site, "", FOOTER_NEWSLETTER.format(n="a"))

    assert _stored() == []
    assert site.newsletter_url == BASE.child("")
