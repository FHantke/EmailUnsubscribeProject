#!/usr/bin/env python3
"""Collect the words signup pages use, as candidates for tier 1 link keywords.

Input: a text file of URLs of pages that definitely contain a subscription form,
one per line (# comments allowed), e.g. https://example.com/newsletter.

For each URL the script loads the page in Selenium, finds the form with the
crawler's own DETECT_JS, and collects words from:
    title    the page <title>
    h1       the page's first <h1>
    path     the URL path, split on / - _ .
    heading  the form's heading
    button   the form's submit text
    field    the email field's placeholder
    text     the text around the form
It then counts single words and two-word phrases by how many pages use them,
and marks which ones the first LINK_TIERS group ("newsletter", "subscribe", ...)
already matches. The rest are candidates for new tier 1 keywords: links to a
signup page tend to reuse the words of its title, heading and URL.

Only page.goto() is used; nothing is clicked or typed. If no form is visible
on load, the script waits --popup-wait seconds and checks once more. Pages are
loaded one at a time with --page-delay plus jitter between them.

The browser window is visible (headful) so you can watch each page load;
pass --headless to hide it, e.g. on a machine without a display.

--jobs N runs N browsers in parallel, each in its own process (the crawler's
--jobs supervisor, reused), with every URL of one site kept in the same
browser so the per-site delay still holds. Expect N windows unless --headless.
Ctrl-C stops every browser after its current page and still writes the results
for the pages done so far.

Run from the repo root:
    python scripts/collect_tier1_keywords.py inputs/form_urls.txt

Writes, inside --out (default outputs/tier1_keywords/):
    pages.csv     one row per URL: status (ok, no_form_detected, http_error,
                  load_error), title, h1, path, and the form's heading, button,
                  placeholder and text. Error pages contribute no words.
    keywords.csv  one row per word or two-word phrase, most pages first, with
                  where it was seen and the tier/keyword that matches it now.
                  Rows with an empty current_tier are the candidates.

Tiers are numbered from 1 here: tier 1 is the first LINK_TIERS group.
"""

import argparse
import csv
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # find the crawler package without PYTHONPATH

from selenium.common.exceptions import WebDriverException as SeErr

from crawler.browser import detect_in_all_frames, make_driver
from crawler.config import (
    LINK_TIERS, LOAD_SETTLE_MS, MAX_JOBS, PAINT_SETTLE_MS, STOP, TARGET_FORM_TYPE,
)
from crawler.jobs import install_stop_handler, run_jobs
from crawler.util import normalize_site, polite_sleep, setup_logging, short, strip_www

# Filler words. Dropped as single words, and a two-word phrase is dropped if it
# starts or ends with one. Kept short on purpose: words like "up", "get", "me"
# and "us" are left in because they make phrases such as "sign up" and "join us".
STOPWORDS = set("""
a an and are as at be by for from has have in into is it its of on or our so
than that the this to was we with you your www com html htm php aspx index en
""".split())

SOURCES = ("title", "h1", "path", "heading", "button", "field", "text")


def tier_match(text):
    """(tier, keyword): the first text tier of LINK_TIERS whose keyword appears in
    `text`, numbered from 1, the way the crawler checks link text. ("", "") if none."""
    text = text.lower()
    for i, (where, keywords) in enumerate(LINK_TIERS):
        if where != "text":
            continue
        for kw in keywords:
            if kw.search(text) if hasattr(kw, "search") else kw in text:
                return i + 1, getattr(kw, "pattern", kw)
    return "", ""


def terms(text):
    """Single words and two-word phrases in `text`, lowercased, without stopwords.
    Phrases never span a sentence break or a " | " between separate texts."""
    out = set()
    for chunk in re.split(r"[|.!?:;,()\n]+", text.lower()):
        words = re.findall(r"[a-z][a-z'-]*[a-z]|[a-z]", chunk)
        out |= {w for w in words if w not in STOPWORDS and len(w) > 2}
        out |= {f"{a} {b}" for a, b in zip(words, words[1:]) if a not in STOPWORDS and b not in STOPWORDS}
    return out


