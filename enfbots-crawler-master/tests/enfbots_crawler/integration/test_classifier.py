# Tests the classifier at cookie-crawler1 aka cc1
import sys
import os
from pathlib import Path
from typing import List

from unittest.mock import patch
from sqlalchemy import select

from enfbots_crawler.modules.classifier import ClassifierAsAService
from enfbots_crawler.database import (
    DBWebsite,
    DBJob,
    store,
    SessionLocal,
    DBWebsiteCrawl,
    ConsiderationBasis,
)
from enfbots_crawler.main import main as enfbot_main


# CC1 endpoint
ENDPOINT_PATH = "http://33b7cb087d.inf.ethz.ch/classifier"

ENDPOINT_USER = "asdf"
ENDPOINT_PASSWORD = os.environ["CLASSIFIER_SERVICE_TOKEN"]


def test_pp():
    classifier = ClassifierAsAService(ENDPOINT_PATH, ENDPOINT_USER, ENDPOINT_PASSWORD)

    pp_file = Path("./tests/enfbots_crawler/data/privacy_policy_sample.txt")

    assert not classifier.is_privacy_policy("").result
    assert not classifier.is_privacy_policy("nothing").result

    with pp_file.open("r") as file:
        content = file.read()
        assert classifier.is_privacy_policy(content).result

        # The following should actually be true; current model is not employing all trainingdata
        # assert not classifier.is_terms_conditions(content).result


def test_tc():
    classifier = ClassifierAsAService(ENDPOINT_PATH, "asdf", ENDPOINT_PASSWORD)

    assert not classifier.is_terms_conditions("").result
    assert not classifier.is_terms_conditions("nothing").result

    tc_file = Path("./tests/enfbots_crawler/data/terms_and_conditions_sample.txt")

    with tc_file.open("r") as file:
        content = file.read()
        assert classifier.is_terms_conditions(content).result

        # The following should actually be true;
        # assert not classifier.is_privacy_policy(content).result


def test_classifier_positive(db_disk, flask_app_function):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_SEARCH"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "True"
    os.environ["CRAWLER_CLASSIFY_SERVICE_ENDPOINT"] = ENDPOINT_PATH
    os.environ["CRAWLER_CLASSIFY_SERVICE_USER"] = ENDPOINT_USER
    os.environ["CRAWLER_CLASSIFY_SERVICE_TOKEN"] = ENDPOINT_PASSWORD

    site = DBWebsite(url=str(flask_app_function))
    job = DBJob(website=site, crawl_id="test_classifier_integration")

    store(job)

    with patch.object(sys, "argv", ["not-important.py", "-u", str(flask_app_function)]):
        enfbot_main()

    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1
        assert len(crawls[0].pp_urls) == 1
        assert len(crawls[0].tc_urls) == 1

        assert crawls[0].pp_urls[0].considered == True
        assert crawls[0].tc_urls[0].considered == True

        assert crawls[0].pp_urls[0].consideration_basis == ConsiderationBasis.CLASSIFIER
        assert crawls[0].tc_urls[0].consideration_basis == ConsiderationBasis.CLASSIFIER


def test_classifier_negative(db_disk, flask_app_function_not_a_pp):
    os.environ["CRAWLER_CREATE_ACCOUNT"] = "False"
    os.environ["CRAWLER_USE_SAFE_BROWSING_API"] = "False"
    os.environ["CRAWLER_USE_SEARCH"] = "False"
    os.environ["CRAWLER_USE_CLASSIFIER"] = "True"
    os.environ["CRAWLER_CLASSIFY_SERVICE_ENDPOINT"] = ENDPOINT_PATH
    os.environ["CRAWLER_CLASSIFY_SERVICE_USER"] = ENDPOINT_USER
    os.environ["CRAWLER_CLASSIFY_SERVICE_TOKEN"] = ENDPOINT_PASSWORD

    site = DBWebsite(url=str(flask_app_function_not_a_pp))
    job = DBJob(website=site, crawl_id="test_classifier_integration")

    store(job)

    with patch.object(sys, "argv", ["not-important.py", "-u", str(flask_app_function_not_a_pp)]):
        enfbot_main()

    with SessionLocal.begin() as session:
        crawls: List[DBWebsiteCrawl] = list(session.scalars(select(DBWebsiteCrawl)).all())

        assert len(crawls) == 1
        assert len(crawls[0].pp_urls) == 1
        assert len(crawls[0].tc_urls) == 1

        assert crawls[0].pp_urls[0].considered == False
        assert crawls[0].tc_urls[0].considered == True

        assert crawls[0].pp_urls[0].consideration_basis == ConsiderationBasis.CLASSIFIER
        assert crawls[0].tc_urls[0].consideration_basis == ConsiderationBasis.CLASSIFIER
