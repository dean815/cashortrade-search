#!/usr/bin/env python3
"""
CashorTrade Search Tool - Search, filter, and sort ticket listings from cashortrade.org

Usage:
    python tickets.py "URL1" ["URL2" ...] [options]

Examples:
    python tickets.py "https://cashortrade.org/phish-at-sphere-tickets/event/3d4f8df0-..."
    python tickets.py "URL1" "URL2" --max-price 200 --sort price
    python tickets.py "URL" --type sale --tickets 2 --section 108 109 --sort price
    python tickets.py "URL" --terminal --sort price-desc
    python tickets.py "URL1" "URL2" --group-by-event
"""

import argparse
import json
import re
import sys
import tempfile
import webbrowser
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as _package_version

import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text

try:
    __version__ = _package_version("cashortrade-search")
except PackageNotFoundError:
    # Running from a raw checkout without an editable/installed package.
    __version__ = "0.0.0+unknown"

API_BASE = "https://api-ng.cashortrade.org/frontend"
SITE_BASE = "https://cashortrade.org"
console = Console()

DEFAULT_TYPES = ["sale", "miracle"]


# ---------------------------------------------------------------------------
# Event / product extraction from URL
# ---------------------------------------------------------------------------

def search_events(query: str, limit: int = 50) -> list[dict]:
    """Search for events by artist/venue name."""
    resp = requests.get(f"{API_BASE}/event/search", params={"q": query, "limit": str(limit)})
    resp.raise_for_status()
    return resp.json().get("results", [])


def extract_event_from_url(url_or_path: str) -> tuple[str, list[dict], str]:
    """Extract event title, event_product list, and canonical page URL from a cashortrade URL.

    Returns (event_title, event_products, page_url).
    """
    path = url_or_path.strip().rstrip("/")
    if path.startswith("http"):
        path = re.sub(r"https?://[^/]+/", "", path)

    event_match = re.search(r"event/([0-9a-f-]{36})", path)
    product_match = re.search(r"product/([0-9a-f-]{36})", path)

    if not event_match:
        console.print("[red]Could not find event ID in the URL.[/red]")
        console.print("[yellow]Expected: .../event/{uuid} or .../event/{uuid}/product/{uuid}[/yellow]")
        sys.exit(1)

    product_id = product_match.group(1) if product_match else None

    # Strip query params for the canonical page URL
    clean_path = path.split("?")[0]
    page_url = f"{SITE_BASE}/{clean_path}"

    import time
    console.print(f"  Fetching: [dim]{page_url}[/dim]")
    for attempt in range(5):
        resp = requests.get(page_url, headers={"Accept": "text/html"}, timeout=15)
        if resp.status_code == 429:
            wait = 2 ** attempt
            console.print(f"  Rate limited, waiting {wait}s...", style="yellow")
            time.sleep(wait)
            continue
        break
    resp.raise_for_status()
    html = resp.text

    # Extract event title from <title> tag
    title_match = re.search(r"<title>([^<]+)</title>", html)
    event_title = "Unknown Event"
    if title_match:
        raw_title = title_match.group(1)
        event_title = raw_title.split(" | ")[0].split(" Tickets")[0].strip()
        # Strip "For Sale: " / "For Trade: " / "For Miracle: " prefixes
        event_title = re.sub(r"^For (?:Sale|Trade|Miracle):\s*", "", event_title, flags=re.IGNORECASE)

    # If product_id in URL, use it directly
    if product_id:
        return event_title, [{"uid": product_id}], page_url

    # Extract event_products from embedded JSON (may be escaped with \")
    html_unescaped = html.replace('\\"', '"')
    products_match = re.search(
        r'"event_products"\s*:\s*(\[.*?\])\s*,\s*"(?:ticket_drop|sold)',
        html_unescaped,
        re.DOTALL,
    )
    if products_match:
        try:
            products = json.loads(products_match.group(1))
            if products:
                return event_title, products, page_url
        except json.JSONDecodeError:
            pass

    # Fallback regex
    product_uids = re.findall(r'event_products.*?uid[\\]*":\s*[\\]*"([0-9a-f-]{36})', html)
    if product_uids:
        return event_title, [{"uid": uid} for uid in set(product_uids)], page_url

    # Last resort: search API using slug
    event_id = event_match.group(1)
    slug = path.split("/event/")[0]
    search_terms = re.sub(r"\b(at|the|in|of|and|a)\b", "",
                          slug.replace("-tickets", "").replace("-", " "),
                          flags=re.IGNORECASE).strip()
    search_terms = re.sub(r"\s+", " ", search_terms)

    console.print(f"  Searching API for: [dim]{search_terms}[/dim]")
    for e in search_events(search_terms):
        if e.get("uid") == event_id and e.get("event_products"):
            return e["title"], e["event_products"], page_url
    for e in search_events(search_terms):
        if e.get("event_products"):
            return e["title"], e["event_products"], page_url

    console.print("[red]Could not find event product data.[/red]")
    sys.exit(1)


