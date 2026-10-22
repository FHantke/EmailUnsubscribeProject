"""Everything you can tune, in one place.

    1. Browser          the window
    2. Limits           how long each step may take
    3. URL matching     addresses blocked, and which links get followed
    4. Form matching    what counts as an email box, a submit button, a popup
    5. Parallel runs    --jobs
    6. Output columns   the CSV schemas
    7. Run state        not a setting

These values define the recorded data. Note anything that changes a
measurement in CLAUDE.md, where the method is written down.
"""

import re


# ---------------------------------------------------------------------------
# 1. Browser
# ---------------------------------------------------------------------------

# Applied through CDP, not --window-size (which sizes the whole window): the
# recorded width and viewport_coverage are measured against exactly this.
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}


# ---------------------------------------------------------------------------
# 2. Limits
# ---------------------------------------------------------------------------

# Waits while scanning one page, in milliseconds. Raise them if a spot-check
# shows forms missed, or credited to a later phase than they belong to.
LOAD_SETTLE_MS = 3000    # for images and scripts, after the HTML arrives
PAINT_SETTLE_MS = 1000   # settle before the first check, so instant popups appear
SCROLL_BUDGET_MS = 5000  # the after_scroll sweep

# Caps on one detection run in one frame.
DETECT_BUDGET_MS = 4000
MAX_SHADOW_SCAN = 15000  # elements walked looking for shadow-DOM boxes

# Backstops against a page that never finishes, in seconds. Selenium enforces
# the first; SiteWatchdog (jobs.py) the second, for a page wedged on load.
SCRIPT_TIMEOUT_S = 30
SITE_TIME_LIMIT_PER_PAGE_S = 120   # × --max-pages; --site-time-limit overrides


# ---------------------------------------------------------------------------
# 3. URL matching
# ---------------------------------------------------------------------------

# Downloads the browser skips (CDP Network.setBlockedURLs; trailing * so a
# query string still matches). Never block images, which are the deliverable,
# fonts, which change layout metrics, or third-party scripts, which host many
# signup embeds.
BLOCKED_URL_PATTERNS = [
    "*.mp4*", "*.m4v*", "*.webm*", "*.mov*", "*.avi*", "*.mkv*",
    "*.mp3*", "*.m4a*", "*.ogg*", "*.oga*", "*.wav*", "*.flac*", "*.aac*",
]

# Which links to follow when a page has no form: the paper's Table 1, extended
# (see docs/link-keywords.md). A link takes the first group it matches, lower
# groups are visited first, and a link matching none is never visited.
# "text" reads the link's words, "url" its address.
LINK_TIERS = [
    ("text", ["newsletter", "weekly ad", "subscri", "inbox", "email", "sale alert"]),
    ("text", ["signup", "sign up", "sign me up", "register", "create", "join",
              "suscr", "inscr", "count me in", "send me"]),
    ("url", ["newsletter", "subscri", "signup", "sign-up", "mailing-list"]),
    ("url", ["/article", "news/", re.compile(r"/20\d\d/")]),   # a year, e.g. /2024/
    ("url", ["/us/", "=us&", "en-us"]),
]

# Never followed, whatever tier they would match.
LINK_BLACKLIST = ["unsubscribe", "mobile", "phone"]    # by the link's words
URL_BLACKLIST = ["unsubscribe"]                        # by its address
SKIP_EXTENSIONS = re.compile(                          # file downloads
    r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mp3|docx?|xlsx?|pptx?)$", re.I
)


# ---------------------------------------------------------------------------
# 4. Form matching
# ---------------------------------------------------------------------------

# Sent into the page by detect_options() (browser.py) and compiled there as
# case-insensitive JavaScript regexes, so keep to syntax that means the same in
# Python and JavaScript. Each matches inside longer words unless \b pins it:
# without its \b, "log ?in" would also match "blog in".
DETECT_PATTERNS = {
    # An input is an email box if it matches the first and not the second.
    "email": r"e-?mail|newsletter",
    "not_email": r"search|query|password|phone|zip|postal|coupon|promo",

    # Makes a short <div>, <span> or link count as a submit button; a real
    # <button> counts whatever its text says. See docs/link-keywords.md.
    "submit": (
        r"\b("
        r"subscri\w*|suscr\w*|inscr\w*|"            # subscribe, suscribirse, inscreva-se
        r"sign ?(me )?up|join|submit|send|"
        r"notify|register|get|continue|next|save|"
        r"count me in|yes|go|ok"
        r")\b"
    ),

    # -> modal_hint, which ranks a form first among equals. From a class or id
    # on the form or its 10 nearest ancestors; modal_html is a last resort over
    # the form's own HTML.
    "modal": r"modal|dialog|popup|pop-up|lightbox|overlay|flyout|slide-?in",
    "modal_html": r"modal|dialog",

    # -> consent_text_hint, from the text around the form.
    "consent": r"consent|i agree|unsubscribe|privacy|opt.?out|terms",
}

