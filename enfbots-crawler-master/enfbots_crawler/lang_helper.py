from typing import Optional
import logging
import requests

logger = logging.getLogger("lang_helper.py")


def translate(endpoint: str, text: str, src: str, tar: str) -> str:
    """
    Use LibreTranslate to translate given text
    :param text: text to be translated
    :param src: language code of original language
    :param tar: language code of target language
    :return: the translated text
    """
    if endpoint.strip() == "":
        raise RuntimeError("CRAWLER_LIBRE_TRANSLATE_ENDPOINT is not defined.")

    size = len(text.encode("utf8"))
    logger.info("Translating %s Bytes", size)

    # the endpoint has to end with /translate
    if not endpoint.strip().endswith("/translate"):
        endpoint += "/translate"
    try:
        response = requests.post(
            url=endpoint,
            json={"q": text, "source": src, "target": tar, "format": "text"},
            headers={"Content-Type": "application/json"},
            timeout=60.0 * 5,
        )
    except Exception:
        logger.error("Unable to connect to LibreTranslate endpoint at %s", endpoint)
        raise

    if response.status_code == 200:
        return response.json()["translatedText"]

    logger.error("Response when translating: %s", response)
    raise RuntimeError("Unable to translate. Status code: " + str(response.status_code))


def detect_language(content: str) -> Optional[str]:
    """
    Returns the most probable language the content is written in. The return value is the language code.
    :param content: Text of which the language should be detected

    :return: The language code of the most probable language or None
    """
    # If polyglot did not find a language, try gcld3
    # Imported here so this module loads where gcld3 can't be built (e.g. on macOS, outside Docker)
    try:
        # pylint: disable=import-outside-toplevel
        import gcld3
    except ImportError:
        logger.warning("gcld3 is not installed; cannot detect the language with it")
        return None

    # pylint: disable=no-member
    detector = gcld3.NNetLanguageIdentifier(min_num_bytes=0, max_num_bytes=10_000)

    langs = detector.FindTopNMostFreqLangs(text=content, num_langs=3)
    if len(langs) == 0:
        return None

    sorted_langs = sorted(langs, reverse=True, key=lambda l: l.probability)
    for l in sorted_langs:
        logger.debug(
            "Detected language using gcld3 %s with probability: %s", l.language, l.probability
        )

    return sorted_langs[0].language
