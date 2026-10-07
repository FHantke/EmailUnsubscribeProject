#!/bin/env python

"""
This script deletes all taken screenshots (namely all *.png files) from the input_file which is obtained by running:
  select url, dump_uuid from jobs
  JOIN websites on websites.id = jobs.website_id
  JOIN website_crawls wc on wc.job_id = jobs.id
  where crawler_hostname LIKE '%regular%' AND crawl_id LIKE '%no_photo%' AND reg_url is not NULL 

)
"""
from pathlib import Path

from hyperlink import URL

print("Start")

input_file = "./data-1687987236658.csv"
enfbots_output = "/var/lib/docker/volumes/crawling_output_2023_06/_data"

num = 0
num_folders = 0
for x in open(input_file, "r").readlines()[1:]:
  url, uuid = x.split(',')
  url = url.strip().strip("\"")
  uuid = uuid.strip().strip("\"")

  path = Path(f"{enfbots_output}/{URL.from_text(url).host}_{uuid}/")
  if path.exists():
    num_folders += 1
  print("Path: " + str(path))
  files = path.glob("*.png")
  for f in files:
    f.unlink()
    num += 1
  

print(f"finished and deleted {num} files in {num_folders} folders")
