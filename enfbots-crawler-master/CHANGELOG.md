# Crawler Changelog

All versions are available at the registry `infsec-server.inf.ethz.ch/enfbots` as `crawler` with a "{VERSION}" tag. (i.e: 0.1.5 is available as `crawler:0.1.5`)

## 0.8 - 17.12.2024
* Chrome version 131

## 0.7.20 - 25.11.2024
* Finish `calculate_probabilities.sh` to perform actual updates in a database
* Update `run_regular_crawl.sh` to send statistics about the crawl

## 0.7.19 - 26.08.2024
* minor changes

## 0.7.18 - 25.08.2024
* `run_regular_crawl.sh`: Fix not starting backup when classifier is also running on the same machine
* `calculate_probabilities.sh`: Also support terms
* `calculate_probabilities.sh` Add `--id` parameter to limit calculations to a specific crawl ID

## 0.7.17 - 13.08.2024
* Store ID of a policy to later update it

## 0.7.16 - 13.08.2024
* `calculate_probabilities.py`: Handle errors when calculating probability for a policy
* Use python 3.12.5

## 0.7.15 - 13.08.2024
* `calculate_probabilities.py` Ignore pages that were a redirect and only calculate if it is missing
* smaller improvements

## 0.7.14 - 31.07.2024
* Check status_code of the classifier

## 0.7.13 - 29.07.2024
* `backup.sh`: Add --store-only to benchmark disks

## 0.7.12 - 27.07.2024
* Use google bigquery to download the CruX list very fast
* Dependency updates
* Handle selenium returning none via driver.page_source

## 0.7.11 - 21.07.2024
* `calculate_probabilities.py` Show progress when calculating ranks

## 0.7.10 - 21.07.2024
* Chromium 125
* Added script to calculate probabilities of URLs beeing a policy/terms in an exisiting database

## 0.7.9 - 03.07.2024
* `load_database.py`: Fix additional_crux_ranks beeing null when downloading crux on the fly
  * manually specificing CruX was not affected

## 0.7.8 - 02.07.2024
* Store probability of beeing a PP/TC page in the database if classifier reports it

## 0.7.7 - 02.07.2024
* No longer store username, password and email if `CRAWLER_CREATE_ACCOUNT` is False

## 0.7.6 - 01.07.2024
* Catch some more exceptions from pdfminer
* **Database upgrade required**: Added TC probability to database
  * currently empty until classifier supports it
* Update to chrome 124
* Some other internal improvements (See git history for more details)

## 0.7.5 - 23.05.2024
* Remove NUL characters from the URL (previously only from the content)
* Added `onion.top` to the block list

## 0.7.4 - 12.05.2024
* Fix two rare crashes

## 0.7.3 - 08.05.2024
* Added missing upgrade script for consideration_basis `TOO_SHORT_TEXT`

## 0.7.2 - 07.05.2024
* Fix bug when classifying content found via trying popular paths

## 0.7.1 - 07.05.2024
* Only look at first four search results
* Use `duckduckgo.com` as new search provider
* Stop processing search results when target was found

## 0.7 - 30.04.2024
* Exclude static_resources in final docker image
* Always run classifier when keyword matching score is greater than zero

## 0.6.21 - 24.04.2024
* Support new classification service which uses a DistilBERT model to classify texts as beeing a PP/TC or not
  * Classifier is hosted at `https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/pptc_classifier`
* Fix not storing GDPRs when their type changed
* `iubenda.com` links are now treated as if they are on the same host domain
* `--is-finished` prints the amount of jobs to do
* `--is-finished` now requires a crawl ID
* Added some testcases and Config() is no reset each run (main call) to not have to reset them after each test

## 0.6.20 - 22.04.2024
* Crawler now detects 404 HTTP errors again when no network interceptor is used
* Also catch PdfSyntaxError when extracting content of pdf
    * Also catch an AttributeError in pdfminer
* Ignore `chargebee.com` links
* Updated some dependencies
* Update to python 3.12.3
* `run_regular_crawl.sh`: Update status message to have the same tabstops and use less empty space
* `run_regular_crawl.sh`: Print ETA gained from the `status` service defined in `docker-compose-regular.yml`

## 0.6.19 - 07.04.2024
* `run_regular_crawl.sh`: Copy statistics file away before doing a backup
* No longer consider PP/TC urls whose content is too short
  * Configureable via Config().`MIN_CHARS_DOCUMENT` (default of 120)
  * Still added but with considered=False
