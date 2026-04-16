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

import requests
from rich.console import Console
from rich.table import Table
from rich.text import Text

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

    console.print(f"  Fetching: [dim]{page_url}[/dim]")
    resp = requests.get(page_url, headers={"Accept": "text/html"}, timeout=15)
    resp.raise_for_status()
    html = resp.text

    # Extract event title from <title> tag
    title_match = re.search(r"<title>([^<]+)</title>", html)
    event_title = "Unknown Event"
    if title_match:
        raw_title = title_match.group(1)
        event_title = raw_title.split(" | ")[0].split(" Tickets")[0].strip()

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
    all_results = []
    offset = 1
    page_size = 50
    session = requests.Session()

    while True:
        parts = [f"event_product[]={uid}" for uid in event_product_uids]
        parts += [f"include_sold=true", f"limit={page_size}", f"offset={offset}"]
        parts += [f"flow[]={f}" for f in ("sale", "trade", "miracle")]

        url = f"{API_BASE}/event/product/proposal/list?{'&'.join(parts)}"
        req = requests.Request("GET", url)
        prepared = req.prepare()
        prepared.url = url  # prevent re-encoding of []
        resp = session.send(prepared)
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

    # Sold status
    all_sold = all(t.get("sold") for t in tickets) if tickets else False
    status = raw.get("status", "")
    is_sold = all_sold or status in ("accepted", "finalized-success")

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

    # Description — strip HTML
    desc = (raw.get("description", "") or "")
    desc = re.sub(r"<[^>]+>", " ", desc).strip()
    desc = re.sub(r"\s+", " ", desc)

    # Link
    link = f"{page_url}?proposal_drawer_uid={raw.get('uid', '')}"

    # Event metadata — look up from product_meta via ticket's event_product uid
    event_product_uid = ""
    if tickets and tickets[0].get("event_product"):
        event_product_uid = tickets[0]["event_product"].get("uid", "")
    meta = product_meta.get(event_product_uid, {})

    # Fallback: if listing has embedded event_product data, use it directly
    if not meta and tickets and tickets[0].get("event_product"):
        ep = tickets[0]["event_product"]
        meta = {
            "event_title": "",
            "event_date": ep.get("start", ""),
            "ticket_type": ep.get("title", ""),
        }

    return {
        "event_title": meta.get("event_title", ""),
        "event_date": meta.get("event_date", ""),
        "ticket_type": meta.get("ticket_type", ""),
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
    """Apply user-specified filters."""
    filtered = listings

    # Sold filter (default: exclude sold)
    if not args.sold:
        filtered = [l for l in filtered if not l["is_sold"]]

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
    """Format a created timestamp for display."""
    if not created:
        return ""
    try:
        from datetime import datetime
        dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m/%d %-I:%M%p").lower()
    except (ValueError, TypeError):
        return created[:10]


def display_listings(listings: list[dict], event_title: str):
    """Display listings in a rich table."""
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
    table.add_column("Flow", width=7, no_wrap=True)
    table.add_column("Qty", width=3, justify="center", no_wrap=True)
    table.add_column("Price", justify="right", width=9, no_wrap=True)
    table.add_column("Section", width=12, no_wrap=True)
    table.add_column("Row", width=3, no_wrap=True)
    table.add_column("Seats", width=12, no_wrap=True, overflow="ellipsis")
    table.add_column("Description", ratio=1, overflow="fold")

    for l in listings:
        flow = l["flow"]
        if flow == "sale":
            flow_text = Text("Sale", style="green")
        elif flow == "trade":
            flow_text = Text("Trade", style="yellow")
        elif flow == "miracle":
            flow_text = Text("Miracle", style="cyan")
        else:
            flow_text = Text(flow)

        price_str = f"${l['price']:.2f}" if l["price"] is not None else "N/A"
        price_text = Text(price_str)
        if l["link"]:
            price_text.stylize(f"link {l['link']}")

        listed_str = format_listed(l["created"])
        row_style = "dim" if l["is_sold"] else ""
        desc = l["description"]
        if l["is_sold"]:
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
            flow_text,
            str(l["num_tickets"]),
            price_text,
            l["section"],
            l["row"] or "-",
            l["seats"] or "-",
            desc,
        ])

        table.add_row(*row_cells, style=row_style)

    console.print(table)


