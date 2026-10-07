#!/usr/bin/python3

import argparse
import logging
import tarfile
import glob
import re
import sys
import threading
import functools

from pathlib import Path
from typing import List, Tuple, cast, Any, Set
from hyperlink import URL

from sqlalchemy import text, select
import tldextract
from tqdm import tqdm
from pqdm.threads import pqdm

from enfbots_crawler import const
from enfbots_crawler.database import initialize_base_db, SessionLocal, DBURL
from enfbots_crawler.config import Config
from enfbots_crawler.scripts.backup import ensure_dirs, get_output_subfolder
from enfbots_crawler.helper import check_database, get_non_unique_items, set_log_formatter

logger = logging.getLogger()

policy_pattern = re.compile(r".*privacy_policy_([\d]+).md")
terms_pattern = re.compile(r".*terms_of_use_([\d]+).md")


class Counter:

    def __init__(self) -> None:
        self.c = 0


count_lock = threading.Lock()
counter = Counter()

# Count the folder that were updated multiple times PER invokation of vcs-tools.py
folders_written_lock = threading.Lock()
folders_written_this_run: Set[str] = set()
folders_multiple_times: Set[str] = set()


def get_url(url_id: int) -> List[Tuple[str, str]]:
    with SessionLocal.begin() as session:
        res = session.execute(select(DBURL.url, DBURL.content_hash).where(DBURL.id == url_id)).all()

        return cast(List[Tuple[str, str]], res)


def is_same(name: str, url: str) -> bool:
    extracted_url = tldextract.extract(url)
    name_extract = tldextract.extract(name)

    return (
        name_extract.domain == extracted_url.domain and name_extract.suffix == extracted_url.suffix
    )


def process_archive(
    file: str, target_root: Path, count_lock: Any, counter: Counter
) -> Tuple[bool, int]:  # returns (Success, if this folder was existing and we performed an UPDATE)
    try:
        log_msg = ""
        log_msg += f"Processing: {file}\n"

        assert target_root.exists()

        with count_lock:
            counter.c += 1

        splitted = Path(file).name.split("_")

        # The folder_name is basically the domain without protocol
        folder_name = splitted[0]
        already_populated = False

        with folders_written_lock:
            if folder_name in folders_written_this_run:
                log_msg += f"THIS folder has already been populated in this run: {folder_name}"
                folders_multiple_times.add(folder_name)
                already_populated = True
            folders_written_this_run.add(folder_name)

        assert folder_name
        log_msg += f"folder_name {folder_name}\n"

        base_folder = get_output_subfolder(str(folder_name), dest_dir=target_root) / folder_name

        existed = 0
        if base_folder.exists() and not already_populated:
            log_msg += f"Second time writing into {base_folder}\n"
            existed = 1
        elif base_folder.exists() and already_populated:
            pass
        else:
            base_folder.mkdir(exist_ok=False)

        has_content = False

        try:
            with tarfile.open(file) as tfile:
                if not tfile:
                    log_msg += f"ERROR; tfile is none: {file}\n"
                    logger.error(log_msg)
                    return (False, existed)

                for cfile in tfile:
                    has_content = True

                    pmatch = policy_pattern.match(cfile.name)
                    tmatch = terms_pattern.match(cfile.name)

                    assert cfile

                    if pmatch or tmatch:
                        match = pmatch if pmatch else tmatch
                        assert match

                        doctype = "pp" if pmatch else "tc"

                        # print(f"Found a {doctype} file at: {name}")

                        id = int(match.group(1))
                        db_url = get_url(id)

                        if len(db_url) == 0:
                            logger.error(f"No url for ID: {id}")
                            return (False, 0)
                        url = db_url[0][0]

                        on_same_domain = is_same(folder_name, url)
                        # print(f"\tIs on same domain: {on_same_domain}")

                        path = list(URL.from_text(url).path)

                        if len(path) >= 1 and path[-1] == "":
                            del path[-1]

                        if len(path) == 0:
                            if on_same_domain:
                                path = ["INDEX"]
                            else:
                                path = [tldextract.extract(url).domain]

                        sfile = tfile.extractfile(cfile)

                        if not sfile:
                            log_msg += f"ERROR: Unable to extract {cfile}\n"

                            logger.error(log_msg)
                            return (False, existed)

                        content = sfile.read()

                        fname = base_folder / (doctype.upper() + "_" + "_".join(path[-4:]) + ".md")

                        if len(fname.name) > 30:
                            fname = fname.parent / (fname.name[:27] + ".md")

                        # TODO: actually implement the logic for updates
                        if fname.exists() and already_populated:
                            log_msg += f" ERROR File already exists from this crawl : {fname}\n"  # TODO: include crawl_ID
                            # TODO: maybe
                            continue

                        update = False
                        if fname.exists():
                            update = True
                        with open(fname, mode="w+") as pfile:
                            log_msg += f"\t URL {doctype}: {url} [updated {update}]: has path: {path} -> {fname}\n"
                            pfile.write(content.decode("utf-8"))

                        sfile.close()
                    else:
                        pass
                        # print(f"NOTHING: {cfile}")
                    # print(cfile.name)
        except tarfile.ReadError as e:
            logger.error(f"Unable to open file at {file}: {e.__dict__}")
            return (False, 0)

        if not has_content:
            logger.error(f"WARNING: {file} has no content")
            return (False, 0)

        logger.info(log_msg)
        return (True, existed)
    except Exception as e:
        logger.error(e)
        return (False, 0)


