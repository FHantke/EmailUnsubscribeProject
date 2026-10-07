from collections.abc import Sequence
import logging
import multiprocessing
from pathlib import Path
from typing import Optional, Tuple, List, Set, cast, Iterable, Dict, Callable, Any
from importlib.metadata import version

import requests
from bs4 import BeautifulSoup
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select

from enfbots_crawler.languages import Language, KeywordType
from enfbots_crawler.helper import set_log_formatter
from enfbots_crawler.database import SessionLocal, initialize_base_db

from enfbots_crawler import Config, MailType, EmailVerificationStatus, PageState
from enfbots_crawler.browser import create_browser
from enfbots_crawler.database import DBMail, DBWebsiteCrawl
from enfbots_crawler.mail_processor import Mail, Sybil
from enfbots_crawler.text_lib import extract_text_from_html

logger = logging.getLogger("enfbots_crawler")


class MailFetcher:
    """
    :ivar sybil: sybil mail loader from enfbots project
    :ivar intids_in_db: already loaded IDs
    :ivar addresses: "to" addresses that we are interested in
    """

    def __init__(self) -> None:
        self.sybil = Sybil()

        if Config().SYBIL_LOAD_FAST:
            self.intids_in_db: Set[int] = set()
            self.addresses: Set[str] = set()
        else:  # if not SYBIL_LOAD_FAST, we have more emails to process, and therefore we have to filter them
            self.intids_in_db = {x for x in _get_processed_mail_ids()}
            self.addresses = {x for x in _get_all_addresses()}
            logger.info(f"Addresses count: {len(self.addresses)}")

    def load_inbox_live(self) -> int:
        self.sybil.time_format = "%A, %d. %B %Y %I:%M%p"
        inbox = self.sybil.load_inbox(
            hours=48
        )  # increased period due to random stops at infsec.server
        logger.warning(f"{len(inbox)} emails in inbox {self.sybil.base_url}")
        self.sybil.inbox = sorted(inbox, key=lambda x: x["intid"])
        self._inbox_filter()
        return len(self.sybil.inbox)

    def load_inbox_csv(self, path: str) -> int:
        self.sybil.time_format = "%Y-%m-%d %H:%M:%S.%f+00"
        import pandas as pd

        df = pd.read_csv(path, keep_default_na=False)
        df = df.rename(
            columns={
                "mailbox_id": "id",
                "id": "intid",
                "to": "to",
                "from_": "from",
                "subject": "subject",
                "timestamp": "date",
            }
        )
        records = df.to_dict("records")
        self.sybil.inbox = sorted(cast(Iterable[Dict[str, str]], records), key=lambda x: x["intid"])
        self._inbox_filter()
        return len(self.sybil.inbox)

    def _inbox_filter(self) -> None:
        to_process = self.sybil.inbox

        if to_process is None or self.sybil.inbox is None:
            logger.error("Inbox is None")
            return
        # filter emails with lower ID
        if Config().SYBIL_DB_LIVE:
            last_processed_mail_id = _get_last_processed_mail_id()
            logger.info(f"Newest ID {last_processed_mail_id}")
            predicate: Callable[[Dict[str, Any]], bool] = (
                lambda mail: mail["intid"] > last_processed_mail_id
            )
            to_process = list(filter(predicate, to_process))

        # filter emails that came to addresses that no website has assigned
        if self.addresses:
            addr_predicate: Callable[[Dict[str, Any]], bool] = (
                lambda mail: mail["to"] in self.addresses
            )
            to_process = list(filter(addr_predicate, to_process))

        # filter emails that were already in the infsec-server DB
        if self.intids_in_db:
            infsec_predicate: Callable[[Dict[str, Any]], bool] = (
                lambda mail: mail["intid"] not in self.intids_in_db
            )
            to_process = list(filter(infsec_predicate, to_process))

        to_process = list(to_process)
        logger.info(f"Filtered, len before: {len(self.sybil.inbox)}, len after {len(to_process)}")
        self.sybil.inbox = to_process

    def process(self, i: int) -> Mail | None:
        if self.sybil.inbox is None:
            return None
        return self.sybil.process_mail(self.sybil.inbox[i])


def _get_last_processed_mail_id() -> int:
    session = SessionLocal()
    with session.begin():
        query = (
            session.query(DBMail.id)
            .filter(DBMail.sybil_id == Config().SYBIL_ID)
            .order_by(DBMail.id.desc())
            .limit(1)
        )
        res = query.first()

        if not res:
            return -1
        else:
            return res[0]


def _get_processed_mail_ids() -> List[int]:
    session = SessionLocal()
    with session.begin():
        query = select(DBMail.id).filter(DBMail.sybil_id == Config().SYBIL_ID)
        res = session.scalars(query).all()

        if not res:
            logger.error("empty database with emails")
            return []
        else:
            return list(res)


