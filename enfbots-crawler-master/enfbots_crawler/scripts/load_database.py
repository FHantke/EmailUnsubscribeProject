#!/usr/bin/env python3
"""
usage: load_database.py [-h] [--download-crux DOWNLOAD_CRUX] [--crawl_list_path [CRAWL_LIST_PATH]] [--num-websites-per-countryrank NUM_WEBSITES_PER_COUNTRYRANK] [--raw RAW] [--crux_path CRUX_PATH]
                        [--tranco_path TRANCO_PATH] [-i ID] [--create-database] [--force-recrawl | --no-force-recrawl] [--location LOCATION] [--enforce-language] [--browser-language BROWSER_LANGUAGE]
                        [--create-account] [--dry] [--threads THREADS] [--shuffle]

options:
                 -h, --help            show this help message and exit
  --crux_path CRUX_PATH
                        Path to a CrUX list (in csv format)
  --tranco_path TRANCO_PATH
                        Path to the Tranco top 1M list
  -i ID, --id ID        ID of the crawl
  --create-database     Create DB tables
  --force-recrawl, --no-force-recrawl
                        Forces a complete recrawl of all inserted jobs
  --location LOCATION   Sets the location for all inserted jobs. Crawlers can define for which location they accept jobs.
  --enforce-language    Enforces the language defined via --browser-language. If the detected language of the website is not in Config().BROWSER_LANGUAGE we abort the crawl
  --browser-language BROWSER_LANGUAGE
                        Sets the browser language (See Config().BROWSER_LANGUAGE) for all inserted jobs
  --create-account      Instructs the crawlers to try to create accounts (See Config().CREATE_ACCOUNT) for all inserted jobs
  --dry                 Run script but do not actually insert into the database
  --threads THREADS     Use N threads
  --shuffle             Shuffle the urls before inserting

  --download-crux DOWNLOAD_CRUX
                        Downloads the CrUX list of the given argument YYYYMM. Needs the environment variable GOOGLE_APPLICATION_CREDENTIALS!
  --crawl_list_path [CRAWL_LIST_PATH]
                        Path to URLs in a CSV
  --num-websites-per-countryrank NUM_WEBSITES_PER_COUNTRYRANK
                        Number of websites to crawl PER country and rank
  --raw RAW             List of domains to insert.

Load the given list of domains into the database as jobs. 

If a static list (via --raw) and sampling (via --num-websites-per-countryrank) 
is given then the first jobs (with lowest created_at) will be the static list
followed by the sampled websites
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
from sqlalchemy import select

from enfbots_crawler.database import DBJob
from enfbots_crawler import Config, DBWebsite, const, TablesMissingException

from enfbots_crawler import SessionLocal, initialize_base_db
from enfbots_crawler.helper import (
    check_database,
    get_non_unique_items,
    open_text,
    set_log_formatter,
)


logger = logging.getLogger()

RANKS = (1000, 5000, 10000, 50000, 100000, 500000, 1000000, 5000000)

# COUNTRIES = ('de', 'fr', 'ch', 'gb', 'us')  # cookies
# https://www.destatis.de/Europa/EN/Country/Country-Codes.html
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


def get_latest_crux_date() -> str:
    """
    As crux may not be released for the current or previous month, we default to
    using a version 1.5 months ago

    Returns:
        str: Date in the format YYYYMM which can directly be used to download
             the given list.
    """
    safe_date = datetime.now() - timedelta(days=45)
    return f"{safe_date.year}{safe_date.month:02d}"


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
    def __init__(self, num_threads: int) -> None:
        self.crux: pd.DataFrame | None = None
        self.tranco: Dict[str, int] = {}
        self.websites: Any
        self.num_threads = num_threads
        self.loaded = False

    def load(self, crux_path: Optional[Path], tranco_path: Optional[Path]) -> None:
        if self.loaded:
            return
        if crux_path:
            df = pd.read_csv(crux_path, index_col=0)
        else:
            if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
                raise RuntimeWarning(
                    "Please define GOOGLE_APPLICATION_CREDENTIALS to point to google credentials or set --crux_path"
                )
            latest_year_month = get_latest_crux_date()
            df = download_crux(
                latest_year_month, Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
            )

            # Also safe to disk
            df.to_csv(f"/tmp/crux_all_{latest_year_month}.csv")

        self.crux = df

        logger.info("Grouping by origin")
        self.ranks_per_country = {x: y for x, y in list(df.groupby(df["origin"]))}
        logger.info("Done grouping by origin")

        if tranco_path:
            with open(tranco_path, "r", encoding="utf-8") as file:
                for i, line in enumerate(file):
                    line_i, url = line.rstrip().split(",")
                    i = int(line_i)
                    domain = self.get_domain(url)
                    if domain:
                        self.tranco[domain] = i
                    elif url:
                        self.tranco[url] = i
        logging.info("MetadataProcessor finished loading")
        self.loaded = True

    def get_tranco_idx(self, domain: str) -> int:
        if domain in self.tranco:
            return self.tranco[domain]
        return -1

    @staticmethod
    def process_country(param: Tuple[str, pd.DataFrame]) -> Tuple[str, Dict]:
        country = param[0]
        crux = param[1]

        d = {
            rank: set(
                crux[(crux["country_code"] == country) & (crux["rank"] == rank)]["origin"].values
            )
            for rank in RANKS
        }
        return (country, d)

    def get_sampled_websites(self, sites_per_countryrank: int) -> set:
        """

        Args:
            sites_n (int): amount of websites to sample per country and rank

        Returns:
            Set of domains: Domains that were sampled
        """
        with ProcessPoolExecutor(max_workers=self.num_threads) as pool:
            logger.info(
                "Starting to generate websites for all countries in %s threads ...",
                self.num_threads,
            )

            cdicts = pool.map(self.process_country, zip(COUNTRIES, [self.crux] * len(COUNTRIES)))

        self.websites = {c: d for c, d in cdicts}
        logger.info("Finished populating websites")

        out: Set = set()
        # this samples sample_n PER rank AND country not only per country
        for country in COUNTRIES:
            for rank in sorted(RANKS):
                websites_in_country_with_rank = self.websites[country][rank]

                # Take at most the amount of websites at that rank/country
                sample_n = min(sites_per_countryrank, len(websites_in_country_with_rank))

                sampled = set(sample(tuple(websites_in_country_with_rank), sample_n))

                overlap = len(sampled & out)
                # logging.info("Overlap size: %i", overlap)

                out = out | sampled
        return out

    @staticmethod
    def get_domain(url: str) -> str:
        return str(url)

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

    def list_to_df(self, samples: List[str]) -> pd.DataFrame:
        res = []
        if self.crux is None:
            raise RuntimeError("self.crux is None. Missing or failed load")

        # First print those that are in sample (the file loaded) but not in crux
        sample_series = pd.DataFrame(samples)

        non_unique = get_non_unique_items(samples)
        if len(non_unique) > 0:
            logging.warning("Non unique urls from list: %s", non_unique)

        contained = sample_series.isin(list(self.crux["origin"])).reset_index()
        not_contained = sample_series[contained.map(lambda x: not x)].dropna()
        if len(not_contained) > 0:
            logging.warning("These URLs are not in the list: %s", list(not_contained[0]))

        logging.info("Calculating ranks")
        df_sample = self.crux[self.crux["origin"].isin(samples)]
        for origin, df_origin in tqdm(
            df_sample.groupby(df_sample["origin"]), desc="Calculating ranks"
        ):
            ranks = {country: None for country in ALL_COUNTRIES}
            lowest_rank = float("inf")
            lowest_country = "zz"
            for row in df_origin.to_dict("records"):
                ranks[row["country_code"]] = row["rank"]
                if row["rank"] < lowest_rank or (
                    row["rank"] == lowest_rank
                    and row["country_code"] < lowest_country
                    and row["country_code"] in COUNTRIES
                ):
                    lowest_rank = row["rank"]
                    lowest_country = row["country_code"]

            res.append(
                {
                    "domain": origin,
                    "chrome_ux_url": origin,
                    "list_index": lowest_rank,
                    "list_index_source": lowest_country,
                    "tranco_index": self.get_tranco_idx(self.get_domain(str(origin))),
                    "additional_crux_ranks": {k: v for k, v in ranks.items() if v is not None},
                }
            )
        logging.info("Finished calculating ranks")
        return pd.DataFrame(res)


class DBImporter(ABC):
    """
    Assumes that SessionLocal was already configured. This inserts jobs into the
    already configured database.

    """

    def __init__(self, shuffle: bool, dry: bool, num_threads: int) -> None: ...

    def import_jobs(self, jobs: List[DBJob]) -> None: ...


class DefaultImporter(DBImporter):
    def __init__(self, shuffle: bool, dry: bool, num_threads: int) -> None:
        self.shuffle = shuffle
        self.dry = dry
        self.num_threads = num_threads

    def import_jobs(self, jobs: List[DBJob]) -> None:
        """
        Inserts all jobs. All jobs will get their website_id set as well as created_at. NO duplication checks are done

        Args:
            jobs (List[DBJob]): Jobs to insert
        """

        # Shuffle if desired
        if self.shuffle:
            logger.info("Shuffling jobs before insertion")
            np.random.default_rng().shuffle(jobs)  # type: ignore

        logging.info("Ensuring the DBWebsites exist in the database for %s domains", len(jobs))

        # Firs ensure that all websites exist in the 'websites' table
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            logging.info("Getting all websites already in the database...")

            websites = {}

            if not self.dry:
                for x in tqdm(session.execute(select(DBWebsite.id, DBWebsite.url)).all()):
                    websites[x.url] = x.id

            missing_websites: List[DBWebsite] = []
            missing_website_domains: List[str] = []

            logging.info("Creating DBWebsites...")
            for job in tqdm(jobs):
                if not self.dry:
                    if (
                        str(job.website.url) not in websites
                        and not str(job.website.url) in missing_website_domains
                    ):
                        str_url = str(job.website.url)
                        website = DBWebsite(url=str_url)
                        missing_websites.append(website)
                        missing_website_domains.append(str_url)
                else:
                    if len(jobs) <= 100:
                        logging.info("Would add website %s", job.website.url)

            logging.info("Bulk save of %s websites", len(missing_websites))
            session.bulk_save_objects(missing_websites, return_defaults=False)
            logging.info("Finished.")

        logging.info("Preparing jobs for insertion")

        # To generate the times fast we still use parallelism and assume 1ms steps between consecutive created_at
        start_time = datetime.now()

        def calc_created_at(index: int) -> datetime:
            return start_time + index * timedelta(milliseconds=1)

        logging.info("Calculating created_at times with a delta of 1ms ")
        for i, job in enumerate(jobs):
            job.created_at = calc_created_at(i)

        logging.info("Inserting them in order")

        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            websites = {}

            logging.info("Setting the website ids")

            if not self.dry:
                for x in tqdm(session.execute(select(DBWebsite.id, DBWebsite.url)).all()):
                    websites[x.url] = x.id

                for job in jobs:
                    job.website_id = websites[job.website.url]

                logging.info("Saving %s jobs...", len(jobs))
                session.bulk_save_objects(jobs)
                logging.info("Stored %s jobs", len(jobs))
            else:
                logging.info("Would create %s jobs", len(jobs))


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
    run_group = parser.add_argument_group()

    run_group.add_argument(
        "--download-crux",
        type=str,
        help="Downloads the CrUX list of the given argument YYYYMM. Needs the environment variable GOOGLE_APPLICATION_CREDENTIALS!",
    )
    run_group.add_argument("--crawl_list_path", nargs="?", type=Path, help="Path to URLs in a CSV")
    run_group.add_argument(
        "--num-websites-per-countryrank",
        help="Number of websites to crawl PER country and rank",
    )
    run_group.add_argument(
        "--raw", help="List of domains to insert (plain text, or compressed as .xz or .gz)."
    )

    # crawl_list_path options:
    parser.add_argument("--crux_path", type=Path, help="Path to a CrUX list (in csv format)")
    parser.add_argument("--tranco_path", type=Path, help="Path to the Tranco top 1M list")
    parser.add_argument("-i", "--id", help="ID of the crawl")
    parser.add_argument("--create-database", help="Create DB tables", action="store_true")
    parser.add_argument(
        "--force-recrawl",
        help="Forces a complete recrawl of all inserted jobs",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--location",
        help="Sets the location for all inserted jobs. Crawlers can define for which location they accept jobs.",
    )
    parser.add_argument(
        "--enforce-language",
        help="Enforces the language defined via --browser-language. If the detected language of the website is not in Config().BROWSER_LANGUAGE we abort the crawl",
        action="store_true",
    )
    parser.add_argument(
        "--browser-language",
        help="Sets the browser language (See Config().BROWSER_LANGUAGE) for all inserted jobs",
    )
    parser.add_argument(
        "--create-account",
        help="Instructs the crawlers to try to create accounts (See Config().CREATE_ACCOUNT) for all inserted jobs",
        action="store_true",
    )
    parser.add_argument(
        "--ignore-crux",
        help="Do not download Crux for the ranks",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--dry", help="Run script but do not actually insert into the database", action="store_true"
    )
    parser.add_argument("--threads", help="Use N threads", dest="threads", default=8)
    parser.add_argument(
        "--shuffle", action="store_true", default=False, help="Shuffle the urls before inserting"
    )
    parser.add_argument(
        "--allow-duplicates",
        help="Allows to import multiple jobs with the same domain. Used for development purposes.",
        action="store_true",
        default=False,
    )

    args = parser.parse_args()

    # Download list
    if args.download_crux:
        if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
            raise RuntimeError(
                "Please define GOOGLE_APPLICATION_CREDENTIALS to point to google credentials"
            )
        df = download_crux(args.download_crux, Path(os.environ["GOOGLE_APPLICATION_CREDENTIALS"]))
        df.to_csv(f"./crux_all_{args.download_crux}.csv")
        return

    if args.crawl_list_path:
        raise RuntimeError("This is currently not implemented")

    crawl_id: Optional[str] = args.id
    dry: Optional[bool] = args.dry
    location: Optional[str] = args.location
    force_recrawl: bool = args.force_recrawl
    enforce_language: Optional[bool] = args.enforce_language
    browser_language: Optional[str] = args.browser_language
    create_account: Optional[str] = args.create_account
    num_threads: int = int(args.threads)
    shuffle: bool = args.shuffle
    allow_duplicates: bool = args.allow_duplicates

    if not dry:
        # initialize DB tables
        logger.info("[Load database]: Connecting to db_url %s", Config().get_db_url(True))

        initialize_base_db(
            alembic_root_dir=Config().code_dir,
            db_url=Config().get_db_url(),
            pool_size=32,
        )

    # Check if database connection works
    if not dry and not check_database(Config().code_dir):
        raise RuntimeError(
            "There seems to be a problem with the database. Check your CRAWLER_DB_* settings!"
        )

    jobs: Dict[str, DBJob] = {}

    importer: DBImporter
    mp = MetadataProcessor(num_threads)

    if not args.ignore_crux:
        mp.load(args.crux_path, args.tranco_path)

    if args.raw:
        with open_text(args.raw) as raw_file:
            lines = [s.strip() for s in raw_file]
        domains = []

        # Print urls without domain scheme (https:// or http://)
        for line in lines:
            url_str = line.rstrip()
            if url_str != "":
                url = URL.from_text(url_str)
                if not url.scheme:
                    logging.warning("Adding domain without scheme: %s", url)
                if str(url).strip() == "":
                    continue
                domains.append(str(url).strip("/"))

        # Only unique domains
        if not allow_duplicates:
            domains = [domains[i] for i in sorted(np.unique(domains, return_index=True)[1])]

        for d in tqdm(
            domains,
            total=len(domains),
            desc=f"Creating DBJobs from static list of {len(domains)} domains",
        ):
            job = DBJob(
                crawl_id=crawl_id,
                force_recrawl=force_recrawl,
                browser_language=browser_language,
                create_account=create_account,
            )

            if location is not None:
                job.location = location

            if enforce_language:
                job.enforce_language = enforce_language

            job.website = DBWebsite()
            job.website.url = d
            job.from_static = True

            # Set the ranks
            if not args.ignore_crux:
                job.additional_crux_ranks = mp.get_ranks_for_website(d)

            if allow_duplicates:
                jobs[d + "_" + str(uuid.uuid4())] = job
            else:
                jobs[d] = job

        logger.info("Loaded %d domains from raw list.", len(domains))

    if args.num_websites_per_countryrank:
        mp.load(args.crux_path, args.tranco_path)
        num_websites_per_countryrank = int(args.num_websites_per_countryrank)

        logging.info("Start sampling %s per country and rank", num_websites_per_countryrank)
        websites = mp.get_sampled_websites(num_websites_per_countryrank)

        logging.info("Converting samples to pandas DataFrame")
        df = mp.list_to_df(list(websites))
        logging.info("Done converting")

        for row in df.iterrows():
            entry = row[1]

            if entry["domain"] in jobs:
                logger.debug("Already in raw list: %s", entry["domain"])
                jobs[entry["domain"]].from_dynamic = True
                continue

            job = DBJob(
                crawl_id=crawl_id,
                force_recrawl=force_recrawl,
                browser_language=browser_language,
                create_account=create_account,
            )

            website = DBWebsite()
            website.url = entry["domain"]

            job.list_index = entry["list_index"]
            job.list_index_source = entry["list_index_source"]
            job.chrome_ux_url = entry["chrome_ux_url"]
            job.tranco_index = entry["tranco_index"]

            job.website = website
            job.additional_crux_ranks = entry["additional_crux_ranks"]

            job.from_dynamic = True

            jobs[entry["domain"]] = job

    importer = DefaultImporter(shuffle, dry or False, int(args.threads))

    importer.import_jobs(list(jobs.values()))


if __name__ == "__main__":
    try:
        main()
    except TablesMissingException:
        logger.error(
            "Database %s is missing the tables. Create a fresh database with 'enfbot --create-database'",
            Config().get_db_url(True),
        )
        sys.exit(1)  # This is fatal
