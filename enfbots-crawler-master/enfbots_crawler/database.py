"""
Library for DB operations implemented in Pony ORM
"""

from __future__ import annotations

import logging
import random
from typing import Optional, List, cast, TypeVar
import datetime
from hyperlink import URL
import time
from pathlib import Path

import alembic.config
import alembic.command
import psycopg2

from sqlalchemy import (
    String,
    Float,
    Boolean,
    Engine,
    Integer,
    func,
    ForeignKey,
    DateTime,
    BigInteger,
    JSON,
    select,
    desc,
    text,
    create_engine,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
    DeclarativeBase,
    sessionmaker,
)

# Imports from this crawler implementation
from enfbots_crawler.enums import (
    CaptchaType,
    MailType,
    InputType,
    FormType,
    DomainStatus,
    EmailOptIn,
    EmailPassword,
    RegistrationStatus,
    EmailVerificationStatus,
    ConsiderationBasis,
    PageState,
)

logger = logging.getLogger("enfbots_crawler")


class Base(DeclarativeBase):
    pass


T = TypeVar("T", bound=Base)

"""
We do not want to use expire after commit to still have access to attributes from objects.
If 'expire_on_commit' is set to true all attributes of instances are marked out of date and 
the next time they are accessed a query will be issued. This is not desired to not overload
the database.
"""
SessionLocal = sessionmaker(expire_on_commit=False)


def update_database(
    db_url: Optional[str],
    alembic_root_dir: Path,
    engine: Optional[Engine] = None,
    pool_size: int = 8,
) -> None:
    if not engine:
        if not db_url:
            raise RuntimeError("Either db_url or engine must be given")
        if db_url.startswith("postgresql+psycopg2://"):
            engine = create_engine(
                db_url,
                pool_size=pool_size,
                connect_args={
                    "application_name": "Enfbots crawler Schema Updater",
                },
            )
        else:
            engine = create_engine(db_url, pool_size=pool_size)

    SessionLocal.configure(bind=engine)

    Base.metadata.create_all(bind=engine, checkfirst=True)
    config = alembic.config.Config(file_=str(alembic_root_dir / "alembic.ini"))
    config.set_main_option("script_location", str(alembic_root_dir / "alembic"))
    config.attributes["configure_logger"] = False
    alembic.command.upgrade(config, "head")


def initialize_base_db(
    db_url: Optional[str],
    alembic_root_dir: Path,
    engine: Optional[Engine] = None,
    create: bool = False,
    pool_size: int = 8,
    connection_info: Optional[str] = None,
) -> None:
    if not engine:
        if not db_url:
            raise RuntimeError("Either db_url or engine must be given")

        if db_url.startswith("postgresql+psycopg2://"):
            extra_info = connection_info if connection_info else ""
            engine = create_engine(
                db_url,
                pool_size=pool_size,
                connect_args={
                    "application_name": f"Enfbots crawler {extra_info}",
                },
            )
        else:
            engine = create_engine(db_url, pool_size=pool_size)

    SessionLocal.configure(bind=engine)

    # Try multiple times in case of network issues
    tries = 3
    for i in range(tries):
        try:
            if create:
                logger.info("Creating initial database structure")
                Base.metadata.create_all(bind=engine, checkfirst=True)
                config = alembic.config.Config(file_=str(alembic_root_dir / "alembic.ini"))
                config.set_main_option("script_location", str(alembic_root_dir / "alembic"))
                config.attributes["configure_logger"] = False
                alembic.command.stamp(config, "head")

                logger.info("Created database.")

                # Create indices and constraints
                # pylint: disable=no-member
                with SessionLocal.begin() as session:

                    if session.bind is None:
                        is_psql = False
                    else:
                        is_psql = session.bind.engine.name == "postgresql"

                    if is_psql:
                        session.execute(CREATE_JOBS_CREATED_AT_INDEX)
                        session.execute(CREATE_JOBS_STARTED_AT_INDEX)
                        session.execute(CREATE_EMAILS_WEBSITE_CRAWL_INDEX)
                        session.execute(CREATE_WEBSITES_URL_INDEX)
                        session.execute(CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT)

                return
        except psycopg2.OperationalError as e:
            if i == tries - 1:
                raise e
            if "could not translate host name" in str(
                e
            ) or "No address associated with hostname" in str(e):
                continue
            raise e


def delete_all(db_url: str) -> None:
    """
    Deletes all tables (and indices) of the database
    """
    engine = create_engine(db_url, pool_size=1)

    Base.metadata.drop_all(engine)


