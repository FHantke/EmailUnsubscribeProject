from pathlib import Path
import os
import sys
from unittest.mock import patch
from typing import List
import time
import random
from datetime import datetime
from concurrent.futures.process import ProcessPoolExecutor

from pytest_mock import MockerFixture

from sqlalchemy import select, create_engine

from enfbots_crawler.database import SessionLocal, DBJob, start_next_job, initialize_base_db

from enfbots_crawler.scripts.load_database import main as load_database_main
from enfbots_crawler import Config


def fetch_job(i: int):
    """
    Simulates executing a DBJob.
    Each crawler is a process executing this 'fetch_job' function.
    """
    db_url = Config().get_db_url()

    # print(f"Fetching job from {db_url}")

    engine = create_engine(
        db_url, connect_args={"application_name": "Enfbots crawler fetch-job test"}, pool_size=1
    )
    initialize_base_db(
        db_url=db_url,
        alembic_root_dir=Config().code_dir,
        create=False,
        connection_info="Testing",
        engine=engine,
    )

    job = start_next_job()

    if job is None:
        return 0

    time.sleep(1 + random.random())

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job)
        job.ended_at = datetime.now()
    session.expunge_all()
    engine.dispose()

    return job.id


def test_postgres(db_postgres):
    """
    Test if the fixture 'db_postgres' works
    """

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs = session.execute(select(DBJob)).all()

        assert len(jobs) == 0


def test_postgres_load(db_postgres):
    """
    Tests if loading to postgres works.
    """
    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    url = "www.test123-f.com"
    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(url)

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = list(session.execute(select(DBJob)).scalars())

        assert len(jobs) == 1
        assert jobs[0].website.url == url

    os.remove(raw_list_path)


def test_postgres_load_crawl_id(db_postgres):
    """
    Tests if fetching a job with a given ID works if multiple jobs are present but only one with the given ID.
    """
    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    # First load some job without ID
    url = "www.test123-f.com"
    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(url)

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    # Now load a job with an ID
    correct_url = "www.correct_job.com"
    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(correct_url)

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--id", "crawl-id-3", "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    job = start_next_job("crawl-id-3")

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job)
        session.refresh(job.website)

    assert job.website.url == correct_url

    os.remove(raw_list_path)


def test_postgres_load_any(db_postgres):
    """
    Tests if fetching any job works. Ff multiple jobs are present the next job is returned regardless of its ID.
    """
    raw_list_path = (Path(__file__).parent / "../temp_list.txt").resolve()

    # First load some job without ID
    url = "www.test123-f.com"
    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(url)

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--id", "crawl-id-3", "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    # Now load a job with an ID
    correct_url = "www.correct_job.com"
    with open(raw_list_path, "w", encoding="utf-8") as file:
        file.write(correct_url)

    load_args = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    with patch.object(sys, "argv", load_args):
        load_database_main()

    job = start_next_job()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job)
        session.refresh(job.website)

    assert job.website.url == url

    job = start_next_job()

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        session.add(job)
        session.refresh(job.website)

    assert job.website.url == correct_url

    os.remove(raw_list_path)


def test_fetch_parallel(db_postgres, mocker: MockerFixture):
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_32.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path), "--ignore-crux"]

    n_jobs = len(open(raw_list_path, "r", encoding="utf-8").readlines())

    with patch.object(sys, "argv", testargs):
        load_database_main()

    with ProcessPoolExecutor(max_workers=4) as pool:
        res = list(pool.map(fetch_job, list(range(n_jobs))))

        assert all(res)

    assert n_jobs == len(res)

    for i in range(1, n_jobs + 1):
        assert i in res

    # pylint: disable=no-member
    with SessionLocal.begin() as session:
        jobs: List[DBJob] = list(session.scalars(select(DBJob)).all())

        assert n_jobs == len(jobs)

        for j in jobs:
            assert j.ended_at
            assert j.num_starts == 1
            assert j.from_static
            assert j.started_at
            assert j.started_at < j.ended_at
