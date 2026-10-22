"""Everything you can tune, in one place.

    1. Browser            the window, and what it is told not to download
    2. Limits             how long each step may take, and how much it may scan
    3. Detection words    what counts as an email box, a submit button, a popup
    4. Link choosing      which links the crawler follows when a page has no form
    5. Parallel runs      --jobs
    6. Output columns     the CSV schemas (append-only; see CLAUDE.md)
    7. Run state          not a setting

Changing a value here changes the recorded data, so note anything that affects
the measurements in CLAUDE.md, where the method is written down.
"""

import re


# ---------------------------------------------------------------------------
# 1. Browser
# ---------------------------------------------------------------------------

# The window every page is seen in, in pixels: a desktop visitor's view.
# browser.py applies this through CDP rather than --window-size, which would
# size the whole window and leave a smaller viewport; the recorded `width` and
# `viewport_coverage` are measured against exactly these numbers.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}

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


# ---------------------------------------------------------------------------
# 2. Limits
# ---------------------------------------------------------------------------

# Waits while scanning one page, in milliseconds (1000 = 1 second). Raise these
# if a spot-check shows forms being missed, or showing up in a later phase than
# they should. Lowering PAINT_SETTLE_MS shifts which phase a form is credited to.
LOAD_SETTLE_MS = 3000    # after the page's HTML arrives, wait at most this long for the rest (images, scripts) to load
PAINT_SETTLE_MS = 1000   # then wait this long before the first check, so popups that open right away have time to appear
SCROLL_BUDGET_MS = 5000  # the most time spent scrolling down the page in the after_scroll phase

# Caps on one detection run inside one frame.
DETECT_BUDGET_MS = 4000  # the most time the search for forms may take
MAX_SHADOW_SCAN = 15000  # the most elements checked when looking for shadow-DOM boxes (see docs/crawl-flow.md)

# Backstops against a page that never finishes, in seconds. The first is
# enforced by Selenium itself; the second by SiteWatchdog in jobs.py, which
# covers a page that wedges while loading, when no script call is in flight.
SCRIPT_TIMEOUT_S = 30           # the most time any one piece of JavaScript may run in the page
SITE_TIME_LIMIT_PER_PAGE_S = 120  # per page allowed by --max-pages, so 6 minutes at the default of 3;
                                  # a normal page needs ~70s. Then the browser is killed and the site
                                  # is logged as site_timeout. --site-time-limit overrides it.


# ---------------------------------------------------------------------------
# 3. Detection words
# ---------------------------------------------------------------------------
# The words DETECT_JS (js.py) looks for. detect_options() in browser.py sends
# them into the page on every detection run, where each becomes a
# case-insensitive JavaScript regex.
#
# Write only syntax that means the same in Python and JavaScript:
#     |  or            ?  the thing before it is optional
#     \b word edge     \w a letter or digit      (?!x) not followed by x
# A pattern matches anywhere in the text, including inside a longer word, unless
# a \b pins it: without its \b, "log ?in" would also match "blog in".
#
# The four groups below are in the order detection uses them; the same steps are
# described in docs/crawl-flow.md, section 5.
DETECT_PATTERNS = {

    # --- 1. Is this input an email box? ------------------------------------
    # Its name, placeholder or label has to match "email" ...
    "email": r"e-?mail|newsletter",
    # ... and must not match any of these, which rule the input out.
    "not_email": r"search|query|password|phone|zip|postal|coupon|promo",

    # --- 2. Is this element a submit button? -------------------------------
    # Only consulted for a short <div>, <span> or link; a real <button> counts
    # whatever its text says. The stems and "next"/"save" were added 2026-10-11
    # from the button texts of known signup pages (see docs/link-keywords.md).
    "submit": (
        r"\b("
        r"subscri\w*|suscr\w*|inscr\w*|"            # subscribe, suscribirse, inscreva-se
        r"sign ?(me )?up|join|submit|send|"
        r"notify|register|get|continue|next|save|"
        r"count me in|yes|go|ok"
        r")\b"
    ),

    # --- 3. Ranking signals: which form comes first ------------------------
    # login_like (ranked last), from these words in the form's HTML or in the
    # plain text around it, links and buttons excluded. The \b and (?!g) date
    # from 2026-10-11: without them "blog in", "dialog in", "design in" and
    # "signing up" all counted. "login-box", "loginForm" and "signin" still do.
    "login": r"\b(log ?in|sign ?in)(?!g)",
    # login_like as well, when the page's own address looks like a login or
    # account page. Added 2026-10-11 for two-step logins, which ask for the
    # email first and show the password box only on the next screen, so there is
    # nothing else to go on (auth.hulu.com/web/create-account/enter-email).
    "login_url": r"\b(auth|login|log-in|signin|sign-in|accounts?|myaccount)\b",
    # modal_hint (ranked first among forms equally far in front), from the class
    # or id of the form or one of its 10 nearest ancestors.
    "modal": r"modal|dialog|popup|pop-up|lightbox|overlay|flyout|slide-?in",
    # modal_hint as a last resort: these two words anywhere in the form's HTML.
    "modal_html": r"modal|dialog",

    # --- 4. Recorded about the form ----------------------------------------
    # Sets consent_text_hint when the text around the form matches.
    "consent": r"consent|i agree|unsubscribe|privacy|opt.?out|terms",
}


# ---------------------------------------------------------------------------
# 4. Link choosing
# ---------------------------------------------------------------------------

# Which links to follow when a page has no form, from Table 1 of the paper.
# A link is checked against each group in order and takes the first group it
# matches; lower groups are visited first, and a link matching none is dropped.
# "text" groups look at the words of the link; "url" groups at the address.
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

# Links never followed, whatever tier they would otherwise match.
# Never by their words (so an "unsubscribe" link is never visited):
LINK_BLACKLIST = ["unsubscribe", "mobile", "phone"]
# Never by their address, needed since the signup-address group above also
# matches "/unsubscribe":
URL_BLACKLIST = ["unsubscribe"]
# Never a file download (PDFs, images, videos, Office files, ...):
SKIP_EXTENSIONS = re.compile(
    r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mp3|docx?|xlsx?|pptx?)$", re.I
)


# ---------------------------------------------------------------------------
# 5. Parallel runs
# ---------------------------------------------------------------------------

MAX_JOBS = 8          # most parallel crawlers allowed with --jobs; each is a browser using ~500-800 MB of memory
SHUTDOWN_GRACE = 90   # after Ctrl-C, seconds each parallel crawler gets to finish its page and save before being killed


# ---------------------------------------------------------------------------
# 6. Output columns
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 7. Run state
# ---------------------------------------------------------------------------

# Not a setting: becomes True when you press Ctrl-C. The crawler checks it
# between pages and stops cleanly instead of in the middle of one.
STOP = {"now": False}
