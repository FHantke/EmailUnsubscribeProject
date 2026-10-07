#!/usr/bin/env python3
"""

Calculates the ranks for jobs of a given crawl_id in the configured database.
"""

import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta
import os
import sys
from random import sample
from abc import ABC
from concurrent.futures.process import ProcessPoolExecutor
import uuid
from typing import List, Dict, Optional, Tuple, Any, Set

from hyperlink import URL
import pandas as pd
import numpy as np
from tqdm import tqdm
from sqlalchemy import select, update

from enfbots_crawler.database import DBJob
from enfbots_crawler import Config, DBWebsite, const, TablesMissingException

from enfbots_crawler import SessionLocal, initialize_base_db
from enfbots_crawler.helper import check_database, set_log_formatter


logger = logging.getLogger()

RANKS = (1000, 5000, 10000, 50000, 100000, 500000, 1000000, 5000000)

COUNTRIES = (
    # EU states
    "at",
    "be",
    "bg",
    "hr",
    "cy",
    "cz",
    "dk",
    "ee",
    "fi",
    "fr",
    "de",
    "gr",
    "hu",
    "ie",
    "it",
    "lv",
    "lt",
    "lu",
    "mt",
    "nl",
    "pl",
    "pt",
    "ro",
    "sk",
    "si",
    "es",
    "se",
    # 'eu', # EU itself domain - does not work for CrUX
    # EFTA states but switzerland removed
    "is",
    "li",
    "no",
    # Other states
    "gb",
    "ch",
)
ALL_COUNTRIES = {
    "ad",
    "ae",
    "af",
    "ag",
    "ai",
    "al",
    "am",
    "ao",
    "ar",
    "as",
    "at",
    "au",
    "aw",
    "ax",
    "az",
    "ba",
    "bb",
    "bd",
    "be",
    "bf",
    "bg",
    "bh",
    "bi",
    "bj",
    "bl",
    "bm",
    "bn",
    "bo",
    "bq",
    "br",
    "bs",
    "bt",
    "bw",
    "by",
    "bz",
    "ca",
    "cd",
    "cf",
    "cg",
    "ch",
    "ci",
    "ck",
    "cl",
    "cm",
    "cn",
    "co",
    "cr",
    "cu",
    "cv",
    "cw",
    "cx",
    "cy",
    "cz",
    "de",
    "dj",
    "dk",
    "dm",
    "do",
    "dz",
    "ec",
    "ee",
    "eg",
    "eh",
    "er",
    "es",
    "et",
    "fi",
    "fj",
    "fk",
    "fm",
    "fo",
    "fr",
    "ga",
    "gb",
    "gd",
    "ge",
    "gf",
    "gg",
    "gh",
    "gi",
    "gl",
    "gm",
    "gn",
    "gp",
    "gq",
    "gr",
    "gt",
    "gu",
    "gw",
    "gy",
    "hk",
    "hn",
    "hr",
    "ht",
    "hu",
    "id",
    "ie",
    "il",
    "im",
    "in",
    "io",
    "iq",
    "ir",
    "is",
    "it",
    "je",
    "jm",
    "jo",
    "jp",
    "ke",
    "kg",
    "kh",
    "ki",
    "km",
    "kn",
    "kp",
    "kr",
    "kw",
    "ky",
    "kz",
    "la",
    "lb",
    "lc",
    "li",
    "lk",
    "lr",
    "ls",
    "lt",
    "lu",
    "lv",
    "ly",
    "ma",
    "mc",
    "md",
    "me",
    "mf",
    "mg",
    "mh",
    "mk",
    "ml",
    "mm",
    "mn",
    "mo",
    "mp",
    "mq",
    "mr",
    "ms",
    "mt",
    "mu",
    "mv",
    "mw",
    "mx",
    "my",
    "mz",
    "na",
    "nc",
    "ne",
    "nf",
    "ng",
    "ni",
    "nl",
    "no",
    "np",
    "nr",
    "nz",
    "om",
    "pa",
    "pe",
    "pf",
    "pg",
    "ph",
    "pk",
    "pl",
    "pm",
    "pr",
    "ps",
    "pt",
    "pw",
    "py",
    "qa",
    "re",
    "ro",
    "rs",
    "ru",
    "rw",
    "sa",
    "sb",
    "sc",
    "sd",
    "se",
    "sg",
    "sh",
    "si",
    "sj",
    "sk",
    "sl",
    "sm",
    "sn",
    "so",
    "sr",
    "ss",
    "st",
    "sv",
    "sx",
    "sy",
    "sz",
    "tc",
    "td",
    "tg",
    "th",
    "tj",
    "tl",
    "tm",
    "tn",
    "to",
    "tr",
    "tt",
    "tv",
    "tw",
    "tz",
    "ua",
    "ug",
    "us",
    "uy",
    "uz",
    "vc",
    "ve",
    "vg",
    "vi",
    "vn",
    "vu",
    "ws",
    "xk",
    "ye",
    "yt",
    "za",
    "zm",
    "zw",
}



