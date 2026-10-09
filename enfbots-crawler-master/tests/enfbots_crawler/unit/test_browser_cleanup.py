import subprocess
import time
from unittest.mock import MagicMock

import pytest
from psutil import Process

from enfbots_crawler import browser
from enfbots_crawler.browser import _cleanup_temp_dir, _is_alive, _process_tree, _wait_for_exit


def _spawn(*cmd: str) -> Process:
    return Process(subprocess.Popen(cmd).pid)


def test_process_tree_includes_descendants():
    # Like Chrome: a parent whose helper process can outlive it
    parent = _spawn("sh", "-c", "sleep 30 & wait")
    time.sleep(0.3)

    tree = _process_tree(parent.pid)
    assert [p.pid for p in tree][0] == parent.pid
    assert len(tree) == 2

    _wait_for_exit(tree, timeout=0.2)
    assert not any(_is_alive(p) for p in tree)


def test_process_tree_of_a_missing_process():
    gone = subprocess.Popen(["true"])
    gone.wait()

    assert _process_tree(None) == []
    assert _process_tree(gone.pid) == []


def test_wait_for_exit_returns_once_processes_exit():
    p = _spawn("sleep", "0.2")
    start = time.monotonic()

    _wait_for_exit([p], timeout=10)

    assert time.monotonic() - start < 5
    assert not _is_alive(p)


def test_wait_for_exit_kills_processes_still_running():
    p = _spawn("sleep", "30")
    start = time.monotonic()

    _wait_for_exit([p], timeout=0.3)

    assert time.monotonic() - start < 5
    assert not _is_alive(p)


def test_zombie_counts_as_gone():
    p = _spawn("true")
    time.sleep(0.3)  # exited, not yet reaped

    assert not _is_alive(p)


def test_cleanup_temp_dir_retries_when_a_file_appears(monkeypatch):
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    temp_dir = MagicMock()
    temp_dir.cleanup.side_effect = [OSError(39, "Directory not empty"), None]

    _cleanup_temp_dir(temp_dir)

    assert temp_dir.cleanup.call_count == 2


def test_cleanup_temp_dir_gives_up_after_three_tries(monkeypatch):
    monkeypatch.setattr(browser.time, "sleep", lambda _: None)
    temp_dir = MagicMock()
    temp_dir.cleanup.side_effect = OSError(39, "Directory not empty")

    with pytest.raises(OSError):
        _cleanup_temp_dir(temp_dir)
    assert temp_dir.cleanup.call_count == 3
