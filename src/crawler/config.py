"""Settings you can tune: time limits, form-detection words, link-choosing rules, and the output columns."""

import re


# Size of the browser window, in pixels. Every page is seen as a desktop visitor would see it.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}

# Time limits for each page, in milliseconds (1000 = 1 second).
# If a spot-check shows forms being missed, or showing up in a later phase
# than they should, make these bigger.
LOAD_SETTLE_MS = 3000    # after the page's HTML arrives, wait at most this long for the rest (images, scripts) to finish loading
PAINT_SETTLE_MS = 1000   # then wait this long before the first check, so popups that open right away have time to appear
SCROLL_BUDGET_MS = 5000  # the most time spent scrolling down the page in the after_scroll phase
DETECT_BUDGET_MS = 4000  # the most time one search for forms may take inside one frame
MAX_SHADOW_SCAN = 15000  # the most elements checked when looking for hidden shadow-DOM boxes (see docs/crawl-flow.md)

# Downloads the browser is told to skip, as URL patterns for CDP
# Network.setBlockedURLs (a trailing * so a query string still matches).
# Video and audio are skipped because they waste bandwidth and CPU. Images and
# fonts are NOT skipped: we need them for the screenshots, and missing fonts
# would change the size of things on the page. Scripts from other websites are
# NOT skipped either, because many signup forms are loaded that way.
# This matches by address, not by resource type as Playwright did before
# 2026-10-21, so media served from an extensionless URL now loads.
BLOCKED_URL_PATTERNS = [
    "*.mp4*", "*.m4v*", "*.webm*", "*.mov*", "*.avi*", "*.mkv*",
    "*.mp3*", "*.m4a*", "*.ogg*", "*.oga*", "*.wav*", "*.flac*", "*.aac*",
]

# Words the form detector (DETECT_JS in js.py) looks for. They are sent into the
# page each time it runs and used there as JavaScript regular expressions, always
# case-insensitive. Keep to syntax that means the same in Python and JavaScript:
# | for "or", ? for "optional", \b for a word edge, \w for a letter or digit,
# .{0,20} for "up to 20 characters". The words also match inside longer words
# unless you put \b around them (e.g. "log ?in" also matches "blog in").
DETECT_PATTERNS = {
    # An input counts as an email box when its name, placeholder or label
    # matches "email" ...
    "email": r"e-?mail|newsletter",
    # ... and does not match one of these.
    "not_email": r"search|query|password|phone|zip|postal|coupon|promo",
    # A form is marked login_like (and ranked lower) when these words are in its
    # HTML, or in the plain text around it (not counting links and buttons).
    # \b and (?!g) since 2026-10-11, so "blog in", "dialog in", "design in" and
    # "signing up" no longer count; "login-box", "loginForm", "signin" still do.
    "login": r"\b(log ?in|sign ?in)(?!g)",
    # ... or when the page's address (host + path) looks like a login or account
    # page. Added 2026-10-11 for two-step logins, which ask for the email first and
    # show the password box only on the next screen (auth.hulu.com/.../enter-email).
    "login_url": r"\b(auth|login|log-in|signin|sign-in|accounts?|myaccount)\b",
    # A form inside an element whose class or id has one of these is marked modal_hint (a popup).
    "modal": r"modal|dialog|popup|pop-up|lightbox|overlay|flyout|slide-?in",
    # Last-resort popup check: these words anywhere in the form's own HTML.
    "modal_html": r"modal|dialog",
    # The text on a short <div>/<span>/link must match this for it to count as a
    # submit button (real <button>s count whatever their text says).
    # suscr/inscr/next/save added 2026-10-11 from button texts on known signup
    # pages; see docs/link-keywords.md
    "submit": r"\b(subscri\w*|suscr\w*|inscr\w*|sign ?(me )?up|join|submit|send|notify|register|get|continue|next|save|count me in|yes|go|ok)\b",
    # Text near the form matching this sets consent_text_hint.
    "consent": r"consent|i agree|unsubscribe|privacy|opt.?out|terms",
}