* Ignore pages `startmail.com` and `paypal.com` (for PP/TC links)
* No longer add redirect jobs to domains that have non OK domain_status
* Catch exception when pycld2 fails because of some invalid utf-8

## 0.6.18 - 03.04.2024
* Include script to search compressed logs
* Always use website's url (instead of chrome_ux_url)
* Detect DNS_ERROR again
* Try to allow more utf-8 errors in content when detecting the language of a website

## 0.6.17 - 28.03.2024
* Raise CrawlerException if a redirect to about:blank (or url '') happens
* Install bzip2 by default

## 0.6.16 - 21.03.2024
* Crawler image can now backup with xz compression by default (previously installation of xz-utils was necessary)
* Catch some exceptions which led to a stop of the container
  * Less manual restarts required

## 0.6.15 - 06.03.2024
* No longer raise a RuntimeError when dumping the html on a pdf page
* Only look at search results classified as the needed page type (i.e. when searching for a PP only look at links that are classified as PP)

## 0.6.14 - 05.03.2024
* Remove invalid utf-8 characters before detecting language
* Increase sleep time before processing to a minimum time of 0.8 seconds (some random amount in [0, 1.2] seconds is added)

## 0.6.13 - 04.03.2024
* `run_regular_crawl.sh`: Print amount of containers running
* `run_regular_crawl.sh`: Show amount of containers running
* HTTPErrors are also catched in crawl()
* Remove whitespace when checking if a URL is a pdf

## 0.6.12 - 03.03.2024
* Catch InvalidSessionIDException, WebDriverException and TimoutError in crawl() to allow it anywhere during the crawl of one website

## 0.6.11 - 03.03.2024
* Try to not exctract html from pdfs (when a late redirect happens)

## 0.6.10 - 03.03.2024
* Remove zero bytes from PP/TC URL contents

## 0.6.9 - 03.03.2024
* Fix exception when javascript returned no links in some rare cases
* Catch UnexpectedAlertPresentException, WebDriverException, TimeoutException
* Use new major html2text version
* Use simpler get_urlcontent body again (one query instead of two)
* `run_regular_crawl.sh`: Remove log output of sawks when sending an email

## 0.6.8 - 02.03.2024
* Use lazy loading of relationships of ORM objects

## 0.6.{2-7} - 29.02.2024
* Debug releases of performance problems with huge databases

## 0.6.1 - 29.02.2024
* Get rid of session.merge when inserting new PP/TC Urls

## 0.6 - 29.02.2024
* Use chrome 122 and new chrome profile only with Ublock Origin Lite
* Any exception in the `run_crawl` function will abort the container
* Some changes to postgres transactions
* `run_regular_crawl.sh`: Crawling speed observer starts after one hour

## 0.5.34 - 26.02.2024
* Do not use session.merge when updating the hostname of a job

## 0.5.33 - 26.02.2024
* Fix error when adding job again to a database session

## 0.5.32 - 26.02.2024
* static_lists/static_list_2024_02.csv is the same as the previous month but shuffled

## 0.5.31 - 25.02.2024
* Implement detection of insecure forms (New column 'is_insecure' in table `forms`)
* Implement `--no-headless` argument which starts the browser with GUI
* Fix bug where jobs from the database without protocol crashed the crawler
* Fix backup.py creating xz compressed files but with `.bz2` extension
* Remove static_resource folder from final image

## 0.5.30 - 21.02.2024
* Testrelease to see if chrome_profile is updated

## 0.5.29 - 20.02.2024
* Download PDF files via chrome and not via requests which some websites detect and block
    * Also includes a testcase for this
* docker-compose-regular.yml: Use google/cloudflare DNS to not use the host DNS
* Updated chrome profile with
    * Disabled "Continue running background apps when Chromium is closed"
    * Removed KDE Connect extension
    * Disabled "show downloads when they're done"
* Wait for some random time before processing links on page in [0, 1.2] seconds
    * Previously we always waited 1 second
* run_regular_crawl.sh: Send an email if the crawling speed is below 10 websites per minute
* Updated nodejs installation method (Old one broke again)
* Print useful advice when database is missing (to use --create-database)
* Merged enfbots_lib directory in enfbots_crawler
    * Enables copying database.py away again
* CI: No longer trigger tests when markdown or docker-compose files are edited
* Version is now also printed into crawler.log in each output folder of a website crawl
* Includes testcases on the job order of load_database.py, 'enfbot -u' and pdf downloading

## 0.5.28
* Use eager page_load_strategy
* Print when calling driver.get as these sometimes take longer
* Updated dependencies

