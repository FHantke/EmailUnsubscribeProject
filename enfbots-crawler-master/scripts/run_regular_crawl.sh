#!/bin/bash

# Dependencies: swaks, jq, docker-compose, docker
#
# This file is run directly on the crawling machine and will start a regular crawl for the CURRENT month.
# In case a crawl crashes or something unexpected happens, be sure to run these commands manually with the correct 'crawl_id'

##### configuration

PATH_DOCKER_COMPOSE_FILE="/opt/docker/enfbots_regular/docker-compose.yml"
DOCKER_COMPOSE_CMD="docker compose"

VERSION="10"

DC_SERVICE_CRAWLERS="regular1 regular2 regular3 regular4"

# Alert email; credentials and recipients come from the environment
ALERT_USER="${ALERT_USER:-}"
ALERT_PASSWORD="${ALERT_PASSWORD:-}"
ALERT_SERVER="smtp.eu.mailgun.org:587"
ALERT_FROM="info-regular-crawl@crawler.inf.ethz.ch"
# ATTENTION: use a coma as a separator
ALERT_RECIPIENTS="${ALERT_RECIPIENTS:-}"

DC="${DOCKER_COMPOSE_CMD} -f ${PATH_DOCKER_COMPOSE_FILE}"

# Send an email if the speed drops below this threshold
WARN_BELOW_WEBSITES_PER_MINUTE=15

# In seconds, time between checking if all containers are running
# and printing runtime information such as progress, speed and memory consumption
INTERVAL_BETWEEN_STATUS_UPDATES=600

datevar=$(date +%Y-%m)

# Update variables in docker-compose
# Format: regular-YYYY-MM
crawl_id="regular-${datevar}"

echo "Running run_regular_crawl.sh version ${VERSION}. Crawl id is '${crawl_id}'"

# send_alert (crawl_id, email_body)
send_alert () {
  subject="[Crawl $1 message]"
  body="$2"
  echo "Sending email [$subject]: $body"
  swaks --auth \
        --from $ALERT_FROM \
        --server $ALERT_SERVER \
        --au "${ALERT_USER}" \
        --ap "${ALERT_PASSWORD}" \
        --to "${ALERT_RECIPIENTS}" \
        --h-Subject: "$subject" \
        --body "$2" > /dev/null
}

# Starts all crawlers in $DC_SERVICE_CRAWLERS
start_crawlers () {
  for service in ${DC_SERVICE_CRAWLERS}; do
    output=$(${DC} up -d "${service}" 2>&1 | tee /dev/tty)
    ec=$?
    if [ $ec -ne 0 ]; then
      send_alert "${crawl_id}" "[crawl $crawl_id]: Failed to start service $service"
      exit 1
    fi
    sleep 60
  done
}

