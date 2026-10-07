import datetime
from typing import cast, List

from pytest_mock import MockerFixture
from sqlalchemy import select, text
from hyperlink import URL

from enfbots_crawler.enums import DomainStatus, PageState

from enfbots_crawler.main import run_domain
import enfbots_crawler.main as main

from enfbots_crawler.database import (
    DBJob,
    DBWebsite,
    DBWebsiteCrawl,
    create_views,
    store,
    start_next_job,
    SessionLocal,
)
from enfbots_crawler.config import Config


def test_single_job(db_memory):
    """
    Test if starting a job works.
    """

    website = DBWebsite(url="www.tests.org")
    store(DBJob(website=website))

    job1 = start_next_job()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job1)

        assert job1.website.url == "www.tests.org"
        assert job1.started_at is not None
        job2 = start_next_job()
        assert job2 is None


def test_multiple_jobs(db_memory):
    """
    Tests if starting one job won't start it again.
    """

    urls = ["www.test1.org", "www.test2.org"]
    websites = {DBWebsite(url=u) for u in urls}
    for website in websites:
        store(DBJob(website=website))

    for _ in range(len(websites)):
        job = start_next_job()
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            session.add(job)
            assert job.website.url in {w.url for w in websites}
            assert job.started_at is not None
            urls.remove(job.website.url)

    job2 = start_next_job()
    assert job2 is None


def test_timeout_job(db_memory):
    urls = ["www.test1.org", "www.test2.org"]
    websites = [DBWebsite(url=u) for u in urls]

    d1 = datetime.datetime.now() - datetime.timedelta(hours=10)
    d2 = datetime.datetime.now() - datetime.timedelta(hours=4)
    store(DBJob(website=websites[0], started_at=d1))
    store(DBJob(website=websites[1], started_at=d2))
    job1 = start_next_job()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        assert job1 is not None

        session.add(job1)
        assert job1.website.url == "www.test1.org"
        assert job1.started_at is not None
        job2 = start_next_job()
        assert job2 is None


def test_ended_job(db_memory):
    urls = ["www.test1.org", "www.test2.org"]
    websites = [DBWebsite(url=u) for u in urls]
    now = datetime.datetime.now()
    d = now - datetime.timedelta(hours=10)
    store(DBJob(website=websites[0], started_at=d, ended_at=now))
    store(DBJob(website=websites[1]))
    job1 = start_next_job()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job1)
        assert job1.website.url == "www.test2.org"
        assert job1.started_at is not None
        job2 = start_next_job()
        assert job2 is None


def test_persistence_in_db(flask_app_function, db_memory, mocker: MockerFixture):
    """
    Tests if the results of a crawl are correctly stored in the database.
    """
    create_views()

    Config().CREATE_ACCOUNT = False
    Config().USE_CLASSIFIER = False

    created_at = datetime.datetime.now()

    url = flask_app_function
    crawl_id = "test_crawl_persistence_in_db"
    ws = DBWebsite(url=str(url))
    job = DBJob(website=ws, crawl_id=crawl_id, created_at=created_at)

    # Needed
    mocker.patch.object(main, "domain_status", return_value=DomainStatus.OK)

    store(job)
    db_job = start_next_job()

    run_domain(str(url), job=cast(DBJob, db_job))

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = list(session.execute(select(DBJob)).scalars())
        assert 1 == len(jobs)

        assert jobs[0].crawl_id == crawl_id
        assert jobs[0].created_at.timestamp() == created_at.timestamp()

        websites: List[DBWebsite] = list(session.execute(select(DBWebsite)).scalars())
        assert 1 == len(websites)

        assert websites[0].url == str(url)
        assert len(websites[0].crawls) == 1

        crawls: List[DBWebsiteCrawl] = list(session.execute(select(DBWebsiteCrawl)).scalars())

        assert len(crawls) == 1

        assert crawls[0].website.url == str(url)
        assert crawls[0].lang == "en"
        assert crawls[0].index_status == PageState.OK

        # When CREATE_ACCOUNT is False we do not store email, username and password
        assert crawls[0].email is None
        assert crawls[0].username is None
        assert crawls[0].password is None

        best_pp_links = list(
            session.execute(
                text(
                    "SELECT pp_url_id, website_crawl_id, url, considered, consideration_basis, crawl_id from best_pp_urls_kw"
                )
            ).all()
        )

        link = best_pp_links[0]

        # ID
        assert link[1] == crawls[0].id

        assert str(link[2]) == flask_app_function.child("policy").to_text()

        # considered is true
        assert link[3]

        # crawl_id
        assert link[5] == jobs[0].crawl_id

        best_tc_links = list(
            session.execute(
                text(
                    "SELECT tc_url_id, website_crawl_id, url, considered, consideration_basis, crawl_id from best_tc_urls_kw"
                )
            ).all()
        )

        link = best_tc_links[0]

        # ID
        assert link[1] == crawls[0].id

        assert str(link[2]) == flask_app_function.child("terms").to_text()

        # considered is true
        assert link[3]

        # crawl_id
        assert link[5] == jobs[0].crawl_id


def test_credentials_stored(browser, flask_app_function, db_memory, mocker: MockerFixture):
    Config().CREATE_ACCOUNT = True
    Config().USE_CLASSIFIER = False

    Config().SYBIL_URL = URL.from_text("https://infsec-server.inf.ethz.ch/sybilmail/")
    Config().SYBIL_AUTH_TOKEN = "test-token"
    Config().SYBIL_ID = 42
    Config().CREDENTIALS = "samsa"

    created_at = datetime.datetime.now()

    url = flask_app_function
    crawl_id = "test_credentials_stored"
    ws = DBWebsite(url=str(url))
    job = DBJob(website=ws, crawl_id=crawl_id, created_at=created_at)

    # Needed
    mocker.patch.object(main, "domain_status", return_value=DomainStatus.OK)

    store(job)
    db_job = start_next_job()

    run_domain(str(url), job=cast(DBJob, db_job))
    url = flask_app_function

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.execute(select(DBWebsiteCrawl)).scalars())
        
        assert len(crawls) == 1
        
        # Personas no longer carry a password; the generated one must be stored
        assert crawls[0].password
        assert crawls[0].username is not None

def test_urls_accessible_from_websitecrawl(flask_app_function, db_memory, mocker: MockerFixture):
    """
    Tests if the PP/TC URLs are accessible and correctly associated with the DBWebsiteCrawl loaded from database.
    """

    Config().CREATE_ACCOUNT = False
    Config().USE_CLASSIFIER = False

    created_at = datetime.datetime.now()

    url = flask_app_function
    crawl_id = "test_urls_accessible_from_websitecrawl"
    ws = DBWebsite(url=str(url))
    job = DBJob(website=ws, crawl_id=crawl_id, created_at=created_at)

    # Needed
    mocker.patch.object(main, "domain_status", return_value=DomainStatus.OK)

    store(job)
    db_job = start_next_job()

    run_domain(str(url), job=cast(DBJob, db_job))
    url = flask_app_function

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.execute(select(DBWebsiteCrawl)).scalars())

        assert crawls[0].website.url == str(url)
        assert len(crawls[0].website.crawls) == 1

        assert len(crawls[0].pp_urls) == 1
        assert len(crawls[0].tc_urls) == 1

        assert crawls[0].pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()
        assert crawls[0].tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()
