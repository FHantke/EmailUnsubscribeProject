"""
Library for credentials generation

Author: Karel Kubicek, <karel.kubicek@inf.ethz.ch>
"""
from __future__ import annotations

import datetime
import json
import logging
import random
import secrets
import string
from datetime import date
from typing import Optional

from enfbots_crawler import Config

logger = logging.getLogger("enfbots_crawler")


class Credentials:
    def __init__(
        self,
        title: str,
        first_name: str,
        last_name: str,
        street: str,
        street_nr: str,
        city: str,
        postal_code: str,
        country: str,
        birthdate: date,
        phone: str,
        password: str,
        organization: str,
    ):
        # Personas carry no password; each set of credentials gets its own
        self.password = password or get_rnd_password()
        self.phone = phone
        self.birthdate = birthdate
        self.country = country
        self.postal_code = postal_code
        self.city = city
        self.street_nr = street_nr
        self.street = street
        self.last_name = last_name
        self.first_name = first_name
        self.title = title
        self.organization = organization

        # email will be fetched later only if required (in case we found a login form)
        self.verify_code: Optional[str] = None
        self.email: Optional[str] = None

        self.username = self.last_name.lower() + get_rnd_str(5)
        self.full_name = f"{self.first_name} {self.last_name}"
        self.full_address = (
            f"{self.full_name}\n"
            f"{self.street} {self.street_nr}\n"
            f"{self.postal_code} {self.city}\n"
            f"{self.country}"
        )
        self.birth_year = birthdate.year
        self.birth_month = birthdate.month
        self.birth_day = birthdate.day

    @staticmethod
    def get() -> Credentials:
        return Credentials.load(Config().CREDENTIALS)

    @staticmethod
    def load(name: str) -> Credentials:
        """The persona in credentials/<name>.json (study sign-ups name theirs per test case)."""
        file = Config().credentials_dir / f"{name.lower()}.json"
        if file.exists():
            with file.open() as f:
                json_creds = json.load(f)
            json_creds["birthdate"] = datetime.datetime.strptime(
                json_creds["birthdate"], "%Y-%m-%d"
            )
            return Credentials(**json_creds)
        else:
            raise FileNotFoundError(f"Cannot find credentials matching name '{name}'")


def get_rnd_str(length: int) -> str:
    """
    Generate random suffix for the username
    :param length: length of the suffix
    :return: n random ASCII chars
    """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(length))


def get_rnd_password(length: int = 14) -> str:
    """
    Generate a password that satisfies common registration policies
    :param length: total length, at least 4
    :return: password with lower and upper case letters, digits and an underscore
    """
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        "_",
    ] + [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
