#!/usr/bin/env bash
# Runs a crawl as several containers at once. SQLite allows one crawler per database, so the site
# list is split into slices, each with its own database, output folder and log in testrun/:
#   <run id>_p<N>.csv / .env / .sqlite / .log, output_<run id>_p<N>/
#
# From the project root:
#   scripts/crawl_parallel.sh discover <sites.csv> <crawl id> <slices>
#       Splits the list (round-robin, so each slice gets the same mix of rank buckets), creates
#       and loads one database per slice and starts one discovery container per slice.
#   scripts/crawl_parallel.sh signup <crawl id> <slices> <sign-up id> <sites file>
#       In each slice's database: test cases for the sites in <sites file> (one URL or host per
#       line; others are left out), then one sign-up container per slice. Settings (persona,
#       dry run, ...) come from testrun/crawler.env, as for single runs.
#   scripts/crawl_parallel.sh status <run id>
#       Jobs started / finished per slice, and the containers still running.
#   scripts/crawl_parallel.sh stop <run id> [<slice>]
#       Stops all slices, or one. The job a slice was on keeps no end time; the crawler
#       retries such jobs only 8 hours after they started.
#   scripts/crawl_parallel.sh resume <run id> <slice>
#       Starts a stopped slice again on the jobs it hasn't started yet.
#
# The containers run in the background, named <run id>_p<N>; logs append to testrun/<name>.log.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
testrun="$root/testrun"
image="enfbots-crawler:local"

usage() {
  # The comment block at the top of this file
  awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
  exit 1
}

# The settings of testrun/crawler.env with this slice's database and output folder
slice_env() {
  local db_id=$1 out_id=$2 env="$testrun/$2.env"
  grep -v -e '^CRAWLER_DB_PATH=' -e '^CRAWLER_OUTPUT_PATH=' "$testrun/crawler.env" > "$env"
  printf 'CRAWLER_DB_PATH=/data/%s.sqlite\nCRAWLER_OUTPUT_PATH=/data/output_%s\n' "$db_id" "$out_id" >> "$env"
  echo "$env"
}

# A one-off command in a container with the slice's settings
in_container() {
  local env=$1
  shift
  docker run --rm --platform linux/amd64 --shm-size=2g --init \
    --env-file "$env" -v "$testrun:/data" "$image" "$@"
}

# A long command in a named background container; its output goes to testrun/<name>.log
start_container() {
  local name=$1 env=$2
  shift 2
  docker run -d --rm --name "$name" --platform linux/amd64 --shm-size=2g --init \
    --env-file "$env" -v "$testrun:/data" "$image" "$@" > /dev/null
  echo "=== start $(date '+%F %T %Z'): $*" >> "$testrun/$name.log"
  nohup docker logs -f "$name" >> "$testrun/$name.log" 2>&1 &
  echo "started $name (log: testrun/$name.log)"
}

is_running() {
  [ -n "$(docker ps -q --filter "name=^$1\$")" ]
}

