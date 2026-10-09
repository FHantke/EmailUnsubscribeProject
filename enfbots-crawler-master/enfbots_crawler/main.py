#!/usr/bin/env python3

"""
This is the entry point when starting enfbot.
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
import socket
import json
from importlib.metadata import version

# Libs
from typing import Optional, cast
from enfbots_crawler.exceptions import WebsiteException
import tldextract
from hyperlink import URL
from filelock import FileLock
import twocaptcha
from readabilipy.utils import run_npm_install

from selenium.common.exceptions import WebDriverException

from enfbots_crawler import (
    CrawlerException,
    DomainBlacklistedError,
    const,
    TablesMissingException,
    OutdatedDatabaseException,
)

# Imports from the enfbots library
from enfbots_crawler.helper import (
    ns_lookup,
    is_google_unsafe,
    assemble_url,
    set_log_formatter,
    is_in_blocklist,
    domain_suffix_to_location,
    get_spoken_languages_of_tld,
    merge_languages_with_prio,
    get_progress,
    get_speed,
    get_jobs_todo,
    check_database,
    check_classifier,
    check_sybilmail,
)
from enfbots_crawler.database import (
    start_next_job,
    initialize_base_db,
    SessionLocal,
    update_database,
    DBJob,
    DBWebsite,
    DBWebsiteCrawl,
    get_latest_crawl,
    get_best_tc_link,
    get_best_pp_link,
    create_views,
    get_website,
)
from enfbots_crawler.modules.stat_collector import StatCollector, CollectType
from enfbots_crawler import Config, DomainStatus
from enfbots_crawler.alerts import send_alert
from enfbots_crawler.browser import create_browser, EnfbotsBrowser
from enfbots_crawler.captcha_solver import CaptchaAccountBalanceException, CaptchaSolverStub
from enfbots_crawler.website import WebSite


logger = logging.getLogger("enfbots_crawler")


def domain_status(domain: str, url: Optional[str] = None) -> DomainStatus:
    test_url = url if url else f"http://{domain}/"
    if Config().USE_SAFE_BROWSING_API and is_google_unsafe(
        test_url, google_api_key=Config().GOOGLE_API_KEY
    ):
        return DomainStatus.UNSAFE

    blocklist = Config().DOMAIN_BLACKLIST
    if blocklist is not None and is_in_blocklist(blocklist, domain):
        return DomainStatus.BLACKLISTED

    tld_location = domain_suffix_to_location(tldextract.extract(domain).suffix)

    # Check if location is blocked
    ips = ns_lookup(domain)
    if not ips:
        ips = ns_lookup(domain.split("//")[-1])
    if ips:
        ip = ips[0]
        lookup = ".".join(reversed(ip.split(".")))
        if lookup[0] == ".":
            lookup = lookup[1:]
        geo_query = lookup + ".origin.asn.cymru.com"
        results = ns_lookup(geo_query, "TXT")
        for line in results:
            split = line.split("|")
            if len(split) < 3:
                logger.error("Unexpected result in domain_status: %s", line)
                continue
            ip_location = split[2].strip()
            if ip_location == tld_location:
                if ip_location in Config().BLACKLIST_LOCATIONS:
                    return DomainStatus.LOCATION_BLOCKED

    return DomainStatus.OK


def run_domain(
    url: str,
    stat_collector: StatCollector = StatCollector(),
    job: Optional[DBJob] = None,
    desired_lang: str = "en",
    seconds_before_processing_page: float = 1.5,
    cached_website_crawl: Optional[DBWebsiteCrawl] = None,
    headless: bool = True,
) -> Optional[WebSite]:
    """
    Process single URL - wrapper that catches all types of exceptions.
    Exits if user interrupted the execution by ctrl+c

    :param hostname: hostname to crawl (can be IP or Domain)
    :param desired_lang: Language code of the language the crawler should try to switch to
    :param job: for crawling from DB, URL is given as DBJob instance
    :return: True if the crawl did not quit unexpectedly
    """

    is_cached = cached_website_crawl is not None

    if not is_cached:
        if str(Config().SYBIL_URL).strip() == "" and Config().CREATE_ACCOUNT:
            raise CrawlerException(
                "You are missing the SYBIL_URL setting "
                "(Set it via the CRAWLER_SYBIL_URL environment variable)"
            )

        if Config().SYBIL_ID < 0 and Config().CREATE_ACCOUNT:
            raise CrawlerException(
                "You are missing the SYBIL_ID setting "
                "(Set it via the CRAWLER_SYBIL_ID environment variable)"
            )

        if Config().SYBIL_AUTH_TOKEN.strip() == "" and Config().CREATE_ACCOUNT:
            raise CrawlerException(
                "You are missing the SYBIL_AUTH_TOKEN setting "
                "(Set it via the SYBIL_AUTH_TOKEN environment variable)"
            )

    # Prints the running configuration
    logging.info("%s", Config())

    start = time.time()
    status = domain_status(url)
    ok = status == DomainStatus.OK or (
        status == DomainStatus.OK_RUSSIAN and not Config().BLACKLIST_RUSSIAN
    )

    if not ok:
        logger.info("The job was rejected with status: %s", status.name)
        if job:
            # pylint: disable=no-member
            with SessionLocal.begin() as session:
                # Here it makes sense to fetch the job again from the database
                job = session.merge(job)
                job.domain_status = status
                job.ended_at = datetime.now()
        raise DomainBlacklistedError(status.name)

    if job:
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            session.add(job)
            job.domain_status = status

            logger.info("Doing job with ID %s to %s", job.id, job.website.url)

    http_target_url = assemble_url(url)

    tld = tldextract.extract(str(http_target_url))

    logger.info("TLD of the website: %s", tld.suffix)

    tld_languages = get_spoken_languages_of_tld(tld.suffix)
    languages = merge_languages_with_prio(tld_languages, Config().BROWSER_LANGUAGE.split(","))
    end = time.time()
    logger.info("Preparation time took %.3f", (end - start))

    start = time.time()
    with create_browser(
        languages=languages,
        seconds_before_processing_page=seconds_before_processing_page,
        intercept_network=Config().CREATE_ACCOUNT,
        headless=headless,
    ) as browser:
        end = time.time()
        stat_collector.add_browser_startup_seconds(end - start)
        site = WebSite(cast(EnfbotsBrowser, browser), http_target_url)

        try:
            if is_cached:
                # pylint: disable=no-member
                with SessionLocal.begin() as session:
                    # This is provided as if is_cached is true, cached_website_crawl is not None
                    assert cached_website_crawl is not None

                    pp_url = get_best_pp_link(
                        cached_website_crawl, Config().MIN_SCORE_KEYWORD_CLASSIFY_PP
                    )
                    tc_url = get_best_tc_link(
                        cached_website_crawl, Config().MIN_SCORE_KEYWORD_CLASSIFY_TC
                    )

                    if pp_url is None or tc_url is None or cached_website_crawl.lang is None:
                        logger.info(
                            "Normal crawl as some info is missing. (%s)", cached_website_crawl
                        )
                        site.crawl()
                        stat_collector.visited_website()
                    else:
                        pp_url = session.merge(pp_url)
                        tc_url = session.merge(tc_url)

                        logger.info("pp_url: %s", pp_url)
                        logger.info("tc_url: %s", tc_url)

                        site.validation_crawl(
                            tc_url=URL.from_text(tc_url.tc_url.url),
                            pp_url=URL.from_text(pp_url.pp_url.url),
                            prev_lang_code=cached_website_crawl.lang,
                        )
                        stat_collector.validated_website()
            else:
                logger.info("Doing a normal crawl")
                site.crawl()
                stat_collector.visited_website()

            stat_collector.add(site.crawl_stat_collector)

            # Store website_crawl in DB
            logger.info("Saving the results into the database.")

            site.get_db_entity(job)

            if job:

                # pylint: disable=no-member
                with SessionLocal.begin() as session:
                    session.add(job)

                    logger.info("Ending the corresponding job.")
                    job.ended_at = datetime.now()

            # Add redirect website
            if site.index_redirect_url and job is not None:

                ds = domain_status(
                    site.index_redirect_url.host, url=site.index_redirect_url.asText()
                )

                if not ds == DomainStatus.OK:
                    logger.warning(
                        "Got redirected to %s but status is: %s", site.index_redirect_url, ds
                    )
                    return None

                # pylint: disable=no-member
                with SessionLocal.begin() as session:
                    exist_query = (
                        session.query(DBJob)
                        .join(DBWebsite.jobs)
                        .filter(
                            DBWebsite.url == site.index_redirect_url.host,
                            DBJob.crawl_id == job.crawl_id,
                        )
                        .first()
                    )
                    if not exist_query:
                        logger.info(
                            "Index page redirected to %s. Creating new job in the database.",
                            site.index_redirect_url,
                        )

                        redir_url = site.index_redirect_url.host

                        if redir_url.strip() == "":
                            logger.error("Got redirected to '' (%s)", site.index_redirect_url)
                            return None
                        ws = get_website(URL.from_text(redir_url))

                        new_job = DBJob(
                            website=ws,
                            crawl_id=job.crawl_id,
                            index_redirect=True,
                        )
                        session.add(new_job)
                    else:
                        logger.info(
                            "Index page redirected to %s "
                            "but the job for it already exists in the database.",
                            site.index_redirect_url,
                        )
        except CaptchaAccountBalanceException:
            send_alert(
                "Captcha account empty",
                "The crawl cannot continue since the captcha account is empty.\n"
                "Please refill me.\n\nBest regards,\nYour friendly neighbourhood bot",
            )
            logger.exception("Captcha service account is out of funds")
            raise
        except KeyboardInterrupt:
            logger.warning("Crawl stopped by user")
            raise
        except WebsiteException as e:
            logger.exception(e)
        except Exception as e:
            # this should never actually happen
            logger.exception(
                "Unknown error occurred during the crawl of website %s", http_target_url
            )
            raise CrawlerException(e) from e
        finally:
            # Stop writing into this website's crawler.log before the next website starts
            site.close_log()

    return site


def run_crawler() -> None:
    """
    Enforcement bots enfbots_crawler

    This file contains all the main functionality and the entry point.
    """
    ver = version("enfbots-crawler")

    # First set up logging by loading the configuration and then
    # set the specified loglevel
    set_log_formatter(const.LOG_FORMAT_INFO, "%Y-%m-%d:%H:%M:%S")
    root_logger = logging.getLogger()
    root_logger.setLevel(
        logging.INFO
    )  # Only until we've loaded the config and set the desired LOG_LEVEL
    Config().reset()
    if not Config().load():
        raise RuntimeError("There seems to be an issue with the configuration")
    root_logger.setLevel(Config().LOG_LEVEL)

    logger.info(
        "Starting enfbots-crawler version %s with loglevel %s",
        ver,
        logging.getLevelName(Config().LOG_LEVEL),
    )

    # Log to output directory if we're staging
    if Config().ENV == "staging":
        log_formatter = root_logger.handlers[0].formatter
        file_handler = logging.FileHandler(Config().LOG_PATH)
        file_handler.setFormatter(log_formatter)
        root_logger.addHandler(file_handler)

    # Parse the input arguments
    parser = argparse.ArgumentParser()

    # Action arguments (mutually exclusive and each is its own run)
    run_group = parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("--create-database", help="Create database", action="store_true")
    run_group.add_argument(
        "--update-database", help="Updates the database to the current version", action="store_true"
    )
    run_group.add_argument("-u", "--url", help="Crawl a single domain")
    run_group.add_argument("-l", "--list", help="Crawl a list of domains")
    run_group.add_argument(
        "-d", "--database", help="Find the next job in the database", action="store_true"
    )
    run_group.add_argument(
        "-s",
        "--store",
        help="Download the given url to the OUTPUT_PATH. Expects PAGE_URL FILE_NAME",
        nargs=2,
    )
    run_group.add_argument(
        "--merge-stats",
        help="Accepts a list of files what will be merged into a file with the last arguments name",
        nargs="*",
    )
    run_group.add_argument(
        "--install-readabilipy",
        help="Installs the needed npm packages for readabilipy, else it gets installed before first use",
        action="store_true",
    )
    run_group.add_argument(
        "--is-finished",
        help="Check if the given ID is finished. Exit code will be 0 if finished, else non-zero",
        action="store_true",
    )
    run_group.add_argument(
        "--get-progress",
        help="Shows the progress of the given crawl id",
        dest="get_progress",
        action="store_true",
    )
    run_group.add_argument(
        "--get-speed",
        help="Shows the speed in crawls per minute (of the last hour) of the given crawl id",
        dest="get_speed",
        action="store_true",
    )
    run_group.add_argument(
        "--eta",
        help="Print the expected time of finish according to the current crawling speed.",
        dest="eta",
        action="store_true",
    )
    run_group.add_argument(
        "--launch-browser",
        help="Only launches the browser which allows modification of the current profile",
        action="store_true",
    )

    # Now follow non-action arguments
    parser.add_argument(
        "-dn",
        "--database-amount",
        help="Number of jobs to do from the database before stopping (or until there are no more jobs)",
    )
    parser.add_argument("-i", "--id", help="ID of the crawl")
    parser.add_argument(
        "-c", "--config", help="Set a configuration option. See config.py", action="append"
    )
    parser.add_argument(
        "--delay",
        help="Debugging option to see what the browser is doing. Wait this amount of seconds before processing the website but after we started browsing the URL.",
    )
    parser.add_argument("--location", help="Only run jobs for this specific location")
    parser.add_argument(
        "--dry-d",
        help="Only fetch job from database without running it.",
        action="store_true",
        dest="dry",
    )
    parser.add_argument(
        "--stats",
        help="Path to a file which already contains statistics and this crawler will add its overall statistics to them or create them",
        dest="stats",
    )
    parser.add_argument(
        "--no-headless",
        help="Start the browser with GUI (headless disabled)",
        action="store_true",
    )
    args = parser.parse_args()

    # Load manual configs i.e. -c CRAWL_ID=crawl-emails
    if args.config:
        for cfg in args.config:
            key, value = cfg.split("=", 1)
            Config().set(key, value)
    if args.id:
        Config().CRAWL_ID = args.id

    if args.database_amount and not args.database_amount.isdigit():
        raise CrawlerException("--database-amount must be an integer")

    if args.is_finished:
        initialize_base_db(
            db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir, create=False
        )
        if not hasattr(args, "id") or args.id is None:
            logger.info("Missing --id argument")
            sys.exit(1)
        logger.info("Checking if crawl %s is finished", args.id)

        try:
            next_job = start_next_job(
                crawl_id=args.id, dry=True, location=args.location, ignore_error_timeout=True
            )
        except Exception as e:
            logger.error(e)
            logger.info("NO, not finished due to error")
            sys.exit(1)

        if next_job is None:
            logger.info("YES, %sis finished", f"{args.id} " if args.id else "")
            sys.exit(0)
        else:
            jobs_todo = get_jobs_todo(Config().code_dir, args.id)

            logger.info("NO, not finished. There are still %i jobs to finish.", jobs_todo)

            sys.exit(1)
        return

    if args.merge_stats:
        filename = args.merge_stats[-1]
        if os.path.isfile(filename):
            logger.error("File already exists: %s.", filename)
            logger.error("Last argument name is filename where the merged statistic are writen to")
            return
        base = StatCollector()
        print(type(args.merge_stats[:-1]))
        for file in args.merge_stats[:-1]:
            with open(file, "r", encoding="utf-8") as file:
                existing_json = json.loads("\n".join(file.readlines()))
                if "bytes_translated" in existing_json:
                    existing_json.pop("bytes_translated")
                existing_stats = StatCollector(
                    collect_type=CollectType.MULTIPLE_CRAWLS, **existing_json
                )
                base.add(existing_stats)

        stat_merged = base.to_json()
        with open(str(args.merge_stats[-1]), "w", encoding="utf-8") as out_file:
            out_file.write(stat_merged)
        logger.info("Merged into: %s", filename)
        return

    if args.install_readabilipy:
        logger.info("Installing readabilipy dependencies")
        run_npm_install()
        return

    # quiet down some extra loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    # Disable for now to see if there are any problems
    logging.getLogger("polyglot").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("seleniumwire").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
    logging.getLogger("pdfminer.psparser").setLevel(logging.INFO)

    # initialize db tables
    if args.create_database:
        initialize_base_db(
            db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir, create=True
        )
        create_views()
        return

    if args.update_database:
        update_database(db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir)
        return

    delay: float
    if args.delay:
        delay = float(args.delay)
    else:
        delay = 0.0

    if args.launch_browser:
        with create_browser(
            seconds_before_processing_page=delay,
            intercept_network=Config().CREATE_ACCOUNT,
            headless=False,
        ) as browser:
            time.sleep(60 * 60)
            return

    # Download website and translate if necessary
    if args.store:
        page_url = URL.from_text(args.store[0])
        dest_name = Path(args.store[1])

        with create_browser(
            seconds_before_processing_page=delay,
            intercept_network=Config().CREATE_ACCOUNT,
            headless=False if args.no_headless else True,
        ) as browser:
            site = WebSite(cast(EnfbotsBrowser, browser), URL.from_text("http://not-set.com/"))
            try:
                site.download_page(page_url, dest_name)
            except KeyboardInterrupt:
                logger.warning("Download stopped by user")
                raise
            # pylint: disable=broad-exception-caught
            except Exception:
                logger.exception("Unknown error occurred during the crawl of website %s", page_url)
        logger.info("Finished downloading %s to %s", page_url, dest_name)
        return

    # Initialize the database
    logger.info("Initializing connection to the database %s", Config().get_db_url(True))
    initialize_base_db(
        db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir, connection_info=ver
    )
    logger.info("Connected to the DB.")

    if args.get_progress:
        if not args.id:
            logger.error("Please provide the crawl_id via --id")
            return

        progress = get_progress(Config().code_dir, args.id)

        logger.info("Progress of crawl %s is: %.2f%%", args.id, progress * 100)
        return

    if args.get_speed:
        if not args.id:
            logger.error("Please provide the crawl_id via --id")
            return

        speed = get_speed(Config().code_dir, args.id)

        logger.info("Speed of crawl %s is %.2f per minute (over the last hour)", args.id, speed)
        return

    if args.eta:
        if not args.id:
            logger.error("Please provide the crawl_id via --id")
            return

        speed = get_speed(Config().code_dir, args.id)
        jobs_todo = get_jobs_todo(Config().code_dir, args.id)

        if speed < 1e-10:
            logger.info("Too slow")
            return
        else:
            minutes_remaining = jobs_todo * 1.0 / speed
            eta = datetime.now() + timedelta(minutes=minutes_remaining)

            logger.info(
                "ETA: %s (%.0f hours)", eta.strftime("%Y-%m-%d %H:%M:%S"), minutes_remaining / 60
            )
        return

    # Check if database connection works
    if not check_database(Config().code_dir):
        raise RuntimeError(
            "There seems to be a problem with the database. Check your CRAWLER_DB_* settings or the database revision!"
        )

    # Check if some critical settings are configured
    if Config().USE_SAFE_BROWSING_API and Config().GOOGLE_API_KEY.strip() == "":
        raise CrawlerException(
            "You are missing the GOOGLE_API_KEY setting "
            "(Set either the CRAWLER_GOOGLE_API_KEY environment variable or CRAWLER_USE_SAFE_BROWSING_API=False)"
        )

    if Config().BROWSER == "chrome" and Config().CHROME_DISABLE_SHM is False:
        # get the size of /dev/shm in kB
        shm_size_kbytes = int(os.popen("df /dev/shm").readlines()[1].split()[1])

        if shm_size_kbytes < 1000 * 128:
            logger.error(
                "Size of /dev/shm/ is smaller than 128MB and CRAWLER_CHROME_DISABLE_SHM is not set. "
                "Chrome either needs more shm or the above flag is set."
            )
            sys.exit(1)

    # As the classifier cannot be run with python 3.11 we need one
    if Config().USE_CLASSIFIER and not check_classifier(
        Config().CLASSIFY_SERVICE_ENDPOINT,
        Config().CLASSIFY_SERVICE_USER,
        Config().CLASSIFY_SERVICE_TOKEN,
    ):
        raise CrawlerException(
            "Classifier does not work but is required due to CRAWLER_USE_CLASSIFIER."
        )

    # Only check Sybilmail if the URL is given; If it's empty it could also be that all jobs have CREATE_ACCOUNT=False
    if (
        Config().CREATE_ACCOUNT
        and str(Config().SYBIL_URL)
        and not check_sybilmail(Config().SYBIL_URL, Config().SYBIL_AUTH_TOKEN)
    ):
        logging.error("Sybilmail at %s does not work", Config().SYBIL_URL)
        return

    if str(Config().TWOCAPTCHA_ACCESS_TOKEN):
        logging.info("Checking twocaptcha")

        # Try multiple times if network is unreliable
        tries = 3
        for i in range(tries):
            try:
                scanner = CaptchaSolverStub(cast(EnfbotsBrowser, None))
                balance = scanner.solver_2captcha.balance()
                logger.info("Twocaptcha balance: %f", balance)
                if balance <= 0.0:
                    raise CrawlerException("Twocaptcha has too little balance")
                break
            except twocaptcha.NetworkException as e:
                time.sleep(10)
                if i == tries - 1:
                    raise e

    # Stores the statistics over all crawls (if there are multiple)
    stats = StatCollector(CollectType.MULTIPLE_CRAWLS)
    stats.start()

    try:
        if args.url:
            logger.info("Crawling single page: %s", args.url)
            run_domain(
                args.url,
                stat_collector=stats,
                seconds_before_processing_page=delay,
                headless=not args.no_headless,
            )
        elif args.list:
            logger.info("Crawling list of pages at: %s", args.list)
            with open(args.list, "r", encoding="utf-8") as urls_input_file:
                for line in urls_input_file:
                    url = line.strip()
                    if url:
                        logger.info("Crawling page: %s", url)
                        run_domain(
                            args.url,
                            stat_collector=stats,
                            seconds_before_processing_page=delay,
                            headless=not args.no_headless,
                        )
        elif args.database:
            num_crawls = int(args.database_amount) if args.database_amount else 1
            logger.info("Will take %i jobs from the database before exiting", num_crawls)
            for i in range(0, num_crawls):
                logger.info("Starting to crawl pages from DB %s", Config().get_db_url(True))
                job = start_next_job(
                    crawl_id=Config().CRAWL_ID, dry=args.dry, location=args.location
                )
                if not job:
                    raise CrawlerException("No more jobs available in the DB")

                logger.info("Started job: %s", job.id)
                # pylint: disable=no-member
                with SessionLocal.begin() as session:
                    session.add(job)

                    # This fetches the values of the website, needed later
                    session.refresh(job.website)

                    if not args.dry:
                        job.crawler_hostname = socket.gethostname()

                    if job.force_recrawl:
                        logger.info("Forced recrawl on job to %s", job.website.url)

                Config().CREATE_ACCOUNT = job.create_account
                if job.browser_language is not None:
                    Config().BROWSER_LANGUAGE = job.browser_language

                logger.info("Running job %s\t%s", job.id, job.website.url)
                if not job.website.url:
                    raise CrawlerException(
                        f"Job {job.id}, {job.crawl_id} in the database contains no domain"
                    )

                # Check if we can cache
                latest_crawl: Optional[DBWebsiteCrawl] = None

                # A cached (validation) crawl only re-checks PP/TC links; email-capture skips it
                if not job.force_recrawl and not Config().EMAIL_CAPTURE_ONLY:
                    logger.info("Checking if previous crawl exists")
                    latest_crawl = get_latest_crawl(cast(DBWebsite, job.website))

                    # pylint: disable=no-member
                    with SessionLocal.begin() as session:
                        if latest_crawl is not None:
                            latest_crawl = session.merge(latest_crawl)
                            # Test if latest_crawl is recent enough
                            if (
                                latest_crawl.created_at.timestamp()
                                < (
                                    datetime.now() - timedelta(days=Config().RECRAWL_AFTER_DAYS)
                                ).timestamp()
                            ):
                                logger.info(
                                    "Latest crawl is to old: %s. \nDoing a normal crawl",
                                    latest_crawl,
                                )
                                latest_crawl = None
                            else:
                                logger.info("Last crawl of %s is: %s", job.website, latest_crawl)

                                # Recrawl if any of the PP/TC urls is missing
                                if len(latest_crawl.pp_urls) > 0 and len(latest_crawl.tc_urls) > 0:
                                    logging.info(
                                        "Using cached crawl for %s from %s",
                                        latest_crawl.website.url,
                                        latest_crawl.job.ended_at,
                                    )
                                else:
                                    latest_crawl = None

                logger.info(
                    "Crawling page: %s and have a cache: %s",
                    job.website.url,
                    latest_crawl is not None,
                )

                if args.dry:
                    logger.info("Would run job: %s", job)
                    continue
                run_domain(
                    job.website.url,
                    job=cast(DBJob, job),
                    stat_collector=stats,
                    seconds_before_processing_page=delay,
                    headless=not args.no_headless,
                    cached_website_crawl=latest_crawl,
                )
        else:
            logger.info("No pages were provided to be crawled")
    except CrawlerException as e:
        # CrawlerExceptions are fatal and exit with non-zero
        raise e
    except WebDriverException as e:
        logger.error("Failed to complete run_crawl due to %s", e)
        # Do not re raise as we probably can continue with another crawl as a
        # WebDriverException was thrown
    finally:
        if args.stats:
            # Check for existing and add it to the current
            lock = FileLock(f"{args.stats}.lock", timeout=120)
            try:
                with lock:
                    if os.path.isfile(args.stats):
                        with open(args.stats, "r", encoding="utf-8") as file:
                            logger.info("Adding to existing stats: %s", args.stats)
                            existing_json = json.loads("\n".join(file.readlines()))
                            existing_stats = StatCollector(
                                collect_type=CollectType.MULTIPLE_CRAWLS, **existing_json
                            )
                            stats.add(existing_stats)

                    stat_str = stats.to_json()
                    with open(args.stats, "w", encoding="utf-8") as file:
                        file.write(stat_str)
            except TimeoutError as e:
                logger.error("Unable to save stats to %s due to held lock", args.stats)
                logger.error(stats)
                raise e

    stats.stop()

    logger.info("Crawler finished with all the jobs")
    logger.info("Stats for this crawl: %s", stats)

    logger.info("Quitting")


def main() -> None:
    """
    Call run_crawler and if any exception occurs we'll stop with code 1.
    Exit code 1 means that there is something fundamentally wrong and
    enfbot should not be called again.
    """
    try:
        run_crawler()

    # pylint: disable=broad-exception-caught
    except TablesMissingException:
        logger.error(
            "Database %s is missing the tables. Create a fresh database with --create-database",
            Config().get_db_url(True),
        )
        sys.exit(1)  # This is fatal
    except OutdatedDatabaseException:
        logger.error(
            "Database %s is outdated. Please upgrade with --update-database",
            Config().get_db_url(True),
        )
        sys.exit(1)  # This is fatal
    except CrawlerException as e:
        logger.error(e)
        sys.exit(1)
    except Exception as e:
        logger.error("%s", str(e))
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
