from pathlib import Path
import sys
from unittest.mock import patch
from typing import List

from sqlalchemy import select

from enfbots_crawler import DBJob, DBWebsite, SessionLocal
from enfbots_crawler.scripts.load_database import main


def test_load_simple(db_disk):
    raw_list_path = (Path(__file__).parent / "../data/load_database_list.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()

        assert 2 == len(jobs)

        domains = []
        for j in jobs:
            assert j.from_static

            domains.append(j.website.url)

        assert "www.internet1.com" in domains
        assert "https://inf.ethz.ch" in domains


def test_load_no_duplicates(db_disk):
    raw_list_path = (Path(__file__).parent / "../data/load_database_duplicates.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()

        for j in jobs:
            assert j.from_static

        assert 3 == len(jobs)


def test_load_duplicates(db_disk):
    """
    Test if --allow-duplicates works. This enables creating concurrent crawls to one website for performance checks.
    """
    raw_list_path = (Path(__file__).parent / "../data/load_database_duplicates.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path), "--allow-duplicates", "--ignore-crux"]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()

        for j in jobs:
            assert j.from_static

        assert 4 == len(jobs)


def _load(*args: str) -> None:
    raw_list_path = (Path(__file__).parent / "../data/load_database_list.txt").resolve()
    testargs = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux", *args]
    with patch.object(sys, "argv", testargs):
        main()


def _job_count_per_crawl() -> dict:
    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()
        counts: dict = {}
        for j in jobs:
            counts[j.crawl_id] = counts.get(j.crawl_id, 0) + 1
        return counts


def test_load_same_list_twice_schedules_once(db_disk):
    _load("--id", "crawl-a")
    _load("--id", "crawl-a")

    assert _job_count_per_crawl() == {"crawl-a": 2}


def test_same_list_in_another_crawl_is_scheduled(db_disk):
    _load("--id", "crawl-a")
    _load("--id", "crawl-b")

    assert _job_count_per_crawl() == {"crawl-a": 2, "crawl-b": 2}


def test_same_list_twice_without_crawl_id_schedules_once(db_disk):
    _load()
    _load()

    assert _job_count_per_crawl() == {None: 2}


def test_allow_duplicates_still_schedules_twice(db_disk):
    _load("--id", "crawl-a", "--allow-duplicates")
    _load("--id", "crawl-a", "--allow-duplicates")

    assert _job_count_per_crawl() == {"crawl-a": 4}


def test_load_no_empty_lines(db_disk):
    raw_list_path = (Path(__file__).parent / "../data/load_database_empty_line.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()

        assert 4 == len(jobs)

        domains = []
        for j in jobs:
            assert j.from_static

            domains.append(j.website.url)

        assert "https://ethz.ch" in domains
        assert "https://inf.ethz.ch" in domains
        assert "https://nzz.ch" in domains
        assert "https://digitec.ch" in domains


def test_dry(db_disk):
    raw_list_path = (Path(__file__).parent / "../data/load_database_empty_line.txt").resolve()

    testargs = ["not-important.py", "--dry", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()
        websites = session.scalars(select(DBWebsite)).all()

        assert 0 == len(jobs)
        assert 0 == len(websites)


def test_crux(db_disk):
    """
    Tests if the sampling from the given cruX list is plausible
    """
    crux_path = (Path(__file__).parent / "../data/small_crux.csv").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--num-websites-per-countryrank",
        "1",
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.scalars(select(DBJob)).all()
        websites: List[DBWebsite] = session.scalars(select(DBWebsite)).all()

        job_domains: List[str] = []
        website_names: List[str] = []

        for j in jobs:
            assert not j.from_static
            assert j.from_dynamic
            job_domains.append(j.website.url)

        for w in websites:
            website_names.append(w.url)

        assert 4 == len(jobs)
        assert 4 == len(websites)

        # all from RANK 100k from .bg:
        assert (
            "https://www.globus-baumarkt.bg" in job_domains
            or "https://springeropen.bg" in job_domains
        )

        # all from RANK 10k from .bg
        assert "http://something.bg" in job_domains

        # all from RANK 100k from .ch:
        assert (
            "https://quests.mystenlabs.ch" in job_domains
            or "https://www.springeropen.ch" in job_domains
        )

        # all from RANK 5k from .de:
        assert "https://www.springeropen.de" in job_domains


def test_merging(db_disk):
    crux_path = (Path(__file__).parent / "../data/small_crux.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list.txt").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--num-websites-per-country",
        "1",
        "--raw",
        str(raw_list_path),
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.query(DBJob).all()

        job_domains: List[str] = []

        for j in jobs:
            if "www.internet1.com" == j.website.url or "https://inf.ethz.ch" == j.website.url:
                assert j.from_static
                assert j.from_dynamic is None or not j.from_dynamic
            else:
                assert j.from_static is None or not j.from_static
                assert j.from_dynamic
            job_domains.append(j.website.url)

        assert "www.internet1.com" in job_domains
        assert "https://inf.ethz.ch" in job_domains

        # all .bg ones
        assert (
            "https://www.globus-baumarkt.bg" in job_domains
            or "http://something.bg" in job_domains
            or "https://springeropen.bg" in job_domains
        )

        # all .ch ones
        assert (
            "https://quests.mystenlabs.ch" in job_domains
            or "https://www.springeropen.ch" in job_domains
        )

        # all .de ones
        assert "https://www.springeropen.de" in job_domains


def test_metadata(db_disk):
    crux_path = (Path(__file__).parent / "../data/small_crux_metadata.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_metadata.txt").resolve()

    testargs = ["not-important.py", "--crux_path", str(crux_path), "--raw", str(raw_list_path)]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.query(DBJob).all()

        # Testdata
        nzz_included = False
        www_nzz_included = False
        srf_included = False
        not_existing_included = False

        for j in jobs:
            assert j.from_static

            if "https://nzz.ch" == j.website.url:
                ranks = j.additional_crux_ranks

                assert ranks["de"] == 50000
                assert ranks["ch"] == 1000
                nzz_included = True
            elif "https://www.nzz.ch" == j.website.url:
                assert len(j.additional_crux_ranks) == 0
                www_nzz_included = True
            elif "https://srf.ch" == j.website.url:
                ranks = j.additional_crux_ranks

                assert ranks["ch"] == 1000

                srf_included = True
            elif "https://not_existing_websiiiiteee333.com" == j.website.url:
                assert len(j.additional_crux_ranks) == 0
                not_existing_included = True
            else:
                assert False  # No other website should be loaded

        assert nzz_included
        assert www_nzz_included
        assert srf_included
        assert not_existing_included


def test_metadata_merge(db_disk):
    crux_path = (Path(__file__).parent / "../data/small_crux_metadata.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_metadata.txt").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--raw",
        str(raw_list_path),
        "--num-websites-per-country",
        "5",
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.query(DBJob).all()

        assert 10 == len(jobs)

        for j in jobs:
            if j.website.url in [
                "https://nzz.ch",
                "https://www.nzz.ch",
                "https://srf.ch",
                "https://not_existing_websiiiiteee333.com",
            ]:
                assert j.from_static
            else:
                assert j.from_dynamic

            if j.website.url == "https://nzz.ch":
                ranks = j.additional_crux_ranks

                assert ranks["de"] == 50000
                assert ranks["ch"] == 1000


def test_order(db_disk):
    """
    If a static list (via --raw) and sampling (via --num-websites-per-countryrank)
    is given then the first jobs (with lowest created_at) will be the static list
    followed by the sampled websites
    """
    crux_path = (Path(__file__).parent / "../data/small_crux_metadata.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_metadata.txt").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--raw",
        str(raw_list_path),
        "--num-websites-per-country",
        "1",
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = session.query(DBJob).all()

        assert len(jobs) >= 5

        assert jobs[0].website.url == "https://nzz.ch"
        assert jobs[1].website.url == "https://www.nzz.ch"
        assert jobs[2].website.url == "https://srf.ch"
        assert jobs[3].website.url == "https://not_existing_websiiiiteee333.com"

        for j in jobs[4:]:

            if j.list_index_source == "de":
                assert j.website.url in ["https://www.springeropen.de", "https://nzz.ch"]

            if j.list_index_source == "bg":
                assert j.website.url in [
                    "https://springeropen.bg",
                    "http://something.bg",
                    "https://www.globus-baumarkt.bg",
                ]

            if j.list_index_source == "ch":
                assert j.website.url in [
                    "https://quests.mystenlabs.ch",
                    "https://www.springeropen.ch",
                    "https://nzz.ch",
                    "https://srf.ch",
                ]


def test_force_recrawl(db_disk):
    crux_path = (Path(__file__).parent / "../data/small_crux_metadata.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_metadata.txt").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--raw",
        str(raw_list_path),
        "--num-websites-per-country",
        "5",
        "--force-recrawl",
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs = session.query(DBJob).all()

        assert 10 == len(jobs)

        for j in jobs:
            assert j.force_recrawl


def test_no_force_recrawl(db_disk):
    crux_path = (Path(__file__).parent / "../data/small_crux_metadata.csv").resolve()
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_metadata.txt").resolve()

    testargs = [
        "not-important.py",
        "--crux_path",
        str(crux_path),
        "--raw",
        str(raw_list_path),
        "--num-websites-per-country",
        "5",
        "--no-force-recrawl",
    ]

    with patch.object(sys, "argv", testargs):
        main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs = session.query(DBJob).all()

        assert 10 == len(jobs)

        for j in jobs:
            assert not j.force_recrawl
