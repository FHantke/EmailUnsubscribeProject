import json

import pytest

from enfbots_crawler import Config, InputType
from enfbots_crawler.credentials import Credentials, get_rnd_password
from enfbots_crawler.input_selenium import InputSelenium


def _persona_names() -> list[str]:
    return sorted(p.stem for p in Config().credentials_dir.glob("*.json"))


@pytest.mark.parametrize("persona", _persona_names())
def test_birth_parts_come_from_birthdate(persona, monkeypatch):
    monkeypatch.setattr(Config(), "CREDENTIALS", persona)
    creds = Credentials.get()

    raw = json.loads((Config().credentials_dir / f"{persona}.json").read_text())["birthdate"]
    year, month, day = (int(x) for x in raw.split("-"))

    assert (creds.birth_year, creds.birth_month, creds.birth_day) == (year, month, day)
    assert all(isinstance(x, int) for x in (creds.birth_year, creds.birth_month, creds.birth_day))


@pytest.mark.parametrize("persona", _persona_names())
def test_personas_store_no_password(persona):
    raw = json.loads((Config().credentials_dir / f"{persona}.json").read_text())

    assert raw["password"] == ""


def test_password_generated_per_credentials():
    first, second = Credentials.get(), Credentials.get()

    assert first.password and second.password
    assert first.password != second.password


def test_generated_password_meets_common_policies():
    for _ in range(200):
        password = get_rnd_password()

        assert len(password) == 14
        assert any(c.islower() for c in password)
        assert any(c.isupper() for c in password)
        assert any(c.isdigit() for c in password)
        assert "_" in password


def _bare_input(estimated_type: InputType, direct_type: InputType, html_type: str) -> InputSelenium:
    # Bypass __init__, which needs a live WebElement; validate_text only reads these attributes
    inp = InputSelenium.__new__(InputSelenium)
    inp.type = estimated_type
    inp.direct_type = direct_type
    inp.html_type = html_type
    inp.pattern = None
    inp.min = inp.max = inp.min_length = inp.max_length = None
    return inp


@pytest.mark.parametrize(
    "estimated_type,direct_type,html_type,attr",
    [
        (InputType.BIRTH_YEAR, InputType.NUMBER_OTHER, "number", "birth_year"),
        (InputType.BIRTH_MONTH, InputType.TEXT_OTHER, "text", "birth_month"),
        (InputType.BIRTH_DAY, InputType.TEXT_OTHER, "text", "birth_day"),
    ],
)
def test_birth_parts_fill_separate_inputs(estimated_type, direct_type, html_type, attr):
    creds = Credentials.get()
    inp = _bare_input(estimated_type, direct_type, html_type)
    expected = str(getattr(creds.birthdate, attr.removeprefix("birth_")))

    # Before the fix this raised TypeError for number inputs and typed a repr for text inputs
    assert inp.validate_text(getattr(creds, attr)) == expected