def start_next_job(
    crawl_id: Optional[str] = None,
    dry: bool = False,
    location: Optional[str] = None,
    ignore_error_timeout: bool = False,
) -> Optional[DBJob]:
    """
    Returns the next job to be done. Takes the next job which has not finished according to created_at and ended_at.
    A job counts as failed if he was started more than 8h ago and has not yet ended.

    Args:
        crawl_id (Optional[str], optional): Id the job should have as crawl_id. Defaults to None.
        dry (bool, optional): If we do a dry run we do not set started_at. Defaults to False.
        location (Optional[str], optional): Location the job should be specified to run in. Defaults to None.

    Returns:
        Optional[DBJob]: Job if there is any, else None
    """

    if ignore_error_timeout:
        d = datetime.datetime.now()
    else:
        # restart job if more than 8 hours passed since the beginning
        d = datetime.datetime.now() - datetime.timedelta(hours=8)

    max_number_of_starts = 3

    additional_condition: List[str] = []
    if crawl_id:
        logger.info("Searching for crawl with ID: '%s'", crawl_id)
        additional_condition.append(f"jobs.crawl_id = '{crawl_id}'")
    if location:
        logger.info("Location '%s'", location)
        additional_condition.append(f"jobs.location = '{location}'")

    condition = " AND ".join(additional_condition)
    if len(additional_condition) > 0:
        condition += " AND "

    if dry:
        statement = f"""SELECT jobs.id, num_starts FROM jobs
            WHERE {condition} (jobs.started_at IS NULL OR
                (jobs.started_at IS NOT NULL
                AND jobs.ended_at IS NULL AND
                jobs.started_at < :latest_startdate AND (jobs.num_starts < :max_num_starts OR jobs.num_starts IS NULL)))
            ORDER BY jobs.created_at ASC
            LIMIT 1"""
    else:
        statement = f"""
            WITH next_job (id, num_starts) AS
                (SELECT jobs.id, jobs.num_starts FROM jobs 
                    WHERE {condition} (jobs.started_at IS NULL OR
                        (jobs.started_at IS NOT NULL   
                        AND jobs.ended_at IS NULL AND
                        jobs.started_at < :latest_startdate AND (jobs.num_starts < :max_num_starts OR jobs.num_starts IS NULL)
                    ))
                ORDER BY jobs.created_at ASC
                LIMIT 1 FOR UPDATE)
            UPDATE jobs
            SET
                num_starts = coalesce((select num_starts from next_job), 0) + 1,
                started_at = :started_at
            where jobs.id = (select id from next_job)
            returning jobs.id
        """

        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            if session.bind is None:
                is_psql = False
            else:
                is_psql = session.bind.engine.name == "postgresql"

            # sqlite does not support FOR UPDATE, remove it as sqlite won't be used to concurrently fetch jobs
            if not is_psql:
                statement = statement.replace("FOR UPDATE", "")

    if dry:
        update_stmt = text(statement).bindparams(
            max_num_starts=max_number_of_starts, latest_startdate=d
        )
    else:
        update_stmt = text(statement).bindparams(
            max_num_starts=max_number_of_starts,
            latest_startdate=d,
            started_at=datetime.datetime.now(),
        )

    n_tries = 15

    for i in range(n_tries):
        # pylint: disable=no-member
        with SessionLocal.begin() as session:
            try:
                update_result = list(session.execute(update_stmt).all())
                break
            except Exception as e:
                logger.error("FAILED commit when fetching the next job")
                time.sleep((i**1.4) * 0.3 + random.random())

                if i == n_tries - 1:
                    raise e

    if len(update_result) == 0:
        return None

    job_id = update_result[0][0]
    logger.info("Next job id: %i", job_id)

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        res_job = session.get(DBJob, job_id, populate_existing=False)

    return res_job


def store(entity: T) -> T:
    """
    entity: Database entity you would like to persist
    """
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(entity)
    return entity


class DBWebsite(Base):
    __tablename__ = "websites"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(unique=True)

    jobs: Mapped[List["DBJob"]] = relationship(
        back_populates="website", uselist=True, lazy="select", enable_typechecks=False
    )

    crawls: Mapped[List["DBWebsiteCrawl"]] = relationship(
        back_populates="website", uselist=True, lazy="select"
    )

    def __repr__(self) -> str:
        if self.url is not None:
            return f"[DBWebsite id={self.id} url={self.url}, #crawls={self.crawls.__len__()}]"
        return f"[DBWebsite id={self.id}, #crawls={self.crawls.__len__()}]"


