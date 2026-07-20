# CashOrTrade Ticket Search Tool

A command-line tool for searching, filtering, and sorting ticket listings from [cashortrade.org](https://cashortrade.org), a peer-to-peer concert/event ticket exchange. Paste one or more event URLs and get back a sortable, filterable table of listings — either as an interactive HTML page or a table printed to your terminal.

## Features

- Search one or more events at once, with results merged or grouped
- Filter by listing type (sale/trade/miracle), ticket count, section, row, and price
- Sort by price or listing date
- Optionally show sold listings alongside (or instead of) active ones
- Self-contained, sortable HTML output by default — easy to share
- Terminal table output available via `--terminal`

## Installation

The recommended way to install is with [pipx](https://pipx.pypa.io/), which handles an isolated environment for you:

```bash
pipx install git+https://github.com/dean815/cashortrade-search.git
```

Once installed, the `tickets` command is available anywhere.

### Alternative: manual venv

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

This installs the same `tickets` console command, scoped to the venv.

Requires Python 3.9+. Dependencies (`requests`, `rich`) are installed automatically either way.

## Usage

```bash
tickets "https://cashortrade.org/<event-slug>/event/<uuid>"
```

By default this generates an HTML file and opens it in your browser, with active listings sorted by price ascending, showing `sale` and `miracle` type listings.

### Options

| Flag | Description |
|---|---|
| `"URL1" "URL2" ...` | Pass multiple event URLs to merge results together |
| `--type sale trade miracle` | Which listing types to include (default: `sale miracle`) |
| `--tickets 2` or `--tickets 2-4` | Filter by exact ticket count or range |
| `--section 108 109 GA` | Filter by section (partial match, multiple allowed) |
| `--row 1-10` | Filter by row range (GA/floor listings always pass through) |
| `--min-price 50` / `--max-price 200` | Price filters |
| `--sort price\|price-desc\|date\|date-asc` | Sort order (default `price`) |
| `--show-sold` | Add a second "sold" section below active listings |
| `--show-only-sold` | Show only sold listings |
| `--group-by-event` | Separate tables per event/ticket-type/date instead of one merged table |
| `--terminal` | Print a table to the terminal instead of opening HTML |

### Examples

```bash
# Cheapest 2-ticket sale listings in section 108/109, under $200
tickets "URL" --type sale --tickets 2 --section 108 109 --max-price 200 --sort price

# Compare two shows side by side, grouped
tickets "URL1" "URL2" --group-by-event

# Terminal view, most expensive first, including sold
tickets "URL" --terminal --sort price-desc --show-sold
```

## Notes

- `date`/`date-asc` sort by listing creation date, not the event date. To organize by event date, use `--group-by-event`.
- API requests are throttled and retried automatically to respect cashortrade.org's rate limits.
