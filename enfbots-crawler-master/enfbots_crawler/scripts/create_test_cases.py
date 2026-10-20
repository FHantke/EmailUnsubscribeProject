#!/usr/bin/env python3
"""
Creates the study's test cases from a discovery crawl: for every website with an eligible capture
form, a control and a treatment case with their own random alias, and one subscribe job each.
Run the jobs afterwards with: enfbot -d -dn <2 x sites> --id <ID>

usage: create_test_cases.py --from-crawl FROM_CRAWL --id ID [--sites SITES] [--limit LIMIT]
                            [--seed SEED] [--dry]

Needs CRAWLER_STUDY_MAIL_DOMAIN (the mail server's domain) and the CRAWLER_DB_* settings.
"""

import argparse
import logging
import random
import sys

from enfbots_crawler import Config, SessionLocal, const, initialize_base_db
from enfbots_crawler.database import DBWebsite
from enfbots_crawler.helper import check_database, set_log_formatter
from enfbots_crawler.study import create_test_cases

logger = logging.getLogger("enfbots_crawler")


def main() -> int:
    set_log_formatter(const.LOG_FORMAT_INFO, "%Y-%m-%d:%H:%M:%S")
    logging.getLogger().setLevel(logging.INFO)
    if not Config().load():
        logger.error("There seems to be an issue with the configuration")
        return 1

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--from-crawl", required=True, help="crawl_id of the discovery crawl")
    parser.add_argument("--id", required=True, help="crawl_id for the subscribe jobs")
    parser.add_argument("--sites", help="only these sites: a file with one URL or host per line")
    parser.add_argument("--limit", type=int, help="at most this many sites")
    parser.add_argument("--seed", type=int, help="seed for the site order and arm order")
    parser.add_argument("--dry", action="store_true", help="print the plan, change nothing")
    args = parser.parse_args()

    only_sites = None
    if args.sites:
        with open(args.sites, encoding="utf-8") as f:
            only_sites = [line.strip() for line in f if line.strip()]

    initialize_base_db(alembic_root_dir=Config().code_dir, db_url=Config().get_db_url())
    if not check_database(Config().code_dir):
        logger.error("Database problem: check the CRAWLER_DB_* settings and --update-database")
        return 1

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        cases = create_test_cases(
            session,
            from_crawl=args.from_crawl,
            study_id=args.id,
            only_sites=only_sites,
            limit=args.limit,
            rng=random.Random(args.seed),
            dry=args.dry,
        )
        urls = {w.id: w.url for w in session.query(DBWebsite)}
        for i, case in enumerate(cases):
            run = "first" if i < len(cases) // 2 else "second"
            print(
                f"{run:6} {case.arm:9} {case.alias:32} {urls[case.website_id]:40} "
                f"capture {case.capture_form_id} ({case.selection_reason})"
            )
    verb = "Would create" if args.dry else "Created"
    print(f"{verb} {len(cases)} test cases and subscribe jobs for {len(cases) // 2} sites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