# -> form_type. The crawler records every form with an email box, but plenty of
# those are not signups; this says which kind each one is, so analysis can
# filter. Checked in order, first match wins, and a form matching nothing is
# DEFAULT_FORM_TYPE. Ordered most reliable rule first: a password box is near
# proof of a login, "get in touch" is only a hint.
#
# A type matches when ANY of its detect keys hits and `unless` does not:
#     fields  input types present in the form, e.g. password
#     text    the form's own HTML, or the plain text around it
#     url     the page address (host + path)
#     unless  blacklist; cancels a match from any of the above
# Regexes go into the page as JavaScript, same syntax rule as DETECT_PATTERNS.
DEFAULT_FORM_TYPE = "signup"
FORM_TYPES = [
    # Same three signals the old login_like column used, so classification of
    # login forms did not shift when form_type replaced it on 2026-10-22. `url`
    # is here for two-step logins, which ask for the email and show the password
    # box only on the next screen; `unless` spares a newsletter box whose own
    # text offers a sign-in to people already subscribed.
    ("login", {
        "fields": ["password"],
        "text": r"\b(log ?in|sign ?in)(?!g)",
        "url": r"\b(auth|login|log-in|signin|sign-in|accounts?|myaccount)\b",
        "unless": r"\balready\b.{0,24}\b(subscrib|registered|member|account)",
    }),
    ("checkout", {
        "text": r"\b(checkout|card number|cvv|billing address|expiry date|place (your )?order|payment method)\b",
    }),
    ("comment", {
        "text": r"\b(leave a (repl|comment)|post (a )?comment|your comment)\w*\b",
    }),
    # Deliberately no `url` key: a newsletter popup on /contact is still a
    # newsletter popup. `unless` spares footers that invite contact and a signup
    # in the same block.
    ("contact", {
        "text": r"\b(contact us|get in touch|send (us )?a message|how can we help|enquir|inquir)\w*\b",
        "unless": r"\b(newsletter|subscri)\w*",
    }),
    ("search", {
        "fields": ["search"],
        "text": r"\bsearch\b",
        "unless": r"\b(newsletter|subscri)\w*",
    }),
]


# ---------------------------------------------------------------------------
# 5. Parallel runs
# ---------------------------------------------------------------------------

MAX_JOBS = 8          # each --jobs shard is a browser using ~500-800 MB
SHUTDOWN_GRACE = 90   # seconds a shard gets after Ctrl-C to finish its page and save


# ---------------------------------------------------------------------------
# 6. Output columns
# ---------------------------------------------------------------------------

# Analysis depends on this order: only ever add columns at the END, never
# rename or reorder. Record every change in CLAUDE.md.
FORM_FIELDS = [
    "timestamp", "site", "page_url", "frame_url", "form_sig",
    "first_seen_phase", "detection_method", "rank_on_page", "placement_guess",
    "z_index", "modal_hint", "form_type", "in_iframe", "in_shadow_dom",   # form_type replaced login_like 2026-10-22
    "n_fields", "field_types", "n_checkboxes", "n_checkboxes_prechecked",
    "fields_missing_label", "email_input_type", "email_has_label",
    "email_placeholder", "email_autocomplete", "email_required",
    "submit_text", "other_clickable_text", "heading",
    "consent_text_hint", "width", "height", "viewport_coverage",
    "screenshot", "context_screenshot", "html_file", "form_text",
    "source",       # added 2026-10-07; always "browser" since 2026-10-08
    "field_names",  # added 2026-10-10; one per field, in field_types order
]

PAGE_FIELDS = [     # one row per page visited
    "timestamp", "site", "page_url", "final_url",
    "http_status", "status", "n_new_forms", "error",
]


# ---------------------------------------------------------------------------
# 7. Run state
# ---------------------------------------------------------------------------

# Not a setting: set by Ctrl-C, checked between pages so a run stops cleanly.
STOP = {"now": False}
