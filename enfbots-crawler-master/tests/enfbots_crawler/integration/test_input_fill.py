import logging
import re
from base64 import b64encode
from datetime import date

import pytest
from hyperlink import URL

from enfbots_crawler.languages import Language

from enfbots_crawler import InputType, Config
from enfbots_crawler.browser import EnfbotsBrowser, create_browser
from enfbots_crawler.credentials import Credentials
from enfbots_crawler.form_selenium import FormSelenium

html = """
<html>
<body>
<form>
    <textare id="textarea"/>
    <input id="text" type="text"/>
    <input id="text_mm" type="text" minlength='4' maxlength='10'/>
    <input id="email" type="email"/>
    <input id="date" type="date"/>
    <input id="pattern" type="text" pattern="[A-Z][0-9]{4}"/>
    <input id="number" type="number" />
    <input id="number_mm" type="number" min='4' max='10'/>
    
    <input id='checkbox' type='checkbox' />
    <input id='checkbox_r' type='checkbox' required/>
    
    <select id='select'>
        <option disabled>Disabled Germany</option>
        <option></option>
        <option value='de'>Germany</option>
        <option value='sl'>Slovenija</option>
    </select>
    <select id='select_month'>
        <option></option>
        <option value='1'>January</option>
        <option value='2'>February</option>
        <option value='3'>March</option>
        <option value='4'>April</option>
        <option value='5'>May</option>
        <option value='6'>June</option>
        <option value='7'>July</option>
        <option value='8'>August</option>
        <option value='9'>September</option>
        <option value='10'>October</option>
        <option value='11'>November</option>
        <option value='12'>December</option>
    </select>
</form>
</body>
</html>
"""

logger = logging.getLogger("enfbots_crawler")


def _get_input(form: FormSelenium, ids: str):
    for inp in form.inputs:
        if inp.id == ids:
            return inp
    return None


@pytest.fixture
def creds() -> Credentials:
    creds = Credentials.get()
    creds.email = "test@example.com"
    return creds


@pytest.fixture(scope="module")
def s_browser():
    with create_browser(seconds_before_processing_page=0.1) as browser:
        yield browser


@pytest.fixture
def form(s_browser: EnfbotsBrowser) -> FormSelenium:
    data_url = "data:text/html;base64," + b64encode(html.encode("utf-8")).decode()
    s_browser.load_page(URL.from_text(data_url))
    return FormSelenium.from_bs(s_browser, s_browser.find_forms()[0])


def test_fill_text(form: FormSelenium):
    inp = _get_input(form, "text")
    test_str = "test str 12 with num!"
    inp.fill_text(test_str)
    assert inp.elem.get_attribute("value") == test_str


def test_text_mm(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "text_mm")
    inp.type = InputType.USERNAME

    creds.username = "Ab"
    inp.fill(creds, False)
    assert 4 <= len(inp.elem.get_attribute("value")) <= 10

    creds.username = "AbAbabababababD"
    inp.fill(creds, False)
    assert 4 <= len(inp.elem.get_attribute("value")) <= 10


def test_email(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "text")
    inp.type = InputType.MAIL
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == creds.email


def test_email_type(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "email")
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == creds.email


def test_text_other_empty(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "text")
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == ""


def test_date_type(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "date")
    inp.type = InputType.BIRTH_FULL
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == creds.birthdate.strftime("%Y-%m-%d")


def test_date_text_en(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "text")
    creds.birthdate = date(1994, 10, 5)
    inp.type = InputType.BIRTH_FULL
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "10/5/94"


def test_date_text_de(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "text")
    inp.lang = Language.get(Config().language_dir, "de")
    inp.type = InputType.BIRTH_FULL
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == creds.birthdate.strftime("%d.%m.%y")


def test_pattern(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "pattern")
    creds.postal_code = "A1000"
    inp.type = InputType.ZIP
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "A1000"

    creds.postal_code = "A10_0"
    inp.fill(creds, False)
    value = inp.elem.get_attribute("value")
    logger.info(f"Pattern generated value: {value}")
    assert value != "A1000"
    assert re.match("^[A-Z][0-9]{4}$", value)


def test_number_ok(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "number")
    inp.type = InputType.ZIP
    creds.postal_code = "1200"
    inp.fill(creds, False)
    value = inp.elem.get_attribute("value")
    assert value == "1200"


def test_number_strip(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "number")
    inp.type = InputType.ZIP
    creds.postal_code = "A1200f_"
    inp.fill(creds, False)
    value = inp.elem.get_attribute("value")
    assert value == "1200"


def test_number_mm(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "number_mm")
    inp.type = InputType.ZIP

    creds.postal_code = "3"
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "4"

    creds.postal_code = "100"
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "10"


def test_checkbox(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "checkbox")

    assert not inp.required
    assert not inp.half_required

    inp.fill(creds, False)
    assert not inp.elem.is_selected()

    inp.fill(creds, True)
    assert inp.elem.is_selected()


def test_checkbox_required(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "checkbox_r")

    assert inp.required
    assert not inp.half_required

    inp.fill(creds, False)
    assert inp.elem.is_selected()


def test_checkbox_half_required(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "checkbox")
    inp.half_required = True
    assert not inp.required

    inp.fill(creds, False)
    assert inp.elem.is_selected()


def test_select(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "select")

    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "sl"

    inp.type = InputType.COUNTRY
    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "de"


def test_select_other(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "select_month")
    inp.type = InputType.TITLE
    creds.title = "Marc"

    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == "3"


def test_select_month(form: FormSelenium, creds: Credentials):
    inp = _get_input(form, "select_month")
    inp.type = InputType.BIRTH_MONTH

    inp.fill(creds, False)
    assert inp.elem.get_attribute("value") == str(creds.birthdate.month)
