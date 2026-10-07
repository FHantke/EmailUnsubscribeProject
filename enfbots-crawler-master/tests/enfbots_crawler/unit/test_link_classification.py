from pathlib import Path

from hyperlink import URL

from enfbots_crawler.languages import Language
from enfbots_crawler import PageType

from enfbots_crawler.keyword_matching import keyword_classify, match_keywords
from enfbots_crawler.website import page_type_keyword_map
from enfbots_crawler.browser import LinkTuple


def test_login():
    link = LinkTuple(URL.from_text("https://github.com/login"), ["Sign in", "/login"])
    possible_types = keyword_classify(
        page_type_keyword_map,
        link.texts,
        match_keywords,
        Language.get(Path("enfbots_crawler/languages"), "en"),
        3,
    )

    if len(possible_types) == 0:
        t = PageType.OTHER
    t = possible_types[0][0]
    assert t == PageType.LOGIN
