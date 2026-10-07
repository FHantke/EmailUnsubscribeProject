import itertools
import logging
import sys

import icu
import yaml
from google.cloud import translate

from enfbots_crawler.languages import KeywordType, Keyword, Language
from enfbots_crawler import Config, languages
from enfbots_crawler.text_helper import coerce_cyrillic

K = KeywordType

desc = {
    K.POLICY: "links: privacy policy",
    K.TERMS: "links: terms and conditions",
    K.REGISTRATION: "links: registration pages",
    K.LOGIN: "links: login/account pages",
    K.US_PN: "links: california privacy policy",
    K.GDPR: "links: GDPR notices",
    K.MAIL_INPUT: "form label: email",
    K.USER_INPUT: "form label: username",
    K.PW_INPUT: "form label: password",
    K.PHONE_INPUT: "form label: phone number",
    K.FIRSTNAME_INPUT: "form label: first name",
    K.LASTNAME_INPUT: "form label: last name",
    K.NAME_INPUT: "form label: full name",
    K.STREET_INPUT: "form label: street name (e.g. Rämistrasse)",
    K.STREET_NR_INPUT: "form label: street number (e.g. 101)",
    K.STREET_FULL_INPUT: "form label: street name + number (e. g. Ramistrasse 101)",
    K.CITY_INPUT: "form label: city",
    K.ZIP_INPUT: "form label: zip/post code",
    K.COUNTRY_INPUT: "form label: country",
    K.FULL_ADDRESS_INPUT: "form label: full address (e.g. Ramistrasse 101, 8092 Zurich, Switzerland)",
    K.BIRTH_DAY_INPUT: "form label: birth day",
    K.BIRTH_MONTH_INPUT: "form label: birth month",
    K.BIRTH_YEAR_INPUT: "form label: birth year",
    K.BIRTH_FULL_INPUT: "form label: birth full date",
    K.CAPTCHA_INPUT: "form label: captcha - the characters you are supposed to read from an image",
    K.SEARCH_INPUT: "form label: search box",
    K.AGE_INPUT: "form label: age",
    K.HONEYPOT_INPUT: "form label: special hidden honeypot field intended to trick bots (us), translation not required",
    K.TITLE_INPUT: "form label: title (e.g. Mr. / Ms.)",
    K.VERIFICATION_CODE: "form label: verification code (one you would receive via SMS or email)",
    K.CHECKBOX_EMAIL: "checkbox label: allow to send news/updates/notifications/offers",
    K.CHECKBOX_PP: "checkbox label: agree to privacy policy",
    K.CHECKBOX_TOS: "checkbox label: agree to terms and conditions",
    K.SUBMIT: "button: submit/next/continue",
    K.SUBMIT_SUCCESS: "keywords representing successful registration - anything that could represent a successful registration,\n# check english version for inspiration, not really important and can be skipped",
    K.SUBMIT_FAILURE: "keywords representing failed registration - anything that could represent a failed registrations,\n# check english version for inspiration, not really important and can be skipped",
    K.CONFIRM_SUCCESS: "keywords representing successful confirmation/activation of email address",
    K.CONFIRM_FAILURE: "keywords representing failed confirmation/activation of email address",
    K.LANGUAGE: "keywords representing this language, also shorthands (e.g. english, en, eng, en-us, en-gb)",
    K.NEWSLETTER: "links: newsletter signup",
    K.CONTACT: "links: contact us, request help",
    K.CONFIRMATION_EMAIL: "keyword in email subject for confirmation or verification email - all possible ways to say confirm/verify this email",
    K.CONFIRMATION_LINK: "links: confirm/verify/activate this account",
    K.UNSUBSCRIBE: "links: unsubscribe from a newletter",
    K.ORGANIZATION_INPUT: "form input: organization/company name",
}

