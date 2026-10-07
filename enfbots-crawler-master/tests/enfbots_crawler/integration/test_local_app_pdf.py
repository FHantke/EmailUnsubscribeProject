"""
Tests if PP/TCs that are linked as PDF files are detected and their content
got extracted as markdown to the output folder.
Also tests that the PDFs are stored in the output folder.
"""

import glob

from enfbots_crawler import Config
from enfbots_crawler.website import WebSite


def crawl_this(browser, flask_app_pdf_function):
    Config().CREATE_ACCOUNT = False
    site = WebSite(browser, flask_app_pdf_function)
    site.crawl()

    return site


def test_pdf_downloaded_and_found(browser, flask_app_function_pdf, db_memory):
    Config().USE_CLASSIFIER = False

    site = crawl_this(browser, flask_app_function_pdf)
    _, db_website = site.get_db_entity()

    assert (
        db_website.pp_urls[0].pp_url.url
        == flask_app_function_pdf.child("static", "doc1.pdf").to_text()
    )
    assert db_website.tc_urls[0].tc_url.url == flask_app_function_pdf.child("terms").to_text()

    found = False
    pdf_found = False
    for x in glob.glob(str(site.output_path.absolute()) + "/*"):
        if "privacy_policy" in str(x) and str(x).endswith(".md"):
            found = True
            content = "\n".join(open(x, "r", encoding="utf-8").readlines())

            assert "Upon your request and expression of consent" in content
            assert "Privacy Policy" in content
            assert "Based on our legitimate interests, we collect" in content
        if "privacy_policy" in str(x) and str(x).endswith(".pdf"):
            pdf_found = True

    assert found
    assert pdf_found