class DBJob(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id"))
    website: Mapped["DBWebsite"] = relationship(
        back_populates="jobs", uselist=False, lazy="select", enable_typechecks=False
    )

    domain_status: Mapped[Optional[DomainStatus]]

    created_at: Mapped[datetime.datetime] = mapped_column(
        # pylint: disable=not-callable
        DateTime(timezone=True),
        server_default=func.now(),
    )
    started_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))

    crawl_id: Mapped[Optional[str]]
    index_redirect: Mapped[bool] = mapped_column(default=False)

    # Location where the crawl should run, this is set when the job is created.
    # Crawlers can define --location XYZ to only accept only jobs for location XYZ.
    location: Mapped[Optional[str]]

    # Index of the list (Crux list)
    list_index: Mapped[Optional[int]] = mapped_column(default=-1)

    # Hostname of the crawler (or other identification) that started the crawl
    # started_at is also set by this crawler.
    crawler_hostname: Mapped[Optional[str]]

    # Amount of crawlers that started this job;
    # Optional because if we upgrade a database it's NULL by default
    num_starts: Mapped[Optional[int]] = mapped_column(default=None)

    # If this job was included in the static list
    # Not mutually exclusive with from_dynamic (could come from both)
    from_static: Mapped[Optional[bool]]

    # If this job was included in the sampling from the CruX list
    # Not mutually exclusive with from_static (could come from both)
    from_dynamic: Mapped[Optional[bool]]

    crawls: Mapped[List["DBWebsiteCrawl"]] = relationship(
        back_populates="job", uselist=True, lazy="select"
    )

    # Study sign-up this job performs (subscribe job); NULL for crawl jobs
    test_case_id: Mapped[Optional[int]] = mapped_column(ForeignKey("test_cases.id"), default=None)
    test_case: Mapped[Optional["DBTestCase"]] = relationship(uselist=False, lazy="select")

    # These indices are based on the job because the websites
    # index may change over time
    tranco_index: Mapped[Optional[int]]
    chrome_ux_url: Mapped[Optional[str]]
    list_index_source: Mapped[Optional[str]]

    additional_crux_ranks = mapped_column(JSON)

    # Other stuff
    other = mapped_column(JSON)

    # Now follow some crawler settings

    # corresponds to setting Config().BROWSER_LANGUAGE
    # 'detect-TLD' will use the languages spoken in the given TLD and as fallback en,de,cz,...
    # TODO: Implement above comment
    browser_language: Mapped[Optional[str]]

    # If true we fail if the language detected on the index page is not
    # in browser_language
    # TODO: implement
    enforce_language: Mapped[bool] = mapped_column(default=False)

    # If the crawler should crawl the index site and search for the links.
    # If False, we check if the website was crawled before and only check if the
    # links are still valid and the crawl where we found the links is
    # not older than 6 months.
    force_recrawl: Mapped[bool] = mapped_column(Boolean, default=False)

    # Defines if we should try to create accounts. Corresponds to CRAWLER_CREATE_ACCOUNT
    create_account: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"[DBJob id={self.id}, website={self.website}, started_at={self.started_at}, ended_at={self.ended_at}, crawl_id={self.crawl_id},browser_language: {self.browser_language}]"


class DBURLContent(Base):
    __tablename__ = "urlcontents"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    content: Mapped[str]

    urls: Mapped[List["DBURL"]] = relationship(back_populates="content", lazy="select")


class DBURL(Base):
    __tablename__ = "urls"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    url: Mapped[str]

    # pylint: disable=not-callable
    time_of_retrieval: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=func.now()
    )

    content_hash: Mapped[str] = mapped_column(ForeignKey("urlcontents.hash"))
    content: Mapped["DBURLContent"] = relationship(uselist=False, lazy="select")

    pps: Mapped[List["CrawlToPrivacyPolicy"]] = relationship(
        back_populates="pp_url", uselist=True, lazy="select"
    )
    tcs: Mapped[List["CrawlToTermsAndConditions"]] = relationship(
        back_populates="tc_url", uselist=True, lazy="select"
    )
    us_pns: Mapped[List["CrawlToUSPrivacyNotice"]] = relationship(
        back_populates="us_pn_url", uselist=True, lazy="select"
    )


class CrawlToPrivacyPolicy(Base):
    __tablename__ = "crawl_to_privacy_policy"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    pp_url: Mapped["DBURL"] = relationship(back_populates="pps", uselist=False, lazy="select")
    pp_url_id: Mapped[int] = mapped_column(ForeignKey("urls.id"))

    crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="pp_urls", uselist=False, lazy="select", passive_deletes=True
    )
    website_crawl_id: Mapped[int] = mapped_column(
        ForeignKey("website_crawls.id", ondelete="CASCADE")
    )

    # Probability for the pp_url beeing a PP if the classifier was used
    pp_probability: Mapped[Optional[float]] = mapped_column(Float(precision=16))

    # Score of the pp_url from the keyword matching
    pp_kw_score: Mapped[Optional[float]] = mapped_column(Float(precision=16))

    # On which basis we decided that this url is of type 'Privacy Policy'
    consideration_basis: Mapped[Optional[ConsiderationBasis]]

    # If this TC is considered to be a TC according to the crawlers settings
    considered: Mapped[Optional[bool]]

    def __repr__(self) -> str:
        if self.pp_url is not None and self.crawl is not None:
            return f"[CrawlToPrivacyPolicy id={self.id} url={self.pp_url.url} website={self.crawl}]"
        return f"[CrawlToPrivacyPolicy id={self.id}]"


class CrawlToTermsAndConditions(Base):
    __tablename__ = "crawl_to_terms_and_conditions"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    tc_url_id: Mapped[int] = mapped_column(ForeignKey("urls.id"))
    tc_url: Mapped["DBURL"] = relationship(lazy="select", back_populates="tcs", uselist=False)

    crawl: Mapped["DBWebsiteCrawl"] = relationship(
        lazy="select", back_populates="tc_urls", uselist=False, passive_deletes=True
    )
    website_crawl_id: Mapped[int] = mapped_column(
        ForeignKey("website_crawls.id", ondelete="CASCADE")
    )

    tc_probability: Mapped[Optional[float]] = mapped_column(Float(precision=16))

    # Score of the tc_url from the keyword matching
    tc_kw_score: Mapped[Optional[float]] = mapped_column(Float(precision=16))

    # On which basis we decided that this url is of type 'Terms and Conditions'
    consideration_basis: Mapped[Optional[ConsiderationBasis]]

    # If this TC is considered to be a TC according to the crawlers settings
    considered: Mapped[Optional[bool]]

    def __repr__(self) -> str:
        if self.tc_url is not None and self.crawl is not None:
            return (
                f"[CrawlTotermsAndConditions id={self.id} url={self.tc_url} website={self.crawl}]"
            )
        return f"[CrawlTotermsAndConditions id={self.id}]"


