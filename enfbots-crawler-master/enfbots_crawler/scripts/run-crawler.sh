#!/bin/bash

# Invoked with run-crawler.sh HARD_TIMEOUT SOFT_TIMEOUT NUM_WEBSITES CRAWLER_ARGS

# Fetches NUM_WEBSITES from the defined database via environment variables and runs them.
# After NUM_WEBSITES it cleans up the environment and then fetches again NUM_WEBSITES.
# This process is repeated until an error occurs or no more jobs are available.

# After SOFT_TIMEOUT a SIGINT (Ctrl+C) signal is sent
# After HARD_TIMEOUT a SIGKILL signal is sent
# NUM_WEBSITES indicates the amount of websites crawled within one invocation of 'enfbots'
# CRAWLER_ARGS contains additional arguments supplied to 'enfbot'

# For debugging purposes
# set -x

if ! [[ $# -ge 3 ]]; then
  echo "error: correct usage: $0 HARD_TIMEOUT SOFT_TIMEOUT NUM_WEBSITES [ADDITIONAL_ARGS]" >&2
  exit 1
fi

hard_timeout="$1"
shift

soft_timeout="$1"
shift

num_websites="$1"
shift

# Check that $num_websites is a numerical value
num_re='^[0-9]+$'
if ! [[ $num_websites =~ $num_re ]]; then
  echo "error: NUM_WEBSITES $num_websites is not a number" >&2;
  exit 1
fi

# Check that HARD_TIMEOUT is bigger than SOFT_TIMEOUT (if they are minutes)
if ! [[ $(echo ${hard_timeout//m}) -gt $(echo ${soft_timeout//m}) ]]; then
  echo "error: HARD_TIMEOUT is not bigger than SOFT_TIMEOUT" >&2;
  exit 1
fi

# Check if we create accounts
create_accounts=$CRAWLER_CREATE_ACCOUNT
var_true='True'

if [[ ${create_accounts,,} = ${var_true,,} ]] || [[ ${create_accounts} == "1" ]]; then
  # At least 7 minutes per website: SOFT_TIMEOUT > num_websites * 10
  # Because we wait 5 minutes for an email
  echo "Creating accounts"
  if ! [[ $(echo ${soft_timeout//m}) -ge $((${num_websites} * 7)) ]]; then
    echo "error: SOFT_TIMEOUT is too small due to us creating accounts. It needs to be at least 7 minutes per website." >&2;
    exit 1
  fi
fi

while
  echo "Starting crawler"
  args=$@
  timeout -s SIGKILL ${hard_timeout} bash -c "timeout -s SIGINT ${soft_timeout} enfbot -d -dn $num_websites $args"
  res=$?
  echo "Exit code from 'enfbot' is $res"

  # Sometimes some chrome process keeps running after the crawler has exited.
  # This makes sure they are all terminated
  pkill chrome
  pkill firefox

  rm -rf /tmp/enfbots_*
  rm -rf /tmp/.org.Chrome*
  rm -rf /tmp/.org.chromium*

  sleep 1

  # Loop as long as result is 0, 124 or 137
  # Meaning of the error codes:
  #   * 0:    means there was no error
  #   * 124:  the crawler timed-out 
  #   * 137:  killed due to timeout or OOM
  [[ $res == 0 || $res == 124 || $res == 137 ]]
do true;
done

