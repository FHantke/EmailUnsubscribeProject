#!/usr/bin/env python3

"""
Usage: process_chromex.py

Assumes files: "chrome-ex-report.json" and "tranco.csv" in Config().root_dir / "resources" / "urls" / "061622"
"""
import pickle
from collections import defaultdict

import tldextract
from tqdm import tqdm

from enfbots_crawler import Config
reload = True

base = Config().root_dir / "resources" / "urls" / "061622"
pkl = base / "dict.pkl"
report_file = base / "chrome-ex-report.json"
tranco_file = base / "tranco.csv"

if reload:
    mapping = defaultdict(list)
    with report_file.open() as f:
        for i, line in enumerate(f):
            url = line[11:-3]
            reg_domain = tldextract.extract(str(url)).registered_domain
            mapping[reg_domain].append(url)

    with pkl.open("wb") as handle:
        pickle.dump(mapping, handle, protocol=pickle.HIGHEST_PROTOCOL)

else:
    with pkl.open("rb") as handle:
        mapping = pickle.load(handle)
        print(len(mapping))


def find_best(res, domain):
    for u in res:
        if "https://www." + domain in u:
            return u
    for u in res:
        if "https://" + domain in u:
            return u
    for u in res:
        if "http://www." + domain in u:
            return u
    for u in res:
        if "http://" + domain in u:
            return u
    for u in res:
        if "www" + domain in u:
            return u

    https_only = [r for r in res if r.startswith("https")]
    if https_only:
        return min(https_only, key=len)
    return min(res, key=len)


print(f"Loaded {len(mapping)} domains")
misses = 0
with tranco_file.open() as f,\
        (base / "ok.txt").open("w") as ok,\
        (base / "miss.txt").open("w") as miss,\
        (base / "complete.txt").open("w") as complete:
    for line in tqdm(f):
        idx, domain = line.strip().split(",", 1)
        res = mapping[domain]
        if res:
            print(idx, domain, res, sep=";", file=complete)
            print(idx, domain, find_best(res, domain), sep=";", file=ok)
        else:
            print(idx, domain, sep=";", file=miss)
            misses += 1
print(misses)