class CrawlToUSPrivacyNotice(Base):
    __tablename__ = "crawl_to_us_privacy_notices"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    us_pn_url_id: Mapped[int] = mapped_column(ForeignKey("urls.id"))
    us_pn_url: Mapped["DBURL"] = relationship(lazy="select", back_populates="us_pns", uselist=False)

    crawl: Mapped["DBWebsiteCrawl"] = relationship(
        lazy="select", back_populates="us_pn_urls", uselist=False, passive_deletes=True
    )
    website_crawl_id: Mapped[int] = mapped_column(
        ForeignKey("website_crawls.id", ondelete="CASCADE")
    )

    # Score of the tc_url from the keyword matching
    us_pn_kw_score: Mapped[Optional[float]] = mapped_column(Float(precision=16))

    # On which basis we decided that this url is of type 'Terms and Conditions'
    consideration_basis: Mapped[Optional[ConsiderationBasis]]

    # If this TC is considered to be a TC according to the crawlers settings
    considered: Mapped[Optional[bool]]

    def __repr__(self) -> str:
        if self.us_pn_url is not None and self.crawl is not None:
            return (
                f"[CrawlToUSPrivacyNotice id={self.id} url={self.us_pn_url} website={self.crawl}]"
            )
        return f"[CrawlToUSPrivacyNotice id={self.id}]"


class DBWebsiteCrawl(Base):
    __tablename__ = "website_crawls"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id"))
    website: Mapped["DBWebsite"] = relationship(
        back_populates="crawls",
        lazy="select",
    )

    # Job which decided to create this crawl
    # Could be null if one uses -u (crawl single URL) or -l (crawl a list of URLs)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    job: Mapped["DBJob"] = relationship(uselist=False, back_populates="crawls", lazy="select")

    dump_uuid: Mapped[Optional[str]]

    index_status: Mapped[Optional[PageState]]

    found_emails = mapped_column(JSON)

    # A validation run means we check only previously found links and validate if they are still the same.
    validation_run: Mapped[bool] = mapped_column(default=False)

    pp_urls: Mapped[List["CrawlToPrivacyPolicy"]] = relationship(
        uselist=True, lazy="select", cascade="all, delete"
    )
    tc_urls: Mapped[List["CrawlToTermsAndConditions"]] = relationship(
        uselist=True, lazy="select", cascade="all, delete"
    )
    us_pn_urls: Mapped[List["CrawlToUSPrivacyNotice"]] = relationship(
        uselist=True, lazy="select", cascade="all, delete"
    )

    reg_url: Mapped[Optional[str]]
    newsletter_url: Mapped[Optional[str]]

    reg_status: Mapped[Optional[RegistrationStatus]]
    email_verification_status: Mapped[Optional[EmailVerificationStatus]]

    states = mapped_column(JSON)

    lang: Mapped[Optional[str]]
    username: Mapped[Optional[str]]
    password: Mapped[Optional[str]]
    email: Mapped[Optional[str]]

    newsletter_username: Mapped[Optional[str]]
    newsletter_password: Mapped[Optional[str]]
    newsletter_email: Mapped[Optional[str]]

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    forms: Mapped[List["DBForm"]] = relationship(
        back_populates="website_crawl", uselist=True, lazy="select", cascade="all, delete"
    )
    mails: Mapped[List["DBMail"]] = relationship(
        back_populates="website_crawl", uselist=True, lazy="select", cascade="all, delete"
    )
    cookies: Mapped[List["DBCookie"]] = relationship(
        back_populates="website_crawl", uselist=True, lazy="select", cascade="all, delete"
    )

    violations: Mapped["DBViolations"] = relationship(
        back_populates="website_crawl", uselist=False, lazy="select", cascade="all, delete"
    )

    capture_forms: Mapped[List["DBCaptureForm"]] = relationship(
        back_populates="website_crawl", uselist=True, lazy="select", cascade="all, delete"
    )

    def __repr__(self) -> str:
        return f"[DBWebsiteCrawl id={self.id} website={self.website}, website_id={self.website_id}, job={self.job}]"


