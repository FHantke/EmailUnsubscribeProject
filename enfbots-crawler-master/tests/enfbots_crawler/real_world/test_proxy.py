import pytest
import requests

from hyperlink import URL
from selenium.webdriver.common.by import By

from enfbots_crawler.browser import create_browser
from enfbots_crawler.main import ns_lookup


@pytest.fixture
def proxy() -> tuple[str, list[str]]:
    proxy_url = URL(scheme="http", host="host.lodrant.si", port=4343)
    proxy_ips = ns_lookup(proxy_url.host) + ns_lookup(proxy_url.host, "AAAA")
    return proxy_url.to_text(with_password=True), proxy_ips


def test_requests(proxy: tuple[str, str]):
    proxy_url, proxy_ips = proxy
    proxies = {"http": proxy_url, "https": proxy_url}
    res = requests.get("https://httpbin.org/get?show_env", proxies=proxies)
    request_ip = res.json()["origin"]
    assert request_ip in proxy_ips


def test_browser(proxy: tuple[str, str]):
    proxy_url, proxy_ips = proxy
    with create_browser(proxy=proxy_url) as browser:
        browser.load_page(URL.from_text("https://ifconfig.co/"))
        ip_tag = browser.driver.find_element(By.CSS_SELECTOR, "code.ip")
        assert ip_tag.text.strip() in proxy_ips
