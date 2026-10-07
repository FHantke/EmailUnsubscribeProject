#!/usr/bin/env python3
"""

Calculates the probabilities for PP/TC in a given database using a specified classifier.
"""

import argparse
import logging
from datetime import datetime, timedelta
import os
import sys
from typing import List, Dict, Optional, Tuple, Any, Set

from hyperlink import URL
from tqdm import tqdm
from pqdm.threads import pqdm
from sqlalchemy import select, update, func, true

from enfbots_crawler.database import (
    DBJob,
    CrawlToPrivacyPolicy,
    CrawlToTermsAndConditions,
    DBURL,
    DBURLContent,
    DBWebsite,
    DBWebsiteCrawl,
)
from enfbots_crawler import (
    Config,
    DBWebsite,
    const,
    TablesMissingException,
    ConsiderationBasis,
    CrawlerException,
)

from enfbots_crawler import SessionLocal, initialize_base_db
from enfbots_crawler.helper import (
    check_database,
    get_non_unique_items,
    set_log_formatter,
    check_classifier,
)

from enfbots_crawler.modules.classifier import (
    ClassifierAbstr,
    ClassifierAsAService,
    ClassificationException,
    ClassificationResult,
)


logger = logging.getLogger()


def main() -> None:
    logging.basicConfig()
    logging.getLogger("root").setLevel(logging.INFO)

    # First set up logging by loading the configuration and then
    # set the specified loglevel
    set_log_formatter(const.LOG_FORMAT_INFO, "%Y-%m-%d:%H:%M:%S")
    root_logger = logging.getLogger()
    root_logger.setLevel(
        logging.INFO
    )  # Only until we've loaded the config and set the desired LOG_LEVEL
    if not Config().load():
        logger.info("There seems to be an issue with the configuration")
        return
    root_logger.setLevel(Config().LOG_LEVEL)

    # Parse the input arguments
    parser = argparse.ArgumentParser()

    parser.add_argument("-i", "--id", help="ID of the crawl", dest="crawl_id")

    parser.add_argument(
        "--dry",
        help="Run script but do not actually change anything",
        action="store_true",
        default=False,
    )

    args = parser.parse_args()

    crawl_id: Optional[str] = args.crawl_id
    dry: Optional[bool] = args.dry

    # initialize DB tables
    logger.info("[Load database]: Connecting to db_url %s", Config().get_db_url(True))

    initialize_base_db(
        alembic_root_dir=Config().code_dir,
        db_url=Config().get_db_url(),
        pool_size=32,
    )

    # Check if database connection works
    if not check_database(Config().code_dir):
        raise RuntimeError(
            "There seems to be a problem with the database. Check your CRAWLER_DB_* settings!"
        )

    # As the classifier cannot be run with python 3.11 we need one
    if not check_classifier(
        Config().CLASSIFY_SERVICE_ENDPOINT,
        Config().CLASSIFY_SERVICE_USER,
        Config().CLASSIFY_SERVICE_TOKEN,
    ):
        raise CrawlerException(
            "Classifier does not work but is required due to CRAWLER_USE_CLASSIFIER."
        )

    classifier = ClassifierAsAService(
        Config().CLASSIFY_SERVICE_ENDPOINT,
        Config().CLASSIFY_SERVICE_USER,
        Config().CLASSIFY_SERVICE_TOKEN,
        Config().DEV_VERIFY_SSL,
        silent=True,
    )

    logger.info("Updating Privacy Policies")
    pp_count_same = 0
    pp_count_new_true = 0
    pp_count_new_false = 0
    tc_count_same = 0
    tc_count_new_true = 0
    tc_count_new_false = 0

    select_cpp = (
        select(
            CrawlToPrivacyPolicy.id,
            CrawlToPrivacyPolicy.consideration_basis,
            CrawlToPrivacyPolicy.considered,
            DBURLContent.content,
        )
        .join(DBWebsiteCrawl, DBWebsiteCrawl.id == CrawlToPrivacyPolicy.website_crawl_id)
        .join(DBWebsite, DBWebsite.id == DBWebsiteCrawl.website_id)
        .join(DBJob, DBJob.id == DBWebsiteCrawl.job_id)
        .join(DBURL, CrawlToPrivacyPolicy.pp_url_id == DBURL.id)
        .join(DBURLContent, DBURLContent.hash == DBURL.content_hash)
        .where(DBJob.crawl_id == crawl_id if crawl_id else true())
    )

    select_ctc = (
        select(
            CrawlToTermsAndConditions.id,
            CrawlToTermsAndConditions.consideration_basis,
            CrawlToTermsAndConditions.considered,
            DBURLContent.content,
        )
        .join(DBWebsiteCrawl, DBWebsiteCrawl.id == CrawlToTermsAndConditions.website_crawl_id)
        .join(DBWebsite, DBWebsite.id == DBWebsiteCrawl.website_id)
        .join(DBJob, DBJob.id == DBWebsiteCrawl.job_id)
        .join(DBURL, CrawlToTermsAndConditions.tc_url_id == DBURL.id)
        .join(DBURLContent, DBURLContent.hash == DBURL.content_hash)
        .where(DBJob.crawl_id == crawl_id if crawl_id else true())
    )

    with SessionLocal.begin() as session:
        # First count the amount of policies to have a total number for tqdm
        num_p = session.scalar(select(func.count("*")).select_from(select_cpp.subquery()))

        num_tc = session.scalar(select(func.count("*")).select_from(select_ctc.subquery()))

    if num_p is None:
        raise RuntimeError("Unexpected result from session.scalar")
    if num_tc is None:
        raise RuntimeError("Unexpected result from session.scalar")

    if int(num_p) == 0 and int(num_tc) == 0:
        logger.warning(f"No privacy policies and terms and conditions for crawl id {crawl_id}")
        return

    logger.info(f"Found {int(num_p)} privacy policies and {int(num_tc)} terms and conditions")

    with SessionLocal.begin() as session:
        cpp_result = session.execute(select_cpp).yield_per(2000)

        ctc_result = session.execute(select_ctc).yield_per(2000)

    # Input-Tuple is [id, consideration_basis, considered, content];
    #    Returned is [classification_result, considered, consideration_basis, crawls_to_privacy_policy.id]
    def classify_pp(
        tuple: Tuple[int, ConsiderationBasis, bool, str]
    ) -> Tuple[ClassificationResult, bool, ConsiderationBasis, int]:
        try:
            prob = classifier.is_privacy_policy(tuple[3])
            considered = tuple[2]
            return (prob, considered, tuple[1], tuple[0])
        except ClassificationException as e:
            return (
                ClassificationResult(result=False, classification_s=0.0, error=str(e)),
                False,
                ConsiderationBasis.UNKNOWN,
                -1,
            )

    def classify_tc(
        tuple: Tuple[int, ConsiderationBasis, bool, str]
    ) -> Tuple[ClassificationResult, bool, ConsiderationBasis, int]:
        try:
            prob = classifier.is_terms_conditions(tuple[3])
            considered = tuple[2]
            return (prob, considered, tuple[1], tuple[0])
        except ClassificationException as e:
            return (
                ClassificationResult(result=False, classification_s=0.0, error=str(e)),
                False,
                ConsiderationBasis.UNKNOWN,
                -1,
            )

    # Do not use more than 4 threads as this overwhelms the classificatoin service (and creates additional overhead slowing
    # everyithing down)
    presult = pqdm(cpp_result, classify_pp, n_jobs=4, total=int(num_p), desc="Classifying")

    tcresult = pqdm(ctc_result, classify_tc, n_jobs=4, total=int(num_tc), desc="Classifying")

    pp_updates: List[Dict] = list()

    for i, x in tqdm(enumerate(presult), desc="[PP]: Updating database", total=int(num_p)):
        prob = x[0]
        considered = x[1]
        consideration_basis = x[2]

        if prob.error is None:
            classifier_considered = prob.result

            if classifier_considered == considered:
                pp_count_same += 1
            elif classifier_considered == True and considered == False:
                pp_count_new_true += 1
            elif classifier_considered == False and considered == True:
                pp_count_new_false += 1

            if not dry:
                new_consideration_basis = consideration_basis + ConsiderationBasis.CLASSIFIER

                new = dict(
                    id=x[3],
                    pp_probability=prob.probability,
                    consideration_basis=new_consideration_basis,
                    considered=considered,
                )
                pp_updates.append(new)

        else:
            logger.error("Failed due to %s", prob.error)

    logger.info("Updating PPs in the database")
    with SessionLocal.begin() as session:
        if not dry:
            session.execute(update(CrawlToPrivacyPolicy), pp_updates)
    logger.info("Done")

    tc_updates: List[Dict] = list()

    for i, x in tqdm(enumerate(tcresult), desc="[TC]: Updating database", total=int(num_tc)):
        prob = x[0]
        considered = x[1]
        consideration_basis = x[2]

        if prob.error is None:
            classifier_considered = prob.result

            if classifier_considered == considered:
                tc_count_same += 1
            elif classifier_considered == True and considered == False:
                tc_count_new_true += 1
            elif classifier_considered == False and considered == True:
                tc_count_new_false += 1

            if not dry:
                new_consideration_basis = consideration_basis + ConsiderationBasis.CLASSIFIER

                new = dict(
                    id=x[3],
                    tc_probability=prob.probability,
                    consideration_basis=new_consideration_basis,
                    considered=considered,
                )
                tc_updates.append(new)
        else:
            logger.error("Failed due to %s", prob.error)

    logger.info("Updating TCs in the database")
    with SessionLocal.begin() as session:
        if not dry:
            session.execute(update(CrawlToTermsAndConditions), tc_updates)
    logger.info("Done")

    print("#PPs that stayed the same: ", pp_count_same)
    print("#PPs that are now true: ", pp_count_new_true)
    print("#PPs that are now false: ", pp_count_new_false)

    print("#TCs that stayed the same: ", tc_count_same)
    print("#TCs that are now true: ", tc_count_new_true)
    print("#TCs that are now false: ", tc_count_new_false)


if __name__ == "__main__":
    try:
        main()
    except TablesMissingException:
        logger.error(
            "Database %s is missing the tables. Create a fresh database with 'enfbot --create-database'",
            Config().get_db_url(True),
        )
        sys.exit(1)  # This is fatal