class DBForm(Base):
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_crawl_id: Mapped[int] = mapped_column(ForeignKey("website_crawls.id"))
    website_crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="forms", uselist=False, lazy="select"
    )

    type: Mapped[Optional[FormType]]
    multi_stage: Mapped[bool] = mapped_column(default=False)
    urls = mapped_column(JSON)
    html: Mapped[Optional[str]]

    # Indicating this form uses an insecure URL to send the form data
    # to. This is optional and NULL can be treated as unknown.
    is_insecure: Mapped[Optional[bool]]

    captcha_type: Mapped[Optional[CaptchaType]]
    site_key: Mapped[Optional[str]]

    reg_status: Mapped[Optional[RegistrationStatus]]
    email_verification_status: Mapped[Optional[EmailVerificationStatus]]

    states = mapped_column(JSON)

    inputs: Mapped[List["DBInput"]] = relationship(
        back_populates="form", uselist=True, lazy="select"
    )
    labels: Mapped["DBLabels"] = relationship(back_populates="form", uselist=False, lazy="select")


class DBInput(Base):
    __tablename__ = "form_inputs"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"))
    form: Mapped["DBForm"] = relationship(uselist=False, lazy="select")

    estimated_type: Mapped[Optional[InputType]]
    html_tag: Mapped[Optional[str]]
    html_id: Mapped[Optional[str]]
    label: Mapped[Optional[str]]
    match_string: Mapped[Optional[str]]
    checkbox_prechecked: Mapped[Optional[bool]]
    is_required: Mapped[Optional[bool]]
    stage: Mapped[Optional[int]]
    content: Mapped[Optional[str]]


class DBMail(Base):
    __tablename__ = "mails"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_crawl_id: Mapped[int] = mapped_column(ForeignKey("website_crawls.id"))
    website_crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="mails", uselist=False, lazy="select"
    )

    sybil_id: Mapped[Optional[int]]

    from_header: Mapped[Optional[str]]
    to_header: Mapped[Optional[str]]
    subject_header: Mapped[Optional[str]]
    date_header: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))
    headers_raw: Mapped[Optional[str]]
    body: Mapped[Optional[str]]
    language: Mapped[Optional[str]]
    is_verify_mail_manual: Mapped[Optional[bool]]
    is_verify_mail_regex: Mapped[Optional[bool]]
    is_verify_mail_ml: Mapped[Optional[bool]]
    has_link: Mapped[Optional[bool]]
    clicked_link: Mapped[Optional[bool]]
    activation_link: Mapped[Optional[str]]
    has_code: Mapped[Optional[bool]]
    verification_code: Mapped[Optional[str]]
    successful_verification: Mapped[Optional[bool]]
    is_new: Mapped[Optional[bool]]
    classification_manual: Mapped[Optional[MailType]]
    classification_regex: Mapped[Optional[MailType]]
    classification_ml: Mapped[Optional[MailType]]
    notes: Mapped[Optional[str]]
    other = mapped_column(JSON)

    created_at: Mapped[Optional[datetime.datetime]] = mapped_column(
        # pylint: disable=not-callable
        DateTime(timezone=True),
        default=func.now(),
    )


class DBCookie(Base):
    __tablename__ = "cookies"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_crawl_id: Mapped[int] = mapped_column(
        ForeignKey("website_crawls.id", ondelete="CASCADE")
    )
    website_crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="cookies", uselist=False, lazy="select"
    )

    name: Mapped[str]
    domain: Mapped[str]
    path: Mapped[str]
    value: Mapped[str]
    exp: Mapped[Optional[int]]
    is_secure: Mapped[bool]
    is_httponly: Mapped[bool]
    same_site: Mapped[Optional[str]]
    classification: Mapped[Optional[str]]
    notes: Mapped[Optional[str]]


class DBLabels(Base):
    __tablename__ = "form_legal_labels"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"))
    form: Mapped["DBForm"] = relationship(back_populates="labels", uselist=False, lazy="select")

    mark_consent: Mapped[Optional[bool]]
    mark_purpose: Mapped[Optional[bool]]

    ma_checkbox: Mapped[Optional[bool]]
    ma_pre_checked: Mapped[Optional[bool]]
    ma_forced: Mapped[Optional[bool]]

    pp_checkbox: Mapped[Optional[bool]]
    pp_pre_checked: Mapped[Optional[bool]]
    pp_forced: Mapped[Optional[bool]]

    tc_checkbox: Mapped[Optional[bool]]
    tc_pre_checked: Mapped[Optional[bool]]
    tc_forced: Mapped[Optional[bool]]

    tying12: Mapped[Optional[bool]]
    tying13: Mapped[Optional[bool]]
    tying23: Mapped[Optional[bool]]
    tying123: Mapped[Optional[bool]]

    forcedpp: Mapped[Optional[bool]]
    forcedtc: Mapped[Optional[bool]]
    forcedpptc: Mapped[Optional[bool]]

    colortrick: Mapped[Optional[bool]]
    colortrick_gr: Mapped[Optional[bool]]
    colortrick_wr: Mapped[Optional[bool]]
    colortrick_bw: Mapped[Optional[bool]]

    hidden: Mapped[Optional[bool]]
    settings: Mapped[Optional[bool]]

    age: Mapped[Optional[bool]]
    credit_card: Mapped[Optional[bool]]
    phone: Mapped[Optional[bool]]
    membership: Mapped[Optional[bool]]
    membershipEU: Mapped[Optional[bool]]

    other = mapped_column(JSON)


