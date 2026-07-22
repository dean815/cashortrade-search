# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python CLI (`tickets.py`) that searches, filters, sorts, and displays ticket listings from cashortrade.org (a peer-to-peer concert/event ticket exchange). Packaged via `pyproject.toml` (setuptools, single `py_modules` entry) as `cashortrade-search`, but nearly all the logic still lives in `tickets.py` itself.

## Running the tool

```bash
cashortrade-search "https://cashortrade.org/<event-slug>/event/<uuid>" [options]
cashortrade-search "URL1" "URL2" --max-price 200 --sort price
cashortrade-search "URL" --type sale --tickets 2 --section 108 109 --sort price
cashortrade-search "URL" --terminal --sort price-desc
cashortrade-search "URL1" "URL2" --group-by-event
```

Or without installing: `python3 tickets.py "URL" [options]` (same flags, same behavior).

Runtime dependencies are `requests` and `rich`. Install the package with dev tooling via `pip install -e ".[dev]"` (pulls in `pytest`, `ruff`, `mypy`, `types-requests`).

## Development commands

```bash
pytest -q            # test suite (tests/test_tickets.py)
ruff check .         # lint
mypy tickets.py      # type check
```

CI (`.github/workflows/ci.yml`) runs all three against Python 3.11 and 3.13 on every push/PR to `main`. Run them locally before opening a PR — the same commands are what CI checks.

## Architecture

The whole program is one linear pipeline, run per invocation from `run()` (invoked by `main()`, which wraps it to turn `KeyboardInterrupt`/network errors/unexpected exceptions into a clean one-line message and exit code instead of a raw traceback):

1. **URL → event data** (`extract_event_from_url`): given a cashortrade event URL, scrapes the event page HTML to get the event title and the list of `event_product` UIDs (each UID represents one ticket type/date, e.g. "Single Day - Friday"). It tries, in order: a direct `product/{uuid}` in the URL, an embedded `event_products` JSON blob in the page HTML, a regex fallback over the same HTML, then a last-resort search via the `/event/search` API. Handles 429s with exponential backoff.
2. **Fetch listings** (`fetch_all_listings`): paginates the `/event/product/proposal/list` API for a set of `event_product` UIDs, throttled to 1 request/sec, with retry/backoff on 429. When multiple event URLs are passed on the command line, `run()` also sleeps 2s between events.
3. **Parse** (`parse_listing`): flattens one raw API listing into a display-ready dict. Notable business logic here:
   - Price prefers the "Gold" membership tier price, falling back to "Free" tier, falling back to the raw ticket price; `miracle` flow listings are always priced at 0.
   - "Sold" is derived either from every ticket in the listing having a `sold` timestamp, or from `status` being `accepted`/`finalized-success`; `sold_at` is the max of those timestamps.
   - Event title/date/ticket type are looked up from a `product_meta` dict (built in `run()` from the event-extraction step) keyed by `event_product` UID, with a fallback to data embedded in the ticket's own `event`/`event_product` payload.
4. **Filter** (`apply_filters`): type/tickets-count/section/price filters. Each `--section` entry can carry an optional `:MAXROW` suffix (e.g. `222:7`) capping that section's row — non-numeric rows (GA/Floor/Pit-style) always pass the cap.
5. **Sold/active split** (in `run()`, after filtering): controlled by `--show-sold` (adds a sold section) and `--show-only-sold` (hides active entirely). This split is intentionally separate from `apply_filters`.
6. **Sort** (`sort_listings`): active listings sort by the `--sort` flag; sold listings always sort by `sold_at` descending, independent of `--sort`.
7. **Display**: HTML is the default output (`render_html` → written to a temp file in `/tmp` → opened via `webbrowser.open`); `--terminal` switches to a `rich` table (`display_listings`) printed to stdout instead. Both renderers support `--group-by-event`, which partitions listings by `(event_title, ticket_type, event_date)` into separate tables/sections rather than one merged table.

Grouping logic (`_group_key`/`_group_title` in `run()`, and an equivalent local implementation inside `render_html`) is duplicated between the terminal and HTML code paths — when changing how listings are grouped or how group headings are formatted, both places need updating.

## Repo layout notes

- `docs/superpowers/plans/` and `docs/superpowers/specs/` contain historical planning/design docs from prior feature work done via the `superpowers` skill workflow (plan + design spec pair per feature). Useful for understanding *why* a feature was built a certain way, but not necessarily reflecting the latest code — read `tickets.py` itself for current behavior.