def _get_all_addresses() -> List[str]:
    session = SessionLocal()
    with session.begin():
        query = select(DBWebsiteCrawl.email)
        res = session.scalars(query).all()

        if not res:
            logger.error("empty database with websites")
            return []
        else:
            return [email for email in res if email]


def get_website_id_and_stat(email_addr: str) -> Optional[Tuple[int, EmailVerificationStatus]]:
    email_addr = email_addr.lower()
    session = SessionLocal()
    with session.begin():
        query = select(DBWebsiteCrawl).filter(DBWebsiteCrawl.email == email_addr)
        res = session.scalars(query).first()

        if not res:
            logger.warning(f"Website with this email addr not found: {email_addr}")
            return None
        return cast(
            Optional[Tuple[int, EmailVerificationStatus]], (res.id, res.email_verification_status)
        )


def get_website_email_count(website_id: int) -> int:
    session = SessionLocal()
    with session.begin():
        w = session.query(DBWebsiteCrawl).get(website_id)
        if w:
            return len(w.mails)
        logger.warning(f"Website {website_id} emails not found")
        return 0


def set_website_stat(wid: int, status: EmailVerificationStatus) -> None:
    session = SessionLocal()
    with session.begin():
        w = session.query(DBWebsiteCrawl).get(wid)
        if w:
            w.email_verification_status = status


def insert_email(wid: int, mail: Mail, successful_verification: bool) -> None:
    session = SessionLocal()
    with session.begin():
        if session.query(DBMail).get(mail.intid):
            logger.warning(f"Mail {mail.intid} already in the DB, skipping")
            return
        db_site = session.query(DBWebsiteCrawl).get(wid)
        if not db_site:
            logger.warning(f"Loading site for {mail.intid} failed, skipping")
            return

        db_mail = DBMail(
            id=mail.intid,
            sybil_id=Config().SYBIL_ID,
            from_header=mail.from_str,
            to_header=mail.to_addr,
            subject_header=mail.subject,
            date_header=mail.date,
            headers_raw=mail.headers,
            body=mail.body,
            language=mail.lang.code,
            is_verify_mail_manual=None,
            is_verify_mail_regex=mail.is_verification,
            is_verify_mail_ml=None,
            has_link=bool(mail.activation_link),
            clicked_link=bool(mail.activation_link),
            activation_link=str(mail.activation_link),
            has_code=mail.has_code,
            verification_code=mail.verification_code,
            successful_verification=successful_verification,
            is_new=False,
            classification_manual=None,
            classification_regex=mail.simple_type,
            classification_ml=None,
            notes=mail.mail_id,
        )

        db_site.mails.append(db_mail)


def verify_email(mail: Mail) -> EmailVerificationStatus:
    if mail.activation_link:
        logger.info(
            f"Activating the account by visiting the activation link {mail.activation_link}"
        )
        try:
            with create_browser() as browser:
                status = browser.load_page(mail.activation_link)
                status_ok = status == PageState.OK
                page_text = browser.get_html()
        except Exception:
            # this should never actually happen
            # it apparently happens on infsec server
            logger.exception(
                f"[Email with mailbox_id {mail.mail_id}: Unknown error occurred during the load of page {mail.activation_link}"
            )
            try:
                r = requests.get(str(mail.activation_link), timeout=30)
                status_code = r.status_code
                status_ok = r.status_code == 200
                page_text = r.text
            except requests.Timeout:
                logger.warning(f"Timeout loading {mail.activation_link}")
                return EmailVerificationStatus.FAILURE_ACTIVATION
            except requests.exceptions.InvalidSchema:
                logger.warning(f"Incorrect link {mail.activation_link}")
                return EmailVerificationStatus.FAILURE_ACTIVATION
            except requests.RequestException:
                logger.exception(f"Error loading {mail.activation_link}:")
                return EmailVerificationStatus.FAILURE_ACTIVATION

        if status_ok:
            path = Path(f"./data/{mail.intid}")
            path.mkdir(parents=True, exist_ok=True)
            with (path / "response.html").open("w") as out_file:
                out_file.write(page_text)
            logger.info(f"Page successfully loaded")

            return _check_confirmation_success(page_text, mail.lang)
        else:
            logger.warning(f"Loaded page resulted in: {status_code}")

    elif mail.verification_code:
        logger.warning(f"Received verification code: {mail.verification_code}, but it is too late")
        return EmailVerificationStatus.FAILURE_VERIFICATION_CODE
    return EmailVerificationStatus.UNKNOWN


