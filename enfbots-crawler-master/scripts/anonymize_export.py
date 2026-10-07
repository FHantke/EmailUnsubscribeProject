#!/bin/env python

# Requires: presidio_anonymizer presidio_analyzer pandas numpy tqdm fasttext-numpy2 pebble numpy
#   Download the fasttext model via: curl https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin -o lid.176.bin
# Usage: anonymize_export.py PATH_TO_CSV


# Format: website_crawls.id,website_crawls.job_id,website_crawls.index_status,website_crawls.lang,jobs.id,started_at,ended_at,jobs.crux_url,jobs.crux_popularity,crawl_to_privacy.pp_url_id,crawl_to_     privacy.pp_kw_score,crawl_to_privacy.crawl_id,urls.id,urls.url,urls.content_hash,contents.content,contents.lang

import sys
from pathlib import Path
import os
import math
from datetime import datetime

import pandas as pd
import numpy as np
from tqdm import tqdm
from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import fasttext
from pebble import ThreadPool, ProcessPool

DO_DETECT_LANG = True

analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

if len(sys.argv) != 2:
    print(f"Usage is {sys.argv[0]} PATH_TO_CSV")
    print()
    sys.exit(0)

if not Path(sys.argv[1]).exists():
    print(f"File at {sys.argv[1]} was not found")
    sys.exit(1)

input_file = Path(sys.argv[1])

