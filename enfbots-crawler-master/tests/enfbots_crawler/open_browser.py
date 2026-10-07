import time
from enfbots_crawler import Config
from enfbots_crawler.browser import Chrome
from hyperlink import URL

Config().BROWSER = "chrome"


def run():
    with Chrome(seconds_before_processing_page=2.5) as browser:
        browser.load_page(URL.from_text("https://nowsecure.nl"))
        time.sleep(10000)


run()