# ---------------------------------------------------------------------------
# API fetching
# ---------------------------------------------------------------------------

def fetch_all_listings(event_product_uids: list[str]) -> list[dict]:
    """Fetch all ticket listings for given event_product UIDs."""
    import time
    all_results = []
    offset = 1
    page_size = 50
    session = requests.Session()
    request_count = 0

    while True:
        parts = [f"event_product[]={uid}" for uid in event_product_uids]
        parts += ["include_sold=true", f"limit={page_size}", f"offset={offset}"]
        parts += [f"flow[]={f}" for f in ("sale", "trade", "miracle")]

        url = f"{API_BASE}/event/product/proposal/list?{'&'.join(parts)}"
        req = requests.Request("GET", url)
        prepared = req.prepare()
        prepared.url = url  # prevent re-encoding of []

        # Throttle: 1 request per second
        if request_count > 0:
            time.sleep(1)

        for attempt in range(5):
            resp = session.send(prepared)
            if resp.status_code == 429:
                wait = min(5 * (attempt + 1), 30)
                console.print(f"  Rate limited, retrying in {wait}s...", style="yellow")
                time.sleep(wait)
                continue
            break
        request_count += 1

        if resp.status_code != 200:
            console.print(f"[red]API error {resp.status_code}: {resp.text}[/red]")
            resp.raise_for_status()

        data = resp.json()
        results = data.get("results", [])
        total = data.get("total", 0)

        if not results:
            break

        all_results.extend(results)
        console.print(f"  Fetched {len(all_results)}/{total} listings...", style="dim", end="\r")

        if len(all_results) >= total:
            break
        offset += page_size

    console.print(f"  Fetched {len(all_results)} total listings.   ", style="dim")
    return all_results


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_listing(raw: dict, page_url: str, product_meta: dict) -> dict:
    """Parse a raw API listing into a flat dict for display/filter/sort."""
    tickets = raw.get("tickets", [])

    # Section
    section = ""
    row = ""
    ga_section = None
    if tickets:
        section = tickets[0].get("section", "") or ""
        row = tickets[0].get("row", "") or ""
        ga_section = tickets[0].get("ga_section")

    if ga_section:
        ga_name = ga_section.get("name", str(ga_section)) if isinstance(ga_section, dict) else str(ga_section)
        display_section = f"GA - {ga_name.title()}"
    elif section:
        display_section = f"Section {section}" if section.isdigit() else section
    else:
        display_section = "Unknown"

    # Seats — collect from ALL tickets
    seats = [t.get("seat", "") or "" for t in tickets]
    seats_str = ", ".join(s for s in seats if s)

    # Number of tickets
    num_tickets = len(tickets)

    # Sold status. `ticket.sold` is either falsy or a timestamp string
    # (e.g. "2026-04-21 01:21:21") — we use the latest such timestamp as
    # the listing's sold-at time.
    sold_timestamps = [t.get("sold") for t in tickets if isinstance(t.get("sold"), str) and t.get("sold")]
    all_sold = bool(tickets) and len(sold_timestamps) == len(tickets)
    status = raw.get("status", "")
    is_sold = all_sold or status in ("accepted", "finalized-success")
    sold_at = max(sold_timestamps) if sold_timestamps else ""

    # Price (Gold membership price preferred, then Free tier)
    prices_by_membership = raw.get("prices_by_membership", [])
    gold_price = None
    free_price = None
    for p in prices_by_membership:
        if "Gold" in p.get("name", ""):
            gold_price = p.get("price")
        elif p.get("name") == "Free":
            free_price = p.get("price")
    price = gold_price or free_price or (tickets[0].get("price") if tickets else None)

    # Miracle tickets are always free
    if raw.get("flow") == "miracle":
        price = 0

    # Description — strip HTML
    desc = (raw.get("description", "") or "")
    desc = re.sub(r"<[^>]+>", " ", desc).strip()
    desc = re.sub(r"\s+", " ", desc)

    # Link
    link = f"{page_url}?proposal_drawer_uid={raw.get('uid', '')}"

    # Event metadata — look up from product_meta via ticket's event_product uid
    event_product_uid = ""
    ep = {}
    if tickets and tickets[0].get("event_product"):
        ep = tickets[0]["event_product"]
        event_product_uid = ep.get("uid", "")
    meta = product_meta.get(event_product_uid, {})

    # Build event_title: prefer product_meta, fall back to listing's embedded event data
    event_title = meta.get("event_title", "")
    if not event_title and tickets and tickets[0].get("event"):
        ev = tickets[0]["event"]
        # event.title is sometimes a list like ['Phish at Sphere']
        ev_title = ev.get("title", "")
        if isinstance(ev_title, list):
            ev_title = ev_title[0] if ev_title else ""
        # Strip "For Sale: " / "For Trade: " / "For Miracle: " prefixes
        ev_title = re.sub(r"^(?:For (?:Sale|Trade|Miracle):\s*)", "", ev_title, flags=re.IGNORECASE)
        event_title = ev_title

    # Build event_date and ticket_type: prefer product_meta, fall back to embedded event_product
    event_date = meta.get("event_date", "") or ep.get("start", "")
    ticket_type = meta.get("ticket_type", "") or ep.get("title", "")

    return {
        "event_title": event_title,
        "event_date": event_date,
        "ticket_type": ticket_type,
        "flow": raw.get("flow", ""),
        "num_tickets": num_tickets,
        "price": price,
        "section": display_section,
        "section_raw": section,
        "row": row,
        "seats": seats_str,
        "description": desc,
        "link": link,
        "created": raw.get("created", ""),
        "is_sold": is_sold,
        "sold_at": sold_at,
        "uid": raw.get("uid", ""),
    }


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def parse_tickets_arg(value: str) -> tuple[int, int]:
    """Parse --tickets value: '2' -> (2,2), '2-4' -> (2,4)."""
    if "-" in value:
        parts = value.split("-", 1)
        return int(parts[0]), int(parts[1])
    n = int(value)
    return n, n


