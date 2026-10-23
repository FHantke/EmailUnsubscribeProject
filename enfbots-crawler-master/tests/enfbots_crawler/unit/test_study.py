import datetime
import json
import random
import re

import alembic.command
import alembic.config
import pytest
from sqlalchemy import inspect, select, text

from enfbots_crawler import Config
from enfbots_crawler.database import (
    DBCaptureForm,
    DBJob,
    DBTestCase,
    DBWebsite,
    DBWebsiteCrawl,
    SessionLocal,
    initialize_base_db,
    start_next_job,
)
from enfbots_crawler.helper import check_database
from enfbots_crawler.study import create_test_cases, new_alias, pick_captures

ALIAS = re.compile(r"^news[0-9]{10}@study\.example$")


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "crawl.sqlite"
    # alembic's env.py reads the DB location from Config, not from the engine
    monkeypatch.setenv("CRAWLER_DB_TYPE", "sqlite")
    monkeypatch.setenv("CRAWLER_DB_PATH", str(db_path))
    monkeypatch.setattr(Config(), "DB_TYPE", "sqlite")
    monkeypatch.setattr(Config(), "DB_PATH", str(db_path))
    monkeypatch.setattr(Config(), "STUDY_MAIL_DOMAIN", "study.example")
    initialize_base_db(
        db_url=f"sqlite:///{db_path}", alembic_root_dir=Config().code_dir, create=True
    )
    return f"sqlite:///{db_path}"


def _discovery(session, crawl_id: str, url: str, *captures: dict) -> int:
    """A website crawled in crawl_id with the given capture forms; returns the website id."""
    website = DBWebsite(url=url)
    session.add(website)
    session.flush()
    job = DBJob(website_id=website.id, crawl_id=crawl_id)
    session.add(job)
    session.flush()
    crawl = DBWebsiteCrawl(website_id=website.id, job_id=job.id)
    session.add(crawl)
    session.flush()
    for c in captures:
        session.add(
            DBCaptureForm(
                website_crawl_id=crawl.id,
                url=url + "/",
                kind=c.get("kind", "newsletter"),
                eligible=c.get("eligible", True),
                trigger=c.get("trigger", "inline"),
                visible=c.get("visible", True),
                signature=c.get("signature", "s"),
                vendor_hint=c.get("vendor_hint"),
            )
        )
    return website.id


@pytest.fixture
def discovery(db):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        _discovery(
            session,
            "disc",
            "https://shop.example",
            {"visible": False, "signature": "hidden-newsletter"},
            {"kind": "other", "signature": "visible-other"},
            {"signature": "visible-newsletter"},
            {"eligible": False, "signature": "login"},
        )
        _discovery(session, "disc", "https://news.example", {"kind": "other", "signature": "a"})
        _discovery(session, "disc", "https://none.example", {"eligible": False, "signature": "b"})
        _discovery(session, "other-crawl", "https://elsewhere.example", {"signature": "c"})


def _sigs(captures):
    return {c.website_crawl.website.url: c.signature for c in captures.values()}


def test_new_alias_is_random_unique_and_matches_the_mailbox_pattern(db):
    taken = {"news0000000000@study.example"}
    aliases = {new_alias(taken) for _ in range(50)}

    assert len(aliases) == 50
    assert all(ALIAS.match(a) for a in aliases)
    assert aliases <= taken


def test_new_alias_needs_the_mail_domain(db, monkeypatch):
    monkeypatch.setattr(Config(), "STUDY_MAIL_DOMAIN", "")
    with pytest.raises(ValueError):
        new_alias(set())


def test_pick_captures_prefers_visible_newsletter_forms(discovery):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        assert _sigs(pick_captures(session, "disc")) == {
            "https://shop.example": "visible-newsletter",
            "https://news.example": "a",
        }


def test_pick_captures_prefers_another_form_to_shopifys_own(db):
    # arlingtonpower: Shopify's footer form (hCaptcha on submit) and a Klaviyo form
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        _discovery(
            session,
            "disc",
            "https://store.example",
            {"vendor_hint": "shopify", "signature": "shopify"},
            {"vendor_hint": "klaviyo", "signature": "klaviyo"},
        )
        _discovery(session, "disc", "https://only.example", {"vendor_hint": "shopify"})
    with SessionLocal.begin() as session:
        assert _sigs(pick_captures(session, "disc")) == {
            "https://store.example": "klaviyo",
            "https://only.example": "s",
        }


def _cases():
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        rows = session.scalars(select(DBTestCase).order_by(DBTestCase.id)).all()
        return [(r.website_id, r.arm, r.alias, r.study_id, r.selection_reason) for r in rows]


def test_create_test_cases_makes_both_arms_and_a_job_each(discovery):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        created = create_test_cases(session, "disc", "subscribe-1", rng=random.Random(1))
        assert len(created) == 4

    cases = _cases()
    by_site: dict[int, set[str]] = {}
    for website_id, arm, alias, study, _ in cases:
        by_site.setdefault(website_id, set()).add(arm)
        assert ALIAS.match(alias) and study == "subscribe-1"
    assert list(by_site.values()) == [{"control", "treatment"}] * 2
    assert len({alias for _, _, alias, _, _ in cases}) == 4
    assert {reason for *_, reason in cases} == {"visible newsletter", "visible other"}

    with SessionLocal.begin() as session:
        jobs = session.scalars(select(DBJob).where(DBJob.crawl_id == "subscribe-1")).all()
        assert len(jobs) == 4
        assert all(j.create_account and j.test_case_id for j in jobs)