def download_crux(yyyymm: str, credentials_path: Path) -> pd.DataFrame:
    if credentials_path is None or not credentials_path.exists():
        raise RuntimeError("Missing google credentials")
    from google.cloud import bigquery

    client = bigquery.Client()

    query = f"SELECT DISTINCT country_code, origin, experimental.popularity.rank as rank FROM `chrome-ux-report.experimental.country` WHERE yyyymm = {yyyymm} AND country_code IN {COUNTRIES}"

    logging.info(f"Downloading crux {yyyymm}")

    df = client.query(query, timeout=30).to_dataframe()

    if len(df) == 0:
        raise RuntimeWarning(f"Empty df received, maybe {yyyymm} was not yet released")

    return df


class MetadataProcessor:
    def __init__(self) -> None:
        self.crux: pd.DataFrame | None = None
        self.tranco: Dict[str, int] = {}
        self.websites: Any
        self.loaded = False

    def load(self, crux_path: Optional[Path]) -> None:
        if self.loaded:
            return

        assert crux_path
        self.crux = pd.read_csv(crux_path, index_col=0)

        logger.info("Grouping by origin")
        self.ranks_per_country = {x: y for x, y in list(self.crux.groupby(self.crux["origin"]))}
        logger.info("Done grouping by origin")

        logging.info("MetadataProcessor finished loading")
        self.loaded = True

    def get_ranks_for_website(self, domain: str) -> Dict:
        if self.crux is None:
            raise RuntimeError("Call MetadataProcessor.load first!")

        # If the domain is not in the crux list, return empty dict
        if domain not in self.ranks_per_country:
            return {}

        grouped = self.ranks_per_country[domain]

        df_origin = grouped

        ranks = {country: None for country in ALL_COUNTRIES}
        for row in df_origin.to_dict("records"):
            ranks[row["country_code"]] = row["rank"]

        return {k: v for k, v in ranks.items() if v is not None}

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

    parser.add_argument(
        "--crawl-id",
        "-i",
        "--id",
        type=str,
        help="Crawl ID for which to calculate the ranks",
        required=True,
        dest="id",
    )
    parser.add_argument(
        "--crux_path",
        "--crux-path",
        type=str,
        help="Path to the crux list (CSV)",
        required=True,
        dest="crux_path",
    )
    parser.add_argument(
        "--dry", help="Run script but do not actually change anything", action="store_true"
    )

    args = parser.parse_args()

    crawl_id: Optional[str] = args.id
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

    mp = MetadataProcessor()

    mp.load(args.crux_path)

    # Firs ensure that all websites exist in the 'websites' table
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        logging.info("Getting all websites already in the database...")

        res = session.execute(
            select(DBJob.id, DBWebsite.url, DBJob.additional_crux_ranks).join(DBWebsite)
                .where(DBJob.crawl_id == crawl_id,
                       DBJob.additional_crux_ranks == None,
                       DBJob.index_redirect == False)
        )

        for x in tqdm(res):
            if x[2] is None:
                ranks = mp.get_ranks_for_website(x[1])
                
                stmt = update(DBJob).where(x[0] == DBJob.id).values(additional_crux_ranks=ranks)
                
                if not dry:
                    session.execute(stmt)


if __name__ == "__main__":
    try:
        main()
    except TablesMissingException:
        logger.error(
            "Database %s is missing the tables. Create a fresh database with 'enfbot --create-database'",
            Config().get_db_url(True),
        )
        sys.exit(1)  # This is fatal
