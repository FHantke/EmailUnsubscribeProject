from __future__ import annotations

import json
import logging
from abc import abstractmethod, ABC
import time

from typing import Any, Optional
import base64

import requests
from requests import Response


class ClassificationResult:
    def __init__(
        self,
        result: bool,
        classification_s: float,
        error: Optional[str] = None,
        probability: Optional[float] = None,
    ):
        # If it is of the requested type
        self.result = result

        # Seconds to classification
        self.classification_s = classification_s

        # If there was an error
        self.error = error

        self.probability = probability


class ClassificationException(Exception):
    pass


class ClassifierAbstr(ABC):
    """
    Abstract interface for any classifier
    """

    @abstractmethod
    def is_privacy_policy(self, markdown: str) -> ClassificationResult: ...

    @abstractmethod
    def is_terms_conditions(self, markdown: str) -> ClassificationResult: ...


class ClassifierAsAService(ClassifierAbstr):
    """
    Uses a a given endpoint which runs the classifier service (at https://gitlab.inf.ethz.ch/PRV-BASIN/karel-collab/pptc_classifier).
    """

    def __init__(self, endpoint: str, user: str, token: str, verify_ssl: bool = True, silent: bool = False) -> None:
        self.endpoint = endpoint
        self.user = user
        self.token = token
        self.verify_ssl = verify_ssl
        self.silent = silent

    @staticmethod
    def parse_response(response: Response) -> ClassificationResult:
        if response.status_code >= 500:
            raise ClassificationException(f"Classification failed: {str(response)}")
        if response.status_code >= 300:
            raise ClassificationException(
                "Unexpected response from classification endpoint: " + str(response)
            )

        result = json.loads(response.content.decode("utf-8"))

        try:
            return ClassificationResult(**result)
        except Exception as e:
            raise ClassificationException(str(e))

    def is_privacy_policy(self, markdown: str) -> ClassificationResult:
        user_token = self.user + ":" + self.token
        auth_string = (base64.encodebytes(user_token.encode("utf-8"))).decode("utf-8").strip()

        if not self.silent:
            logging.info("Class:ifying using service on %s", self.endpoint)
        for _ in range(3):
            try:
                response = requests.post(
                    url=self.endpoint + f"/classify/pp/",
                    data=markdown.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {auth_string}",
                    },
                    verify=self.verify_ssl,
                )

                return self.parse_response(response)
            except Exception as e:
                ex = e
                time.sleep(30)
        raise ex

    def is_terms_conditions(self, markdown: str) -> ClassificationResult:
        user_token = self.user + ":" + self.token
        auth_string = (base64.encodebytes(user_token.encode("utf-8"))).decode("utf-8").strip()

        if not self.silent:
            logging.info("Classifying using service on %s", self.endpoint)
        for _ in range(3):
            try:
                response = requests.post(
                    url=self.endpoint + f"/classify/tc/",
                    data=markdown.encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Basic {auth_string}",
                    },
                    verify=self.verify_ssl,
                )
                return self.parse_response(response)
            except Exception as e:
                ex = e
                time.sleep(30)
        raise ex