operators = {
        # Global
        "CREDIT_CARD": OperatorConfig("replace", {"new_value": "<redacted credit-card>"}),
        "CRYPTO": OperatorConfig("replace", {"new_value": "<redacted crypto>"}),
        "DATE_TIME": OperatorConfig("keep"),
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<redacted email>"}),
        "IBAN_CODE": OperatorConfig("replace", {"new_value": "<redacted iban>"}),
        "IP_ADDRESS": OperatorConfig("replace", {"new_value": "<redacted ip>"}),
        "NRP": OperatorConfig("replace", {"new_value": "<redacted>"}),
        "LOCATION": OperatorConfig("keep"),
        "PERSON": OperatorConfig("replace", {"new_value": "<redacted name>"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<redacted phone number>"}),
        "MEDICAL_LICENSE": OperatorConfig("replace", {"new_value": "<redacted medical license>"}),
        "URL": OperatorConfig("keep"),

        # USA
        "US_BANK_NUMBER": OperatorConfig("replace", {"new_value": "<redacted bank number>"}),
        "US_DRIVER_LICENSE": OperatorConfig("replace", {"new_value": "<redacted driver license>"}),
        "US_ITIN": OperatorConfig("replace", {"new_value": "<redacted itin>"}),
        "US_PASSPORT": OperatorConfig("replace", {"new_value": "<redacted passport number>"}),
        "US_SSN": OperatorConfig("replace", {"new_value": "<redacted>"}), # Important

        # UK
        "UK_NHS": OperatorConfig("replace", {"new_value": "<redacted NHS number>"}),
        "UK_NINO": OperatorConfig("replace", {"new_value": "<redacted nin>"}),

        # Spain
        "ES_NIF": OperatorConfig("replace", {"new_value": "<redacted NIF>"}),
        "ES_NIE": OperatorConfig("replace", {"new_value": "<redacted NIE>"}),

        # Italy
        "IT_FISCAL_CODE": OperatorConfig("replace", {"new_value": "<redacted PIN>"}),
        "IT_DRIVER_LICENSE": OperatorConfig("replace", {"new_value": "<redacted driver license number>"}),
        "IT_VAT_CODE": OperatorConfig("replace", {"new_value": "<redacted VAT code>"}),
        "IT_PASSPORT": OperatorConfig("replace", {"new_value": "<redacted passport number>"}),
        "IT_IDENTITY_CARD": OperatorConfig("replace", {"new_value": "<redacted identity card number>"}),

        # Poland
        "PL_PESEL": OperatorConfig("replace", {"new_value": "<redacted pesel>"}),

        # Singapore
        "SG_NRIC_FIN": OperatorConfig("replace", {"new_value": "<redacted nric number>"}),
        "SG_UEN": OperatorConfig("replace", {"new_value": "<redacted uen>"}),

        # Australia
        "AU_ABN": OperatorConfig("replace", {"new_value": "<redacted abn>"}),
        "AU_ACN": OperatorConfig("replace", {"new_value": "<redacted acn>"}),
        "AU_TFN": OperatorConfig("replace", {"new_value": "<redacted tfn>"}),
        "AU_MEDICARE": OperatorConfig("replace", {"new_value": "<redacted medical number>"}),

        # India
        # "IN_PAN": OperatorConfig("replace", {"new_value": "<redacted pan>"}),
        "IN_PAN": OperatorConfig("keep"), # redacts 'registered'
        "IN_AADHAAR": OperatorConfig("replace", {"new_value": "<redacted pin>"}),
        "IN_VEHICLE_REGISTRATION": OperatorConfig("replace", {"new_value": "<redacted vin>"}),
        "IN_VOTER": OperatorConfig("replace", {"new_value": "<redacted voter id>"}),
        "IN_PASSPORT": OperatorConfig("replace", {"new_value": "<redacted passport number>"}),

        # Finland
        "FI_PERSONAL_IDENTITY_CODE": OperatorConfig("replace", {"new_value": "<redacted pin>"}),

        # By default redact, in case an entity is new or there is a typo
        "DEFAULT": OperatorConfig("replace", {"new_value": "<redacted>"}),
}


class LanguageIdentification:

    def __init__(self, model_path):
        pretrained_lang_model = model_path
        self.model = fasttext.load_model(pretrained_lang_model)

    def predict_lang(self, text):
        return self.model.predict(text, k=1) # returns top 2 matching languages

lang_ident = LanguageIdentification("./lid.176.bin")

def anonymize(data):
    content = data[0]

    if data[1] > 0:
        print(f"{datetime.now().isoformat()}: {data[1]}%")

    try:
        if content and isinstance(content, str):
            # Detect the contents language
            if DO_DETECT_LANG:
                prob_lang = lang_ident.predict_lang(content.replace("\n", ""))
            else:
                prob_lang = 'en'

            most_probable_lang = prob_lang[0][0].removeprefix("__label__").strip()

            try:
                entities = analyzer.analyze(text=content, language=most_probable_lang)
                return (anonymizer.anonymize(text=content, analyzer_results=entities, operators=operators).text, most_probable_lang)
            except ValueError:
                pass

            # Fallback is english
            entities = analyzer.analyze(text=content, language="en")
            return (anonymizer.anonymize(text=content, analyzer_results=entities, operators=operators).text, most_probable_lang)
    except Exception as e:
        print(e)
        return ("Unable to anonymize.", float('nan'))

    return (float('nan'), float('nan'))


print("Loading CSV")
df = pd.read_csv(input_file, low_memory=False, sep=",", na_values=None)

i = 0
print(f"Loaded CSV. Size: {df.size} and dimensions: {df.shape}")

# Anonymize all contents
tqdm.pandas(desc="Anonymizing")

num_threads = 8
data = df["contents.content"]
multiple = len(data) / 100

i_update = np.int32(np.ceil(([multiple] * 100) * np.array(range(100))))

def calc_percent(i):
    if i in i_update:
        return i // multiple
    return 0


print("Calculating progress updates")
with ThreadPool(num_threads) as pool:
    numbers = list(pool.map(calc_percent, range(len(data))).result())

print("Running...")
with ProcessPool(num_threads) as pool:
    future = pool.map(anonymize, zip(data, numbers))

    it = future.result()

# Modify existing df
print("Updating dataframe")
anonymized_tuples = pd.Series(it)

df["contents.content"] = anonymized_tuples.apply(lambda x: x[0])
df["contents.lang"] = anonymized_tuples.apply(lambda x: x[1])

# Store as CSV file
print("Storing as CSV")
pre, ext = os.path.splitext(input_file)
df.to_csv("".join(pre + "_anon.csv"), index=False)

print("Finished")
