# How the link and button keywords were extended (2026-10-11)

The crawler's keyword lists come from Englehardt, Han & Narayanan (2018). On
2026-10-11 we extended three of them using words collected from real signup
pages. This document records the data, the analysis, what was added, and what
was considered and rejected, so the change can be reported in the methods
section and repeated later.

## What the keywords do

| List | File | Used for |
|---|---|---|
| `LINK_TIERS`, tier 1 | `src/crawler/config.py` | Link text that makes a link the **first** choice to visit when the landing page has no form |
| `LINK_TIERS`, tier 2 | `src/crawler/config.py` | Link text that makes a link the **second** choice |
| `LINK_TIERS`, tier 3 (new, section 6) | `src/crawler/config.py` | Words in a link's **address** that make it the third choice |
| `SUBMIT_HINT` | `DETECT_PATTERNS["submit"]` in `src/crawler/config.py` (used by `DETECT_JS`) | Words that make a `<div>`, `<span>` or link count as a submit button in bottom-up detection |

Link keywords match **anywhere** in a link's text (case-insensitive), so a
short keyword catches every link that contains it. That is why every candidate
was judged on what *other* links it would also match, not only on how often it
appears on signup forms.

## 1. Data

- **Input:** `inputs/form_urls.txt`, **146 URLs** of pages known to contain an
  email subscription form, from 144 different sites (news sites, shops,
  Substack newsletters, company blogs, …).
- **Collection:** `scripts/collect_tier1_keywords.py`, run with 5 parallel
  browsers (`--jobs 5`). For each URL it loads the page, finds the form with the
  crawler's own `DETECT_JS`, and records the page title, `<h1>`, URL path, and
  the form's heading, button text, email placeholder and surrounding text.
  Nothing is clicked or typed.
- **Result** (`outputs/tier1_keywords/pages.csv`):

  | Status | Pages |
  |---|---|
  | form found (`ok`) | 118 |
  | page loaded, no form detected | 22 |
  | failed to load | 3 |
  | HTTP error | 3 |

  159 forms in total were found on the 118 pages.
- **Analysis input:** the button text and form text columns of `pages.csv`
  were exported to `button_text.txt` (115 lines) and `form_text.txt` (108
  lines), one line per page.

## 2. Analysis

**Button text** → `button_text_unique.csv`. Several buttons on one page are
joined by ` | ` in a line, so lines were split into single buttons (127 in
all), then lowercased, with spacing and leading/trailing symbols removed
(`Sign Up >`, `→ Submit`). That leaves **30 distinct wordings**. The most
common:

| Buttons | Wording | Already matched by |
|---|---|---|
| 62 | subscribe | tier 1 |
| 19 | submit | — |
| 17 | sign up | tier 2 |
| 2 | suscribirse (Spanish) | — |
| 2 | next | — |
| 1 each | send me the next briefing, count me in, inscreva-se (Portuguese), update my subscriptions, save newsletter options, … | mostly — |

