import logging
import os
import threading
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from typing import Optional

import pytest
from pytest_mock import MockerFixture
from hyperlink import URL

from enfbots_crawler.database import initialize_base_db, delete_all

from enfbots_crawler import Config, CaptchaType
from enfbots_crawler.browser import create_browser
from enfbots_crawler.credentials import Credentials

from tests.apps.flask_app import flask_app  # type: ignore
from tests.apps.flask_app_pdf import flask_app_pdf  # type: ignore
from tests.apps.flask_app import flask_email  # type: ignore
from tests.apps.flask_app_short import flask_app as flask_app_short

logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("seleniumwire").setLevel(logging.WARNING)
logging.getLogger("polyglot").setLevel(logging.INFO)
logging.getLogger("selenium").setLevel(logging.INFO)
logging.getLogger("hpack").setLevel(logging.INFO)

KeyPair = namedtuple("KeyPair", ["site_key", "secret_key", "type"])

# Site keys are public; secret keys are only needed for live verification and come from the environment
_captcha_keys = {
    "recaptcha_v2": KeyPair(
        "6Ld_JJkdAAAAAAVyL5ycyjKzl1JAQS7i2L7f5NDc",
        os.environ.get("TEST_RECAPTCHA_V2_SECRET", ""),
        CaptchaType.ReCAPTCHAv2,
    ),
    "recaptcha_v3": KeyPair(
        "6LcQKJkdAAAAAM-E7Su1RdtlwDrioItcaFlbJMmX",
        os.environ.get("TEST_RECAPTCHA_V3_SECRET", ""),
        CaptchaType.ReCAPTCHAv3,
    ),
    "hcaptcha": KeyPair(
        "8e2c97ea-d32c-49a6-adad-2d2e6587e13e",
        os.environ.get("TEST_HCAPTCHA_SECRET", ""),
        CaptchaType.HCaptcha,
    ),
}

logging.basicConfig(level=logging.INFO)


os.environ["CRAWLER_AWAIT_VERIFY_EMAIL"] = "False"
os.environ["CRAWLER_VERIFY_EMAIL_ON_REQUEST"] = "False"


# Creates a new database for each testfunction containing
# an argument named 'db_memory'
# For some reason when we call main() of main.py it does not connect
# to this database, use db_disk in that case!
@pytest.fixture
def db_memory():
    db_url = "sqlite+pysqlite:///:memory:"

    os.environ["CRAWLER_DB_PATH"] = ":memory:"
    os.environ["CRAWLER_DB_TYPE"] = "sqlite"

    initialize_base_db(
        db_url=db_url,
        alembic_root_dir=Config().code_dir,
        create=True,
    )


@pytest.fixture
def db_disk():
    path = (Path(__file__).parent / "test_crawl.sqlite").absolute()
    db_url = "sqlite+pysqlite:///" + str(path)

    os.environ["CRAWLER_DB_PATH"] = str(path)
    os.environ["CRAWLER_DB_TYPE"] = "sqlite"

    initialize_base_db(
        db_url=db_url,
        alembic_root_dir=Config().code_dir,
        create=True,
    )
    yield
    os.remove(path)


# Uses an existing postgres database called 'enfbots_gitlab_tests'
@pytest.fixture
def db_postgres():
    """
    This is a postgres instance on infsec-server.inf.ethz.ch. This is used for tests to concurrently fetch jobs.
    """

    os.environ["CRAWLER_DB_TYPE"] = "postgres"
    os.environ["CRAWLER_DB_USERNAME"] = "enfbots_gitlab_test_user"
    os.environ["CRAWLER_DB_PASSWORD"] = os.environ["TEST_DB_PASSWORD"]
    os.environ["CRAWLER_DB_HOST"] = "infsec-server.inf.ethz.ch"
    os.environ["CRAWLER_DB_PORT"] = "5432"
    os.environ["CRAWLER_DB_NAME"] = "enfbots_gitlab_tests"

    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.INFO)

    Config().load()
    db_url = Config().get_db_url()

    initialize_base_db(
        db_url=db_url, alembic_root_dir=Config().code_dir, create=False, connection_info="Testing"
    )
    delete_all(db_url)

    initialize_base_db(
        db_url=db_url, alembic_root_dir=Config().code_dir, create=True, connection_info="Testing"
    )

    yield


@pytest.fixture(scope="session")
def captcha_keys():
    return _captcha_keys


@contextmanager
def create_flask_app(
    show_links: bool,
    redirect_pp_to: Optional[str] = None,
    override_pp_content: Optional[str] = None,
):
    """
    Creates a flask app which mocks emails and other functionalities.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    for name, kp in _captcha_keys.items():
        flask_app.app.config["secret_key_" + name] = kp.secret_key
        flask_app.app.config["site_key_" + name] = kp.site_key

    server, port = flask_app.create_server(show_links, redirect_pp_to, override_pp_content)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield URL.from_text(f"http://localhost:{port}/website/")
    server.shutdown()


@contextmanager
def create_flask_app_short(short_tc: bool):
    """
    Creates a flask app which provides the privacy policy too short.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    server, port = flask_app_short.create_server(True, short_tc=short_tc)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield URL.from_text(f"http://localhost:{port}")
    server.shutdown()


@contextmanager
def create_flask_app_pdf():
    """
    Creates a flask app which provides the privacy policy as pdf file.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    server, port = flask_app_pdf.create_server()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield URL.from_text(f"http://localhost:{port}")
    server.shutdown()


@contextmanager
def create_flask_email():
    """
    Creates a flask app which actually sends emails.
    """
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    for name, kp in _captcha_keys.items():
        flask_email.app.config["secret_key_" + name] = kp.secret_key
        flask_email.app.config["site_key_" + name] = kp.site_key

    server, port = flask_email.create_server()
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield URL.from_text(f"http://localhost:{port}/website")
    server.shutdown()


@pytest.fixture
def flask_app_function():
    with create_flask_app(show_links=True, override_pp_content=None) as u:
        yield u


@pytest.fixture
def flask_app_function_not_a_pp():
    content = """Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."""
    with create_flask_app(show_links=True, override_pp_content=content) as u:
        yield u


@pytest.fixture
def flask_app_function_short_tc():
    with create_flask_app_short(short_tc=True) as u:
        yield u


@pytest.fixture
def flask_app_function_short():
    with create_flask_app_short(short_tc=False) as u:
        yield u


@pytest.fixture
def flask_app_function_missing_pp():
    with create_flask_app(show_links=True, redirect_pp_to="test_missing_pp") as u:
        yield u


@pytest.fixture
def flask_app_function_pdf():
    with create_flask_app_pdf() as u:
        yield u


@pytest.fixture
def flask_app_function_no_links():
    with create_flask_app(False) as u:
        yield u


@pytest.fixture
def flask_app_function_external_forbidden_pp():
    with create_flask_app(True, "https://www.deepl.com/uk/privacy") as u:
        yield u


@pytest.fixture
def flask_email_function():
    with create_flask_email() as u:
        yield u


@pytest.fixture(scope="session")
def flask_app_session():
    with create_flask_app(True) as u:
        yield u


@pytest.fixture
def output_directory():
    out_dir = TemporaryDirectory()
    Config().OUTPUT_PATH = Path(out_dir.name)
    with out_dir:
        yield Config().OUTPUT_PATH


@pytest.fixture
def browser():
    Config().load()

    with create_browser(seconds_before_processing_page=0.5) as b:
        yield b


@pytest.fixture
def email_creds(mocker: MockerFixture):
    creds = Credentials.get()
    creds.email = "test@example.com"
    mocker.patch.object(Credentials, "get", return_value=creds)
