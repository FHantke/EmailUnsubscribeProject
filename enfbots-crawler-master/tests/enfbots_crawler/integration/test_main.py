import sys
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, call
import tempfile
import json

from typing import cast, List
from hyperlink import URL

import pytest
from pytest_mock import MockFixture
from sqlalchemy import select

from enfbots_crawler.helper import ns_lookup
from enfbots_crawler.database import SessionLocal, start_next_job, store, DBJob

from enfbots_crawler import (
    DBWebsite,
    DomainStatus,
    EmailVerificationStatus,
    RegistrationStatus,
    CrawlerException,
    Config,
    main,
    PageState,
    DBWebsiteCrawl,
)
from enfbots_crawler.main import main as enfbot_main
from enfbots_crawler.modules.stat_collector import StatCollector

from tests.apps.flask_app import flask_app  # type: ignore


@pytest.fixture
def mock_unsafe(mocker: MockFixture):
    mocker.patch.object(main, "is_google_unsafe", return_value=False)


def test_run_job(
    db_memory,
    output_directory: Path,
    flask_app_function,
    mocker: MockFixture,
    email_creds,
    mock_unsafe,
):
    Config().CREATE_ACCOUNT = True
    # This test requires that we try to register; This is set to false by env == 'test'
    Config().AWAIT_VERIFY_EMAIL = True
    Config().SYBIL_URL = URL.from_text("localhost:0")  # failure to connect
    Config().SYBIL_ID = 42
    Config().SYBIL_AUTH_TOKEN = "some-token"

    mocker.patch.object(main, "assemble_url", return_value=flask_app_function)
    ws = DBWebsite(url=flask_app_function.to_text())
    store(ws)
    job = DBJob(website=ws, crawl_id="test_crawl_test_run_job")

    store(job)
    db_job = start_next_job()
    assert db_job

    site = main.run_domain(flask_app_function.host, job=cast(DBJob, db_job))

    assert site
    assert not site.index_redirect_url

    directories = list(output_directory.iterdir())
    assert len(directories) == 1
    assert directories[0].name.startswith(f"{flask_app_function.host}_")
    files = list(directories[0].iterdir())
    file_names = [f.name for f in files]

    assert "index.html" in file_names
    assert "form_0_stage_0_submit.html" in file_names

    if Config().ALLOW_SCREENSHOTS:
        assert "form_0_stage_0_submit_window_0.png" in file_names
        assert "form_0_stage_0_fill_window_0.png" in file_names
        assert "form_0_stage_0_window_0.png" in file_names

    found_tc = False
    found_pp = False
    for x in site.dumped_htmls:
        if "terms_of_use_" in str(x):
            found_tc = True
        if "privacy_policy_" in str(x):
            found_pp = True
    assert found_tc and found_pp

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        job = session.query(DBJob).filter(DBJob.id == job.website.id).one()

        assert job.started_at and job.ended_at
        assert job.started_at < job.ended_at < datetime.now()
        assert not job.index_redirect

        db_website_crawl = job.crawls[0]

        assert db_website_crawl.website.url == flask_app_function.to_text()
        assert job.website.url == flask_app_function.to_text()
        assert db_website_crawl.reg_url == flask_app_function.child("register").to_text()
        assert db_website_crawl.tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()
        assert (
            db_website_crawl.pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()
        )
        assert (
            db_website_crawl.email_verification_status
            == EmailVerificationStatus.FAILURE_REACHING_SYBILMAIL
        )
        assert db_website_crawl.reg_status == RegistrationStatus.SUCCESS_KEYWORDS


def test_index_redirect(
    db_memory, output_directory, flask_app_function, mock_unsafe, mocker: MockFixture
):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    Config().SYBIL_URL = URL.from_text("localhost:0")  # failure to connect
    Config().SYBIL_ID = 42
    Config().SYBIL_AUTH_TOKEN = "some-token"

    flask_app.INDEX_REDIRECT = "https://gitlab.inf.ethz.ch/"
    mocker.patch.object(main, "assemble_url", return_value=flask_app_function)
    ws = DBWebsite(url=flask_app_function.to_text())
    job = DBJob(website=ws, crawl_id="test_crawl_test_index_redirect")
    store(job)

    db_job = start_next_job()
    site = main.run_domain(flask_app_function.host, job=cast(DBJob, db_job))

    assert site
    assert site.index_redirect_url

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        job = session.query(DBJob).filter(DBJob.id == job.website.id).one()
        assert job
        assert db_job

        assert db_job.started_at
        assert job.started_at
        assert job.ended_at

        assert job.started_at.timestamp() == db_job.started_at.timestamp()

        assert db_job.started_at.timestamp() < job.ended_at.timestamp() < datetime.now().timestamp()
        assert not db_job.index_redirect

        db_website = session.query(DBWebsite).filter(DBWebsite.id == job.website.id).one()

        assert db_website.url == flask_app_function.to_text()
        assert db_website.crawls[0].email_verification_status == EmailVerificationStatus.UNKNOWN
        assert db_website.crawls[0].reg_status == RegistrationStatus.FAILURE_NOT_FOUND

        new_job = session.query(DBJob).filter(DBJob.started_at == None).one()
        assert new_job.website.url == "gitlab.inf.ethz.ch"
        assert new_job.index_redirect
        assert not new_job.started_at and not new_job.ended_at


