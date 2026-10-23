# What `--submit` does, step by step

Companion to [crawl-flow.md](crawl-flow.md), which covers detection. This is the
other phase: signing up to the forms a crawl already found, so the study can
follow what happens afterwards — the confirmation flow, double opt-in, the
welcome email, and whether the address is later leaked or sold.

All of it lives in [`src/crawler/submit.py`](../src/crawler/submit.py), the only
module in the project that types into a page or clicks anything. A crawl never
reaches it.

```bash
python src/find_forms.py inputs/sites.txt --out outputs/run6          # 1. crawl
python src/find_forms.py --submit --out outputs/run6 \                # 2. rehearse
    --submit-email 'study+{site}@gmail.com' --submit-dry-run
python src/find_forms.py --submit --out outputs/run6 \                # 3. sign up
    --submit-email 'study+{site}@gmail.com' --submit-limit 5
```

## Why it is a separate phase

`--submit` takes no sites argument. It reads the `forms` table for the run named
by `--out` and works from that. Three things follow:

- A crawl is detection-only in the strongest sense: the submitting code is not on
  its path at all, so no change to detection can make a crawl submit by accident.
- The forms can be reviewed against their screenshots **before** anything real is
  sent. The 2026-10-23 audit found 4 of 81 forms given the wrong type; signing up
  to a misclassified login form would create a real account.
- Submission can be re-run, paced and limited independently of crawling.

## 1. Choosing the targets

`submission_targets()` in [output.py](../src/crawler/output.py) returns, per site,
the lowest-`rank_on_page` form whose `form_type` is `subscription` — one per site,
because a site is signed up to at most once.

`Output.submitted_sites()` then drops every site that already has a submission row
with outcome `submitted` or `submitting`, **in any run**. Only outcomes that
reached the click count, so a site whose form could not be found last time is
still open to a later attempt. `--submit-again` ignores the guard; `--submit-limit
N` caps what is left.

## 2. Finding the form again

Each site gets its own Chrome, as in a crawl. `_find_target()` reopens the form's
`page_url` and then replays the same four stimuli `scan_page()` uses, in the same
order, because a delayed popup or an exit-intent bar needs the same prompting the
second time:

| Phase | Stimulus |
|---|---|
| `on_load` | nothing; the page has settled (`LOAD_SETTLE_MS`, `PAINT_SETTLE_MS`) |
| `after_delay` | sleep `--popup-wait` |
| `after_scroll` | `SCROLL_JS` |
| `after_exit_intent` | `simulate_exit_intent()` |

After each, `_look()` runs `DETECT_JS` in the document and recursively in every
frame, and compares each candidate's `form_signature()` against the stored
`form_sig`. The form is identified by exactly the hash detection used, so "the
same form" means the same thing in both phases. The first match wins and **the
driver is left standing in that form's frame**, which is where it has to be to
fill it. No match after all four phases → outcome `not_found`.

`DETECT_JS` is called with `with_elements=True`, which is the one thing detection
does not use: it makes the script return the form, the email box, the fields and
the submit button as real WebElements. That avoids a second, drifting copy of
`isSubmitLike()` in Python, and it reaches forms inside shadow DOM, which a
`[data-ux-form-id]` lookup cannot.

## 3. Filling it in

`_fill()`:

1. The email box gets the address from `--submit-email`, with `{site}` replaced by
   the site's hostname — per-site aliases, so a later leak or sale is traceable to
   the site that received the address. No email box → outcome `no_email_field`.
2. Every other field is touched **only if the form marks it required** (`required`
   or `aria-required`) and it is empty. The value comes from `SUBMIT_FILL` in
   [config.py](../src/crawler/config.py) — the first pattern matching the field's
   name, id, placeholder or label — falling back to `SUBMIT_FILL_DEFAULT`. A
   required `<select>` takes its first non-empty option.
3. Checkboxes: only **unchecked required** ones are ticked.

Optional fields and the default state of consent boxes are left exactly as the
site set them, because they are themselves what the study measures: a column like
`n_checkboxes_prechecked` is meaningless if the crawler goes around ticking things.

`_describe()` reads every field's name, type, required flag, label and current
value in a single `FIELD_INFO_JS` call rather than one attribute read per field.

## 4. Capturing the filled form — before the click

This is the record of precisely what was sent: `<sig>_filled.png` (the form),
`<sig>_filled_context.png` (the whole window) and `<sig>_filled.html`, written
next to the crawl's own shots under `--out`. It reuses `capture()`, which gained a
`suffix` so the detection screenshots are not overwritten and an `el` so the
element already in hand is used instead of a fresh lookup.

`_freeze()` runs first. Typing sets a field's value *property*, while `outerHTML`
serializes its *attributes*, so without this the saved HTML would be a blank form.
It copies `value` → `value=""`, and `checked`/`selected` likewise. It changes
nothing about what is submitted, which reads the properties.

Under `--submit-dry-run` the run stops here, outcome `filled_only`. That is the
rehearsal: everything filled in and photographed, nothing sent.

## 5. Submitting, and what comes back

The `submissions` row is written **before** the click, with outcome `submitting`.
`SiteWatchdog` can SIGKILL Chromium at any moment, and a real subscription must
never go unrecorded. An error later updates that row rather than replacing it, so
what was filled in survives the failure.

`_click()` scrolls the submit button into view and clicks it, falling back to the
page's own `.click()` when something covers it — a consent box behind a styled
label, a button under a cookie banner. It never calls `form.submit()`: a real
click is what the page's own JavaScript listens for.

After `SUBMIT_SETTLE_MS`, `_result()` captures `<sig>_after.*` and reads the final
URL, the HTTP status, the first heading and the first 600 characters of the page.
If the form navigated away, its element is stale and only the context screenshot
survives — which is the thank-you page, the thing worth having. Outcome
`submitted`.

## 6. Pacing

`--submit-delay` (default `SUBMIT_DELAY_S`, 30s) between sites, ten times
`--page-delay`, because a submission is a write. `--submit` refuses `--jobs > 1`:
one writer and one pace, since N shards each enforcing a local limit would give
N times the limit. Ctrl-C stops at the next site, as in a crawl.

## Outcomes

| Outcome | Meaning |
|---|---|
| `submitted` | Clicked, and the result recorded |
| `filled_only` | `--submit-dry-run`: filled and photographed, never clicked |
| `not_found` | The form did not reappear in any phase or frame |
| `no_email_field` | Found, but with nowhere to put the address |
| `no_submit_button` | Found and filled, but nothing submit-like in it |
| `click_failed` | Neither a real click nor a scripted one worked |
| `submitting` | Killed between the click and the result; something may have been sent |
| `site_timeout` | Over `--site-time-limit`; the browser was killed |
| `error` | Anything else; the message is in the `error` column |

A site skipped because it was already submitted to gets no row at all — it is
reported in the log instead.

## Ethics

Submitting creates real subscriptions, and sometimes real accounts, on real sites,
which detection-only crawling does not. **Ethics/IRB sign-off is an open question**
as of 2026-10-23; see CLAUDE.md. Until it is settled, prefer `--submit-dry-run`,
and use `--submit-limit` on anything live.
