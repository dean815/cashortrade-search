# Multi-Event Search with HTML Output — Design Spec

## Goal

Enhance the CashorTrade ticket search tool to accept multiple event URLs, add event date and ticket type to results, and output an interactive HTML file that opens in the browser by default.

## Current State

- Single-file CLI (`tickets.py`) that takes one CashorTrade URL
- Fetches listings via CashorTrade API, parses, filters, sorts
- Outputs a rich terminal table via the `rich` library
- Filters: `--type`, `--tickets`, `--section`, `--min-price`, `--max-price`, `--sold`
- Sort: `--sort price|price-desc|date|date-asc`

## Changes

### 1. Multi-URL Input

Accept one or more CashorTrade URLs as positional arguments:

```
python tickets.py "URL1" "URL2" "URL3" [options]
```

- `url` arg changes from a single string to `nargs="+"` (one or more)
- Each URL is processed independently (extract event, fetch listings)
- All listings are merged into a single list before filtering/sorting

### 2. New Columns: Event, Date, Ticket Type

Each parsed listing gains three new fields:

- **Event** — the event title (e.g., "Phish at Sphere")
- **Date** — the event date, extracted from the event page or API data
- **Ticket Type** — the product/ticket type (e.g., "3-Day Pass", "Single Day - Friday", "Travel Package"), extracted from the `event_products` data

These fields already exist in the CashorTrade API/HTML responses — they just need to be extracted and carried through to display.

### 3. HTML Output (Default)

Generate a self-contained HTML file and open it in the default browser.

**HTML features:**
- Single HTML file with embedded CSS (no external dependencies)
- Responsive table with all current columns plus Event, Date, Ticket Type
- Sortable columns (click header to sort) via inline JavaScript
- Price cells hyperlinked to the CashorTrade listing (same as current terminal behavior)
- Color-coded listing types (Sale=green, Miracle=cyan, Trade=yellow)
- Sold listings styled as dimmed/strikethrough
- Price summary row at the bottom
- Clean, readable design — light background, alternating row colors

**File handling:**
- Write to a temp file (`/tmp/tickets-{timestamp}.html`)
- Auto-open in default browser via `webbrowser.open()`

### 4. Terminal Output (Optional)

The existing rich table output is preserved behind a `--terminal` flag:

```
python tickets.py "URL1" --terminal
```

When `--terminal` is passed, behavior is identical to current — rich table printed to stdout, no HTML file generated.

### 5. Group-by-Event View

A `--group-by-event` flag renders separate tables per event instead of one merged table:

```
python tickets.py "URL1" "URL2" --group-by-event
```

- In HTML mode: separate `<table>` elements with event title as heading above each
- In terminal mode: separate rich tables with event title printed above each
- Sorting and filtering apply within each group
- Price summary shown per group

### 6. Default Sort

Change default sort from `price` (ascending) to... it's already `price` ascending. No change needed — this is already the behavior.

## What Stays the Same

- All existing filters (`--type`, `--tickets`, `--section`, `--min-price`, `--max-price`, `--sold`)
- All existing sort options (`price`, `price-desc`, `date`, `date-asc`) — note: `date`/`date-asc` sort by **listing creation date**, not event date. To view results organized by event date, use `--group-by-event`.
- API interaction logic (fetch, pagination)
- URL parsing and event extraction logic
- Single-URL usage still works identically (just produces HTML instead of terminal output)

## Architecture

No new files — all changes are within `tickets.py`. The additions are:

1. **Event date/ticket type extraction** — extend `extract_event_from_url()` and `parse_listing()` to carry these fields
2. **HTML renderer** — a new `render_html()` function that takes the same listing data and produces an HTML string
3. **Group-by logic** — a utility that partitions listings by event before passing to the renderer
4. **Arg changes** — `url` becomes `nargs="+"`, add `--terminal` and `--group-by-event` flags

## Out of Scope

- Multi-site support (Ticketmaster, StubHub, etc.) — future phase
- Artist name / date search — future phase
- Persistent saved searches or notifications
- Any backend or server component