intro = """# enfbots_crawler keyword translation for language {{name}} ({{lang}})
#
# The keywords/phrases in this file will be used to find and classify various elements of a website in order to help a robot
# navigate websites and automatically fill in forms.
#
# Helpful tips:
#  * Please do not blindly translate from english, what we are interested in are the actual words/phrases
#    used on websites in your language, so if you have time please check a few example websites first 
#  * Each category should contain both phrases or single words that match its purpose specified in the latter comments.
#  * Each category comes with it own description with type and supposed value. Try to provide as many possible phrases one could
#    use to describe the thing the crawler is looking for.
#  * Do not worry about the conjugation of the words, the crawler should be able to adapt to any possible conjugation, provide just the most common one.
#  * If a specific important word can appear both as a verb and a noun try to provide both (e.g. registration, register)
#  * If the use of an english word is common in your language you do not have to provide it
#  * Check the english keyword file if you need inspiration for a certain category
#  * lower/upper case does not matter
#  * accent marks don't matter (e.g. ä, ö, š, ž,...) but you can use them 
#  * Optionally, if you find some keywords more important compared to others, you can change the importance (weight) of
#    the keywords by a multiplier. So "create account": 1.5 means this keywords is 50% better indicator of registration
#    than other words. Do not worry about too much, even English uses these weight very sparsly. 
# 
# Further descriptions to our comment above each keyword type:
#  * form label - when filling in a form on a webpage (like registration) these are the text associated to input fields
#    (e.g., *Username:* [ input field ]). These are usually in HTML tag <label>.
#  * checkbox label - similarly to form label, this would be the label of a form checkbox
#  * button - a text on a button, which provides a given functionality
#  * links - the text you expect to find on a link to the page of a certain type (e.g., Read our _privacy policy_)
#
# SPECIAL FORMATTING: if multiple phrases contain the same word and ordering you can use the following syntax
# instead of "privacy policy" and "privacy statement" use "privacy [policy|statement]"
# any number of words can be enclosed in the square brackets and delimited by |
#
# THANK YOU!
"""


class MyDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(MyDumper, self).increase_indent(flow, False)


def quoted_presenter(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


def null_presenter(dumper, _):
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


yaml.add_representer(str, quoted_presenter)
yaml.add_representer(type(None), null_presenter)

IGNORED_KEYWORDS = [KeywordType.HONEYPOT_INPUT]


def dump_map_to_file(lang: Language) -> None:
    result = dict()
    for keyword_type in KeywordType:
        name = keyword_type.name.lower()
        if keyword_type in IGNORED_KEYWORDS and lang.code != "en":
            continue
        if keyword_type in lang.keywords:
            d = {k.text: k.weight for k in lang.keywords[keyword_type]}
            result[name] = d
        else:
            result[name] = {"????": None}
    yaml_string = yaml.dump(
        result, default_flow_style=False, allow_unicode=True, Dumper=MyDumper, sort_keys=False
    )
    cache_str = intro.replace("{{name}}", icu.Locale(lang.code).getDisplayName()).replace(
        "{{lang}}", lang.code
    )
    for line in yaml_string.split("\n"):
        if not line.startswith(" ") and not line.startswith("#") and line.endswith(":"):
            name = line[1:-2]
            cache_str += f"# {desc[KeywordType[name.upper()]]}\n"
            cache_str += f"{name}:\n"
        else:
            cache_str += line + "\n"
    with (Config().language_dir / f"{lang.code}.yaml").open("w") as file:
        file.write(cache_str)


def _translate_words(words: list[str], to: str) -> list[str]:
    """Translating Text."""

    client = translate.TranslationServiceClient()
    location = "global"

    parent = f"projects/lodrantl-core/locations/{location}"

    response = client.translate_text(
        request={
            "parent": parent,
            "contents": words,
            "mime_type": "text/plain",  # mime types: text/plain, text/html
            "source_language_code": "en-US",
            "target_language_code": to,
        }
    )
    translations = [t.translated_text for t in response.translations]
    return [new for new, orig in zip(translations, words) if new != orig]


def google_translate(lang: Language) -> None:
    print("Translating: " + lang.code)
    english_map = Language.get("en", load_model=False)
    for kw_type in KeywordType:
        values = lang.keywords[kw_type] if kw_type in lang.keywords else None
        if kw_type not in IGNORED_KEYWORDS and (values is None or (len(values) == 1 and values[0].text == "????")):
            en = english_map.get_keywords(kw_type)
            words, weights = [], []
            for kw in en:
                for phrase in itertools.product(*kw.words):
                    words.append(" ".join(phrase))
                    weights.append(kw.weight)

            weights = [x.weight for x in en]
            translations = _translate_words(words, lang.code)
            lang.keywords[kw_type] = [
                Keyword(t, lang, weight=w, lemmatize=False) for t, w in zip(translations, weights)
            ]


def cleanup(lang: Language) -> None:
    en = Language.get("en")
    if lang.code != "en":
        for kw_type, values in lang.keywords.items():
            kw_map = {kw.text for kw in en.get_keywords(kw_type)}
            lang.keywords[kw_type] = [v for v in values if v.text not in kw_map]


def transliterate(lang: Language) -> None:
    for typ, group in language.keywords.items():
        for kw in group:
            kw.text = coerce_cyrillic(kw.text, lang.code)


if __name__ == "__main__":
    logging.basicConfig()
    for code in languages.get_supported_languages():
        print("Dumping", code)
        language = Language.get(code, load_model=False)
        if "--translate" in sys.argv:
            google_translate(language)

        cleanup(language)

        if "--transliterate" in sys.argv and language.code in ("sr",):
            transliterate(language)

        dump_map_to_file(language)