def apply_filters(listings: list[dict], args) -> list[dict]:
    """Apply user-specified filters (excluding sold/active split — that's done in main)."""
    filtered = listings

    # Type filter
    if args.type:
        types = set(args.type)
        filtered = [l for l in filtered if l["flow"] in types]

    # Tickets filter
    if args.tickets:
        lo, hi = parse_tickets_arg(args.tickets)
        filtered = [l for l in filtered if lo <= l["num_tickets"] <= hi]

    # Section filter (multiple sections, partial match)
    if args.section:
        patterns = [s.lower() for s in args.section]
        filtered = [
            l for l in filtered
            if any(p in l["section"].lower() or p in l["section_raw"].lower() for p in patterns)
        ]

    # Row filter (range, e.g. --row 1-10). Listings without a numeric row
    # (GA / Floor / Pit / etc.) are always included — the filter only applies
    # to seated sections.
    if args.row:
        lo, hi = parse_tickets_arg(args.row)  # reuse: "5" -> (5,5), "1-10" -> (1,10)
        filtered = [
            l for l in filtered
            if not l["row"].isdigit() or lo <= int(l["row"]) <= hi
        ]

    # Price filters
    if args.min_price is not None:
        filtered = [l for l in filtered if l["price"] is not None and l["price"] >= args.min_price]
    if args.max_price is not None:
        filtered = [l for l in filtered if l["price"] is not None and l["price"] <= args.max_price]

    return filtered


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def sort_listings(listings: list[dict], sort_key: str) -> list[dict]:
    """Sort listings. Keys: price, price-desc, date, date-asc."""
    if sort_key == "price":
        return sorted(listings, key=lambda l: l["price"] if l["price"] is not None else float("inf"))
    elif sort_key == "price-desc":
        return sorted(listings, key=lambda l: l["price"] if l["price"] is not None else float("-inf"), reverse=True)
    elif sort_key == "date":
        return sorted(listings, key=lambda l: l["created"], reverse=True)  # newest first
    elif sort_key == "date-asc":
        return sorted(listings, key=lambda l: l["created"])
    else:
        console.print(f"[red]Unknown sort: {sort_key}. Options: price, price-desc, date, date-asc[/red]")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def format_listed(created: str) -> str:
    """Format a created timestamp for display in local time."""
    if not created:
        return ""
    try:
        from zoneinfo import ZoneInfo
        # API returns UTC timestamps
        dt_utc = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
        dt_local = dt_utc.astimezone()
        hour = str(int(dt_local.strftime("%I")))
        return f"{dt_local.strftime('%m/%d')} {hour}:{dt_local.strftime('%M%p').lower()}"
    except (ValueError, TypeError):
        return created[:10]


