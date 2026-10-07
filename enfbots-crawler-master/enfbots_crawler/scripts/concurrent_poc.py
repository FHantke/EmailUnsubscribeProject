"""
This file demonstrates how concurrently a file (in stat_file) can be updated without data getting corrupted.

"""

import os
import json

from pqdm.threads import pqdm
from filelock import FileLock

from enfbots_crawler.modules.stat_collector import StatCollector, CollectType

NUM_THREADS = 64
NUMBER = 1000000
STAT_FILE = "./stats.json"

if not os.path.exists(STAT_FILE):
    print("missing file at " + str(STAT_FILE))
    exit(1)

print("Starting...")


def increment() -> int:
    s = StatCollector()
    s.visited_website()

    try:
        lock = FileLock(f"{STAT_FILE}.lock")
        with lock:
            with open(STAT_FILE, "r", encoding="utf-8") as file:
                existing_json = json.loads("\n".join(file.readlines()))
                existing_stats = StatCollector(
                    collect_type=CollectType.MULTIPLE_CRAWLS, **existing_json
                )
                existing_stats.add(s)

                stat_merged = existing_stats.to_json()

            with open(STAT_FILE, "w", encoding="utf-8") as file:
                file.write(stat_merged)

    except Exception as e:
        print(e)

    return 1


pqdm(list(range(NUMBER)), increment, n_jobs=NUM_THREADS, total=NUMBER)