def main() -> None:
    logging.basicConfig()

    log_formatter = logging.Formatter(
        fmt=const.LOG_FORMAT_INFO,
        datefmt="%Y-%m-%d:%H:%M:%S",
    )
    fileh = logging.FileHandler("vcs-tools.log")
    fileh.setFormatter(log_formatter)

    logger.addHandler(fileh)

    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            logger.removeHandler(handler)
            continue
        handler.setFormatter(log_formatter)
    logger.setLevel(Config().LOG_LEVEL)

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--compressed-folder",
        help="Compressed crawl output folder",
        required=True,
        dest="compressed_folder",
    )
    parser.add_argument(
        "--third-level",
        help="If we should use three subfolders with the first three characters of each URL",
    )
    parser.add_argument(
        "--repo-folder",
        help="Folder which contains the PP/TCs",
        required=True,
        dest="repo_folder",
    )
    parser.add_argument(
        "-n", help="Number of threads to use (default: 4)", default=4, dest="num_threads"
    )
    parser.add_argument("-i", "--id", help="ID of the crawl")

    args = parser.parse_args()

    compressed_folder = Path(args.compressed_folder)

    if not Config().load():
        logger.info("There seems to be an issue with the configuration")
        return
    logger.setLevel(Config().LOG_LEVEL)

    repo_folder = Path(args.repo_folder)
    if not repo_folder.exists():
        logger.error("The repo folder does not exist at %s", repo_folder)
        sys.exit(1)

    if not compressed_folder.exists():
        logger.error("The compressed folder does not exist at %s", compressed_folder)
        sys.exit(1)

    if args.id:
        crawl_compressed_folder = compressed_folder / args.id
    else:
        crawl_compressed_folder = compressed_folder

    if not crawl_compressed_folder.exists():
        logger.error("The compressed folder does not exist at %s", crawl_compressed_folder)
        sys.exit(1)

    logger.info("Initializing database connection to: %s", Config().get_db_url(True))
    initialize_base_db(
        db_url=Config().get_db_url(),
        alembic_root_dir=Path("../enfbots_crawler/"),
        connection_info="jupyter notebook",
        pool_size=64,
    )

    # Check if database connection works
    if not check_database(Config().code_dir):
        raise RuntimeError(
            "There seems to be a problem with the database. Check your CRAWLER_DB_* settings!"
        )

    crawl_folder = crawl_compressed_folder

    allowed_types = (".tar.xz", ".tar.bz2")
    files = []
    for t in allowed_types:
        files.extend(glob.glob(str(crawl_folder) + f"/*/*/*{t}"))

    ensure_dirs(repo_folder)

    num_archives = len(files)

    parallel = True
    if parallel:
        result = pqdm(
            files, lambda x: process_archive(x, repo_folder, count_lock, counter), n_jobs=32
        )
    else:
        result = [process_archive(x, repo_folder, count_lock, counter) for x in files]

    failed = map((lambda x: not x[0]), result)
    num_updates = functools.reduce((lambda a, b: a + b), map(lambda x: x[1], result), 0)

    logger.addHandler(logging.StreamHandler())

    logger.info("All successfull: %s", not any(failed))
    logger.info("Number of archive files: %i", num_archives)
    logger.info(
        "Count of process_archive calls (should match above): %s; matches: %i",
        counter.c,
        counter.c == num_archives,
    )
    logger.info("Tried to write a second (or third) time to: %s", folders_multiple_times)
    logger.info("Number of updated domains: %i", num_updates)


if __name__ == "__main__":
    main()
