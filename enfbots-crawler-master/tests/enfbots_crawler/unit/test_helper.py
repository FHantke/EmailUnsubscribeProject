import gzip
import lzma
from pathlib import Path

import pytest

from enfbots_crawler.helper import merge_languages_with_prio, get_spoken_languages_of_tld, open_text
from enfbots_crawler.languages import get_supported_languages

SITES = "https://example.com\nhttps://www.beispiel.de\nhttps://příklad.cz\n"


def test_no_priority() -> None:
    spoken = get_spoken_languages_of_tld("us")

    merged = merge_languages_with_prio(spoken, get_supported_languages())

    assert merged == get_supported_languages()


def test_priority_ch() -> None:
    spoken = get_spoken_languages_of_tld("ch")

    # "ch": "de,fr,it,rm", # Switzerland
    merged = merge_languages_with_prio(spoken, get_supported_languages())

    assert [
        "de",
        "fr",
        "it",
        "rm",
        "en",
    ] == merged[0:5]


def test_priority_DE() -> None:
    spoken = get_spoken_languages_of_tld("de")

    # "ch": "de,fr,it,rm", # Switzerland
    merged = merge_languages_with_prio(spoken, get_supported_languages())

    assert "de" == merged[0]


@pytest.mark.parametrize(
    "name,write",
    [
        ("sites.csv", lambda p, s: p.write_text(s, encoding="utf-8")),
        ("sites.csv.xz", lambda p, s: p.write_bytes(lzma.compress(s.encode("utf-8")))),
        ("sites.csv.gz", lambda p, s: p.write_bytes(gzip.compress(s.encode("utf-8")))),
    ],
)
def test_open_text_reads_plain_and_compressed(tmp_path: Path, name, write) -> None:
    path = tmp_path / name
    write(path, SITES)

    with open_text(path) as f:
        assert f.read() == SITES


def test_shipped_static_list_is_readable() -> None:
    path = Path(__file__).parents[3] / "static_lists" / "static_list_2024_02.csv.xz"

    with open_text(path) as f:
        first = f.readline().strip()
        count = 1 + sum(1 for _ in f)

    assert first.startswith(("http://", "https://"))
    assert count == 502612
