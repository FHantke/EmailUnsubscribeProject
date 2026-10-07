import sys
from pathlib import Path
from unittest.mock import patch
import shutil
import tempfile
import tarfile

from enfbots_crawler.scripts.backup import main


def test_simple():
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "1",
        "--from",
        str(backup_data_path),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input folter still exists
    assert len(list(backup_data_path.iterdir())) == 1

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 37

    localhost_domain_path = Path(tmp_dir) / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.bz2"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:bz2") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)


def test_remove():
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()
    input_dir = Path(tempfile.mktemp(prefix="input_dir_"))

    shutil.copytree(backup_data_path, input_dir)

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "1",
        "--remove-after",
        "--from",
        str(input_dir),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input directory is now empty
    assert len(list(input_dir.iterdir())) == 0

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 37

    localhost_domain_path = Path(tmp_dir) / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.bz2"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:bz2") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)


def test_threads():
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "16",
        "--from",
        str(backup_data_path),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input folter still exists
    assert len(list(backup_data_path.iterdir())) == 1

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 37

    localhost_domain_path = Path(tmp_dir) / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.bz2"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:bz2") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)


def test_crawl_id():
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "1",
        "--id",
        "test-crawl-id",
        "--from",
        str(backup_data_path),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input folter still exists
    assert len(list(backup_data_path.iterdir())) == 1

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 1

    localhost_domain_path = Path(tmp_dir) / "test-crawl-id" / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.bz2"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:bz2") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)


def test_xz():
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "1",
        "--xz",
        "--from",
        str(backup_data_path),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input folter still exists
    assert len(list(backup_data_path.iterdir())) == 1

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 37

    localhost_domain_path = Path(tmp_dir) / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.xz"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:xz") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)


def test_remove_file():
    """
    Tests if files are also removed if they successfully compressed
    """
    backup_data_path = (Path(__file__).parent / "../data/backup_data").resolve()
    input_dir = Path(tempfile.mktemp(prefix="input_dir_"))

    shutil.copytree(backup_data_path, input_dir)

    with open(input_dir / "test.txt", "w", encoding="utf-8") as file:
        file.write("")

    tmp_dir = tempfile.mktemp(prefix="test_backup_")
    Path(tmp_dir).mkdir()

    testargs = [
        "not-important.py",
        "-n",
        "1",
        "--remove-after",
        "--from",
        str(input_dir),
        "--to",
        str(tmp_dir),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # input directory is now empty
    assert len(list(input_dir.iterdir())) == 0

    # Subfolder structure was created
    assert len(list(Path(tmp_dir).iterdir())) == 37

    localhost_domain_path = Path(tmp_dir) / "l" / "o"
    assert localhost_domain_path.exists()

    compressed_file = localhost_domain_path / "localhost_297yXH1X.tar.bz2"
    assert compressed_file.exists()

    with tarfile.open(compressed_file, "r:bz2") as file:
        file.extractall(path=localhost_domain_path)

    # Assert the content matches
    extracted_path = localhost_domain_path / "localhost_297yXH1X"

    assert 3 == len(list(extracted_path.iterdir()))

    with (extracted_path / "index.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "index content: 42\n"

    with (extracted_path / "privacy_policy.html").open("r", encoding="utf-8") as file:
        assert file.readline() == "42\n"

    with (extracted_path / "privacy_policy.md").open("r", encoding="utf-8") as file:
        assert file.readline() == "privacy policy md content"

    shutil.rmtree(tmp_dir)
