"""Deciding what a form is, from what DETECT_JS saw.

The judgement half of detection. `js.py` reports what only a painted page can
tell you - what is visible, how large it is, how far in front it sits - and this
decides, from the markup and wording it reports back, what the form is and how
the candidates rank.

Why here and not in the page: these rules are the ones that get edited. Keeping
them in Python makes them testable in milliseconds, so a change to `FORM_TYPES`
can be replayed over every form ever collected rather than checked by crawling a
fixture in a browser - which is how the 2026-10-23 audit had to be done. It is
also one regular-expression dialect instead of two.

What stays in `js.py`: anything needing getComputedStyle, a bounding box or a
shadow root; CAPTCHA detection, which walks the DOM by selector and would need
an HTML parser here (the project deliberately ships none); and
`consent_text_hint`, which reads the text *including* links, since the consent
wording is usually inside one - the text this module is given has links taken
out, because a "Sign in" link next to a newsletter box must not type it login.
"""

import re
from urllib.parse import urlparse

from crawler.config import DEFAULT_FORM_TYPE, FORM_TYPES, TARGET_FORM_TYPE, VENDOR_HINTS

# A dropdown's choices are not the form's wording: 200 country names would
# otherwise decide its type. js.py drops them from the text it reports; this
# drops them from the markup, which is matched separately.
_OPTION = re.compile(r"<option\b[^>]*>.*?</option>", re.I | re.S)

# How much of a form is read. Matching the whole of a very large one buys
# nothing and costs time; these are the limits DETECT_JS used before the rules
# moved here, kept so the two agree.
_HTML_FOR_TYPE = 20000
_HTML_FOR_VENDOR = 50000

# FORM_TYPES compiled once, in the order they are checked.
_TYPES = [(name, {k: re.compile(v, re.I) for k, v in rules.items() if k != "fields"},
           rules.get("fields", []))
          for name, rules in FORM_TYPES]


def form_type(html, near, addr, input_types):
    """What kind of form this is: the first rule in FORM_TYPES that matches.

    `html` is the form's markup, `near` the plain text around it, `addr` the
    page address plus the form's action, `input_types` every input type the
    form contains - including hidden and invisible ones, because a password box
    is a password box whether or not it is on screen yet.

    A `fields` match is hard evidence and ignores the rule's `unless`; wording
    and the address are softer and can be cancelled by it.
    """
    html = _OPTION.sub(" ", html)[:_HTML_FOR_TYPE]
    for name, pats, fields in _TYPES:
        if any(f in input_types for f in fields):
            return name
        text, url, unless = pats.get("text"), pats.get("url"), pats.get("unless")
        soft = (text and (text.search(html) or text.search(near))) or (url and url.search(addr))
        if soft and not (unless and (unless.search(html) or unless.search(near))):
            return name
    return DEFAULT_FORM_TYPE


def vendor(html):
    """The email platform behind the form, from the markup its embed leaves."""
    low = html[:_HTML_FOR_VENDOR].lower()
    for needle, name in VENDOR_HINTS:
        if needle in low:
            return name
    return ""


def rank(cands):
    """Order the candidates by the paper's rules and number them.

    Each rule only breaks ties in the ones before it: highest effective z-index
    first, so a popup beats the footer form under it; then a modal-looking one;
    then anything that is not the form the study is about, last; then more
    fields first.
    """
    cands.sort(key=lambda c: (-c["z_index"], -int(bool(c["modal_hint"])),
                              0 if c["form_type"] == TARGET_FORM_TYPE else 1,
                              -c["n_fields"]))
    for i, cand in enumerate(cands, 1):
        cand["rank_on_page"] = i
    return cands


def annotate(cands, frame_url):
    """Type, vendor and rank every candidate DETECT_JS found in one frame.

    Mutates and returns the list, in rank order. The three fields the rules read
    are dropped afterwards: they are large, and nothing downstream wants them.
    """
    parsed = urlparse(frame_url)
    page = (parsed.hostname or "") + (parsed.path or "")
    for cand in cands:
        html, near = cand.get("form_html", ""), cand.get("near_text", "")
        cand["form_type"] = form_type(
            html, near, page + " " + cand.get("form_action", ""), cand.get("input_types", []))
        cand["vendor"] = vendor(html)
    rank(cands)
    for cand in cands:
        for key in ("form_html", "near_text", "input_types"):
            cand.pop(key, None)
    return cands
