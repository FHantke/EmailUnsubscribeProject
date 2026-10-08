from sqlalchemy import inspect

from enfbots_crawler import Config
from enfbots_crawler.database import (
    CREATE_EMAILS_WEBSITE_CRAWL_INDEX,
    CREATE_JOBS_CREATED_AT_INDEX,
    CREATE_JOBS_STARTED_AT_INDEX,
    CREATE_WEBSITES_URL_INDEX,
    CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT,
    SessionLocal,
    create_views,
    initialize_base_db,
)
from enfbots_crawler.helper import check_database


def test_create_database_can_run_twice(tmp_path, monkeypatch):
    db_path = tmp_path / "crawl.sqlite"
    # The alembic stamp inside initialize_base_db reads the DB location from Config, not the engine
    monkeypatch.setenv("CRAWLER_DB_TYPE", "sqlite")
    monkeypatch.setenv("CRAWLER_DB_PATH", str(db_path))
    monkeypatch.setattr(Config(), "DB_TYPE", "sqlite")
    monkeypatch.setattr(Config(), "DB_PATH", str(db_path))

    for _ in range(2):  # same steps as `enfbot --create-database`
        initialize_base_db(
            db_url=f"sqlite:///{db_path}", alembic_root_dir=Config().code_dir, create=True
        )
        create_views()

    inspector = inspect(SessionLocal().get_bind())
    assert {"websites", "jobs", "website_crawls"} <= set(inspector.get_table_names())
    assert {"best_pp_urls_kw", "best_tc_urls_kw", "best_us_pn_urls_kw"} <= set(
        inspector.get_view_names()
    )
    assert check_database(Config().code_dir)


def test_postgres_setup_statements_are_guarded():
    for statement in (
        CREATE_JOBS_CREATED_AT_INDEX,
        CREATE_JOBS_STARTED_AT_INDEX,
        CREATE_EMAILS_WEBSITE_CRAWL_INDEX,
        CREATE_WEBSITES_URL_INDEX,
    ):
        assert "CREATE INDEX IF NOT EXISTS" in str(statement)

    assert "IF NOT EXISTS (SELECT 1 FROM pg_constraint" in str(CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT)
