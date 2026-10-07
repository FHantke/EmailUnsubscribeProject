"""
This file should include all exceptions used in the crawler
"""


class CrawlerException(Exception):
    """
    Indicates that the crawler has some unrecoverable error and should stop crawling.
    """


class TablesMissingException(CrawlerException):
    """
    Indicates that the database is missing and needs to be created using --create-database
    If the sqlite file is missing this error can also be thrown.
    """


class WebsiteException(Exception):
    """
    Indicates that a website had some problem. The crawler can continue crawling other sites.
    """


class OutdatedDatabaseException(CrawlerException):
    """
    Indicates that the database needs an upgrade (i.e. add columns or tables).
    Thus one should run --update-database.
    """


class DomainBlacklistedError(Exception):
    pass


class DatabaseUninitialized(Exception):
    pass
