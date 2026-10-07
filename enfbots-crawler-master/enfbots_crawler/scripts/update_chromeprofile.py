#!/bin/env python
"""
Run this script and afterwards create a tar archive of ./resources/chrome_profile.

Running can be done with python PATH_TO/update_chromeprofile.py --profile-path ./resources/chrome_profile
    * Will terminate after 30 seconds

This can be done with `tar czf chrome_profile_YYYY_MM_DD.tar.gz -C resources chrome_profile` in the project root (next to the `resources` folder).

If developing inside a container: Run the container with 'docker run -v `pwd`:/crawler crawler:development /bin/bash' and then this script.
Afterwards the ./resources/chrome_profile should contain the updated profile.
This can be done with `tar czf chrome_profile_YYYY_MM_DD.tar.gz -C resources chrome_profile` in the project root (next to the `resources` folder).
"""
import argparse
from pathlib import Path
import time

from enfbots_crawler.browser import create_browser
from enfbots_crawler.config import Config


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--profile-path", type=Path, help="Path to the chrome profile")
    parser.add_argument(
        "--manual",
        action="store_true",
        default=False,
        help="Start the browser and manually apply changes to the profile",
    )

    args = parser.parse_args()

    Config().load()

    Config().CHROME_DISABLE_SHM = True

    if args.profile_path:
        Config().CHROME_PROFILE_PATH = args.profile_path

    headless = not args.manual

    with create_browser(use_temp=False, seconds_before_processing_page=1.0, headless=headless):
        if args.manual:
            input("Press enter to quit chrome")
        else:
            time.sleep(30)


if __name__ == "__main__":
    main()