def detect(driver):
    """Signup-form candidates in every frame; anything classified as another
    kind of form (login, checkout, contact, ...) is dropped."""
    return [c for c in detect_in_all_frames(driver, "kw") if c["form_type"] == TARGET_FORM_TYPE]


def read_page(url, args):
    """Load one page in its own driver. Returns (HTTP status, words by source,
    number of forms found)."""
    driver = make_driver(args)
    try:
        driver.get(url)
        deadline = time.monotonic() + LOAD_SETTLE_MS / 1000
        while time.monotonic() < deadline:
            if driver.execute_script("return document.readyState") == "complete":
                break
            time.sleep(0.1)
        time.sleep(PAINT_SETTLE_MS / 1000)
        status = driver.execute_script(
            "const n = performance.getEntriesByType('navigation')[0];"
            "return n && n.responseStatus ? n.responseStatus : 0;") or 0
        if status >= 400:  # an error page: its words would only pollute the counts
            return status, {}, 0
        forms = detect(driver)
        if not forms:  # maybe a delayed popup
            time.sleep(args.popup_wait)
            forms = detect(driver)
        h1 = driver.execute_script("const h = document.querySelector('h1'); return h ? h.innerText : '';")
        return status, {
            "title": driver.title,
            "h1": re.sub(r"\s+", " ", h1).strip(),
            "path": re.sub(r"[/_.-]+", " ", unquote(urlparse(driver.current_url).path)).strip(),
            "heading": " | ".join(dict.fromkeys(c["heading"] for c in forms if c["heading"])),
            "button": " | ".join(dict.fromkeys(t for c in forms for t in c["submit_text"])),
            "field": " | ".join(dict.fromkeys(c["email_placeholder"] for c in forms if c["email_placeholder"])),
            "text": " | ".join(dict.fromkeys(c["form_text"] for c in forms if c["form_text"])),
        }, len(forms)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def write_csv(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


PAGE_COLUMNS = ["url", "status", "http_status", "n_forms", "error", *SOURCES]
KEYWORD_COLUMNS = ["term", "n_pages", "sources", "current_tier", "matched_keyword", "example_url"]


def crawl(urls, args):
    """Load each URL in turn, one driver per page. Returns one pages.csv row per
    URL visited; stops early, keeping what it has, once Ctrl-C sets STOP."""
    pages = []
    for n, url in enumerate(urls, 1):
        if STOP["now"]:
            break
        if n > 1:
            polite_sleep(args)
        print(f"[{n}/{len(urls)}] {url}", flush=True)
        row = {"url": url, "status": "ok", "http_status": "", "n_forms": 0, "error": ""}
        try:
            row["http_status"], words, row["n_forms"] = read_page(url, args)
        except SeErr as e:
            row.update(status="load_error", error=short(e))
            pages.append(row)
            continue
        if not words:
            row["status"] = "http_error"
            pages.append(row)
            print(f"    HTTP {row['http_status']}; skipped", flush=True)
            continue
        if not row["n_forms"]:
            # Still use title, h1 and path: the form may be one the detector misses.
            row["status"] = "no_form_detected"
        row.update(words)
        pages.append(row)
        print(f"    {row['n_forms']} form(s); title: {words['title'][:70]!r}", flush=True)
    return pages


def keywords_from(pages):
    """keywords.csv rows from pages.csv rows: every term, used by the most pages first."""
    seen = defaultdict(lambda: {"pages": set(), "sources": set()})
    for row in pages:
        if row["status"] not in ("ok", "no_form_detected"):
            continue
        for source in SOURCES:
            for t in terms(row.get(source) or ""):
                seen[t]["pages"].add(row["url"])
                seen[t]["sources"].add(source)
    keywords = []
    for t, s in seen.items():
        tier, kw = tier_match(t)
        keywords.append({"term": t, "n_pages": len(s["pages"]),
                         "sources": " | ".join(x for x in SOURCES if x in s["sources"]),
                         "current_tier": tier, "matched_keyword": kw,
                         "example_url": sorted(s["pages"])[0]})
    keywords.sort(key=lambda k: (-k["n_pages"], k["term"]))
    return keywords


def finish(pages, out):
    """Write pages.csv and keywords.csv, then print a summary."""
    keywords = keywords_from(pages)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "pages.csv", pages, PAGE_COLUMNS)
    write_csv(out / "keywords.csv", keywords, KEYWORD_COLUMNS)

    count = lambda *statuses: sum(1 for p in pages if p["status"] in statuses)
    print(f"\n{len(pages)} URLs: form found on {count('ok')}, {count('no_form_detected')} without a "
          f"detected form, {count('load_error', 'http_error')} failed to load. Output in {out}/")
    print("Most common terms that no tier matches yet:")
    for k in [k for k in keywords if not k["current_tier"]][:20]:
        print(f"    {k['n_pages']:>3} page(s)  {k['term']!r:30} {k['sources']}")


