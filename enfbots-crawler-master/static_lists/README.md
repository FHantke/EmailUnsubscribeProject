# Site lists

Frozen populations that study samples are drawn from. Files are never overwritten: a newer month gets a new file next to the old one.
Cite the sources with [`CITATION.bib`](CITATION.bib).

| File | Region | Source | Month | Sites |
|---|---|---|---|---|
| `crux_us_202608.csv.xz` | US | CrUX, via the crux-top-lists mirror | 2026-08 | 1,000,000 |
| `crux_global_202608.csv.xz` | Global | CrUX, via the crux-top-lists mirror | 2026-08 | 1,000,000 |
| `static_list_2024_02.csv.xz` | Mostly EU | ETH enfbots-crawler 0.8.11 | early 2024 | 502,612 |

EU sampling is paused (decision of 2026-10-07): the ETH list is kept for reference only, and no EU CrUX month is frozen yet.

## CrUX snapshots (2026-08)

Google's Chrome UX Report (CrUX) ranks the origins Chrome users visit, in popularity buckets rather than exact ranks.
The files come from the [zakird/crux-top-lists](https://github.com/zakird/crux-top-lists) mirror, which caches CrUX's BigQuery data monthly.
CrUX datasets by Google are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (stated on the [CrUX methodology page](https://developer.chrome.com/docs/crux/methodology)).
The mirror has no license file; its README asks for citation of the repository and two papers by Ruth et al., all listed in `CITATION.bib`.

Downloaded 2026-10-07T19:36Z. 2026-08 was the newest month published at that time.

| | `crux_us_202608.csv.xz` | `crux_global_202608.csv.xz` |
|---|---|---|
| Source URL | `https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/country/us/202608.csv.gz` | `https://raw.githubusercontent.com/zakird/crux-top-lists/main/data/global/202608.csv.gz` |
| Original `.gz` SHA-256 | `9e7377a7e0aedc3fdc9a579ccfef006566b172ef2687ac9928f687932c5c1a20` | `4ae541994a7e28f2a9ddd33f711effde9346c4128c506782fa77c268d8f3905b` |
| Decompressed CSV SHA-256 | `df4170be957c089a9e277f83b213c02905830c737bc55e51354f1eca28fc39b8` | `ef50e55a5770efdd1146eb7d5802924d285b52983e98e98535bbdbef239c486d` |
| `.xz` SHA-256 | `7adbff68349b1898135edd5c7e45ab0fd71b41e06041869277722a35e8e4fe86` | `e9c78c20b1595bdbcc11824375e9049cc1dd60a723da0005c51b40910d6f3e74` |

Both files have the header `origin,rank`. `rank` is the bucket's upper bound; per-bucket counts are the same in both files:

| `rank` | 1000 | 5000 | 10000 | 50000 | 100000 | 500000 | 1000000 |
|---|---|---|---|---|---|---|---|
| sites | 1,000 | 4,000 | 5,000 | 40,000 | 50,000 | 400,000 | 500,000 |

How they were made: download the `.gz`, check it with `gzip -t`, decompress, re-compress with `xz -9e`, and confirm the `.xz` decompresses to the same SHA-256 as the original CSV.
Anyone can re-verify a file against the mirror by comparing the decompressed SHA-256.

**Not for `load_database.py --raw` directly**: it expects one URL per line, and these files have a header and a `rank` column. Draw a URL-only `study_*.csv` from them first.

## ETH source list: `static_list_2024_02.csv.xz`

ETH Zurich's fixed list of sites from enfbots-crawler 0.8.11, one URL per line (502,612 unique URLs, mostly European sites).
Its construction is undocumented; every line has the shape of a CrUX origin (`https://host`), which suggests a frozen CrUX sample.
The original also shipped `static_list_2024_01.csv` with the same URLs in a different order, so only `2024_02` is kept.
Order matters: jobs are created in file order.

| | SHA-256 |
|---|---|
| `static_list_2024_02.csv` (decompressed) | `1ec05f5cca932fb7a1abcf66747866306c179d9108174feebfc968982ec9cfae` |
| `static_list_2024_02.csv.xz` | `80a1ed60b0fed87e3a1764caf5f85e2a23fe949c10fd6708d5dd781e590ef53d` |

`load_database.py --raw` reads this `.xz` directly. To get the plain file: `xz -dk static_list_2024_02.csv.xz` (the result is git-ignored).

## Study samples: `study_<name>.csv` + `study_<name>.json`

Every list the study actually crawls is committed here as plain text, one URL per line. The `.json` next to it records how the list was drawn:

```json
{
  "created": "YYYY-MM-DD",
  "sources": [{"file": "crux_us_202608.csv.xz", "sha256": "7adbff68…"}],
  "method": "how sites were drawn, e.g. stratified by rank bucket",
  "seed": 12345,
  "size": 0,
  "filters": []
}
```

Raw `.csv` files other than `study_*` are ignored by git.
