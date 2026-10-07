from __future__ import annotations

from typing import Optional, Dict, Any
from enum import Enum
import datetime
import json


class CollectType(str, Enum):
    SINGLE_CRAWL = "SINGLE"
    MULTIPLE_CRAWLS = "MULTIPLE"


class StatCollector:
    def __init__(
        self,
        collect_type: CollectType = CollectType.SINGLE_CRAWL,
        total_runtime_seconds: float = 0.0,
        browser_startup_seconds: float = 0.0,
        classifications: int = 0,
        classification_errors: int = 0,
        classification_seconds: float = 0,
        pages_loaded: int = 0,
        num_searches: int = 0,
        websites_visited: int = 0,
        websites_validated: int = 0,
    ) -> None:
        self.collect_type = collect_type
        self.total_runtime_seconds = total_runtime_seconds
        self.browser_startup_seconds = browser_startup_seconds

        self.classifications = classifications
        self.classification_errors = classification_errors
        self.classification_seconds = classification_seconds

        self.pages_loaded = pages_loaded
        self.num_searches = num_searches

        self.start_time: Optional[datetime.datetime] = None
        self.stop_time: Optional[datetime.datetime] = None

        self.websites_validated = websites_validated
        self.websites_visited = websites_visited

    def classified(self, duration_seconds: float) -> None:
        self.classifications += 1
        self.classification_seconds += duration_seconds

    def page_loaded(self) -> None:
        self.pages_loaded += 1

    def error(self) -> None:
        self.classification_errors += 1

    def search_performed(self) -> None:
        self.num_searches += 1

    def start(self) -> None:
        self.start_time = datetime.datetime.now()

    def stop(self) -> None:
        self.stop_time = datetime.datetime.now()

        if self.start_time is not None and self.collect_type is CollectType.SINGLE_CRAWL:
            delta = self.stop_time - self.start_time
            self.total_runtime_seconds = delta.total_seconds()

    def visited_website(self) -> None:
        self.websites_visited += 1

    def validated_website(self) -> None:
        self.websites_validated += 1

    def add_browser_startup_seconds(self, seconds: float) -> None:
        self.browser_startup_seconds += seconds

    def __str__(self) -> str:
        if self.collect_type is CollectType.SINGLE_CRAWL:
            if self.stop_time is not None and self.start_time is not None:
                delta = datetime.timedelta(seconds=self.total_runtime_seconds)
                duration = str(delta)
            elif self.start_time is None:
                duration = "Not started"
            elif self.stop_time is None:
                duration = "Not stopped"
        else:
            delta = datetime.timedelta(seconds=self.total_runtime_seconds)
            duration = str(delta)

        message = f"[StatCollector with type {self.collect_type.name}]"
        message += f"\n\tTotal time: {duration}"
        if (
            self.collect_type is CollectType.MULTIPLE_CRAWLS
            and self.stop_time is not None
            and self.start_time is not None
        ):
            stat_collector_runtime = self.stop_time - self.start_time
            message += f"\n\tTotal time StatCollector was running: {str(stat_collector_runtime)}"
        if self.browser_startup_seconds > 0:
            browser_startup_time = datetime.timedelta(seconds=int(self.browser_startup_seconds))
            message += f"\n\tTotal time browser startup: {browser_startup_time}"
        message += f"\n\tTotal classifications: {self.classifications}"
        message += f"\n\tTotal classification time: {self.classification_seconds:0.2f} seconds"
        message += f"\n\tTotal pages loaded: {str(self.pages_loaded)}"
        message += f"\n\tTotal searches: {str(self.num_searches)}"
        message += f"\n\tTotal errors when classifying: {self.classification_errors}"
        message += f"\n\tTotal websites visited: {self.websites_visited}"
        message += f"\n\tTotal websites validated: {self.websites_validated}"

        return message

    def add(self, other: StatCollector) -> None:
        self.collect_type = CollectType.MULTIPLE_CRAWLS
        self.total_runtime_seconds += other.total_runtime_seconds

        self.classifications += other.classifications
        self.classification_seconds += other.classification_seconds

        self.pages_loaded += other.pages_loaded
        self.num_searches += other.num_searches
        self.classification_errors += other.classification_errors
        self.browser_startup_seconds += other.browser_startup_seconds
        self.websites_validated += other.websites_validated
        self.websites_visited += other.websites_visited

    def to_json(self) -> str:
        json_dict: Dict[str, Any] = dict()

        json_dict["total_runtime_seconds"] = int(self.total_runtime_seconds)

        json_dict["classifications"] = self.classifications
        json_dict["classification_seconds"] = round(self.classification_seconds, 2)
        json_dict["classification_errors"] = self.classification_errors

        json_dict["pages_loaded"] = self.pages_loaded
        json_dict["num_searches"] = self.num_searches
        json_dict["browser_startup_seconds"] = int(self.browser_startup_seconds)
        json_dict["websites_validated"] = self.websites_validated
        json_dict["websites_visited"] = self.websites_visited

        return json.dumps(json_dict, sort_keys=True, indent=4)
