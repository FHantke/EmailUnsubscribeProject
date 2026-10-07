from typing import List, cast

from hyperlink import URL

from enfbots_crawler import InputType, FormType
from enfbots_crawler.browser import EnfbotsBrowser
from enfbots_crawler.form_bs import FormBS
from enfbots_crawler.website import WebSite


def crawl(url: str, browser):
    site = WebSite(
        browser,
        URL.from_text(url),
    )
    site.crawl()


def _get_forms(browser, form_url: URL) -> List[FormBS]:
    base_url = form_url.replace(path=[], query=[])
    site = WebSite(
        browser,
        base_url,
    )
    site.br.load_page(base_url)
    site._setup_language()
    site.br.load_page(form_url)

    return cast(EnfbotsBrowser, site.br).find_forms(site.lang)


def test_peavey(native, browser):
    crawl("https://www.peaveymart.com/myaccount", browser)


def test_cornerjob(native, browser):
    crawl("https://www.taxi.com/join/", browser)


def test_watchfiresigns(native, browser):
    # we get caught somehow, gotta figure out some day
    crawl("https://www.watchfiresigns.com/dealers/register", browser)


def test_brakes(native, browser):
    # we get caught somehow, gotta figure out some day
    crawl("https://www.brake.co.uk/become-a-customer-register/company-details", browser)


def test_captcha(native, browser):
    crawl("http://captchas.net/registration/", browser)


def test_ciep(native, browser):
    crawl("https://online.ciep.uk/Default.aspx?tabid=61&type=corp", browser)


def test_carwash(browser):
    url = URL.from_text("https://kartemquin.com/user/register#main")
    browser.load_page(url)
    forms = browser.find_forms()


def test_livebook(browser):
    url = URL.from_text("https://livebookmark.stream")
    site = WebSite(
        browser,
        url,
    )
    site.crawl()


def test_one(browser, native):
    crawl("https://www.oneplace.com/", browser)


def test_bellusa(browser):
    url = URL.from_text(
        "https://www.bellusacademy.edu/blog/what-distance-online-learning-really-looks-like-at-bellus-academy/"
    )
    forms = _get_forms(browser, url)
    assert len(forms) == 1
    input_types = [i.estimated_type for i in forms[0].inputs]
    assert InputType.FULL_NAME in input_types and InputType.MAIL in input_types


def test_missouri(browser):
    url = URL.from_text("https://missouriartscouncil.org")
    forms = _get_forms(browser, url)
    assert len(forms) == 1
    input_types = [i.estimated_type for i in forms[0].inputs]
    assert InputType.ZIP in input_types and InputType.MAIL in input_types


def test_shipox(browser):
    url = URL.from_text("https://shipox.com")
    forms = _get_forms(browser, url)
    assert len(forms) == 1
    input_types = [i.estimated_type for i in forms[0].inputs]
    assert InputType.FULL_NAME in input_types and InputType.MAIL in input_types


def test_stepstone(browser):
    url = URL.from_text("https://www.stepstone.be/candidate/register")
    forms = _get_forms(browser, url)
    assert len(forms) == 1
    assert forms[0].type == FormType.REGISTER


def test_customerlabs(browser):
    url = URL.from_text("https://app.customerlabs.com/signup/")
    forms = _get_forms(browser, url)
    assert len(forms) == 2
    assert forms[0].type == FormType.REGISTER and forms[1].type == FormType.REGISTER
