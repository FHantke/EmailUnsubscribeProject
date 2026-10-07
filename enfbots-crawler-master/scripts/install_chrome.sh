#!/bin/bash

# Installs chrome to the current directory or the first argument.
#
set -x

cdir=$(realpath ${1:-"$(pwd)"})
echo "Installing to ${cdir}"

CRAWLER_CHROME_DRIVER_PATH="${cdir}/chromedriver"
CRAWLER_CHROME_PATH="${cdir}/chrome/"
CRAWLER_CHROME_PROFILE_PATH="${cdir}/chrome_profile"

mkdir -p ${CRAWLER_CHROME_DRIVER_PATH}
mkdir -p ${CRAWLER_CHROME_PATH}
mkdir -p ${CRAWLER_CHROME_PROFILE_PATH}

# Chrome version 143
mkdir /tmp/install
cd /tmp/install || exit
wget -qO chrome-linux.zip 'https://www.googleapis.com/download/storage/v1/b/chromium-browser-snapshots/o/Linux_x64%2F1536376%2Fchrome-linux.zip?generation=1761614713976098&alt=media'
unzip -o chrome-linux.zip
mv chrome-linux/* "${CRAWLER_CHROME_PATH}"

wget -qO chromedriver.zip 'https://www.googleapis.com/download/storage/v1/b/chromium-browser-snapshots/o/Linux_x64%2F1536376%2Fchromedriver_linux64.zip?generation=1761614717487914&alt=media'
unzip -o chromedriver.zip
mv chromedriver_linux64/chromedriver "${CRAWLER_CHROME_DRIVER_PATH}"

rm -rf /tmp/install/