def display_listings(listings: list[dict], event_title: str, show_sold_col: bool = False):
    """Display listings in a rich table. Pass show_sold_col=True for the
    sold-only view (adds a 'Sold' column with the time-sold timestamp)."""
    import shutil
    term_width = shutil.get_terminal_size().columns
    table_width = max(term_width, 160)

    # Check if we need event-level columns (multiple events in one table)
    multi_event = len(set(l["event_title"] for l in listings)) > 1

    table = Table(
        title=f"{event_title}  ({len(listings)} listings)",
        show_lines=True,
        pad_edge=True,
        width=table_width,
    )

    if multi_event:
        table.add_column("Event", width=25, no_wrap=True, overflow="ellipsis")
    table.add_column("Date", width=10, no_wrap=True)
    table.add_column("Type", width=15, no_wrap=True, overflow="ellipsis")
    table.add_column("Listed", width=14, no_wrap=True)
    if show_sold_col:
        table.add_column("Sold", width=14, no_wrap=True)
    table.add_column("Qty", width=3, justify="center", no_wrap=True)
    table.add_column("Price", justify="right", width=9, no_wrap=True)
    table.add_column("Section", width=12, no_wrap=True)
    table.add_column("Row", width=3, no_wrap=True)
    table.add_column("Seats", width=12, no_wrap=True, overflow="ellipsis")
    table.add_column("Description", ratio=1, overflow="fold")

    for l in listings:
        price_str = f"${l['price']:.2f}" if l["price"] is not None else "N/A"
        price_text = Text(price_str)
        if l["link"]:
            price_text.stylize(f"link {l['link']}")

        listed_str = format_listed(l["created"])
        sold_str = format_listed(l.get("sold_at", "")) if show_sold_col else ""
        row_style = "dim" if l["is_sold"] and not show_sold_col else ""
        desc = l["description"]
        if l["is_sold"] and not show_sold_col:
            desc = f"[SOLD] {desc}"

        # Format event date
        event_date_str = ""
        if l["event_date"]:
            try:
                dt = datetime.strptime(l["event_date"], "%Y-%m-%d %H:%M:%S")
                event_date_str = dt.strftime("%m/%d/%Y")
            except (ValueError, TypeError):
                event_date_str = l["event_date"][:10]

        row_cells = []
        if multi_event:
            row_cells.append(l["event_title"])
        row_cells.extend([
            event_date_str,
            l["ticket_type"],
            listed_str,
        ])
        if show_sold_col:
            row_cells.append(sold_str)
        row_cells.extend([
            str(l["num_tickets"]),
            price_text,
            l["section"],
            l["row"] or "-",
            l["seats"] or "-",
            desc,
        ])

        table.add_row(*row_cells, style=row_style)

    console.print(table)