## 0.5.27
* Create new databases where the urls of each website in *websites* is unique
  * Upgrade will be in 0.5.28 (This version is for testing the unique creation)

## 0.5.26
* Fix wrong usage of `pkill` (chrome processes were no longer killed since *0.5.24*)
* More verbose logging to pinpoint slow instructions

## 0.5.25
* Fix fetching jobs with given crawl_id

## 0.5.24
* **BUG**: Unable to fetch jobs with given crawl_id
* Updated chrome profile to 2024-01-31
* `run_regular_crawl.sh`: Also print crawling speed when checking status
* chrome profile is now included in this repository
* Now includes testcases for a real postgres database and concurrently fetching jobs
* Starting the next job should be much faster due to a single transaction beeing performed

## 0.5.23
* `run_regular_crawl.sh`: Prints progress of the current crawl when checking status
  * Print used memory when checking the status
* Implement `--get-speed` for getting the crawling speed per minute of the last hour

## 0.5.22
* Network interceptor is only launched when we try to register (used to solve captchas)
  * Might improve performance
* Detect also email addresses that have some simple styling applied (i.e. **some-mail**@eth*.ch* will be detected)
* Added `--get-progress` for getting the progress of a given crawl_id

## 0.5.21
* `run-crawler.sh`: Kill all chrome processes when enfbot is finished
* No longer show PP/TC Urls duplicated
* No longer us tqdm for enumerations that usually take less than 10 seconds
* Improved log messages

## 0.5.20
* Added static list

## 0.5.19
* `enfbot --is-finished`: No longer prints 'None' as crawl_id
  * This also no longer ignores if a job still has to be retried (num_starts is less than 3 but was not yet finished)
* Update all JSON columns to be a proper JSON dict instead of just a JSON encoded string
* Improve insertion speed when adding metadata (the `additional_crux_ranks` column) from the big crux list

## 0.5.18
* Implement jobs.from_{static,dynamic} in `load_database.py`
  * from_static column in the *jobs* table is true if it was loaded using `--raw`
  * from_dynamic column is true of it was loaded because it was sampled via `--num-websites-per-countryrank`
* Remove merged `pptc_crawler` code and tests
* `run_regular_crawl.sh`: Use the timezone of zurich and ISO format of the dates in the emails
* `run_regular_crawl.sh`: Check if crawl with given ID is actually finished after all containers are down
  * Else send an email

## 0.5.17
* Use old sampling strategy but rename argument to `--num-websites-per-countryrank`
* WebDriverException no longer stops the container

## 0.5.16
* Stop using `session.merge` again
  * Tested to work in debug crawl
* Add `--xz` argument to `backup.py` to compress using xz compression

## 0.5.15
* Revert removal of `session.merge`
  * As I was not sure if it is working