def _check_confirmation_success(page_html: str, lang: Language) -> EmailVerificationStatus:
    # check success by keyword detection
    page_text = extract_text_from_html(
        BeautifulSoup(page_html, "html.parser", multi_valued_attributes=None)
    ).lower()

    success_counter = 0
    # Success Keywords
    for keyword in lang.get_keywords(KeywordType.CONFIRM_SUCCESS):
        if keyword.text in page_text:
            logger.info(f"Success activation keyword {keyword.text} found")
            success_counter += 1
    # Failure Keywords
    for keyword in lang.get_keywords(KeywordType.CONFIRM_FAILURE):
        if keyword.text in page_text:
            logger.info(f"Failure activation keyword {keyword.text} found")
            success_counter -= 1

    logger.info(f"Activation keyword score {success_counter}")
    if success_counter > 0:
        return EmailVerificationStatus.SUCCESS_ACTIVATION
    elif success_counter < 0:
        return EmailVerificationStatus.FAILURE_LINK_FAIL_KEYWORD
    else:
        return EmailVerificationStatus.FAILURE_LINK_NO_KEYWORD


def needs_verification(ver_status: EmailVerificationStatus, email: Mail, website_id: int) -> bool:
    if Config().SYBIL_SKIP_LATER_VERIFICATION:
        return False
    if ver_status == EmailVerificationStatus.SUCCESS_ACTIVATION:
        return False
    if get_website_email_count(website_id) <= 3:
        return True
    if email.simple_type == MailType.SERVICING_OPT_IN:
        return False  # For now, we limit number of emails where we try verification to 3
    return False


def process_single_mail(mf: MailFetcher, i: int) -> None:
    email = mf.process(i)

    if not email:
        return

    res = get_website_id_and_stat(email.to_addr)
    if res is None or not isinstance(res, Sequence):
        logger.info(f"res is {res} of type {type(res)}")
        return
    assert res is not None  # For some reason this is necessary
    status = None
    (website_id, ver_status) = res
    if needs_verification(ver_status, email, website_id):
        logging.debug("Mail needs verification: " + str(email.intid))
        try:
            status = verify_email(email)
        except Exception:
            logger.exception("Unable to verify")
            return
    else:
        logging.debug("Mail needs NO verification: " + str(email.intid))

    try:
        success = status is not None and status == EmailVerificationStatus.SUCCESS_ACTIVATION

        insert_email(website_id, email, success)
    except IntegrityError:
        logger.exception("Non-unique entry, skipped.")


def process_new() -> None:
    initialize_base_db(db_url=Config().get_db_url(), alembic_root_dir=Config().code_dir)
    mf = MailFetcher()
    if Config().SYBIL_DB_LIVE:
        inbox_len = mf.load_inbox_live()
    else:
        path = Config().SYBIL_DB_EXPORT_PATH
        if not path or not Path(path).is_file():
            logger.error(f"Confirmation shall run from local data, but the path {path} is invalid")
        inbox_len = mf.load_inbox_csv(path)
    logger.info(f"Loaded {inbox_len}")

    if PARALLEL and not Config().SYBIL_DB_LIVE:
        pool = multiprocessing.Pool(4)
        step = 1000
        for idx in range(0, inbox_len, step):
            i_from = idx
            i_to = min(idx + step, inbox_len)
            logger.info(f"processing range ({i_from}, {i_to})")
            pool.starmap(process_single_mail, [(mf, i) for i in range(i_from, i_to)])
    else:
        for i in range(0, inbox_len):
            freq = 1 if (Config().ENV == "dev" or inbox_len < 5000) else 1000
            if i % freq == 0:
                if mf.sybil.inbox is not None:
                    intid = mf.sybil.inbox[i]["intid"]
                    mailbox_id = mf.sybil.inbox[i]["id"]
                else:
                    intid = -1
                    mailbox_id = -1

                logger.info(f"Processing mail [id: {str(intid)}, mailbox_id: {str(mailbox_id)}")
            process_single_mail(mf, i)


if __name__ == "__main__":
    ver = version("enfbots-crawler")

    set_log_formatter(
        "%(asctime)s,%(msecs)03d %(name)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
        "%Y-%m-%d:%H:%M:%S",
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(
        logging.INFO
    )  # Only until we've loaded the config and set the desired LOG_LEVEL
    Config().load()
    root_logger.setLevel(Config().LOG_LEVEL)
    logger.setLevel(Config().LOG_LEVEL)

    print(
        f"Starting enfbots-crawler mail_confirm version {ver} with loglevel {str(logging.getLevelName(Config().LOG_LEVEL))}"
    )

    # construct logger used throughout the crawling
    log_formatter = logging.Formatter(
        fmt="%(asctime)s,%(msecs)03d %(name)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d:%H:%M:%S",
    )

    # console_handler = logging.StreamHandler()
    # console_handler.setFormatter(log_formatter)
    # root_logger.addHandler(console_handler)

    # quiet down some extra loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("polyglot").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("seleniumwire").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

    PARALLEL = False  # likely not used, but can be useful in future and the code is not that messy to remove it

    process_new()