def test_rejected_job(
    db_memory, output_directory, flask_app_function, mock_unsafe, mocker: MockFixture
):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    Config().SYBIL_URL = URL.from_text("localhost:0")  # failure to connect
    Config().SYBIL_ID = 42
    Config().SYBIL_AUTH_TOKEN = "some-token"

    crawl_id = "test_crawl_test_rejected_job"
    ws = DBWebsite(url="baddns12345.every")
    job = DBJob(website=ws, crawl_id=crawl_id)
    mocker.patch.object(main, "assemble_url", return_value=flask_app_function)
    mocker.patch.object(main, "domain_status", return_value=DomainStatus.UNSAFE)

    # Create new job in the database
    job = store(job)
    db_job = start_next_job()

    with pytest.raises(main.DomainBlacklistedError):
        main.run_domain(flask_app_function.host, job=cast(DBJob, db_job))

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        db_job = session.query(DBJob).filter(DBJob.id == job.website.id).one()

        assert db_job.started_at and db_job.ended_at
        assert db_job.started_at < db_job.ended_at < datetime.now()


def test_ux_job(db_memory, output_directory, flask_app_function, mock_unsafe, mocker: MockFixture):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    url = flask_app_function
    crawl_id = "test_crawl_test_ux_job"
    ws = DBWebsite(url=str(url))
    job = DBJob(website=ws, crawl_id=crawl_id)
    mocker.patch.object(main, "assemble_url", return_value=url)

    store(job)
    db_job = start_next_job()
    site = main.run_domain(url.host, job=cast(DBJob, db_job))

    assert site
    assert site.base_url == url

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job)
        session.refresh(job)

        assert job.started_at and job.ended_at
        assert job.started_at < job.ended_at < datetime.now()


def test_ns_lookup():
    assert ns_lookup("localhost", "A") == ["127.0.0.1"]
    assert ns_lookup("localhost") == ["127.0.0.1"]


def test_blacklist(mock_unsafe):
    Config().DOMAIN_BLACKLIST = (
        Config().root_dir / "tests" / "enfbots_crawler" / "integration" / "blacklist.txt"
    )
    assert main.domain_status("blacklisted.com") == DomainStatus.BLACKLISTED
    assert main.domain_status("sub.blacklisted.com") == DomainStatus.BLACKLISTED


def test_russian(mock_unsafe):
    assert main.domain_status("yandex.com") == DomainStatus.OK
    assert main.domain_status("mail.ru") == DomainStatus.OK


def test_ok(mock_unsafe):
    assert main.domain_status("ethz.ch") == DomainStatus.OK


def test_wrong_credentials(mocker: MockFixture):
    """
    This tests if the 'enfbots' command (equivalent to main()) exits with error code 1.
    This indicates the 'run-crawler.sh' to stop as a fatal error occured
    """
    os.environ["CRAWLER_DB_PATH"] = "postgresql+psycopg2:///localhost:0"
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"

    sys_exit_mocked = mocker.patch("sys.exit")

    testargs = ["not-important.py", "-d", "-dn", "10"]

    with patch.object(sys, "argv", testargs):
        main.main()

    assert sys_exit_mocked.called

    assert sys_exit_mocked.call_args == call(1)


def test_empty_jobs(db_memory, mocker: MockFixture):
    """
    Tests if the exit code is 1 if no jobs are in the database.
    The exit code 1 indicates 'run-crawler.sh' to stop as a fatal error occured.

    Args:
        db_memory (_type_): _description_
        mocker (MockFixture): _description_
    """
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"

    sys_exit_mocked = mocker.patch("sys.exit")

    testargs = ["not-important.py", "-d", "-dn", "1"]

    with patch.object(sys, "argv", testargs):
        main.main()

    assert sys_exit_mocked.called

    assert sys_exit_mocked.call_args == call(1)


