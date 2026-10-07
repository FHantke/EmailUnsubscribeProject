# Enforcement bots crawler

This crawler is a product of Karel Kubicek's research, Patrice Kast's bachelor thesis
"Enforcement Bots:  Nothing can block us! Automating website registration for GDPR compliance analysis" and Luka
Lodrant's Master's thesis "Machine learning assisted crawler for legal compliance analysis of registration forms". It was
used to automatically create accounts on the top million most popular websites of the
[Tranco domain list](https://tranco-list.eu/list/89WV/1000000). It includes systems to bypass CAPTCHAs and other bot
protections.

## Pipeline Status

Here you can see the current status of the project.

Current pipeline status: [![pipeline status](https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/enfbots-crawler/badges/master/pipeline.svg)](https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/enfbots-crawler/-/commits/master)
Current coverage: [![coverage report](https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/enfbots-crawler/badges/master/coverage.svg)](https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/enfbots-crawler/-/commits/master)

## Further readme files

* `DATABASE-README.md`: Contains further information related to the database management
* `DOCKER-README.md`: Contains further information related to the setup of the docker host

## Project requirements

* docker

## Setup of "enfbots-crawler" on Ubuntu

1. Inside this folder run `docker build . -f Dockerfile --build-arg BROWSER=chrome --target production -t crawler:YOUR_TAG`
2. To run the container with the crawler installed:
    * ``docker run --rm -it -v `pwd`:/crawler crawler:YOUR_TAG /bin/bash``
        * `--rm` will remove the container afterwards

## Structure

This code package has the following structure:

* **CHANGELOG.md**
    * Contains a changelog for all releases
* **./enfbots_output/**
    * Crawl output goes here
* **./resources/**
    * When running the crawler: firefox profile, `geckodriver` and privacy policy classifier
* **./static_resources/**
    * Resources used when building the docker image
* **./enfbots_crawler/**
    * source code of the crawler
* **./docker-compose/**
    * Docker config for a production crawler
* **./scripts/**
    * various scripts used in development
* **./tests/**
    * unit, integration and real world tests, test resources
    * path `tests/unit` and `tests/integration` are executed in the CI pipeline

## Running

Use `python enfbots_crawler/main.py` the following arguments to control the crawling and registration process:

* `-h, --help`: display information about all command line arguments
* `--create-database`: Create tables and create database (only for sqlite) as defined by `CRAWLER_DB_*`
* `--update-database`: Update the database to the current version
* `-u URL, --url URL`: Crawl a single provided domain
* `-l file, --list file`: Crawl domains from a txt file
* `-s URL OUTPUT_FILENAME.md`: Download the given URL and store markdown in `OUTPUT_FILENAME.md`
* `--merge-stats [FILE1 FILE2 ... MERGED]`: Merges all files into `MERGED` (which should not exist)
* `--install-readabilipy`: Installs the needed npm packages for readabilipy. Used in the `Dockerfile` to have a smoother startup of multiple containers
* `-d`: Get a domain from the DB and crawl it
  * This assumes existing database with jobs. To load the jobs, use `scripts/load_database.py`
* `-dn DATABASE_AMOUNT, --database-amount DATABASE_AMOUNT`: Number of jobs to fetch from the database before stopping (or until no jobs are available)
* `-i ID, --id ID`: ID of the crawl, Jobs can have different IDs and if none is defined the crawler will fetch any job else only jobs with the given `ID`
* `--location`: Similar as ID, but for Jobs column `location`
* `--stats STATS_FILE`: Path to `STATS_FILE` which the crawler will update with the statistics of the completed run
* `--get-progress`: Shows the progress of the given crawl id
* `--get-speed`: Shows the speed in crawls per minute (of the last hour) of the given
                 crawl id

You are also expected to have a Google safe browsing API key when using CRAWLER_USE_SAFE_BRWOSING=True (default).
Override CRAWLER_GOOGLE_API_KEY in config for local testing or provide the CRAWLER_GOOGLE_API_KEY env variable. Ask Karel for the key.

## Configuration

The crawler can be configured using environment variables.

The full list can be seen in `./enfbots_crawler/config.py`

# Development

## Code style

Use [black](https://github.com/psf/black) for consistent code style.

In vscode this extension includes the black formatter:  `ms-python.black-formatter`.

## Running tests

The following command runs all tests:

```bash
./enfbots_crawler/scripts/run-tests.sh
```

To also test the interaction with a classifier, set:

```bash
export CLASSIFIER_SERVICE_TOKEN=asdf_new
```

To run separate tests:
* Unit tests `pytest test/enfbots_crawler/unit`
    * also run with `./enfbots_crawler/scripts/run-tests.sh`
* Integration tests `pytest test/enfbots_crawler/integration`
    * also run with `./enfbots_crawler/scripts/run-tests.sh`
* Real world tests `pytest test/enfbots_crawler/real-world`
    * are **NOT** not run with `./enfbots_crawler/scripts/run-tests.sh`

Some tests rely on the database `enfbots_gitlab_tests` running on infsec-server.
Do not run tests locally when the CI/CD pipeline is running as this interferes with these tests.

## chrome profile

The chrome profile is updated with every build (and thus release) in the Dockerfile.
This will update the browser extensions and apply other updates that come with newer
chrome releases.

If you need to change some settings of the browser (they are stored in the chrome profile)
you can do the following:

Run from the project root (where the README.md lies):

```bash
tar xzf static_resources/chrome_profile_2024_02_20.tar.gz -C resources
```

**UPDATE** the above path to point to the latest chrome profile inside `static_resources`.

```bash
python ./enfbots_crawler/scripts/update_chromeprofile.py --profile-path ./resources/chrome_profile --manual
```

Now you can do changes to the browser's settings and afterwards press enter in the CLI.

```bash
tar czf chrome_profile_20XX_XX_XX.tar.gz -C resources chrome_profile
```

This will create a new chrome profile. **Update** the path afterwards in `Dockerfile` to use it in later builds.

## Upgrading chrome

* Find branch-position on https://chromiumdash.appspot.com/releases?platform=Linux by clicking on a desired version
* Search branch-position folder on https://commondatastorage.googleapis.com/chromium-browser-snapshots/index.html?prefix=Linux_x64/
  * There exists a search field ;)
  * branch position may be off by +- 10. This can be accounted for by removing the last digit from the exact branch position
* Update download links in `./scripts/install_chrome.sh` for the file `chromedriver_linux64.zip` and `chrome-linux.zip`

## Running the PP/TC scraper

To run the scraper via docker-compose in a tmux session, run:
```
tmux new-session -s crawl -d;
tmux send -t crawl 'sh PATH_TO/run_regular_crawl.sh | tee -a /opt/docker/enfbots_regular/regular_crawl.log' ENTER
```
Where the `PATH_TO` needs to be adjusted to match the path to the file *script/run_regular_crawl.sh*.

The user needs to be in the group `docker` (`sudo usermod -aG docker USERNAME`)


## Authors

* Karel Kubicek, <karel.kubicek@inf.ethz.ch>
    * Project leader
* Patrice Kast, <patrice.kast@kastgroup.com>
    * Captcha solving, fundamental extension of crawler, deployment
* Luka Lodrant, <luka.lodrant@inf.ethz.ch>
    * Automaton redesign, machine learning integration
* David Bernhard, <dbernhard@ethz.ch>
    * Infrastructure maintenance, crawler developer for over one year, CI/CD improvements