def render_html(active: list[dict], sold: list[dict], title: str, group_by_event: bool = False) -> str:
    """Render active + sold listings as a self-contained HTML string.

    Active listings are rendered in the primary table; sold listings are
    rendered in a second table below with an extra 'Sold' column. When
    `group_by_event` is True, both tables are emitted per group."""

    # Check if multiple events present (look at combined set so the Event
    # column appears consistently across both tables)
    multi_event = len(set(l["event_title"] for l in (active + sold))) > 1

    def format_event_date(date_str):
        if not date_str:
            return ""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%m/%d/%Y")
        except (ValueError, TypeError):
            return date_str[:10]

    def format_listed_html(created):
        if not created:
            return ""
        try:
            from zoneinfo import ZoneInfo
            dt_utc = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
            dt_local = dt_utc.astimezone()
            hour = str(int(dt_local.strftime("%I")))
            return f"{dt_local.strftime('%m/%d')} {hour}:{dt_local.strftime('%M%p').lower()}"
        except (ValueError, TypeError):
            return created[:10]

    def render_table(rows, table_title, show_event_col, show_sold_col=False):
        """Render one <table> block. When show_sold_col=True, adds a
        'Sold' column (time sold) — used for the sold-listings view."""
        headers = []
        if show_event_col:
            headers.append("Event")
        headers.extend(["Date", "Ticket Type", "Listed"])
        if show_sold_col:
            headers.append("Sold")
        headers.extend(["Qty", "Price", "Section", "Row", "Seats", "Description"])

        header_html = "".join(f'<th onclick="sortTable(this)">{h}</th>' for h in headers)

        row_htmls = []
        for i, l in enumerate(rows):
            zebra = " even" if i % 2 == 0 else " odd"
            # In the sold table don't apply the 'sold' row styling (line-through
            # / faded) — every row is sold, so it's just noise.
            sold_cls = " sold" if l["is_sold"] and not show_sold_col else ""
            cls = f'class="{zebra.strip()}{sold_cls}"'

            price_str = f"${l['price']:.2f}" if l["price"] is not None else "N/A"
            if l["link"]:
                price_cell = f'<a href="{l["link"]}">{price_str}</a>'
            else:
                price_cell = price_str

            desc = l["description"]
            if l["is_sold"] and not show_sold_col:
                desc = f"[SOLD] {desc}"

            cells = []
            if show_event_col:
                cells.append(f"<td>{l['event_title']}</td>")
            cells.extend([
                f"<td>{format_event_date(l['event_date'])}</td>",
                f"<td>{l['ticket_type']}</td>",
                f"<td>{format_listed_html(l['created'])}</td>",
            ])
            if show_sold_col:
                cells.append(f"<td>{format_listed_html(l.get('sold_at', ''))}</td>")
            cells.extend([
                f'<td style="text-align:center">{l["num_tickets"]}</td>',
                f'<td style="text-align:right;font-weight:600">{price_cell}</td>',
                f"<td>{l['section']}</td>",
                f"<td>{l['row'] or '-'}</td>",
                f"<td>{l['seats'] or '-'}</td>",
                f"<td>{desc}</td>",
            ])

            row_htmls.append(f"<tr {cls}>{''.join(cells)}</tr>")

        # Price summary — for active tables use non-sold listings; for the
        # sold view summarize the sold prices so the user can see what things
        # actually cleared at.
        if show_sold_col:
            prices = [l["price"] for l in rows if l["price"] is not None]
        else:
            prices = [l["price"] for l in rows if l["price"] is not None and not l["is_sold"]]
        summary_html = ""
        if prices:
            summary_html = (
                f'<div class="price-summary">'
                f'<strong>Price summary:</strong> '
                f'Min: ${min(prices):.2f} &nbsp;|&nbsp; '
                f'Max: ${max(prices):.2f} &nbsp;|&nbsp; '
                f'Avg: ${sum(prices)/len(prices):.2f} &nbsp;|&nbsp; '
                f'Median: ${sorted(prices)[len(prices)//2]:.2f}'
                f'</div>'
            )

        return f"""
        <div class="table-section">
            <h2>{table_title} ({len(rows)} listings)</h2>
            <table>
                <thead><tr>{header_html}</tr></thead>
                <tbody>{"".join(row_htmls)}</tbody>
            </table>
            {summary_html}
        </div>
        """

    def _key(l):
        return (
            l["event_title"] or "Unknown Event",
            l["ticket_type"] or "",
            l["event_date"] or "",
        )

    def group_title(key):
        event_title, ticket_type, event_date = key
        parts = [event_title]
        if ticket_type:
            parts.append(ticket_type)
        if event_date:
            parts.append(format_event_date(event_date))
        return " — ".join(parts)

    # Build table sections
    sections = []
    if group_by_event:
        from collections import OrderedDict
        # Preserve order of first appearance across active+sold
        key_order = OrderedDict()  # type: ignore[var-annotated]
        active_groups = {}  # type: ignore[var-annotated]
        sold_groups = {}  # type: ignore[var-annotated]
        for l in active:
            k = _key(l)
            key_order.setdefault(k, None)
            active_groups.setdefault(k, []).append(l)
        for l in sold:
            k = _key(l)
            key_order.setdefault(k, None)
            sold_groups.setdefault(k, []).append(l)

        for k in key_order:
            heading = group_title(k)
            if active_groups.get(k):
                sections.append(render_table(active_groups[k], heading, show_event_col=False))
            if sold_groups.get(k):
                sections.append(render_table(
                    sold_groups[k],
                    f"{heading} — Sold",
                    show_event_col=False,
                    show_sold_col=True,
                ))
    else:
        if active:
            sections.append(render_table(active, title, show_event_col=multi_event))
        if sold:
            sections.append(render_table(
                sold,
                f"{title} — Sold",
                show_event_col=multi_event,
                show_sold_col=True,
            ))

    tables_html = "".join(sections)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: #f8f9fa; color: #333; padding: 20px; }}
    h1 {{ font-size: 1.5rem; margin-bottom: 16px; color: #1a1a1a; }}
    h2 {{ font-size: 1.2rem; margin-bottom: 8px; color: #1a1a1a; }}
    .table-section {{ margin-bottom: 32px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff;
             box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 0.85rem; }}
    th {{ background: #1a1a1a; color: #fff; padding: 10px 12px; text-align: left;
          cursor: pointer; user-select: none; white-space: nowrap; }}
    th:hover {{ background: #333; }}
    th::after {{ content: " \\2195"; opacity: 0.4; font-size: 0.75em; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #e9ecef; vertical-align: top; }}
    tr.even {{ background: #fff; }}
    tr.odd {{ background: #f8f9fa; }}
    tr:hover {{ background: #e9ecef; }}
    tr.sold {{ opacity: 0.5; }}
    tr.sold td {{ text-decoration: line-through; }}
    a {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .price-summary {{ margin-top: 12px; padding: 10px 14px; background: #e9ecef;
                      border-radius: 6px; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
{tables_html}
<script>
function sortTable(th) {{
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const idx = Array.from(th.parentNode.children).indexOf(th);
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
    th.parentNode.querySelectorAll('th').forEach(h => delete h.dataset.dir);
    th.dataset.dir = dir;

    rows.sort((a, b) => {{
        let av = a.children[idx].textContent.trim();
        let bv = b.children[idx].textContent.trim();
        // Try numeric sort (strip $ and commas)
        const an = parseFloat(av.replace(/[$,]/g, ''));
        const bn = parseFloat(bv.replace(/[$,]/g, ''));
        if (!isNaN(an) && !isNaN(bn)) {{
            return dir === 'asc' ? an - bn : bn - an;
        }}
        return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    }});

    // Re-apply zebra striping
    rows.forEach((row, i) => {{
        row.classList.remove('even', 'odd');
        row.classList.add(i % 2 === 0 ? 'even' : 'odd');
        tbody.appendChild(row);
    }});
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    parser = argparse.ArgumentParser(
        description="CashorTrade Search Tool — paste a URL, get sortable/filterable listings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "URL"
  %(prog)s "URL1" "URL2" --max-price 200 --sort price
  %(prog)s "URL" --section 108 109 110 --type sale miracle
  %(prog)s "URL" --tickets 2-4 --sort date
  %(prog)s "URL1" "URL2" --group-by-event
  %(prog)s "URL" --terminal --sold --sort price-desc
        """,
    )

    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    parser.add_argument("urls", nargs="+", help="One or more CashorTrade event URLs")
    parser.add_argument("--type", nargs="+", choices=["sale", "trade", "miracle"],
                        default=DEFAULT_TYPES,
                        help="Listing types to show (default: sale miracle)")
    parser.add_argument("--tickets",
                        help="Number of tickets: exact (e.g. 2) or range (e.g. 2-4)")
    parser.add_argument("--section", nargs="+",
                        help="Filter by section(s), partial match (e.g. 108 109 GA)")
    parser.add_argument("--row",
                        help="Filter by row: exact (e.g. 5) or range (e.g. 1-10)")
    parser.add_argument("--min-price", type=float, help="Minimum price per ticket")
    parser.add_argument("--max-price", type=float, help="Maximum price per ticket")
    parser.add_argument("--show-sold", "--sold", dest="show_sold", action="store_true",
                        help="Also show a separate section with sold listings "
                             "(includes a 'Sold' column with time sold)")
    parser.add_argument("--show-only-sold", dest="show_only_sold", action="store_true",
                        help="Show ONLY sold listings (hides the active section)")
    parser.add_argument("--sort", choices=["price", "price-desc", "date", "date-asc"],
                        default="price",
                        help="Sort order (default: price ascending)")
    parser.add_argument("--terminal", action="store_true",
                        help="Output to terminal instead of HTML (default: HTML)")
    parser.add_argument("--group-by-event", action="store_true",
                        help="Show separate tables per event instead of one merged table")

    args = parser.parse_args()

    # Validate tickets arg
    if args.tickets:
        try:
            parse_tickets_arg(args.tickets)
        except ValueError:
            parser.error("--tickets must be a number (e.g. 2) or range (e.g. 2-4)")

    import time
    all_parsed = []

    for i, url in enumerate(args.urls):
        if i > 0:
            time.sleep(2)  # pace requests between events
        console.print(f"Loading event from: [dim]{url}[/dim]")
        event_title, products, page_url = extract_event_from_url(url)
        product_uids = [p["uid"] for p in products]
        console.print(f"  Event: [bold green]{event_title}[/bold green]")

        # Build product metadata lookup
        product_meta = {}
        for p in products:
            uid = p["uid"]
            product_meta[uid] = {
                "event_title": event_title,
                "event_date": p.get("start", ""),
                "ticket_type": p.get("title", ""),
            }

        console.print("  Fetching listings...")
        raw_listings = fetch_all_listings(product_uids)
        parsed = [parse_listing(r, page_url, product_meta) for r in raw_listings]
        all_parsed.extend(parsed)

    # Filter (does NOT include the sold/active split — that happens below)
    filtered = apply_filters(all_parsed, args)

    # Sold section visibility is controlled by the flags:
    #   (neither)          -> active only (default, pre-refactor behavior)
    #   --show-sold        -> active + sold
    #   --show-only-sold   -> sold only (hides active)
    show_sold = args.show_sold or args.show_only_sold
    show_active = not args.show_only_sold

    active = [l for l in filtered if not l["is_sold"]] if show_active else []
    sold = [l for l in filtered if l["is_sold"]] if show_sold else []

    # Sort: active by user's --sort; sold by time-sold (most recent first)
    active = sort_listings(active, args.sort)
    sold = sorted(sold, key=lambda l: l.get("sold_at", ""), reverse=True)

    # Display summary
    if show_sold and show_active:
        console.print(
            f"\n[bold]{len(active)}[/bold] active  +  "
            f"[bold]{len(sold)}[/bold] sold"
            f"  (from {len(all_parsed)} total)\n"
        )
    elif show_sold:
        console.print(
            f"\n[bold]{len(sold)}[/bold] sold listings"
            f" (from {len(all_parsed)} total)\n"
        )
    else:
        console.print(
            f"\n[bold]{len(active)}[/bold] listings"
            f" (from {len(all_parsed)} total)\n"
        )

    if not active and not sold:
        console.print("[yellow]No listings match your filters.[/yellow]")
        return

    # ---- grouping helpers shared by terminal + HTML paths -----------------
    def _group_key(l):
        return (
            l["event_title"] or "Unknown Event",
            l["ticket_type"] or "",
            l["event_date"] or "",
        )

    def _group_title(key):
        event_title, ticket_type, event_date = key
        parts = [event_title]
        if ticket_type:
            parts.append(ticket_type)
        if event_date:
            try:
                dt = datetime.strptime(event_date, "%Y-%m-%d %H:%M:%S")
                parts.append(dt.strftime("%m/%d/%Y"))
            except (ValueError, TypeError):
                parts.append(event_date[:10])
        return " — ".join(parts)

    def _print_price_summary(rows, label="Price summary"):
        prices = [l["price"] for l in rows if l["price"] is not None]
        if prices:
            console.print(f"\n[bold]{label}:[/bold]  "
                          f"Min: ${min(prices):.2f}  |  "
                          f"Max: ${max(prices):.2f}  |  "
                          f"Avg: ${sum(prices)/len(prices):.2f}  |  "
                          f"Median: ${sorted(prices)[len(prices)//2]:.2f}")

    if args.terminal:
        # ---- Terminal output ----
        if args.group_by_event:
            from collections import OrderedDict
            key_order = OrderedDict()
            active_groups, sold_groups = {}, {}
            for l in active:
                k = _group_key(l)
                key_order.setdefault(k, None)
                active_groups.setdefault(k, []).append(l)
            for l in sold:
                k = _group_key(l)
                key_order.setdefault(k, None)
                sold_groups.setdefault(k, []).append(l)

            for k in key_order:
                heading = _group_title(k)
                if active_groups.get(k):
                    display_listings(active_groups[k], heading)
                    _print_price_summary(active_groups[k])
                    console.print()
                if sold_groups.get(k):
                    display_listings(sold_groups[k], f"{heading} — Sold", show_sold_col=True)
                    _print_price_summary(sold_groups[k], label="Sold price summary")
                    console.print()
        else:
            title = "All Events" if len(args.urls) > 1 else (
                (active + sold)[0]["event_title"] if (active or sold) else "Unknown"
            )
            if active:
                display_listings(active, title)
                _print_price_summary(active)
            if sold:
                console.print()
                display_listings(sold, f"{title} — Sold", show_sold_col=True)
                _print_price_summary(sold, label="Sold price summary")
    else:
        # ---- HTML output (default) ----
        title = "All Events" if len(args.urls) > 1 else (
            (active + sold)[0]["event_title"] if (active or sold) else "Unknown"
        )
        html = render_html(active, sold, title, group_by_event=args.group_by_event)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="tickets-", delete=False
        ) as f:
            f.write(html)
            html_path = f.name

        console.print(f"Opening: {html_path}")
        webbrowser.open(f"file://{html_path}")


def main():
    """Top-level entry point.

    Runs the pipeline and turns expected failure conditions into a clean,
    one-line error + non-zero exit — never a raw Python traceback. Our own
    "could not find event" paths already raise SystemExit with a red message,
    so they propagate through untouched.
    """
    try:
        run()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)
    except requests.exceptions.RequestException as e:
        console.print(f"[red]Error: network request failed: {e}[/red]")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001 - defensive top-level safety net
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
