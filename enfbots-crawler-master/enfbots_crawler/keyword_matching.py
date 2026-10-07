"""
All browsing activities of the enfbots_crawler are defined here
"""

from __future__ import annotations

import itertools
import math
from typing import List, Mapping, Sequence, Callable, cast, Iterable, TypeVar
import logging

# Imports from the enfbots library
from enfbots_crawler.languages import Keyword, MatchString, KeywordType, Language

T = TypeVar("T")

logger = logging.getLogger("keyword_matching.py")


def match_keywords_lemmatized(
    matches: List[MatchString], keywords: List[Keyword], min_kw_match_length: int
) -> float:
    """
    Checks whether the text contains any of the keyword
    :param keywords: list of keywords we are trying to match
    :return: relative score of the match
    """
    score: float = 0
    partial_matches: str = ""

    for match in matches:
        for keyword in keywords:
            my_score: float = 0

            try:
                if keyword.words:
                    indices: list[float] = []
                    weights: list[float] = []
                    for kw_word, kw_lemma in itertools.zip_longest(keyword.words, keyword.lemmas):
                        check_lemma = match.lang == keyword.lang
                        mm: list[tuple[int, float]] = []
                        for k, (word, lemma) in enumerate(zip(match.words, match.lemmas)):
                            if word and word in kw_word:
                                partial_matches += " " + word
                                mm.append((k, 1))
                                break
                            elif check_lemma and lemma and kw_lemma and lemma in kw_lemma:
                                partial_matches += " " + word
                                mm.append((k, 0.8))
                            elif len(word) > min_kw_match_length and word not in partial_matches:
                                for w in kw_word:
                                    if len(w) > min_kw_match_length:
                                        if word in w:
                                            partial_matches += " " + word
                                            mm.append((k, 0.3))
                                            break
                                        elif w in word:
                                            partial_matches += " " + w
                                            mm.append((k, 0.3))
                                            break
                        if mm:
                            u, v = max(mm, key=lambda x: x[1])
                            indices.append(u)
                            weights.append(v)

                    my_score = sum(weights) / len(keyword.words)
                    if len(indices) > 1:
                        # penalise missed ordering
                        for k in range(len(indices) - 1):
                            my_score *= 0.8 ** (indices[k + 1] - indices[k] - 1)
                elif keyword.text in match.text and len(keyword.text) > min_kw_match_length:
                    my_score = 1

                if keyword.weight is not None:
                    my_score *= keyword.weight
                if match.weight is not None:
                    my_score *= match.weight

                if my_score > 0:
                    score += my_score
            except OverflowError:
                return float("inf")
    return score


def keyword_score(
    mapping: Mapping[T, KeywordType | Sequence[KeywordType]],
    strings: Sequence[MatchString | str],
    match_keywords_fn: Callable[[List[MatchString], List[Keyword], int], float],
    lang: Language,
    min_kw_match_length: int,
) -> dict[T, float]:
    scores: dict[T, float] = {}

    words: List[MatchString] = cast(List[MatchString], list())
    for m in strings:
        if isinstance(m, MatchString):
            words.append(m)
        elif m:
            words.append(MatchString(m, lang))

    for tag_type, keyword_type in mapping.items():
        if isinstance(keyword_type, Iterable):
            keywords = [kw for kwt in keyword_type for kw in lang.get_keywords(kwt)]
        else:
            keywords = lang.get_keywords(keyword_type)
        scores[tag_type] = match_keywords_fn(words, keywords, min_kw_match_length)

    return scores


def keyword_classify(
    mapping: Mapping[T, KeywordType | Sequence[KeywordType]],
    strings: Sequence[MatchString | str],
    match_keywords_fn: Callable[[List[MatchString], List[Keyword], int], float],
    lang: Language,
    min_kw_match_length: int,
) -> List[tuple[T, float]]:
    """
    Uses the mapping to scan options and decide on multiple possible types
    for this text.
    :param mapping: mapping between keywords and types
    :param strings: strings to scan for matches
    :param default: type to return when nothing matches
    :param lang: language of the site the form is in
    :return: the best match type
    """
    scores = keyword_score(mapping, strings, match_keywords_fn, lang, min_kw_match_length)

    # Take all types wiht non zero score and then the best three types
    good_scores = list(
        reversed(sorted([x for x in scores.items() if x[1] > 0.0], key=lambda x: x[1]))
    )[:3]

    logger.debug("keyword_classify: Classifying %s", strings)
    logger.debug("keyword_classify: Possible types: %s", good_scores)
    return good_scores


def match_keywords(
    matches: List[MatchString], keywords: List[Keyword], min_kw_match_length: int
) -> float:
    """
    Checks whether the text contains any of the keywords
    :param matches: List of strings we are looking for matches in
    :param keywords: list of keywords we are trying to match
    :return: relative score of the match
    """
    max_score: float = 0

    for match in matches:
        score: float = 0
        for keyword in keywords:
            if _contains_keyword(match, keyword) or _contains_keyword(match, keyword, True):
                char_length = 0
                for words in keyword.words:
                    max_length = 0
                    for word in words:
                        max_length = max(max_length, len(word))
                    char_length += max_length
                score += (
                    keyword.weight * len(keyword.words) / len(match.words) * math.log(char_length)
                )
        max_score = max(max_score, score)

    return max_score


def _contains_keyword(match: MatchString, keyword: Keyword, use_lemma: bool = False) -> bool:
    """
    Checks whether the text contains the full keyword
    """
    words = match.lemmas if use_lemma else match.words
    kw_words = keyword.lemmas if use_lemma else keyword.words

    if not words or not kw_words:
        return False

    i: int = 0
    j: int = 0
    while i < len(words) and j < len(kw_words):
        for choice in kw_words[j]:
            tmp = choice.split("_")
            if i + len(tmp) <= len(words):
                flag: bool = True
                for k in range(len(tmp)):
                    if tmp[k] != words[i + k]:
                        flag = False
                        break
                if flag:
                    i += len(tmp) - 1
                    j += 1
                    break
        i += 1

    return j == len(kw_words)