def test_is_finished_false(db_disk, flask_app_function, mocker: MockFixture, caplog):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    ws = DBWebsite(url=flask_app_function.to_text())
    crawl_id = "test_crawl_is_finished_false"
    job = DBJob(website=ws, crawl_id=crawl_id)
    store(job)

    sys_exit_mocked = mocker.spy(sys, "exit")

    testargs = ["not-important.py", "--is-finished", "-i", crawl_id]

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", testargs):
            main.main()

    assert "NO, not finished" in str(caplog.text)
    assert "There are still 1 jobs to finish" in str(caplog.text)


def test_is_finished_missing_id(db_disk, flask_app_function, mocker: MockFixture, caplog):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    flask_app.INDEX_REDIRECT = None

    sys_exit_mocked = mocker.spy(sys, "exit")

    testargs = ["not-important.py", "--is-finished"]

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", testargs):
            main.main()

    sys_exit_mocked.assert_called()
    assert sys_exit_mocked.call_args == call(1)

    assert "Missing --id argument" in caplog.text


def test_is_finished_true(db_disk, flask_app_function, mocker: MockFixture, caplog):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    flask_app.INDEX_REDIRECT = None

    ws = DBWebsite(url=flask_app_function.to_text())
    crawl_id = "test_crawl_is_finished_true"
    job = DBJob(website=ws, crawl_id=crawl_id)
    store(job)

    sys_exit_mocked = mocker.spy(sys, "exit")

    testargs = ["not-important.py", "-d", "-dn", "1"]
    with patch.object(sys, "argv", testargs):
        main.main()

    assert not sys_exit_mocked.called

    testargs = ["not-important.py", "--is-finished", "-i", crawl_id]

    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", testargs):
            main.main()

    assert f"YES, {crawl_id} is finished" in str(caplog.text)


def test_dns_error(db_disk, mocker: MockFixture, caplog):
    """
    A crawl to a domain which does not exist should have index_status of DNS_ERROR
    """

    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    ws = DBWebsite(url="https://www.should-not-exist-38fjoi4OIFEOlO.de")

    job = DBJob(website=ws, crawl_id="test_dns_error")
    store(job)

    sys_exit_mocked = mocker.spy(sys, "exit")

    testargs = ["not-important.py", "-d", "-dn", "1"]

    try:
        with patch.object(sys, "argv", testargs):
            main.main()
    except SystemExit:
        pass

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        websites: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(websites) == 1
        assert websites[0].index_status == PageState.DNS_ERROR


def test_timeout(db_disk, caplog):
    """
    A crawl to an IP which does not answer should time-out and have the correct index_status
    """

    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_PAGE_TIMEOUT_SEC"] = "1"

    ws = DBWebsite(url="10.255.255.1")

    job = DBJob(website=ws, crawl_id="test_timeout")
    store(job)

    testargs = ["not-important.py", "-d", "-dn", "1"]

    try:
        with patch.object(sys, "argv", testargs):
            main.main()
    except SystemExit:
        pass

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        websites: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(websites) == 1
        assert websites[0].index_status == PageState.TIMEOUT

    os.environ["CRAWLER_PAGE_TIMEOUT_SEC"] = "120"


def test_is_not_finished_crash(db_disk, caplog):
    """
    When a crawl crashes we usually wait 8h before retrying that website.

    """
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    ws = DBWebsite(url="https://localhost:53")
    crawl_id = "test_crawl_is_finished_crash"
    job = DBJob(website=ws, crawl_id=crawl_id)
    store(job)

    testargs = ["not-important.py", "-d", "-dn", "1"]

    def raise_crawler_exception(*args, **kwargs):
        raise CrawlerException()

    try:
        with patch.object(main, "run_domain", new=raise_crawler_exception):
            with patch.object(sys, "argv", testargs):
                main.main()
    except SystemExit:
        pass

    testargs = ["not-important.py", "--is-finished", "-i", crawl_id]

    with pytest.raises(SystemExit):
        # Raises SystemExit as we are not finished
        with patch.object(sys, "argv", testargs):
            main.main()

    assert "NO, not finished" in str(caplog.text)


def test_progress(db_disk, flask_app_function, caplog):
    """
    Tests if --get-progress works
    """

    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_USE_SEARCH"] = "never"

    created_at = datetime.now()

    url = flask_app_function
    crawl_id = "test_progress"
    ws = DBWebsite(url=str(url))
    job = DBJob(website=ws, crawl_id=crawl_id, created_at=created_at)
    store(job)

    enfbot_args = ["not-important.py", "--get-progress", "--id", crawl_id]

    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    assert f"crawl {crawl_id} is: 0.00%" in caplog.text

    with patch.object(sys, "argv", ["not-important.py", "-d", "-dn", "1"]):
        enfbot_main()

    enfbot_args = ["not-important.py", "--get-progress", "--id", crawl_id]
    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    assert f"crawl {crawl_id} is: 100.00%" in caplog.text


