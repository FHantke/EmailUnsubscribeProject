"""
This file contains some constants used in crawling
"""

import re

FORBIDDEN_DOMAINS = (
    "google.com",
    "google.de",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "telegram.org",
    "wordpress.com",
    "github.com",
    "linkedin.com",
    "startmail.com",
    "paypal.com",
    "tumblr.com",
    "microsoft.com",
    "hcaptcha.com",
    "twitter.com",
    "x.com",
    "chargebee.com",
    "onion.top",
)

LOG_FORMAT_INFO = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# Use this as the above while debugging
LOG_FORMAT_DEBUG = (
    "%(asctime)s,%(msecs)03d %(name)s %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s"
)


EMAIL_REGEX = r"([a-zA-Z0-9_.+-]{1,100})@([a-zA-Z0-9-]{1,100}\.[a-zA-Z0-9-.]{1,100})"

email_pattern = re.compile(EMAIL_REGEX)
