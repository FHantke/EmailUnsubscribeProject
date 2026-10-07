import os
import sys
from pathlib import Path
from unittest.mock import patch
from typing import List
import socket

from pytest_mock import MockFixture

from enfbots_crawler.scripts.load_database import main as load_database_main
from enfbots_crawler.main import main as enfbot_main
from enfbots_crawler import DBWebsiteCrawl, SessionLocal, DBJob, DBWebsite, PageState
from enfbots_crawler.website import WebSite


def test_load_simple(db_disk, flask_app_function, mocker: MockFixture):
    """
    Tests if a crawl can be loaded via load_database.py and then
    will be crawled if the crawler is invoked with 'enfbot -d -dn 1'
    """

    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    url = flask_app_function

    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(str(url))

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    enfbot_args = ["not-important.py", "-d", "-dn", "1"]

    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = session.query(DBWebsiteCrawl).all()

        crawl_domains: List[str] = []

        for c in crawls:
            crawl_domains.append(c.website.url)

        assert str(url).rstrip("/") in crawl_domains

        jobs: List[DBJob] = session.query(DBJob).all()

        assert len(jobs) == 1
        assert jobs[0].ended_at is not None

    sys_exit_mocked = mocker.patch("sys.exit")

    assert not sys_exit_mocked.called

    os.remove(raw_list_path)


def test_load_and_test_force_recrawl(db_disk, flask_app_function):
    """
    Tests if a forced recrawl calls .crawl() of the website.
    """

    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    url = flask_app_function

    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(str(url) + "\n")

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--force-recrawl", "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    enfbot_args = ["not-important.py", "-d", "-dn", "1"]

    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--force-recrawl", "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        crawls: List[DBJob] = session.query(DBJob).all()

        assert len(crawls) == 2

        website_crawls: List[DBWebsiteCrawl] = session.query(DBWebsiteCrawl).all()

        assert len(website_crawls) == 2

        assert (
            website_crawls[0].pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()
        )
        assert (
            website_crawls[0].tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()
        )
        assert website_crawls[0].validation_run == False

        assert (
            website_crawls[1].pp_urls[0].pp_url.url == flask_app_function.child("policy").to_text()
        )
        assert (
            website_crawls[1].tc_urls[0].tc_url.url == flask_app_function.child("terms").to_text()
        )
        assert website_crawls[1].validation_run == False

        websites: List[DBWebsite] = session.query(DBWebsite).all()

        assert len(websites) == 1


def test_status_unknown_error(db_disk):
    """
    This testcase verifies that a crawl where a connection cannot be established
    will have a index_status of UNKNOWN_ERROR.
    """

    os.environ["CRAWLER_USE_CLASSIFIER"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"

    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write("localhost:94\n")

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--force-recrawl", "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    enfbot_args = ["not-important.py", "-d", "-dn", "1"]

    with patch.object(sys, "argv", enfbot_args):
        enfbot_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        website_crawls: List[DBWebsiteCrawl] = session.query(DBWebsiteCrawl).all()

        assert len(website_crawls) == 1
        assert website_crawls[0].index_status == PageState.UNKNOWN_ERROR

        jobs: List[DBJob] = session.query(DBJob).all()

        assert len(jobs) == 1
        assert jobs[0].crawler_hostname == socket.gethostname()
