#!/usr/bin/python3
"""Persist-only delivery handler for Postfix pipe(8).

Postfix runs this once per recipient (destination_recipient_limit = 1),
with the message on stdin and envelope data as key=value arguments:

    class=primary queue_id=... sender=... original_recipient=...
    recipient=... client_address=... client_hostname=... client_helo=...
    size=...

It writes the message (.eml) and a metadata sidecar (.json) to
/srv/mail/<class>/YYYY/MM/DD/, durably, and exits.

Exit status contract with Postfix:
    0   delivered; Postfix removes the message from its queue
    75  EX_TEMPFAIL; Postfix keeps the message queued and retries
pipe(8) treats ANY other exit status as a permanent failure, so every
failure path in this file must end in 75.

Delivery is at-least-once: if a failure happens after the .eml is
published but before Postfix records success, the retry writes a second
copy under a new name. Deduplicate at analysis time on
(queue_id, envelope_recipient, sha256).
"""

import datetime
import hashlib
import json
import os
import sys
import uuid

ROOT = "/srv/mail"
TMP = os.path.join(ROOT, "tmp")
SENTINEL = os.path.join(ROOT, ".mailstore")
CLASSES = ("primary", "quarantine", "admin")
EXPECTED_KEYS = (
    "class",
    "queue_id",
    "sender",
    "original_recipient",
    "recipient",
    "client_address",
    "client_hostname",
    "client_helo",
    "size",
)
HANDLER_VERSION = "2"
EX_TEMPFAIL = 75
CHUNK = 1 << 16


def parse_args(argv):
    """Parse key=value arguments. Values may be empty (null sender)."""
    args = {}
    for item in argv:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"malformed argument {item!r}")
        args[key] = value
    missing = [k for k in EXPECTED_KEYS if k not in args]
    if missing:
        raise ValueError(f"missing arguments: {', '.join(missing)}")
    if args["class"] not in CLASSES:
        raise ValueError(f"unknown class {args['class']!r}")
    return args


def fsync_path(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure_dir(path):
    """Create path and any missing parents, fsyncing each new entry."""
    missing = []
    probe = path
    while not os.path.isdir(probe):
        missing.append(probe)
        probe = os.path.dirname(probe)
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o750)
        except FileExistsError:
            pass  # a concurrent delivery created it first
        fsync_path(os.path.dirname(directory))


def deliver(args):
    # The data store is "available" only if its sentinel file exists.
    # With a separate data volume, the sentinel lives on that volume, so it
    # is absent whenever the volume isn't mounted and mail would otherwise
    # land on the root disk hidden under the mount point. On a single disk,
    # renaming the sentinel is a deliberate way to pause delivery. Either
    # way the result is a deferral, never a write to the wrong place.
    if not os.path.isfile(SENTINEL):
        raise RuntimeError(f"{SENTINEL} missing: data store not available")

    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    # Unique per delivery, never derived from content: the same message
    # delivered to two aliases must produce two files.
    base = f"{stamp}-{args['queue_id']}-{uuid.uuid4().hex}"
    final_dir = os.path.join(
        ROOT, args["class"], now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")
    )
    ensure_dir(TMP)
    ensure_dir(final_dir)

    tmp_eml = os.path.join(TMP, base + ".eml")
    tmp_json = os.path.join(TMP, base + ".json")

    digest = hashlib.sha256()
    written = 0
    stdin = sys.stdin.buffer
    with open(tmp_eml, "xb") as out:
        while True:
            chunk = stdin.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            written += len(chunk)
        out.flush()
        os.fsync(out.fileno())

    meta = {
        "handler_version": HANDLER_VERSION,
        "received_utc": now.isoformat(),
        "class": args["class"],
        "queue_id": args["queue_id"],
        "envelope_sender": args["sender"],
        "envelope_recipient": args["recipient"],
        "original_recipient": args["original_recipient"],
        "client_address": args["client_address"],
        "client_hostname": args["client_hostname"],
        "client_helo": args["client_helo"],
        "postfix_size": args["size"],
        "bytes_written": written,
        "sha256": digest.hexdigest(),
        "file": base + ".eml",
    }
    with open(tmp_json, "x", encoding="utf-8") as out:
        json.dump(meta, out, ensure_ascii=False, indent=1, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())

    os.chmod(tmp_eml, 0o440)
    os.chmod(tmp_json, 0o440)
    fsync_path(TMP)

    # Publish the message before its sidecar, so a .json never exists
    # without the .eml it describes. Both paths are on the same
    # filesystem, so each rename is atomic.
    os.rename(tmp_eml, os.path.join(final_dir, base + ".eml"))
    os.rename(tmp_json, os.path.join(final_dir, base + ".json"))
    fsync_path(final_dir)
    fsync_path(TMP)


def main():
    os.umask(0o027)
    deliver(parse_args(sys.argv[1:]))


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:  # anything at all: defer, never bounce
        try:
            sys.stderr.write(f"deferred by handler: {exc!r}\n")
            sys.stderr.flush()
        except BaseException:
            pass
        os._exit(EX_TEMPFAIL)
    sys.exit(0)