# First argument is the crawl_id to print information from
# Second argument is if the speed should be monitored (1 enables, everything else disables)
# Also prints information about memory usage, progress and speed of the crawl
# After one hour this also checks if the speed of the crawl is below WARN_BELOW_WEBSITES_PER_MINUTE.
# If it is below an email will be sent to ALERT_RECIPIENTS.
await_crawlers () {
  seconds_passed=0

  # shellcheck disable=SC2086 # Intended splitting of DC_SERVICE_CRAWLERS
  while [ "$($DC ps ${DC_SERVICE_CRAWLERS} | wc -l)" -ne 1 ]
  do
    out=$(${DC} up status 2>&1)
    if [ $? -ne 0 ]; then
      send_alert "${crawl_id}" "[crawl $crawl_id]: Failed to get status.\nOutput is: ${out}"
      exit 1
    fi

    out_ps=$(${DC} ps | wc -l)

    progress=$(echo "$out" | grep -oP 'is: \K[\d\.]*(?=%)')
    speed=$(echo "$out" | grep -oP "Speed of crawl $1 is \K[\d\.]*(?= per minute)")

    if [ "${speed}" = "" ]; then
      echo "Speed is empty; Output was: $out"
      sleep 10
      continue
    fi
    eta=$(echo "$out" | grep -oP "ETA: \K[\d\s\- :.]*(?= \()")

    num_containers_up=$(python -c "print($out_ps - 1)")
    load_avg_15=$(cat /proc/loadavg | cut -d ' ' -f 3)

    mem_used_in_mb=$(free -m | grep "Mem: " | tr -s ' ' | cut -d ' ' -f 3)

    status_msg="[$(TZ=Europe/Zurich date -Iminutes | cut -d "+" -f 1)]:"
    status_msg="$status_msg  $progress%%"
    status_msg="$status_msg  \tMemory: $mem_used_in_mb MB"
    status_msg="$status_msg  \tSpeed: $speed websites per minute"
    status_msg="$status_msg  \t$num_containers_up containers up"
    status_msg="$status_msg  \tLoad avg 15: $load_avg_15"
    status_msg="$status_msg  \tExpected finish: $eta\n"

    # Makes the tabs in $status_msg align nicely
    tabs 31,50,86,107,129

    printf "$status_msg"

    # sh has no floating calculator, use python as it is definitely installed
    if [ "${seconds_passed}" -ge 3600 ] && [ $2 -eq 1 ] && [ $(python -c "print(${speed}<${WARN_BELOW_WEBSITES_PER_MINUTE})") = 'True' ]; then
      send_alert "${crawl_id}" "The crawling speed is slower than ${WARN_BELOW_WEBSITES_PER_MINUTE} websites per minute! Currently at $speed websites per minute. (Progress: $progress%%)"
    fi
    sleep ${INTERVAL_BETWEEN_STATUS_UPDATES} # Wait ten minutes
    seconds_passed=$(($seconds_passed+$INTERVAL_BETWEEN_STATUS_UPDATES))
  done
}

###############
# run script
###############

# Check if DOCKER_COMPOSE_CMD is runnable
output=$(${DOCKER_COMPOSE_CMD})
ec=$?
if [ $ec -ne 0 ]; then
  send_alert "${crawl_id}" "[crawl $crawl_id]: DOCKER_COMPOSE_CMD is not runnable: $output"
  exit 1
fi

# Check if PATH_DOCKER_COMPOSE_FILE exists
if [ ! -e "${PATH_DOCKER_COMPOSE_FILE}" ]; then
  send_alert "${crawl_id}" "File PATH_DOCKER_COMPOSE_FILE does not exist: $PATH_DOCKER_COMPOSE_FILE"
  exit 1
fi


# Get the crawler output path where all crawled files are stored
CRAWLER_OUTPUT_PATH=$(grep -E ":/crawler/enfbots_output" ${PATH_DOCKER_COMPOSE_FILE} | tr -s ' ' | tr -d "\'" | cut -d ' ' -f 3 | cut -d ":" -f 1 | head -n 1)

# Assert that CRAWLER_OUTPUT_PATH exists
if [ ! -d "${CRAWLER_OUTPUT_PATH}" ]; then
  send_alert "${crawl_id}" "The output path ${CRAWLER_OUTPUT_PATH} does not exist"
  exit 1
fi

# Check if the output folder contains anything
if [ $(ls -1 "/${CRAWLER_OUTPUT_PATH}" | head -n 1 | wc -l) -ne 0 ]; then
  send_alert "${crawl_id}" "There is still output in the output folder at ${CRAWLER_OUTPUT_PATH}"
  exit 1
fi

echo "Running regular crawl with docker file: ${PATH_DOCKER_COMPOSE_FILE}"

# Update crawl ID
sed -i -E "s/--id regular-[0-9]{4}-[0-9]{2}/--id ${crawl_id}/g" $PATH_DOCKER_COMPOSE_FILE

# Statistics filename
sed -i -E "s/000_regular-[0-9]{4}-[0-9]{2}/000_${crawl_id}/g" $PATH_DOCKER_COMPOSE_FILE

# Debugging mode enabled
# set -x

# Check if any crawl is running OR the docker-compose file is corrupt
# shellcheck disable=SC2086 # Intended splitting of DC_SERVICE_CRAWLERS
output=$($DC ps ${DC_SERVICE_CRAWLERS} 2>&1)

