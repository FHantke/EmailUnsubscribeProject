from enfbots_crawler.text_lib import extract_content_from_html
from enfbots_crawler.text_helper import coerce_cyrillic, full_split
import pytest

page = """
<html><head>
<meta charset="utf-8"/>
<title> Index </title>
<link href="/static/style.css" rel="stylesheet"/>
</head>
<body><br/><br/><br/><br/><br/>
<div align="center">
<div align="center" class="border">
<div class="header">
<h1 class="word">Index</h1>
</div><br/><br/><br/>
<h1 class="title">
Welcome to the index page...
</h1>
<a class="btn" href="/login">Login</a>
</div>
</div>
</body></html>
"""


def test_extract():
    content = extract_content_from_html(page, clean=True)
    assert "Welcome to the index page" in content
    assert "Login" in content


def test_cyrilic():
    assert coerce_cyrillic("приватност") == "privatnost"


@pytest.mark.parametrize(
    "input,expected",
    [
        ("This is a simple testcase.", ["this", "is", "a", "simple", "testcase"]),
        ("Now we test söme umläuts.", ["now", "we", "test", "söme", "umläuts"]),
        ("CamelCaseTestCase", ["camel", "case", "test", "case"]),
        ("ABCamel CombinedTestABCase", ["ab", "camel", "combined", "test", "ab", "case"]),
        ("यह हिन्दी है", ["यह", "हिन्दी", "है"]),
        ("欢迎来到", ["欢迎来到"]),
        ("안녕하세요, 세계", ["안녕하세요", "세계"]),
    ],
)
def test_full_split(input, expected):
    assert full_split(input) == expected
