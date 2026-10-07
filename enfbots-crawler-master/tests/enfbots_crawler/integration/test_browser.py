from contextlib import closing
import socket
from pathlib import Path

from PIL import Image  # type: ignore
from hyperlink import URL
from enfbots_crawler import PageState
from enfbots_crawler.browser import EnfbotsBrowser


def find_free_port():
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("localhost", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def test_ok(flask_app_function, browser):
    url = flask_app_function.child("static", "mozilla_article.html")
    status = browser.load_page(url)
    assert status == PageState.OK


def test_anchor_ok(flask_app_function, browser):
    url = flask_app_function.child("static", "mozilla_article.html")
    status = browser.load_page(url)
    assert status == PageState.OK
    assert browser.current_url == url
    url = url.replace(fragment="anchor")
    status = browser.load_page(url)
    assert status == PageState.OK
    assert browser.current_url == url


def test_missing(flask_app_function, browser):
    url = flask_app_function.child("static", "missing.html")
    status = browser.load_page(url)
    assert status == PageState.HTTP_ERROR


def test_bad_dns(browser):
    url = URL.from_text("http://doesnotexist.local")
    status = browser.load_page(url)
    assert status == PageState.DNS_ERROR


def test_bad_port(browser):
    url = URL.from_text(f"http://localhost:{find_free_port()}")
    status = browser.load_page(url)
    assert status == PageState.TCP_ERROR


def test_screenshot(flask_app_function, browser: EnfbotsBrowser, output_directory: Path):
    url = flask_app_function.child("static", "mozilla_article.html")
    browser.load_page(url)
    browser.take_screenshot(output_directory, "test_image")

    png = output_directory / "test_image_window_0.png"
    assert png.exists() and png.is_file()
    with Image.open(png) as img:
        # cannot be more precise due to different size of displays
        assert img.height > 0
        assert img.width > 0


def test_dump_html(browser, output_directory: Path, flask_app_function):
    browser.load_page(flask_app_function.child("register"))
    browser.dump_html(output_directory, "register")
    files = list(output_directory.iterdir())
    assert len(files) == 1
    assert files[0].name == "register.html"
    assert "register_page_unique_body_id" in files[0].read_text()