def test_sqlite_database_missing(mocker: MockFixture, caplog):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    sys_exit_mocked = mocker.patch("sys.exit")

    testargs = ["not-important.py", "-u", "some-unimportant-url.com"]
    with patch.object(sys, "argv", testargs):
        main.main()

    assert sys_exit_mocked.called
    assert sys_exit_mocked.call_args == call(1)
    assert "--create-database" in caplog.text


def test_sqlite_upgrade(caplog, mocker: MockFixture):
    old_sqlite_file = (Path(__file__).parent / "../data/old_crawl.sqlite").resolve()

    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_DB_PATH"] = str(old_sqlite_file)

    sys_exit_mocked = mocker.spy(sys, "exit")

    testargs = ["not-important.py", "-u", "some-unimportant-url.com"]
    with pytest.raises(SystemExit):
        with patch.object(sys, "argv", testargs):
            main.main()

    assert sys_exit_mocked.called
    assert sys_exit_mocked.call_args == call(1)
    assert "--update-database" in caplog.text


def test_single_download(flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    to_download = flask_app_function.child("policy").to_text()

    with tempfile.NamedTemporaryFile(mode="w+t", prefix="temp_", suffix=".md") as file:
        testargs = ["not-important.py", "-s", to_download, str(file.name)]
        with patch.object(sys, "argv", testargs):
            main.main()

        content = open(file.name, "r", encoding="utf-8").read()

        assert "This Privacy Policy describes" in content
        assert "Personal Data means any information that identifies" in content


def test_single_domain(db_disk, flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    flask_app.INDEX_REDIRECT = None

    url = flask_app_function.to_text()

    testargs = ["not-important.py", "-u", url]
    with patch.object(sys, "argv", testargs):
        main.main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        websites: List[DBWebsite] = list(session.scalars(select(DBWebsite)).all())

        assert len(websites) == 1
        assert websites[0].url == url

        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1
        assert crawls[0].website.url.rstrip("/") == str(url).rstrip("/")


def test_statistics(db_disk, flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"

    flask_app.INDEX_REDIRECT = None

    url = flask_app_function.to_text()

    stats_file = Path("test_stats.stats")
    assert not stats_file.exists()

    testargs = ["not-important.py", "-u", url, "--stats", str(stats_file.absolute())]
    with patch.object(sys, "argv", testargs):
        main.main()

    with open(stats_file, "r", encoding="utf-8") as file:
        existing_json = json.loads("\n".join(file.readlines()))
        existing_stats = StatCollector(**existing_json)

        assert existing_stats.pages_loaded == 6
        assert existing_stats.websites_visited == 1

    stats_file.unlink()


def test_missing_protocol_single_domain(db_disk, flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"

    orig_url = str(flask_app_function)

    if orig_url.startswith("http://"):
        # pylint: disable=bad-str-strip-call
        url = orig_url.strip("http://")
    else:
        url = orig_url

    assert not url.startswith("http")

    with patch.object(sys, "argv", ["not-important.py", "-u", url]):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1
        assert crawls[0].index_status == PageState.OK

        websites: List[DBWebsite] = list(session.scalars(select(DBWebsite)).all())

        # Only one website should get added
        assert len(websites) == 1
        assert websites[0].url == orig_url.rstrip("/")


def test_missing_protocol_job(db_disk, flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"

    orig_url = str(flask_app_function)
    crawl_id = "test_crawl_test_missing_protocol_job"

    if orig_url.startswith("http://"):
        # pylint: disable=bad-str-strip-call
        url = orig_url.strip("http://")
    else:
        url = orig_url

    assert not url.startswith("http")

    ws = DBWebsite(url=url)
    job = DBJob(website=ws, crawl_id=crawl_id)

    store(job)

    with patch.object(sys, "argv", ["not-important.py", "-d", "-dn", "1"]):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1
        assert crawls[0].index_status == PageState.OK

        websites: List[DBWebsite] = list(session.scalars(select(DBWebsite)).all())

        # Two websites, one when the job was added (there without http://)
        # and a second website with
        assert len(websites) == 2
        assert websites[0].url == url.rstrip("/")
        assert websites[1].url == orig_url.rstrip("/")


def test_http_404_error(db_disk, flask_app_function_missing_pp) -> None:
    """
    Tests that a privacy policy with a 404 http error is ignored.
    Tests via browser setup of a normal CLI invokation.
    """
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_SEARCH"] = "False"

    site = DBWebsite(url=str(flask_app_function_missing_pp))
    job = DBJob(website=site, crawl_id="http_404_error")

    store(job)

    with patch.object(sys, "argv", ["not-important.py", "-d", "-dn", "1"]):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1

        assert len(crawls[0].pp_urls) == 0
        assert len(crawls[0].tc_urls) == 1