def test_every_first_arm_runs_before_any_second_arm(discovery):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        cases = create_test_cases(session, "disc", "subscribe-1", rng=random.Random(2))
        first_pass = {c.website_id for c in cases[:2]}
        order = [c.id for c in cases]

    started = [start_next_job(crawl_id="subscribe-1").test_case_id for _ in range(4)]
    assert started == order
    with SessionLocal.begin() as session:
        sites = [session.get(DBTestCase, i).website_id for i in started]
    assert set(sites[:2]) == first_pass == set(sites[2:])


def test_sites_with_test_cases_are_never_signed_up_again(discovery):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        create_test_cases(session, "disc", "subscribe-1")
    with SessionLocal.begin() as session:
        assert create_test_cases(session, "disc", "subscribe-2") == []
    assert len(_cases()) == 4


@pytest.mark.parametrize(
    "status, submitted, blocks",
    [
        ("dry_run", False, False),
        ("skipped_form_not_found", False, False),
        ("error", False, True),
        ("success_text", True, True),
        ("no_change", True, True),
    ],
)
def test_only_submitted_or_open_test_cases_block_a_site(discovery, status, submitted, blocks):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        for case in create_test_cases(session, "disc", "subscribe-dry"):
            case.submit_status = status
            case.submitted_at = datetime.datetime.now() if submitted else None
    with SessionLocal.begin() as session:
        again = create_test_cases(session, "disc", "subscribe-real")
    assert (again == []) == blocks


def test_sites_filter_limit_and_dry_run(discovery):
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        planned = create_test_cases(
            session, "disc", "subscribe-1", only_sites=["shop.example"], dry=True
        )
        assert len(planned) == 2
    assert _cases() == []

    with SessionLocal.begin() as session:
        assert len(create_test_cases(session, "disc", "subscribe-1", limit=1)) == 2
    assert len(_cases()) == 2


def _persona(tmp_path, monkeypatch, name: str, email) -> None:
    # A persona file in a temporary credentials folder, based on us_jordan
    data = json.loads((Config().credentials_dir / "us_jordan.json").read_text())
    data["email"] = email
    monkeypatch.setattr(Config(), "credentials_dir", tmp_path)
    (tmp_path / f"{name}.json").write_text(json.dumps(data))
    monkeypatch.setattr(Config(), "STUDY_PERSONA", name)


def test_persona_with_its_own_address_makes_one_test_case_per_site(
    discovery, tmp_path, monkeypatch
):
    _persona(tmp_path, monkeypatch, "tester", "someone@temp.example")
    monkeypatch.setattr(Config(), "STUDY_MAIL_DOMAIN", "")  # not needed for test sign-ups

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        cases = create_test_cases(session, "disc", "signup-test")
        assert [(c.arm, c.persona) for c in cases] == [("test", "tester")] * 2
        assert all(re.match(r"^test[0-9]{10}@test\.invalid$", c.alias) for c in cases)
        jobs = session.scalars(select(DBJob).where(DBJob.crawl_id == "signup-test")).all()
        assert len(jobs) == 2


def test_persona_email_must_be_an_address(discovery, tmp_path, monkeypatch):
    _persona(tmp_path, monkeypatch, "tester", "REPLACE-WITH-YOUR-TEMP-MAIL-ADDRESS")
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        with pytest.raises(ValueError):
            create_test_cases(session, "disc", "signup-test")


def _alembic_config() -> alembic.config.Config:
    config = alembic.config.Config(file_=str(Config().code_dir / "alembic.ini"))
    config.set_main_option("script_location", str(Config().code_dir / "alembic"))
    config.attributes["configure_logger"] = False
    return config


def test_migration_adds_test_cases_to_a_previous_database(db):
    # A database at the previous revision: no test_cases table, no jobs.test_case_id. SQLite
    # cannot drop a foreign-key column, so jobs is rebuilt without it (constraints don't matter)
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.execute(text("DROP TABLE test_cases"))
        info = session.execute(text("PRAGMA table_info(jobs)"))
        cols = [r[1] for r in info if r[1] != "test_case_id"]
        session.execute(text(f"CREATE TABLE jobs_old AS SELECT {', '.join(cols)} FROM jobs"))
        session.execute(text("DROP TABLE jobs"))
        session.execute(text("ALTER TABLE jobs_old RENAME TO jobs"))
    alembic.command.stamp(_alembic_config(), "d4a7f2c9e813")

    alembic.command.upgrade(_alembic_config(), "head")

    bind = SessionLocal().get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("test_cases")}
    assert columns == {c.name for c in DBTestCase.__table__.columns}
    assert "test_case_id" in {c["name"] for c in inspect(bind).get_columns("jobs")}
    assert check_database(Config().code_dir)
