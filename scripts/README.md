# scripts

One-off and helper scripts that are not part of the crawler: data cleanup,
analysis, conversions, doc rendering.

- Run them from the repo root, e.g. `python scripts/<name>.py`.
- To use crawler code (such as `FORM_FIELDS`), add `src/` to `sys.path` at the top
  of the script, as `collect_tier1_keywords.py` does, then
  `from crawler.config import FORM_FIELDS`.
- Same dependency rule as the crawler: Selenium and the standard library only.
- Start each script with a docstring saying what it does and how to run it.

## Scripts

| Script | What it does |
|---|---|
| `collect_tier1_keywords.py` | Loads each listed signup page, finds its form with `DETECT_JS`, and counts the words of the page title, `<h1>`, URL path and the form's heading, button, placeholder and text, marking which ones the `LINK_TIERS` keywords already match. Unmatched terms are candidates for new tier 1 keywords. `--jobs N` runs N browsers in parallel. |
