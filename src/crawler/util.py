"""Small helpers shared across modules."""

import hashlib
import logging
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from crawler.config import LINK_TIERS


def setup_logging(path=None):
    """Send the "crawler" logger to the console (message only) and, if `path` is
    given, append to that file too, with a timestamp and level on every line.
    Console output goes to stdout so --jobs can relay it from each shard."""
    log = logging.getLogger("crawler")
    log.setLevel(logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(console)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        to_file = logging.FileHandler(path, encoding="utf-8")
        to_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(to_file)
    return log


def fmt_duration(seconds):
    """Seconds as "4.2s", "3m 07s" or "1h 02m 13s"."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    h, rest = divmod(int(seconds), 3600)
    m, s = divmod(rest, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def now():
    """Current UTC time as an ISO-8601 string, to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short(err):
    """First line of an error, capped at 200 chars, for the CSV error column."""
    text = str(err).strip().splitlines()
    return text[0][:200] if text else type(err).__name__


def slug(text):
    """Filesystem-safe name for a site; names its screens/ and html/ subdirectories."""
    return re.sub(r"[^A-Za-z0-9.-]+", "_", text)[:80]


def strip_www(host):
    """Lowercased hostname without a leading "www."."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def same_site(host, base):
    """True if host is base, or either one is a subdomain of the other."""
    host = strip_www(host)
    return host == base or host.endswith("." + base) or base.endswith("." + host)


def normalize_site(line):
    """One input line (domain, URL, or rank,domain row) as a URL, defaulting to https."""
    s = line.strip()
    if "," in s:
        s = s.split(",")[-1].strip()
    if not re.match(r"^https?://", s, re.I):
        s = "https://" + s
    return s


def load_sites(path):
    """Site list in file order, minus blanks, # comments, a Tranco header row and duplicates."""
    seen, sites = set(), []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("rank,"):
            continue
        if line not in seen:
            seen.add(line)
            sites.append(line)
    return sites


def polite_sleep(args):
    """Wait --page-delay plus up to 1s of jitter between browser page loads on one site."""
    time.sleep(args.page_delay + random.uniform(0, 1))


def flat(value):
    """A list as "a | b" for a CSV cell; anything else passes through."""
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    return value


def form_signature(cand, frame_url):
    """Stable 10-character ID for a form; dedupes it across pages and phases and names its files.

    Built from attributes that survive re-rendering (detection method, frame host,
    email field name/id/placeholder, submit text, field count, heading), never from
    position, so the same footer form on every page of a site hashes the same.
    """
    key = "|".join([
        cand["detection_method"], urlparse(frame_url).netloc,
        cand["email_name"], cand["email_id"], cand["email_placeholder"],
        "/".join(cand["submit_text"]), str(cand["n_fields"]), cand["heading"][:60],
    ])
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def link_tier(text, url):
    """Index of the first LINK_TIERS tier the link matches (lower is more promising), or None."""
    for i, (where, keywords) in enumerate(LINK_TIERS):
        hay = text if where == "text" else url
        for kw in keywords:
            if kw.search(hay) if isinstance(kw, re.Pattern) else kw in hay:
                return i
    return None
