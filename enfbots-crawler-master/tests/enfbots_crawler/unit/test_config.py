"""
Tests if the Config works as intented
"""

import os

from enfbots_crawler import Config


def test_load() -> None:
    os.environ["CRAWLER_DB_USERNAME"] = "test"

    config = Config()
    config.load()

    assert config.DB_USERNAME == "test"


def test_invalid(caplog) -> None:
    os.environ["CRAWLER_UNDEFINEEEED"] = "test"

    config = Config()
    res = config.load()

    assert not res
    assert "unknown key UNDEFINEEEED" in caplog.text

    os.environ.pop("CRAWLER_UNDEFINEEEED")