# Check command exit code
ec=$?
if [ $ec -ne 0 ]; then
  send_alert "${crawl_id}" "[crawl $crawl_id]: Error code $ec when checking if containers are running"
  exit 1
fi

# Check if any crawlers are running
if [ "$(echo "$output" | grep "enfbots/crawler" | wc -l)" -ne 0 ]; then
  send_alert "${crawl_id}" "[crawl $crawl_id]: There are crawlers running (Is a previous crawl still running?); Aborting. \n\nRunning:\n$output"
  exit 1
fi

send_alert "${crawl_id}" "[crawl $crawl_id]: Starting job-creator at $(TZ=Europe/Zurich date -Iminutes)"

# Start job-creator
output=$($DC up job-creator 2>&1 | tee /dev/tty)
ec=$?

if [ $ec -ne 0 ]; then
  send_alert "${crawl_id}" "[crawl $crawl_id]: Error when starting job-creator: $output"
  exit 1
fi

# Start containers
start_crawlers

send_alert "${crawl_id}" "[crawl $crawl_id]: $(TZ=Europe/Zurich date -Iminutes): Started services: ${DC_SERVICE_CRAWLERS}"

# Await shutdown of all containers; maybe restart some
await_crawlers "${crawl_id}" 1

# Now all containers are down
send_alert "${crawl_id}" "[crawl $crawl_id]: $(TZ=Europe/Zurich date -Iminutes): Finished crawling all jobs ONCE. Now retrying the last failing jobs."

# Maybe some jobs have to be retried, 2nd attempt
echo "Waiting 8h before second last attempt"
sleep 8h
start_crawlers
await_crawlers "${crawl_id}" 0

# Last try
echo "Waiting 8h before last attempt"
sleep 8h
start_crawlers
await_crawlers "${crawl_id}" 0

send_alert "${crawl_id}" "[crawl $crawl_id]: $(TZ=Europe/Zurich date -Iminutes): Finished crawling all jobs."

# Check if actually no job is available any more
output=$(${DC} up is-finished 2>&1)
ec=$?
if [ $ec -ne 0 ]; then
  send_alert "${crawl_id}" "[crawl $crawl_id]: Error code $ec when checking if crawl is finished. \nOutput was: $output"
  exit 1
fi

if [ "$(echo "${output}" | grep "YES, ${crawl_id} is finished")" = "" ];  then
  send_alert "${crawl_id}" "[crawl ${crawl_id}]: All containers down. But --is-finished reports: $output"
  exit 1
fi

send_alert "${crawl_id}" "[crawl $crawl_id]: All containers have finished crawling at $(TZ=Europe/Zurich date -Iminutes). Starting backup..."

# Copy statistics file away
STAT_FILE=$(realpath "$CRAWLER_OUTPUT_PATH/000_${crawl_id}.stats")

send_alert "${crawl_id}" "[crawl $crawl_id]: DEBUG, STAT_FILE=$STAT_FILE and CRAWLER_OUTPUT_PATH=$CRAWLER_OUTPUT_PATH"

# Do not use quotes here as we use the wildcard from above
out=$(ls ${STAT_FILE})

# Check if only one exists
ec=$?
if [ $ec -ne 0 ]; then
  send_alert "${crawl_id}" "Statistics file at ${STAT_FILE} was not found: $out"
  exit 1
fi

if [ $(echo $out | wc --words) -ne 1 ]; then
  send_alert "${crawl_id}" "Too many folders match: $out"
  exit 1
fi

statistics_file=${out}

cp "${statistics_file}" "./${crawl_id}.stats"
stats=$(cat $statistics_file)
formatted_stats=$(echo ${stats} | jq)

echo "Stats for this crawl: $formatted_stats"

# Run backup; This is done with attaching
output=$(${DC} up --attach backup backup 2>&1 | tee /dev/tty)

send_alert "${crawl_id}" "[crawl $crawl_id]: Finished backup at $(TZ=Europe/Zurich date -Iminutes)"
send_alert "${crawl_id}" "[crawl $crawl_id]: $formatted_stats \nVersion: ${VERSION}"