class DBViolations(Base):
    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_crawl_id: Mapped[int] = mapped_column(ForeignKey("website_crawls.id"))
    website_crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="violations", uselist=False, lazy="select"
    )

    email_opt_in: Mapped[Optional[EmailOptIn]]
    password: Mapped[Optional[EmailPassword]]
    unsubscribe: Mapped[Optional[bool]]
    legal_notice_email: Mapped[Optional[bool]]
    legal_notice_address: Mapped[Optional[bool]]
    legal_notice_name: Mapped[Optional[bool]]
    third_party_sharing: Mapped[Optional[bool]]

    no_opt_in: Mapped[Optional[bool]]
    invalid_consent: Mapped[Optional[bool]]
    no_consent: Mapped[Optional[bool]]

    gdpr_unspecific: Mapped[Optional[bool]]
    gdpr_unfree: Mapped[Optional[bool]]
    gdpr_ambiguous: Mapped[Optional[bool]]
    gdpr_nudging: Mapped[Optional[bool]]

    other = mapped_column(JSON)


class DBCaptureForm(Base):
    """
    An email-capture form (newsletter, offer, waitlist, ...) seen during an email-capture crawl,
    whether or not the study can sign up to it (see eligible / reject_reason).
    """

    __tablename__ = "capture_forms"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)

    website_crawl_id: Mapped[int] = mapped_column(
        ForeignKey("website_crawls.id", ondelete="CASCADE")
    )
    website_crawl: Mapped["DBWebsiteCrawl"] = relationship(
        back_populates="capture_forms", uselist=False, lazy="select"
    )

    # Page the form was found on
    url: Mapped[str]

    # newsletter / other (more kinds follow with the offer keywords)
    kind: Mapped[str]

    eligible: Mapped[bool]
    # First rule the form failed, e.g. "password" or "phone_required"; NULL if eligible
    reject_reason: Mapped[Optional[str]]

    # Step after which the form was first visible: "inline" (in the page as loaded), "delay",
    # "scroll" or "exit_intent" (pop-up triggers); for a form never seen visible, the step
    # it was first found at
    trigger: Mapped[str] = mapped_column(default="inline")
    # Whether its email field was visible after that step; False: only ever hidden in the page
    visible: Mapped[Optional[bool]]

    # Email platform guessed from the form's HTML, e.g. "klaviyo" or "mailchimp"
    vendor_hint: Mapped[Optional[str]]

    # Path of iframes containing the form; NULL for the top document
    frame_path: Mapped[Optional[str]]

    # Visible inputs: estimated type, HTML type, name, required, visible, label
    fields = mapped_column(JSON)

    # Plain strings rather than the CaptchaType enum, so new types need no migration
    captcha_type: Mapped[Optional[str]]
    captcha_visible: Mapped[Optional[bool]]

    # Identifies the same form across pages of one crawl (e.g. a footer newsletter form)
    signature: Mapped[str] = mapped_column(String(40))

    html: Mapped[Optional[str]]

    created_at: Mapped[datetime.datetime] = mapped_column(
        # pylint: disable=not-callable
        DateTime(timezone=True),
        server_default=func.now(),
    )


class DBTestCase(Base):
    """
    One sign-up of the RFC 8058 study: an alias subscribed to a capture form. Each site gets a
    control and a treatment case; only the treatment alias is unsubscribed later.
    """

    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    website_id: Mapped[int] = mapped_column(ForeignKey("websites.id"))
    capture_form_id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), ForeignKey("capture_forms.id")
    )
    capture_form: Mapped["DBCaptureForm"] = relationship(uselist=False, lazy="select")

    # crawl_id of the subscribe jobs, e.g. "subscribe-pilot"
    study_id: Mapped[str]
    # "control" or "treatment"
    arm: Mapped[str]
    alias: Mapped[str] = mapped_column(unique=True)
    # credentials/<persona>.json used for required fields
    persona: Mapped[str]
    # Why this capture was chosen for the site, e.g. "visible newsletter"
    selection_reason: Mapped[Optional[str]]

    # pending, dry_run, success_text, form_gone, redirect, captcha_blocked, failed, unknown,
    # skipped_<reason> (e.g. skipped_form_not_found) or error
    submit_status: Mapped[str] = mapped_column(default="pending")
    # Signals behind submit_status: fields filled, keywords seen, URLs, ...
    submit_detail = mapped_column(JSON)
    submit_page_url: Mapped[Optional[str]]
    submitted_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))

    # Set by the later double opt-in confirmation step
    confirm_status: Mapped[Optional[str]]
    confirmed_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime.datetime] = mapped_column(
        # pylint: disable=not-callable
        DateTime(timezone=True),
        server_default=func.now(),
    )


def get_website(url: URL) -> DBWebsite:
    str_url = url.to_text()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        query = text(
            """INSERT INTO websites(url) VALUES (:url) ON CONFLICT (url) DO NOTHING"""
        ).bindparams(url=str_url)

        session.execute(query)

        result = session.execute(select(DBWebsite).where(DBWebsite.url == str_url)).scalars().all()

        return result[0]


