#!/usr/bin/python3
import subprocess
import traceback
from pathlib import Path
import csv


STORAGE_DIR = Path('/mnt/cookie_storage/enfbots/2022-06/')
DEST_DIR = Path('/home/karel/tmp')
APHABET = '0123456789abcdefghijklmnopqrstuvwxyz'
C3 = False
# sample = [["https://www.claris.com", "mJNhCXMv"]]
sample = Path('urls_uuids_long.csv')


def remove_http(url: str) -> str:
    return url.split('://')[1]


def extract(from_path: str, dest: str) -> None:
    try:
        cmd = ['tar', '-xf', from_path, '-C', dest]
        print(cmd)
        output = subprocess.check_output(cmd).decode("utf-8").strip()
        print(output)
    except Exception:
        print(f"E: {traceback.format_exc()}")
        exit()


def process() -> None:
    if isinstance(sample, list):
        to_process = sample
    elif isinstance(sample, Path) and sample.suffix == '.csv':
        with open(sample, newline='') as csvfile:
            csv_reader = csv.reader(csvfile, delimiter=',', quotechar='"')
            to_process = list(csv_reader)
            if to_process[0][0] == 'url' and to_process[0][1] == 'dump_uuid':
                to_process.pop(0)
    else:
        exit('Specify what websites to sample')
    for url_uuid in to_process:
        url = remove_http(url_uuid[0])
        uuid = url_uuid[1]

        if len(url) < 3 or url[0] not in APHABET or url[1] not in APHABET or url[2] not in APHABET:
            from_path = STORAGE_DIR / 'other'
        elif C3:
            from_path = STORAGE_DIR / url[0] / url[1] / url[2]
        else:
            from_path = STORAGE_DIR / url[0] / url[1]

        from_path = from_path / (url + '_' + uuid + '.tar.bz2')

        if not from_path.exists():
            print(f'Error: path {from_path} does not exist!')
            continue

        extract(str(from_path), str(DEST_DIR))


if __name__ == '__main__':
    process()
