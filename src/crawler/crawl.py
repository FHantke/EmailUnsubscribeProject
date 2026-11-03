"""Per-site flow: the landing page, then ranked links."""

from urllib.parse import urldefrag, urlparse

from crawler.browser import make_driver, rank_links, scan_page
from crawler.config import STOP
from crawler.util import normalize_site, polite_sleep, strip_www


class BrowserStartError(Exception):
    """The browser would not start, before the site was touched. That is the
    worker's fault, not the site's (no driver for this CPU, a broken image, out
    of memory), so the site must not be recorded as failed: see crawl_queue()."""


def crawl_site(raw_site, args, output):
    """Crawl one site end to end.

    The landing page, then links from rank_links() up to --max-pages, stopping
    at the first page with a form unless --explore is set. Each site gets its own
    driver, so it starts from a clean profile and takes nothing from the last site.
    Raises BrowserStartError if that driver cannot be started.
    """
    landing = normalize_site(raw_site)
    site = landing
    seen = set()

    try:
        driver = make_driver(args)
    except Exception as e:
        raise BrowserStartError(str(e)) from e
    try:
        found = scan_page(driver, landing, site, args, output, seen)
        visited = {landing, urldefrag(driver.current_url)[0]}
        pages_done = 1
        if found == 0 or args.explore:
            base = strip_www(urlparse(driver.current_url).hostname or urlparse(landing).hostname)
            links = rank_links(driver, base, visited)
            for link in links:
                if pages_done >= args.max_pages or (found and not args.explore):
                    break
                if STOP["now"]:
                    break
                polite_sleep(args)
                found += scan_page(driver, link, site, args, output, seen)
                visited.add(link)
                pages_done += 1
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    # No delay here: the next site is a different host. Same-host delays stay above.