# Becomes True when you press Ctrl-C. The crawler checks it between pages and
# stops cleanly instead of in the middle of a page.
STOP = {"now": False}

MAX_JOBS = 8          # most parallel crawlers allowed with --jobs; each one is a browser using ~500-800 MB of memory
SHUTDOWN_GRACE = 90   # after Ctrl-C, seconds each parallel crawler gets to finish its page and save before being killed
# The most time one site may take, per page allowed by --max-pages (so 6 minutes
# at the default of 3 pages); a normal page needs at most ~70s. After that the
# browser is killed and the site logged as site_timeout. --site-time-limit overrides it.
SITE_TIME_LIMIT_PER_PAGE_S = 120
# The most time any one piece of JavaScript may run in the page before Selenium
# gives up on it. Selenium enforces this; Playwright had no equivalent, which is
# why a page with a wedged main thread used to hang a whole shard indefinitely.
SCRIPT_TIMEOUT_S = 30

# Rules for choosing which links to follow, from Table 1 of the paper.
# A link is checked against each group in order and gets the number of the
# first group it matches (0 to 4). Lower numbers are visited first.
# "text" groups look at the words of the link; "url" groups look at the address.
LINK_TIERS = [
    # "subscri" (the paper: "subscribe") also matches subscription, subscriptions, subscriber; changed 2026-10-11
    ("text", ["newsletter", "weekly ad", "subscri", "inbox", "email", "sale alert"]),
    # "suscr", "inscr", "count me in", "send me" added 2026-10-11 from signup-button texts
    # (Spanish suscribirse/suscríbete, Portuguese inscreva-se, French s'inscrire)
    ("text", ["signup", "sign up", "sign me up", "register", "create", "join",
              "suscr", "inscr", "count me in", "send me"]),
    # Added 2026-10-11 (not in the paper): a signup page recognised by its address,
    # for links whose text says nothing ("Stay informed" -> /newsletter) or that
    # are icons. Caught 101 of the 113 known signup URLs that have a path; see
    # docs/link-keywords.md. "email" is left out: it is in contact-page and
    # tracking addresses (/email-us, ?utm_medium=email).
    ("url", ["newsletter", "subscri", "signup", "sign-up", "mailing-list"]),
    ("url", ["/article", "news/", re.compile(r"/20\d\d/")]),  # /20\d\d/ = a year like /2024/; the paper used "/2017"
    ("url", ["/us/", "=us&", "en-us"]),
]
# Never follow a link whose words contain one of these (so an "unsubscribe" link is never visited).
LINK_BLACKLIST = ["unsubscribe", "mobile", "phone"]
# Never follow a link whose address contains one of these, whatever its words say.
# Needed since the signup-address group above also matches "/unsubscribe".
URL_BLACKLIST = ["unsubscribe"]
# Never follow a link to a file download (PDFs, images, videos, Office files, ...).
SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mp3|docx?|xlsx?|pptx?)$", re.I
)

# The columns of forms.csv, in order. Analysis scripts depend on this order:
# only ever add new columns at the END, and never rename or reorder these.
FORM_FIELDS = [
    "timestamp", "site", "page_url", "frame_url", "form_sig",
    "first_seen_phase", "detection_method", "rank_on_page", "placement_guess",
    "z_index", "modal_hint", "login_like", "in_iframe", "in_shadow_dom",
    "n_fields", "field_types", "n_checkboxes", "n_checkboxes_prechecked",
    "fields_missing_label", "email_input_type", "email_has_label",
    "email_placeholder", "email_autocomplete", "email_required",
    "submit_text", "other_clickable_text", "heading",
    "consent_text_hint", "width", "height", "viewport_coverage",
    "screenshot", "context_screenshot", "html_file", "form_text",
    "source",  # added 2026-10-07; always "browser" since 2026-10-08 (older runs may also have "http")
    "field_names",  # added 2026-10-10; each field's name (or id), in the same order as field_types
]
# The columns of pages.csv: one row for every page visited.
PAGE_FIELDS = [
    "timestamp", "site", "page_url", "final_url",
    "http_status", "status", "n_new_forms", "error",
]