def render_html(listings: list[dict], title: str, group_by_event: bool = False) -> str:
    """Render listings as a self-contained HTML string."""

    # Check if multiple events present
    multi_event = len(set(l["event_title"] for l in listings)) > 1

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
            dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%m/%d %-I:%M%p").lower()
        except (ValueError, TypeError):
            return created[:10]

    def flow_color(flow):
        return {"sale": "#2d8a4e", "miracle": "#0891b2", "trade": "#ca8a04"}.get(flow, "#666")

    def render_table(rows, table_title, show_event_col):
        """Render one <table> block."""
        headers = []
        if show_event_col:
            headers.append("Event")
        headers.extend(["Date", "Ticket Type", "Listed", "Flow", "Qty", "Price",
                         "Section", "Row", "Seats", "Description"])

        header_html = "".join(f'<th onclick="sortTable(this)">{h}</th>' for h in headers)

        row_htmls = []
        for i, l in enumerate(rows):
            zebra = " even" if i % 2 == 0 else " odd"
            cls = f'class="{zebra.strip()}{" sold" if l["is_sold"] else ""}"'

            price_str = f"${l['price']:.2f}" if l["price"] is not None else "N/A"
            if l["link"]:
                price_cell = f'<a href="{l["link"]}">{price_str}</a>'
            else:
                price_cell = price_str

            flow_html = f'<span style="color:{flow_color(l["flow"])};font-weight:600">{l["flow"].title()}</span>'

            desc = l["description"]
            if l["is_sold"]:
                desc = f"[SOLD] {desc}"

            cells = []
            if show_event_col:
                cells.append(f"<td>{l['event_title']}</td>")
            cells.extend([
                f"<td>{format_event_date(l['event_date'])}</td>",
                f"<td>{l['ticket_type']}</td>",
                f"<td>{format_listed_html(l['created'])}</td>",
                f"<td>{flow_html}</td>",
                f'<td style="text-align:center">{l["num_tickets"]}</td>',
                f'<td style="text-align:right;font-weight:600">{price_cell}</td>',
                f"<td>{l['section']}</td>",
                f"<td>{l['row'] or '-'}</td>",
                f"<td>{l['seats'] or '-'}</td>",
                f"<td>{desc}</td>",
            ])

            row_htmls.append(f"<tr {cls}>{''.join(cells)}</tr>")

        # Price summary
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

    # Build table sections
    if group_by_event:
        from collections import OrderedDict
        groups = OrderedDict()
        for l in listings:
            key = l["event_title"] or "Unknown Event"
            groups.setdefault(key, []).append(l)
        tables_html = "".join(
            render_table(group, name, show_event_col=False)
            for name, group in groups.items()
        )
    else:
        tables_html = render_table(listings, title, show_event_col=multi_event)

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

def main():
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

    parser.add_argument("urls", nargs="+", help="One or more CashorTrade event URLs")
    parser.add_argument("--type", nargs="+", choices=["sale", "trade", "miracle"],
                        default=DEFAULT_TYPES,
                        help="Listing types to show (default: sale miracle)")
    parser.add_argument("--tickets",
                        help="Number of tickets: exact (e.g. 2) or range (e.g. 2-4)")
    parser.add_argument("--section", nargs="+",
                        help="Filter by section(s), partial match (e.g. 108 109 GA)")
    parser.add_argument("--min-price", type=float, help="Minimum price per ticket")
    parser.add_argument("--max-price", type=float, help="Maximum price per ticket")
    parser.add_argument("--sold", action="store_true",
                        help="Include sold listings (excluded by default)")
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

    all_parsed = []

    for url in args.urls:
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

    # Filter
    filtered = apply_filters(all_parsed, args)

    # Sort
    filtered = sort_listings(filtered, args.sort)

    # Display
    console.print(
        f"\n[bold]{len(filtered)}[/bold] listings"
        f" (from {len(all_parsed)} total)\n"
    )

    if not filtered:
        console.print("[yellow]No listings match your filters.[/yellow]")
        return

    # For now, always use terminal output (HTML comes in Task 4-5)
    if args.group_by_event:
        from collections import OrderedDict
        groups = OrderedDict()
        for l in filtered:
            key = l["event_title"] or "Unknown Event"
            groups.setdefault(key, []).append(l)

        for event_name, group_listings in groups.items():
            display_listings(group_listings, event_name)
            prices = [l["price"] for l in group_listings if l["price"] is not None and not l["is_sold"]]
            if prices:
                console.print(f"\n[bold]Price summary:[/bold]  "
                              f"Min: ${min(prices):.2f}  |  "
                              f"Max: ${max(prices):.2f}  |  "
                              f"Avg: ${sum(prices)/len(prices):.2f}  |  "
                              f"Median: ${sorted(prices)[len(prices)//2]:.2f}\n")
    else:
        title = "All Events" if len(args.urls) > 1 else (filtered[0]["event_title"] if filtered else "Unknown")
        display_listings(filtered, title)
        prices = [l["price"] for l in filtered if l["price"] is not None and not l["is_sold"]]
        if prices:
            console.print(f"\n[bold]Price summary:[/bold]  "
                          f"Min: ${min(prices):.2f}  |  "
                          f"Max: ${max(prices):.2f}  |  "
                          f"Avg: ${sum(prices)/len(prices):.2f}  |  "
                          f"Median: ${sorted(prices)[len(prices)//2]:.2f}")


if __name__ == "__main__":
    main()
