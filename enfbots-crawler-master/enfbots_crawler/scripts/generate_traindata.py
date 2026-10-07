#!/bin/env python

import argparse
from typing import List
from pathlib import Path

from sqlalchemy import (
    select,
)
from tqdm import tqdm

from enfbots_crawler import SessionLocal, initialize_base_db

from enfbots_crawler import Config
from enfbots_crawler import CrawlToPrivacyPolicy, CrawlToTermsAndConditions, DBURL, DBURLContent

print("Start")


def is_in(lst: List[str], s: str) -> bool:
    for x in lst:
        if s in x:
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--crawl-output-folder",
        type=Path,
        help="Path to folder containing the crawled websites",
        required=True,
    )
    parser.add_argument(
        "--positives", type=Path, help="Path to file containing positive PP/TCs", required=True
    )
    parser.add_argument(
        "--negatives", type=Path, help="Path to file containing negative PP/TCs", required=True
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Path to folder where two subfolders for positive/negative content will be created",
        required=True,
    )

    args = parser.parse_args()

    # Load files
    positives = list(map(lambda s: s.strip(), open(args.positives, "r").readlines()))
    negatives = list(map(lambda s: s.strip(), open(args.negatives, "r").readlines()))

    # Remove empty lines
    positives = list(filter(lambda x: x != "", positives))
    negatives = list(filter(lambda x: x != "", negatives))

    # Load config and connect to the database
    Config().load()
    print(
        f"Initializing connection to database {Config().DB_HOST}:{Config().DB_PORT}/{Config().DB_NAME}"
    )
    initialize_base_db(
        db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir, create=True
    )

    # Create folder structure for the output
    pp_folder = Path(args.output) / "pp"
    pp_folder.mkdir(exist_ok=True)
    tc_folder = Path(args.output) / "tc"
    tc_folder.mkdir(exist_ok=True)

    pos_pp_folder = args.output / "pp" / "positives"
    may_pp_folder = args.output / "pp" / "maybe"
    neg_pp_folder = args.output / "pp" / "negatives"
    pos_pp_folder.mkdir(exist_ok=True)
    may_pp_folder.mkdir(exist_ok=True)
    neg_pp_folder.mkdir(exist_ok=True)

    pos_tc_folder = args.output / "tc" / "positives"
    may_tc_folder = args.output / "tc" / "maybe"
    neg_tc_folder = args.output / "tc" / "negatives"
    pos_tc_folder.mkdir(exist_ok=True)
    may_tc_folder.mkdir(exist_ok=True)
    neg_tc_folder.mkdir(exist_ok=True)

    # Get all PP urls
    pp_query = (
        select(
            CrawlToPrivacyPolicy,
            DBURL.url,
            DBURLContent.content,
            CrawlToPrivacyPolicy.considered,
            DBURL.content_hash,
        )
        .join(DBURL, DBURL.id == CrawlToPrivacyPolicy.pp_url_id)
        .join(DBURLContent, DBURLContent.hash == DBURL.content_hash)
    )
    tc_query = (
        select(
            CrawlToTermsAndConditions,
            DBURL.url,
            DBURLContent.content,
            CrawlToTermsAndConditions.considered,
            DBURL.id,
            DBURL.content_hash,
        )
        .join(DBURL, DBURL.id == CrawlToTermsAndConditions.tc_url_id)
        .join(DBURLContent, DBURLContent.hash == DBURL.content_hash)
    )

    # Debugging
    # pp_query = pp_query.limit(5)
    # tc_query = tc_query.limit(5)

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        pps = session.execute(pp_query).all()
        tcs = session.execute(tc_query).all()

        for p in tqdm(pps):
            content = p.content

            if p.considered:
                if is_in(positives, p.url):
                    print(f"PP: Is ground truth: {p.url}")
                    open(pos_pp_folder / (str(p.content_hash) + ".md"), "w").write(content)
                else:
                    print(f"PP: Is considered: {p.url}")
                    open(may_pp_folder / (str(p.content_hash) + ".md"), "w").write(content)
            else:  # not considered
                print(f"PP: Probably not: {p.url}")
                open(neg_pp_folder / (str(p.content_hash) + ".md"), "w").write(content)

        for t in tqdm(tcs):
            content = t.content

            if t.considered:
                if is_in(positives, t.url):
                    print(f"PP: Is ground truth: {t.url}")
                    open(pos_tc_folder / (str(t.content_hash) + ".md"), "w").write(content)
                else:
                    print(f"PP: Is considered: {t.url}")
                    open(may_tc_folder / (str(t.content_hash) + ".md"), "w").write(content)
            else:  # not considered
                print(f"PP: Probably not: {t.url}")
                open(neg_tc_folder / (str(t.content_hash) + ".md"), "w").write(content)


if __name__ == "__main__":
    main()
else:
    print("generate_traindata.py is intended to be run via python")
