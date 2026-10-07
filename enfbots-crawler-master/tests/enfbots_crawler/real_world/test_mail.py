import datetime

import pytest
from hyperlink import URL

from enfbots_crawler.credentials import Credentials
from enfbots_crawler.mail_processor import Sybil


@pytest.fixture
def sybil():
    return Sybil()


def test_get_inbox(sybil: Sybil):
    inbox = sybil.load_inbox()
    assert len(inbox) > 0
    assert inbox[0]["subject"] and inbox[0]["to"]


def test_create_email(sybil: Sybil):
    creds = Credentials.get()
    sybil.create_mail_address(creds)
    assert creds.email and creds.email.startswith(creds.username)


def test_get_emails(sybil: Sybil):
    creds = Credentials.get()
    creds.email = "fausxqemr0bbc@infsec-server.inf.ethz.ch"
    emails = sybil.get_emails(creds)
    assert len(emails) == 1
    email = emails[0]
    assert email.date == datetime.datetime(2021, 12, 6, 21, 35)
    assert email.subject == "Test Email"
    assert "luka.lodrant@gmail.com" in email.from_addr
    assert "Sybil test email" in email.body


def test_stepstone(sybil: Sybil):
    creds = Credentials.get()
    creds.email = "fausfrlya1617@infsec-server.inf.ethz.ch"
    emails = sybil.get_emails(creds)
    assert emails[-1].activation_link == URL.from_text(
        "https://www.stepstone.be/5/new-account-confirmation.html?userID=3070338&offerID=0&secr=1BB22A03C7ECB63&cid=B2C_CLC_SYS11&sl=C699B58C0A3070338"
    )
    assert emails[-1].verification_code is None


def test_code(sybil: Sybil):
    creds = Credentials.get()
    creds.email = "fauswpvzb5da2@infsec-server.inf.ethz.ch"
    emails = sybil.get_emails(creds)
    assert emails[0].activation_link is None
    assert emails[0].verification_code == "835462"