def get_urlcontent(hash: str, content: str) -> DBURLContent:
    """Checks if the given content was already stored and returns the given DBURLContent,
    else inserts a new one.

    Args:
        hash (str): Hash of the content
        content (str): Content to be stored

    Returns:
        DBURLContent: Database object
    """

    # Remove 0 bytes
    content = content.replace("\x00", "")

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        query = text(
            """INSERT INTO urlcontents(hash, content) VALUES(:hash, :content) ON CONFLICT DO NOTHING"""
        ).bindparams(hash=hash, content=content)

        session.execute(query)

        result = (
            session.execute(select(DBURLContent).where(DBURLContent.hash == hash)).scalars().all()
        )

        assert len(result) == 1

        return result[0]


def get_latest_crawl(website: DBWebsite) -> Optional[DBWebsiteCrawl]:
    """
    Returns the most recent DBWebsiteCrawl to the given website. Most recent in terms of created_at of DBWebsiteCrawl (not DBJob.ended_at).

    Args:
        website (DBWebsite): Website

    Returns:
        Optional[DBWebsiteCrawl]: Most recent crawl or None if the given website was never crawled before
    """
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        last_crawl = (
            select(DBWebsiteCrawl)
            .join(DBJob, DBWebsiteCrawl.job_id == DBJob.id, isouter=False)
            .where(DBWebsiteCrawl.website_id == website.id, DBWebsiteCrawl.validation_run == False)
            .order_by(desc(DBWebsiteCrawl.created_at))
            .limit(1)
        )

        result = session.scalars(last_crawl).one_or_none()

        return cast(Optional[DBWebsiteCrawl], result)


def get_best_tc_link(
    db_website_crawl: DBWebsiteCrawl, threshold_kw_score: float
) -> Optional[CrawlToTermsAndConditions]:
    """
    Returns the best TC link of this DBWebsiteCrawl. Only in terms of keyword-matching score.

    Args:
        db_website_crawl (DBWebsiteCrawl): Crawl
        threshold_kw_score (float): Minimum required keyword-matching score to be considered a real TC link.

    Returns:
        Optional[CrawlToTermsAndConditions]: Best TC Link or None if none was found.
    """
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        return (
            session.query(CrawlToTermsAndConditions)
            .where(CrawlToTermsAndConditions.website_crawl_id == db_website_crawl.id)
            .where(CrawlToTermsAndConditions.tc_kw_score > threshold_kw_score)
            .order_by(desc(CrawlToTermsAndConditions.tc_kw_score))
            .limit(1)
            .one_or_none()
        )


def get_best_pp_link(
    db_website_crawl: DBWebsiteCrawl, threshold_kw_score: float
) -> Optional[CrawlToPrivacyPolicy]:
    """
    Returns the best PP link of this DBWebsiteCrawl. Only in terms of keyword-matching score.

    Args:
        db_website_crawl (DBWebsiteCrawl): Crawl
        threshold_kw_score (float): Minimum required keyword-matching score to be considered a real PP link.

    Returns:
        Optional[CrawlToPrivacyPolicy]: Best PP link or None if none was found.
    """
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        return (
            session.query(CrawlToPrivacyPolicy)
            .where(CrawlToPrivacyPolicy.website_crawl_id == db_website_crawl.id)
            .where(CrawlToPrivacyPolicy.pp_kw_score > threshold_kw_score)
            .order_by(desc(CrawlToPrivacyPolicy.pp_kw_score))
            .limit(1)
            .one_or_none()
        )


def create_views() -> None:
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        if session.bind is None:
            is_psql = False
        else:
            is_psql = session.bind.engine.name == "postgresql"

        # only create views for psql as sqlite does not support right joins
        if is_psql:
            session.execute(CREATE_OR_REPLACE_best_pp_urls_kw)
            session.execute(CREATE_OR_REPLACE_best_tc_urls_kw)
            session.execute(CREATE_OR_REPLACE_best_us_pn_urls_kw)
        else:
            # SQLite has no CREATE OR REPLACE VIEW; IF NOT EXISTS keeps --create-database re-runnable
            for view in (
                CREATE_OR_REPLACE_best_pp_urls_kw,
                CREATE_OR_REPLACE_best_tc_urls_kw,
                CREATE_OR_REPLACE_best_us_pn_urls_kw,
            ):
                session.execute(
                    text(str(view).replace("CREATE OR REPLACE VIEW", "CREATE VIEW IF NOT EXISTS"))
                )


CREATE_OR_REPLACE_best_pp_urls_kw = text(
    """
CREATE OR REPLACE VIEW best_pp_urls_kw AS 
  SELECT cpp.pp_url_id, wc.id as website_crawl_id, urls.url, cpp.pp_kw_score, cpp.consideration_basis, cpp.considered, j.crawl_id from website_crawls wc
    LEFT JOIN
    (SELECT wc.id, MIN(pp_url_id) as pp_url_id, sub.crawl_id FROM website_crawls as wc
      RIGHT JOIN
	   (SELECT cppi.website_crawl_id as website_crawl_id, MAX(cppi.pp_kw_score) as max, j.crawl_id from crawl_to_privacy_policy cppi
		  INNER JOIN website_crawls wc ON wc.id = cppi.website_crawl_id
		  INNER JOIN jobs j ON j.id = wc.job_id
        WHERE cppi.pp_kw_score > 1.2 or cppi.consideration_basis = 'CACHED'
		GROUP BY cppi.website_crawl_id, j.crawl_id) sub ON sub.website_crawl_id = wc.id
    LEFT JOIN crawl_to_privacy_policy cpp on cpp.website_crawl_id = wc.id
    GROUP BY wc.id, sub.crawl_id) sub ON sub.id = wc.id
  LEFT JOIN jobs j on j.id = wc.job_id
  LEFT JOIN crawl_to_privacy_policy cpp on cpp.pp_url_id = sub.pp_url_id
  LEFT JOIN urls on urls.id = cpp.pp_url_id;
"""
)

