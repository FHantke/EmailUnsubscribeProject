#!/bin/bash

# This file searches through the logs of a compressed crawl output.

# $1 is path to the compressed crawl output

for x in $(find "${1}" -name "*.xz"); do
  echo "$x"
  filename=$(basename -- "$x")

  # We know that all are .tar.SOMETHING
  filename="${filename%.*.*}"

  # echo -e "\t$filename"
  # tar -tf $x

  tar -xOf "${x}" "$filename/crawler.log" | grep -e "${2}"
done