def shard_of(urls, i, n):
    """The URLs for parallel browser i of n. Every URL on one site goes to the
    same browser, so --page-delay still spaces out the loads on that site."""
    sites = {}
    for u in urls:
        sites.setdefault(strip_www(urlparse(u).hostname), len(sites))
    return [u for u in urls if sites[strip_www(urlparse(u).hostname)] % n == i]


def main():
    ap = argparse.ArgumentParser(description="Collect words from known newsletter signup pages.")
    ap.add_argument("urls", help="Text file of URLs of pages that contain a subscription form")
    ap.add_argument("--out", default="outputs/tier1_keywords", help="Output directory (default: outputs/tier1_keywords)")
    ap.add_argument("--popup-wait", type=int, default=8,
                    help="Seconds to wait for a delayed popup when no form shows on load (default: 8)")
    ap.add_argument("--page-delay", type=float, default=3, help="Base seconds between page loads (default: 3)")
    ap.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    ap.add_argument("--user-agent", help="Override the browser user agent")
    ap.add_argument("--headless", action="store_true", help="Hide the browser window (default: visible)")
    ap.add_argument("--no-stealth", action="store_true",
                    help="Drive Chrome with plain Selenium (default: undetected_chromedriver)")
    ap.add_argument("--jobs", type=int, default=1,
                    help=f"Run N browsers in parallel, each in its own process (default: 1, max {MAX_JOBS}, "
                         "~500 MB RAM each)")
    ap.add_argument("--shard", help=argparse.SUPPRESS)  # "i/N", set by --jobs for each child process
    args = ap.parse_args()
    args.stealth = not args.no_stealth   # browser.py reads this
    setup_logging()  # console only; lets run_jobs() relay each browser's output
    if not 1 <= args.jobs <= MAX_JOBS:
        ap.error(f"--jobs must be between 1 and {MAX_JOBS}")

    lines = Path(args.urls).read_text(encoding="utf-8").splitlines()
    urls = list(dict.fromkeys(normalize_site(l) for l in lines if l.strip() and not l.strip().startswith("#")))
    if not urls:
        sys.exit(f"{args.urls} has no URLs (it is empty, or every line is blank or a # comment). "
                 "Add one URL per line and save the file.")
    out = Path(args.out)

    if args.jobs > 1:
        # This process only supervises: each child runs one browser on its share
        # of the sites and writes pages.part<i>.csv; merge() combines them.
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("pages.part*.csv"):  # left over from an earlier run
            old.unlink()

        def merge():
            pages = []
            for part in sorted(out.glob("pages.part*.csv")):
                with open(part, newline="", encoding="utf-8") as f:
                    pages += list(csv.DictReader(f))
            order = {u: k for k, u in enumerate(urls)}
            pages.sort(key=lambda r: order.get(r["url"], len(order)))
            finish(pages, out)

        sys.exit(run_jobs(args, merge))

    install_stop_handler()
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        pages = crawl(shard_of(urls, i, n), args)
        out.mkdir(parents=True, exist_ok=True)
        write_csv(out / f"pages.part{i}.csv", pages, PAGE_COLUMNS)
    else:
        finish(crawl(urls, args), out)
    if STOP["now"]:
        print("Stopped early; the results cover the pages loaded so far.", flush=True)
        sys.exit(130)


if __name__ == "__main__":
    main()