CREATE_OR_REPLACE_best_tc_urls_kw = text(
    """
CREATE OR REPLACE VIEW best_tc_urls_kw AS
  SELECT ctc.tc_url_id, wc.id as website_crawl_id, urls.url, ctc.tc_kw_score, ctc.consideration_basis, ctc.considered, j.crawl_id from website_crawls wc 
    LEFT JOIN 
    (SELECT wc.id, MIN(tc_url_id) as tc_url_id, sub.crawl_id FROM website_crawls as wc
      RIGHT JOIN
        (SELECT ctci.website_crawl_id as website_crawl_id, MAX(ctci.tc_kw_score) as max, j.crawl_id as crawl_id from crawl_to_terms_and_conditions ctci
		  INNER JOIN website_crawls wc ON wc.id = ctci.website_crawl_id
		  INNER JOIN jobs j ON j.id = wc.job_id
        WHERE ctci.tc_kw_score > 0.8 or ctci.consideration_basis = 'CACHED'
		GROUP BY ctci.website_crawl_id, j.crawl_id) sub ON sub.website_crawl_id = wc.id
    LEFT JOIN crawl_to_terms_and_conditions ctc on ctc.website_crawl_id = wc.id
	GROUP BY wc.id, sub.crawl_id) sub ON sub.id = wc.id
  LEFT JOIN jobs j on j.id = wc.job_id
  LEFT JOIN crawl_to_terms_and_conditions ctc on ctc.tc_url_id = sub.tc_url_id
  LEFT JOIN urls on urls.id = ctc.tc_url_id;
"""
)

CREATE_OR_REPLACE_best_us_pn_urls_kw = text(
    """
CREATE OR REPLACE VIEW best_us_pn_urls_kw AS 
  SELECT cupn.us_pn_url_id, wc.id as website_crawl_id, urls.url, cupn.us_pn_kw_score, cupn.consideration_basis, cupn.considered, j.crawl_id from website_crawls wc
    LEFT JOIN
    (SELECT wc.id, MIN(us_pn_url_id) as us_pn_url_id, sub.crawl_id FROM website_crawls as wc
      RIGHT JOIN
	   (SELECT cupni.website_crawl_id as website_crawl_id, MAX(cupni.us_pn_kw_score) as max, j.crawl_id from crawl_to_us_privacy_notices as cupni
		  INNER JOIN website_crawls wc ON wc.id = cupni.website_crawl_id
		  INNER JOIN jobs j ON j.id = wc.job_id
		WHERE cupni.us_pn_kw_score > 0.8 or cupni.consideration_basis = 'CACHED'
		GROUP BY cupni.website_crawl_id, j.crawl_id) sub ON sub.website_crawl_id = wc.id
    LEFT JOIN crawl_to_us_privacy_notices cupn on cupn.website_crawl_id = wc.id
    GROUP BY wc.id, sub.crawl_id) sub ON sub.id = wc.id
  LEFT JOIN jobs j on j.id = wc.job_id
  LEFT JOIN crawl_to_us_privacy_notices cupn on cupn.us_pn_url_id = sub.us_pn_url_id
  LEFT JOIN urls on urls.id = cupn.us_pn_url_id;
"""
)

CREATE_JOBS_CREATED_AT_INDEX = text(
    """
CREATE INDEX IF NOT EXISTS created_at_index
ON jobs USING btree
(created_at ASC NULLS LAST)
"""
)

CREATE_JOBS_STARTED_AT_INDEX = text(
    """
CREATE INDEX IF NOT EXISTS started_at_index
ON jobs USING btree
(started_at ASC NULLS LAST)
"""
)

CREATE_EMAILS_WEBSITE_CRAWL_INDEX = text(
    """
CREATE INDEX IF NOT EXISTS emails_website_crawl_id_index
ON mails USING btree
(website_crawl_id ASC NULLS LAST)
"""
)

CREATE_WEBSITES_URL_INDEX = text(
    """
CREATE INDEX IF NOT EXISTS websites_url_index
ON websites USING btree
(url varchar_ops ASC NULLS LAST)
"""
)

# Postgres has no ADD CONSTRAINT IF NOT EXISTS; the check keeps --create-database re-runnable
CREATE_WEBSITES_URL_UNIQUE_CONSTRAINT = text(
    """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'websites_url_unique') THEN
        ALTER TABLE websites ADD CONSTRAINT websites_url_unique UNIQUE (url);
    END IF;
END
$$
"""
)
