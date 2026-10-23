"""
Test cases for the RFC 8058 study: which capture form to sign up to on each site, the aliases of
its control and treatment arms, and the subscribe jobs that perform the sign-ups.
"""

from __future__ import annotations

import datetime
import logging
import random
import secrets
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from enfbots_crawler import Config
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.database import DBCaptureForm, DBJob, DBTestCase, DBWebsite, DBWebsiteCrawl

logger = logging.getLogger("enfbots_crawler")

ARMS = ("control", "treatment")


def host(url: str) -> str:
    """https://www.Example.com/path -> www.example.com (also accepts a bare host)."""
    return url.split("://", 1)[-1].split("/", 1)[0].strip().lower()


def new_alias(taken: set[str]) -> str:
    """
    Random alias such as news4821937750@domain, not yet in taken (which it is added to).
    Random rather than sequential, so senders can neither guess other aliases nor pair the arms.
    """
    domain = Config().STUDY_MAIL_DOMAIN.strip().lower()
    if not domain:
        raise ValueError("Set CRAWLER_STUDY_MAIL_DOMAIN to the mail server's domain")
    while True:
        digits = "".join(secrets.choice("0123456789") for _ in range(Config().ALIAS_DIGITS))
        alias = f"{Config().ALIAS_PREFIX}{digits}@{domain}"
        if alias not in taken:
            taken.add(alias)
            return alias


def placeholder_alias(taken: set[str]) -> str:
    """
    Unique stand-in for test cases whose persona brings its own address (test sign-ups): the
    .invalid domain is reserved and can never receive mail.
    """
    while True:
        digits = "".join(secrets.choice("0123456789") for _ in range(Config().ALIAS_DIGITS))
        alias = f"test{digits}@test.invalid"
        if alias not in taken:
            taken.add(alias)
            return alias


def persona_email(persona: str) -> Optional[str]:
    """The persona's own address, for test sign-ups; None for study personas."""
    email = Credentials.load(persona).email
    if email and "@" not in email:
        raise ValueError(f"Persona {persona} has an email that is not an address: {email!r}")
    return email or None


def _preference(capture: DBCaptureForm) -> tuple[int, int, int, int]:
    # Visible before hidden, newsletter before other kinds, Shopify's own form last (it showed an
    # hCaptcha challenge on 5 of 5 stores in the 2026-10-21/22 pilots, a Klaviyo form on the
    # same kind of store went through), then the first one found
    return (
        0 if capture.visible else 1,
        0 if capture.kind == "newsletter" else 1,
        1 if capture.vendor_hint == "shopify" else 0,
        capture.id,
    )


def selection_reason(capture: DBCaptureForm) -> str:
    reason = f"{'visible' if capture.visible else 'hidden'} {capture.kind}"
    return reason if capture.trigger == "inline" else f"{reason} ({capture.trigger})"


def pick_captures(session: Session, from_crawl: str) -> dict[int, DBCaptureForm]:
    """The preferred eligible capture of each website in the discovery crawl, by website id."""
    rows = session.scalars(
        select(DBCaptureForm)
        .join(DBWebsiteCrawl, DBWebsiteCrawl.id == DBCaptureForm.website_crawl_id)
        .join(DBJob, DBJob.id == DBWebsiteCrawl.job_id)
        .where(DBJob.crawl_id == from_crawl, DBCaptureForm.eligible.is_(True))
    ).all()
    best: dict[int, DBCaptureForm] = {}
    for capture in rows:
        website_id = capture.website_crawl.website_id
        if website_id not in best or _preference(capture) < _preference(best[website_id]):
            best[website_id] = capture
    return best


def create_test_cases(
    session: Session,
    from_crawl: str,
    study_id: str,
    only_sites: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
    rng: Optional[random.Random] = None,
    dry: bool = False,
) -> list[DBTestCase]:
    """
    Two test cases (control, treatment) per website with an eligible capture in from_crawl, and
    one subscribe job each. Websites with a submitted or still pending test case are skipped, so
    no site is signed up twice. Jobs run in created_at order: every site's first arm, then every
    second arm, with the arm order drawn per site, so a site's two sign-ups are a whole pass apart.

    If the persona (STUDY_PERSONA) has its own email address, this is a test: one test case per
    website (arm "test"), all signed up with that address, under placeholder aliases.
    """
    rng = rng or random.Random()
    persona = Config().STUDY_PERSONA
    shared_email = persona_email(persona)
    arms_per_site = ("test",) if shared_email else ARMS
    if shared_email:
        logger.warning(
            "Persona %s has its own address %s: test sign-ups, one per site, no study aliases",
            persona,
            shared_email,
        )
    allowed = {host(s) for s in only_sites} if only_sites is not None else None
    urls: dict[int, str] = {
        row.id: row.url for row in session.execute(select(DBWebsite.id, DBWebsite.url))
    }
    # Submitted, or still to run (pending; error = its job is retried). Dry runs and skipped
    # sign-ups submitted nothing, so their sites can get new test cases
    already = set(
        session.scalars(
            select(DBTestCase.website_id).where(
                DBTestCase.submitted_at.is_not(None)
                | DBTestCase.submit_status.in_(("pending", "error"))
            )
        ).all()
    )
    taken = set(session.scalars(select(DBTestCase.alias)).all())

    planned = []
    for website_id, capture in sorted(pick_captures(session, from_crawl).items()):
        if allowed is not None and host(urls[website_id]) not in allowed:
            continue
        if website_id in already:
            logger.info("Skipping %s: it already has test cases", urls[website_id])
            continue
        planned.append((website_id, capture))
    rng.shuffle(planned)
    if limit is not None:
        planned = planned[:limit]

    first, second = [], []
    for website_id, capture in planned:
        arms = list(arms_per_site)
        rng.shuffle(arms)
        cases = [
            DBTestCase(
                website_id=website_id,
                capture_form_id=capture.id,
                study_id=study_id,
                arm=arm,
                alias=placeholder_alias(taken) if shared_email else new_alias(taken),
                persona=persona,
                selection_reason=selection_reason(capture),
                submit_status="pending",
            )
            for arm in arms
        ]
        first.append(cases[0])
        second.extend(cases[1:])
    cases = first + second
    if dry:
        return cases

    session.add_all(cases)
    session.flush()
    start = datetime.datetime.now()
    for i, case in enumerate(cases):
        session.add(
            DBJob(
                website_id=case.website_id,
                crawl_id=study_id,
                create_account=True,
                test_case_id=case.id,
                # 1 ms apart, like load_database.py, so start_next_job keeps this order
                created_at=start + datetime.timedelta(milliseconds=i),
            )
        )
    return cases
