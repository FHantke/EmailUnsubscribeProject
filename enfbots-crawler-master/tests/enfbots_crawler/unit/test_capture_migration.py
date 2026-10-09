import alembic.command
import alembic.config
import pytest
from sqlalchemy import inspect, text

from enfbots_crawler import Config
from enfbots_crawler.database import (
    DBCaptureForm,
    SessionLocal,
    initialize_base_db,
    update_database,
)
from enfbots_crawler.helper import check_database

PREVIOUS = "265e6a96f4ce"


def _alembic_config() -> alembic.config.Config:
    config = alembic.config.Config(file_=str(Config().code_dir / "alembic.ini"))
    config.set_main_option("script_location", str(Config().code_dir / "alembic"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture
def old_database(tmp_path, monkeypatch):
    """A database at the revision before capture_forms existed."""
    db_path = tmp_path / "crawl.sqlite"
    # alembic's env.py reads the DB location from Config, not from the engine
    monkeypatch.setenv("CRAWLER_DB_TYPE", "sqlite")
    monkeypatch.setenv("CRAWLER_DB_PATH", str(db_path))
    monkeypatch.setattr(Config(), "DB_TYPE", "sqlite")
    monkeypatch.setattr(Config(), "DB_PATH", str(db_path))
    url = f"sqlite:///{db_path}"

    initialize_base_db(db_url=url, alembic_root_dir=Config().code_dir, create=True)
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.execute(text("DROP TABLE capture_forms"))
    alembic.command.stamp(_alembic_config(), PREVIOUS)
    return url


def _columns() -> set[str]:
    return {c["name"] for c in inspect(SessionLocal().get_bind()).get_columns("capture_forms")}


def test_migration_creates_capture_forms(old_database):
    alembic.command.upgrade(_alembic_config(), "head")

    assert _columns() == {c.name for c in DBCaptureForm.__table__.columns}
    assert check_database(Config().code_dir)


def test_update_database_on_old_revision(old_database):
    # create_all() runs first and creates the table; the migration must then skip it
    update_database(db_url=old_database, alembic_root_dir=Config().code_dir)

    assert "capture_forms" in inspect(SessionLocal().get_bind()).get_table_names()
    assert check_database(Config().code_dir)
