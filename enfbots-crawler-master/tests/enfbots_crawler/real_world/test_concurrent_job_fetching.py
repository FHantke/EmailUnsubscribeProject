from pathlib import Path
import sys
from typing import List
import time
import random

from concurrent.futures.process import ProcessPoolExecutor

from pytest_mock import MockerFixture
from unittest.mock import patch
from sqlalchemy import select, create_engine
from datetime import datetime

from enfbots_crawler import start_next_job, initialize_base_db

from enfbots_crawler import SessionLocal, Config
from enfbots_crawler.database import DBJob
from enfbots_crawler.scripts.load_database import main as load_main


def fetch_job(i: int):
    """
    Each crawler is a process executing this 'fetch_job' function.
    """
    db_url = Config().get_db_url()

    print(f"Fetching job from {db_url}")

    engine = create_engine(
        db_url, connect_args={"application_name": f"Enfbots crawler fetch-job test"}, pool_size=1
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

        print(f"Started job: {job.id}")
    session.expunge_all()
    engine.dispose()

    return job.id


def test_fetch_parallel(db_postgres, mocker: MockerFixture):
    raw_list_path = (Path(__file__).parent / "../data/load_database_list_big.txt").resolve()

    testargs = ["not-important.py", "--raw", str(raw_list_path)]

    n_jobs = len(open(raw_list_path, "r", encoding="utf-8").readlines())

    with patch.object(sys, "argv", testargs):
        load_main()

    with ProcessPoolExecutor(max_workers=32) as pool:
        res = list(pool.map(fetch_job, list(range(n_jobs))))

        assert all(res)

    print("FINISHED")

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