discover() {
  [ $# -eq 3 ] || usage
  local sites=$1 crawl_id=$2 slices=$3 i
  [ -f "$sites" ] || { echo "No site list $sites"; exit 1; }
  for i in $(seq 1 "$slices"); do
    if [ -e "$testrun/${crawl_id}_p$i.sqlite" ]; then
      echo "testrun/${crawl_id}_p$i.sqlite exists already: pick a new crawl id"
      exit 1
    fi
  done
  awk -v n="$slices" -v out="$testrun/${crawl_id}_p" \
    'NF { print > (out (c++ % n + 1) ".csv") }' "$sites"

  for i in $(seq 1 "$slices"); do
    local name="${crawl_id}_p$i" env count
    env=$(slice_env "$name" "$name")
    count=$(grep -c . "$testrun/$name.csv")
    echo "--- slice $i: $count sites"
    in_container "$env" enfbot --create-database
    in_container "$env" python enfbots_crawler/scripts/load_database.py \
      --raw "/data/$name.csv" --id "$crawl_id" --shuffle --ignore-crux
    # Room for the jobs that redirects to other domains add
    start_container "$name" "$env" enfbot -d -dn $((count + count / 10 + 10)) --id "$crawl_id"
  done
}

signup() {
  [ $# -eq 4 ] || usage
  local crawl_id=$1 slices=$2 signup_id=$3 sites=$4 i
  [ -f "$sites" ] || { echo "No sites file $sites"; exit 1; }
  cp "$sites" "$testrun/${signup_id}_sites.txt"
  for i in $(seq 1 "$slices"); do
    local db="${crawl_id}_p$i" name="${signup_id}_p$i" env cases
    [ -e "$testrun/$db.sqlite" ] || { echo "No testrun/$db.sqlite"; exit 1; }
    env=$(slice_env "$db" "$name")
    echo "--- slice $i"
    in_container "$env" python enfbots_crawler/scripts/create_test_cases.py \
      --from-crawl "$crawl_id" --id "$signup_id" --sites "/data/${signup_id}_sites.txt" --seed 20261023
    cases=$(sqlite3 -readonly "$testrun/$db.sqlite" \
      "select count(*) from jobs where crawl_id = '$signup_id' and started_at is null;")
    if [ "$cases" -eq 0 ]; then
      echo "no sign-ups in slice $i"
      continue
    fi
    start_container "$name" "$env" enfbot -d -dn $((cases + 5)) --id "$signup_id"
  done
}

status() {
  [ $# -eq 1 ] || usage
  local run_id=$1 db
  for db in "$testrun"/*_p*.sqlite; do
    [ -e "$db" ] || continue
    local counts
    counts=$(sqlite3 -readonly "$db" "select count(*), coalesce(sum(started_at is not null), 0),
      coalesce(sum(ended_at is not null), 0) from jobs where crawl_id = '$run_id';")
    [ "${counts%%|*}" -gt 0 ] || continue
    IFS='|' read -r total started ended <<< "$counts"
    printf '%-32s %4s jobs, %4s started, %4s finished\n' "$(basename "$db")" "$total" "$started" "$ended"
  done
  docker ps --filter "name=${run_id}_p" --format '{{.Names}}: {{.Status}}'
}

stop() {
  [ $# -eq 1 ] || [ $# -eq 2 ] || usage
  local run_id=$1 names
  if [ $# -eq 2 ]; then
    names="${run_id}_p$2"
  else
    names=$(docker ps --filter "name=${run_id}_p" --format '{{.Names}}')
  fi
  [ -n "$names" ] || { echo "Nothing running for $run_id"; return; }
  for name in $names; do
    docker stop "$name" > /dev/null && echo "stopped $name"
    echo "=== stopped $(date '+%F %T %Z')" >> "$testrun/$name.log"
  done
}

resume() {
  [ $# -eq 2 ] || usage
  local run_id=$1 name="$1_p$2" env db left
  env="$testrun/$name.env"
  [ -e "$env" ] || { echo "No $env: was slice $2 of $run_id ever started?"; exit 1; }
  if is_running "$name"; then
    echo "$name is still running"
    exit 1
  fi
  # The slice's database, from its env file (a sign-up slice uses its discovery slice's)
  db="$testrun/$(sed -n 's|^CRAWLER_DB_PATH=/data/||p' "$env")"
  left=$(sqlite3 -readonly "$db" \
    "select count(*) from jobs where crawl_id = '$run_id' and started_at is null;")
  if [ "$left" -eq 0 ]; then
    echo "$name has no jobs left to start"
    return
  fi
  echo "$name: $left jobs left"
  start_container "$name" "$env" enfbot -d -dn $((left + 5)) --id "$run_id"
}

[ $# -ge 1 ] || usage
command=$1
shift
case "$command" in
  discover) discover "$@" ;;
  signup) signup "$@" ;;
  status) status "$@" ;;
  stop) stop "$@" ;;
  resume) resume "$@" ;;
  *) usage ;;
esac