* Add `twitter.com` and `x.com` to forbidden newsletter URLs (won't subscribe to those)

## 0.5.14
* Remove more `session.merge` calls (now all calls are gone)
  * They could be replaced with `session.add` as no remote changes to the same websitecrawl can happen

## 0.5.13
* Set application name in postgresql connection
* No longer use `session.merge` when storing results in the database
* Only fetch one next job
  * Should reduce network traffic
* Implemented `enfbot --is-finished` to check if no jobs are available in the database for a given crawl
* Added testcases for backup.py
* Added some documentation
* Exit with error code 1 if an exception gets raised when storing the result of a website-crawl
  * This happened when the database was full
* Use sys.exit instead of exit() to allow patching of this method in testcases
* run-crawler.sh Also restarts containers if they were killed due to a TIMEOUT or OOM
* Fix printing all links found on a page instead of the amount

## 0.5.12
* Fix build as `npm` is no longer installed with `nodejs`

## 0.5.11
* Fixed `load_database.py` on cc3
* Exit enfbot when some exception happens
    * To abort a container if the database has some issue

## 0.5.10
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.9
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.9
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.8
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.7
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.6
* Do not use, Tried to fix `load_database.py` on cc3

## 0.5.5
* Do not print the database password
* Tried to fix `load_database.py` generation on cc3

## 0.5.4
* **Breaking** (requires DB update): Remove DDG from enums
    * Also update database views of best PP/TC and US-PN urls
* Allow PP/TCs to be on any subdomain of the given domain (ie. inf.ethz.ch can have a PP/TC at ethz.ch)
* Set timeout when checking sybilmail emails (which could hang indefinitely)
* Update to chromium version 119
* Update to latest debian base (bookworm)
    * Also updates python from 3.12 to 3.12.1
* run_regular_crawl.sh:
    * Fix emails not getting sent
    * Add check to verify that the output folder is empty before starting crawl
    * Sent an alert email if PATH_DOCKER_COMPOSE_FILE does not exist
* Includes testcases for `load_database.py`
* Refactored `load_database.py`
    * now samples N websites PER country and not per country and rank
    * `additional_crux_ranks` is now populated in jobs table with all crux ranks
    * jobs from a raw list also contain `additional_crux_ranks` and in the other column "{"from_list": 1}"

## 0.5.3
* Fixed but that PP/TCs found via search have a wrong ConsiderationBasis
* Add some indices to the database to speed up queries
* PP/TCs must have the same domain when searched

## 0.5.2
* **Breaking**: Rename configuration `USE_DDG` to `USE_SEARCH` (environment variable is now called `CRAWLER_USE_SEARCH`)

## 0.5.1
* Includes run_regular.crawl.sh which can be use for regular crawls
* Use startpage.com as search engine as duckduckgo gives no response via the VPN when using docker

## 0.5
* **Database update required**
* Fix bug of having ConsiderationBasis.NONE even when keyword matching score was used
* Print floats with less precision
* Improved database views and introduce ConsiderationBasis.CACHED if a link was taken from a previous crawl
* load_database.py: No longer load websites with an empty URL

## 0.4.17
* Uses python 3.12
* Check TC of a previous crawl when trying to only verify links of it
* Update some dependencies
* CI updates

## 0.4.16
* Update to latest selenium which finally allows file downloads
* Update .gitlab-ci.yml
  * Use correct registry URL which is available from outside infsec-server.inf.ethz.ch
  * New rules when to execute stages/phases

## 0.4.15
* Released to test cc3 gitlab-runner

## 0.4.14
* Fix previous version as it had a type error

## 0.4.13 [not released due to missing type]
* Updates to load_database.py
  * Add option to xample X amount of websites PER country

## 0.4.12
* Fix: Add db-dtypes as dependency to fix error when running load_database.py

## 0.4.11
* Use latest duckduckgo_search
* Updates to load_database.py
  * Use only websites from defined countries
  * Print if the crux list is empty (happens if the list was not yet released for a given month)
  * Check if GOOGLE_APPLICATION_CREDENTIALS is set which is needed to download the crux list
  * docker image now includes dependencies to run load_database.py by default (previously only possible if the dev dependencies were installed)

## 0.4.10
* Fixed `backup.py` and now approximately prints a line if one percent of the backup is done
* No longer try popular path `/datenschutzerklaerung` on non-german websites

## 0.4.9
* Fix DDG aborting a TC search because the website already has a POLICY
* Broken `backup.py`

## 0.4.8
* Update dependencies
* `backup.py` no longer prints huge amounts of empty lines

## 0.4.7
* `run-crawler.sh` is now invoked with `run-crawler.sh HARD_TIMEOUT SOFT_TIMEOUT NUM_WEBSITES [ADDITIONAL_ARGS]`
* Containers can now run `./scripts/backup.py`
* Print when finished with all forms (registration attempt finished)
* Includes more popular paths for various languages

## 0.4.6
* Use latest duckduckgo_search
* Use chromium 118
* More log output when registering
* Fix creation of database on ETH's postgres instance
* include iproute package in image to set default gateway

## 0.4.5
* No longer ship xvfb in docker image

## 0.4.4
* Use the new chrome headless and remove Xvfb

## 0.4.3
* Fix installing readabilipy dependencies in docker release 'production'

## 0.4.2
* Ship dockerimage with readabilipy dependencies already installed

## 0.4.1
* Added more popular paths to language files

## 0.4
* Use duckduckgo as fallback if no PP/TC was found
  * Configured via `CRAWLER_USE_DDG` which supports 'always', 'missing' (when no other URL was found), 'never'
* Abort if `CRAWLER_ENV` is something that is not defined
* Update dependencies
  * Use chrome 117
* Wait when an exception occurs when checking twocaptcha balance
* Language files now support `popular_pp_path` and `popular_tc_path` which are added to popular paths which are checked when no other URL was found
* Use ReadabiliPy which no longer prints its errors
* Markdown files of privacy policies no longer end with `_.md` but `.md`

## 0.3.11
* (Now fixed) Second pass is True which means all inputs are filled

## 0.3.10 (not published due to failing tests)
* Second pass is True which means all inputs are filled

## 0.3.9
* Added credentials for the enfbots_checkbox-consent-{True,False} crawls

## 0.3.8
* Checks if the revision of a database is up to date when the connection was established and not before
* Uses latest python minor version
* Use latest nodesource install script

## 0.3.7
* Added `USE_SAFE_BROWSING_API` configuration to set if the google safe-browsing API is queried to check if a domain is safe

## 0.3.6
* Fixed run-crawler.sh

## 0.3.{4,5} (run-crawler.sh is broken)
* Tried to quick fix run-crawler.sh

## 0.3.3 (run-crawler.sh is broken)
* Add hard timeout to run-crawler.sh
* Retry to connect to the database if address is not associated with a hostname

## 0.3.2
* Fixed readabilipy as this repository introduced a commit which breaks readabilipy `https://github.com/lodrantl/ReadabiliPy`

## 0.3 (Do not use as readabilipy broke)
* Support for 'popular' paths which are paths for PP/TC that will be tried to be accessed if no PP/TC is found
  * Defined in `enfbots_crawler/config.py:Config.POPULAR_*`
* Add more domains to forbidden newsletter domains
* Check balance only at startup of crawler and not before executing a job
* Remove bytes_tanslated statistic
* Store html on disk for every page we look at
  * Are called `{terms_of_use,privacy_policy}_[URL-ID].html`
* Count index page also as page loaded
* Update `enfbots_crawler/scripts/run-crawler.sh` to support timeout
* Jobs are now tried for at most three times

## 0.2.9
* Stop with exit code 1 if no jobs are in the database, also stop with nonzero exitcode if a CrawlerException occurs
  * Needed for `timeout` to not continue in this case
* Fix very long search for emails in the content of a website due to the regex beeing to loose

## 0.2.7
* **BUG**: Displayed as 0.2.8
* Add support again for blocked newsletters (Wordfence for now)

## 0.2.6
* Twocaptcha balance is checked again if a network error occurs
* Database is checked again if a network error occurs
* Remove functionality of blocked newsletters as this was suspected in preventing the registration of websites
    * This was not the case as the script which populates the 'emails' table was not running

## 0.2.5
* Enable kiosk printing which should fix freezes if the printing dialog was opened by the website when loading
* Check twocaptcha balance if we create an account and if it is zero we abort
* Implement forbidden newsletter urls as configuration

## 0.2.4
* Also check balance before submitting for twocaptcha
* Print when we press escape
  * Used to debug website freezes
* Create indices for: jobs.created_at, jobs.started_at, emails.website_crawl_id, websites.url

## 0.2.3
* Try multiple times polling for new emails when a DNS error occurs
* Check at startup if the configured database is up to date and refuse to run if it is not
* Add `--update-database` to update the configured database
* Check the balance of Twocaptcha if it's defined at startup

## 0.2.2
* Return non-zero exit code when no more jobs are avaialble or due to missing configuration of GOOGLE_API_KEY

## 0.2.1
* Retry on DNS errors when checking the google safebrowsing API
* Introduce timeout when polling sybilmail
* Allow concurrent updates to a statistics file on disk (Multiple cralwers can have `--stats crawl.stats` without overwriting eachothers progress)

## 0.2:
  * **Breaking:** moved a lot of scripts from `scripts/` to `enfbots_crawler/scripts`
  * **Breaking** Use new database layout to support regular crawls
    * Store the markdown also in the database
    * Upgrades of a database from 0.1.X are not supported!
  * Detection of US privacy notices (currently only via keyword matching)
  * Implemented *classification-service* at `./pptc_crawler/classifier_service/classifier_service.py`
    * actually in 0.1.4, but was missed in the CHANGELOG
    * can now also return the probability for PP
    * variable amount of workers and timeout of API is configureable via CLI arguments (`-workers N` and `-timeout M` respectively)
    * Support for partial translation via `-translate-words N` which will translate only the first `N/2` words and the last `N/2` (the middle will stay as it is)
  * New crawler implementation `pptc_crawler`
    * crawls only PP/TC
  * Use gcld3 to detect the language of a document if polyglot is uncertain
    * From google and should be much better, but takes some seconds
  * Also check pdf links and classify them as PP/TC
    * And store the content as txt file in the output folder
  * Implement StatCollector to collect statistics of durations and keep some counters (Amount of classifications, pages visited, ...)
  * Next job is job with lowest `created_at` (and matching `location` and `crawl_id` if specified)
  * If `forced_recrawl` is not set the crawler will check if the website was recently crawled (`RECRAWL_AFTER_DAYS`) and only check PP/TC links if they were found in the previous crawl
  * Setting `STORE_MARKDOWN` controls if the output_folders will contain the markdown of the gathered documents/links
  * Setting `USE_CLASSIFIER` can be used to define if the classifier should be used (else only the keyword-matching is regarded)
  * Raise an exception if a page is in an unsupported language
  * Allow a page to be classified as multiple PageTypes (i.e. A page may contain a PP and a TC)
  * New parameter `--store URL [outputfilename.md]` parameter to download specific URL as markdown
  * New parameter `--delay N` to set the delay to `N` seconds before starting to process a loaded page
  * New parameter `-dn N` to specify how many jobs should be fetched from database until quitting
  * New parameter `--stats FILE.stats` to store some statistics about crawl (accumulates if it exists) before quitting
  * New parameter `--merge-stats FILE1 FILE2 ... MERGED` which merged multiple statistic files (`MERGED` must be a new file)
  * New column `found_emails` in website_crawls which stores all emails that are found on all considered pages
  * Add script (`./scripts/update_chromeprofile.py`) to update a chrome-profile, see this file for more details
  * Add setting `BROWSER_LANGUAGE` which sets the accepted-languages header; If a page has another language we fail
  * Split minimum required keyword-matching score into `MIN_PROBABILITY_CLASSIFIER_PP` and `MIN_PROBABILITY_CLASSIFIER_TC` (also used by US privacy notice)
  * At startup the classifier and sybilmail are checked via the `/version` endpoint (Only if they are essential for the crawl)
  * Implementation stuff
    * Uses sqlalchemy 2.0
    * define logging format in `const.py`
    * Use fixed version of chrome as `apt-install` may install a version not yet supported by `selenium`
    * Check database connection before starting a crawl
  * CI will build each tagged commit and publish it as a tagged docker image
  * Improved `./enfbots_crawler/scripts/load_database.py`
    * support `--raw` to import only a list of domains
      * Order of the list if -threads is 1
    * support `-threads N` to use N threads (works with `--raw` and without)
    * support `--download-crux YYYYMM` to download the list as csv to `./crux_all_YYYYMM.csv`
    * Inserts in order of TLD, domain, subdomain
    * Set location, crawl_id, forced-recrawl via CLI args
    * Prints if there are duplicates contained in the list
  * Updates keywords for various languages
  * Update dependencies
  * Fixed bugs
    * Add timeouts to urllib requests to not wait forever
    * Catch exception when pdf is malformed when extracting text
    * Avoid exception in polyglot if text contains invalid UTF-8 characters
    * Fixed CRAWLER_LOG_LEVEL=DEBUG not writing DEBUG messages
    * Fixed individual log outputs when using `--list`
    * Classifying the first page blindly and not calling the classifier if the score is too low
    * Only check if SYBIL_* is set if CREATE_ACCOUNT is true

## 0.1.4:
  * [enfbots_crawler]: Introduce `CRAWLER_CREATE_ACCOUNT` which is a boolean indicating if we should try to create an account
  * Print classifications of urls including score

## 0.1.3:
 * Added credentials of young users
 * Fix sqlalchemy version to 1.4.46 to not accidentally use 2.X

## 0.1.2:
 * Some script updates (load_database.py, mail_confirm.py)
 * Introduce timeout after 423 and 504 errors of the sybilmail API
 * Regard umlauts as normal characters when splitting words for keyword detection
 * Fix config not honoring DB_PORT
 * mail_confirm should be more robust to crashes
 * Update to selenium 4.8.0 to support chromium v109

## 0.1.1:
 * Print version when running mail_confirm
 * Fix crash if xpath returned no href elements when searching activation link in email
 * Fix bug of not crawling all domains exactly once
 * Updated dependencies

## 0.1.0:

* Initial release
    * Tested:
        * http website
        * https website
        * finding verification link and activating (worked for bike-components.de)
    * Untested: Captcha (Working until key is necessary for service)

# Docker Changelog (for image 'crawler' on infsec-server.inf.ethz.ch/enfbots)

All crawler versions are available at the registry `infsec-server.inf.ethz.ch.ch/enfbots` with a "{VERSION}" tag. (i.e: 0.1.5 is available as tag 0.1.5)

## 2023-02-10
* Ship version 0.1.2

## 2023-01-19
* Ship version 0.1.1


## 2023-01-09:
* Ship version 0.1.0