**Form text** → `form_text_keywords.csv`. Each line was split into single words
and two-word phrases (filler words such as *the*, *your* dropped; phrases do
not cross sentence breaks), and each term was counted once per form: **3,091
terms**, 363 used by 3 or more forms. Most frequent terms were field labels
(*first name*, *address*, *country*) and legal text (*privacy policy*,
*terms*, *consent*, and Substack's standard footer on 11 forms). Terms that no
tier matched and that describe the newsletter itself included *news* (25
forms), *updates* (15), *weekly* (14), *latest* (14), *daily* (12),
*delivered*, *free*, *offers*, *events* and *stay* (10 each).

## 3. What was added

| List | Change | Evidence | Why it is safe |
|---|---|---|---|
| Tier 1 | `"subscribe"` → `"subscri"` | "update my subscriptions" was not matched: *subscribe* is not contained in *subscription* | Matches subscribe, subscriber, subscription; "unsubscribe" links are still dropped by `LINK_BLACKLIST` before scoring |
| Tier 2 | + `"suscr"` | *suscribirse* on 2 forms | Spanish words starting *suscr* are all about subscribing (*suscríbete*, *suscripción*). The shorter stem is needed: *suscri* misses *suscríbete*, whose *í* is a different letter |
| Tier 2 | + `"inscr"` | *inscreva-se* on 1 form | Portuguese *inscreva-se*, French *s'inscrire*, *inscription* |
| Tier 2 | + `"count me in"`, `"send me"` | 1 form each | Signup phrasing that rarely appears on other links |
| `SUBMIT_HINT` | + `suscr\w*`, `inscr\w*`, `next`, `save` | the button wordings above that the pattern did not yet recognise | Only applies to short clickable elements next to an email box, so *next* and *save* are low risk there |

The button wordings went to **tier 2**, not tier 1, because a button word on a
link (*sign up*, *count me in*) usually leads to a signup or account page,
which is a good guess but less certain than *newsletter* or *subscribe*.

## 4. What was considered and not added

| Candidate | Reason |
|---|---|
| *news*, *free*, *offers*, *events* | Match ordinary menu links (News, Events, Offers, Free trial); the crawler would visit those sections first |
| *daily*, *latest* | Match common news-site links (Daily crossword, Latest stories) |
| *updates*, *weekly*, *stay in the loop* | Low risk, but not chosen in this round; the first to try next |
| *submit*, *next*, *save*, *send*, *get* as link keywords | Match links like "Next page", "Submit a tip", "Save 20%". Kept in `SUBMIT_HINT` only |
| *on*, *thanks*, *post comment*, *services interested* | Not signup buttons (a checkbox value, a thank-you message, a comment form, a contact form) |

## 5. Limits

- The words come from the signup **pages**, while the link keywords are
  matched against the **links** pointing to them. The two usually share words,
  but not always.
- The sample is 146 URLs, mostly English. The non-English additions rest on 1–2
  forms each.
- The change has not yet been measured on a crawl. To measure it, crawl a set
  of sites that is *not* in `form_urls.txt` once with the old keywords and once
  with the new ones, and compare how often a form is found and on which page.

## 6. Signup addresses (also 2026-10-11)

The paper's tiers look for signup words only in a link's **text**. But the
URLs in `form_urls.txt` show that signup pages usually say what they are in
their **address**. Of the 113 URLs with a path (the other 33 are homepages),
the most common path words were *newsletter* (40), *signup* (27), *subscribe*
(24), *newsletters* (20), *sign-up* (8) and *email* (9). A link reading "Stay
informed" that points to `/newsletter`, or an icon with no text, was therefore
dropped.

A new `LINK_TIERS` group now matches the address against `newsletter`,
`subscri`, `signup`, `sign-up` and `mailing-list`. It catches **101 of the 113**
signup URLs with a path. `sign-up` is listed separately because the text
keyword *sign up* has a space. The 12 it misses use words like `/email`,
`/emailupdates`, `/connect` or `/healthbeat`.

| Decision | Reason |
|---|---|
| placed **third**, after the two text groups | words on the link are still the strongest signal; a link known only by its address now ranks above the paper's article and locale groups instead of being dropped |
| *email* left out | it is in contact pages (`/email-us`) and in tracking codes on ordinary links (`?utm_medium=email`) |
| `URL_BLACKLIST = ["unsubscribe"]` added | the new group matches `/unsubscribe` too, and the old blacklist only checked link text |

Tested on a local page whose links were "About", an article, "Next page",
"Manage preferences" → `/unsubscribe` and "Stay informed" → `/newsletter/`: the
crawler visited `/newsletter/` first, found the form, and never requested
`/unsubscribe`.

## 7. Reproducing

```bash
venv/bin/python scripts/collect_tier1_keywords.py inputs/form_urls.txt --jobs 5 --headless
```

This writes `pages.csv` and `keywords.csv` to `outputs/tier1_keywords/`. The
button and form-text analysis in section 2 was done as a one-off and is not yet
a script in `scripts/`.
