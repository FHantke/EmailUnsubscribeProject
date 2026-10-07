from enfbots_crawler.languages import get_supported_languages, Language, KeywordType

from enfbots_crawler import Config


def test_supported():
    assert len(get_supported_languages()) == 43


def test_validity():
    """
    Tests if everything is translated in the ./enfbots_crawler/languages/*.yml files.
    """
    for code in get_supported_languages():
        lang = Language.get(Config().language_dir, code, load_model=False)
        for kw_type in KeywordType:
            lang.get_keywords(kw_type)

            # We do not expect to have a translation for every HONEYPOT_INPUT and US_PN (only in english) keyword
            if kw_type not in [
                KeywordType.HONEYPOT_INPUT,
                KeywordType.US_PN,
                KeywordType.GDPR,
                KeywordType.POPULAR_PP_PATH,
                KeywordType.POPULAR_TC_PATH,
            ]:
                assert kw_type in lang.keywords
                assert "????" not in lang.keywords[kw_type]
