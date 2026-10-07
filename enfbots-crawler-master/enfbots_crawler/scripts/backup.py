#!/usr/bin/python3

import argparse
import os
import subprocess
import traceback
from pathlib import Path
import shutil

from typing import Optional, Tuple, List

from pqdm.threads import pqdm

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

assert len(ALPHABET) == 36


def ensure_dirs(dest_dir: Path, crawl_id: Optional[str] = None, third_level: bool = False) -> None:
    """
    Makes sure dest_dir contains the required folder structure.
    The structures is: ./[a-Z]/[a-Z]/<website starting with the characters of the two parent folders>/

    Args:
        dest_dir (Path): _description_
        crawl_id (Optional[str], optional): _description_. Defaults to None.
        third_level (bool, optional): _description_. Defaults to False.
    """
    # No crawl_id subfolder if none is defined
    if crawl_id is None or crawl_id.strip() == "":
        cur = dest_dir
    else:
        cur = dest_dir / crawl_id
        cur.mkdir(exist_ok=True)

    other_dir = cur / "other"
    other_dir.mkdir(exist_ok=True)

    for c1 in ALPHABET:
        cur1 = cur / c1
        cur1.mkdir(exist_ok=True)

        for c2 in ALPHABET:
            cur2 = cur1 / c2
            cur2.mkdir(exist_ok=True)

            if third_level:
                for c3 in ALPHABET:
                    cur3 = cur2 / c3
                    cur3.mkdir(exist_ok=True)

def get_output_subfolder(url: str, dest_dir: Path, third_level: bool = False) -> Path:
    if (len(url) < 3 or url[0] not in ALPHABET or url[1] not in ALPHABET or url[2] not in ALPHABET):
        return dest_dir / "other"
    if third_level:
        return dest_dir / url[0] / url[1] / url[2]
    else:
        return dest_dir / url[0] / url[1]

def copy(
    src_dir: Path,
    dest_dir: Path,
    num_threads: int,
    crawl_id: Optional[str],
    third_level: bool = False,
    remove_after_compression: bool = False,
    compression_algorithm: str = "bzip2",
) -> None:
    files = list(os.listdir(src_dir))
    # We print every len(files)/100 items a newline to show progress via a new line which is displayed when using `docker compose up`
    one_percent = [False] * max(1, int(len(files) * 0.01))
    one_percent[-1] = True
    print_progress = one_percent * 101

    in_data = zip(files, print_progress)

    def store_outputfolder(t: Tuple[Path, bool]) -> bool:
        file = t[0]
        if t[1]:  # Print a newline if told
            print()
        url = str(file).split("_", maxsplit=1)[0]

        this_dest_dir = dest_dir
        if crawl_id is not None:
            this_dest_dir /= crawl_id

        target_path = get_output_subfolder(url, this_dest_dir, third_level)

        try:
            assert compression_algorithm in ["xz", "bzip2", "store"]

            if compression_algorithm == "xz":
                extension = "xz"
            elif compression_algorithm == "bzip2":
                extension = "bz2"
            elif compression_algorithm == "store":
                extension = ""
            else:
                assert False

            if compression_algorithm == "store":
                filename = target_path / (str(file) + f".tar")
            else:
                filename = target_path / (str(file) + f".tar.{extension}")

            cmd: List[str | Path] = [
                "tar",
                "cfP",
                filename,
                "-C",
                src_dir,
                file,
            ]
            
            if compression_algorithm != "store":
                cmd.append(f"--use-compress-prog={compression_algorithm}")

            # The call check_output will raise an exception if the command
            # returned a non zero exit code
            subprocess.check_output(cmd).decode("utf-8").strip()

            if remove_after_compression:
                source = src_dir / str(file)
                if (source).is_file():
                    os.remove(source)
                else:
                    shutil.rmtree(source)
        except Exception:
            print(f"E: {traceback.format_exc()}")
            raise

        return True

    pqdm(
        in_data,
        store_outputfolder,
        n_jobs=num_threads,
        total=len(files),
        exception_behaviour="immediate",
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument("--from", help="Crawl output folder", required=True, dest="src_dir")
    parser.add_argument(
        "--to",
        help="Folder where the compressed data will be written",
        required=True,
        dest="dest_dir",
    )

    parser.add_argument(
        "--third-level",
        help="If we should use three subfolders with the first three characters of each URL",
    )
    parser.add_argument(
        "--id", help="Compress ALL data in a subfolder of DEST_DIR called ID", dest="crawl_id"
    )
    parser.add_argument(
        "--remove-after",
        help="Remove source files after compressing them to the destination directory",
        action="store_true",
    )
    parser.add_argument(
        "-n", help="Number of threads to use (default: 4)", default=4, dest="num_threads"
    )
    parser.add_argument("--xz", help="Use xz compression", action="store_true")
    parser.add_argument("--store-only", help="Use no compression", action="store_true")

    args = parser.parse_args()

    compression_algorithm="xz" if args.xz else "bzip2"
    if args.store_only:
        compression_algorithm = "store"

    ensure_dirs(Path(args.dest_dir), args.crawl_id, args.third_level)
    copy(
        Path(args.src_dir),
        Path(args.dest_dir),
        int(args.num_threads),
        args.crawl_id,
        args.third_level,
        args.remove_after,
        compression_algorithm=compression_algorithm,
    )


if __name__ == "__main__":
    main()
