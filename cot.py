#!/usr/bin/env python3
"""
CashorTrade Search Tool - Search, filter, and sort ticket listings from cashortrade.org

Usage:
    python cot.py "https://cashortrade.org/.../event/{id}" [options]
    python cot.py "https://cashortrade.org/.../event/{id}/product/{id}" [options]

Examples:
    python cot.py "https://cashortrade.org/phish-at-sphere-tickets/event/3d4f8df0-..." --max-price 200
    python cot.py "URL" --type sale --tickets 2 --section 108 109 --sort price
    python cot.py "URL" --type sale miracle --tickets 2-4 --sort date
    python cot.py "URL" --sold --sort price-desc
"""

import argparse
import json
import re
import sys

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

def parse_listing(raw: dict, page_url: str) -> dict:
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

    return {
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
    """Display listings in a rich table with details below."""
    table = Table(
        title=f"{event_title}  ({len(listings)} listings)",
        show_lines=False,
        pad_edge=True,
    )

    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Qty", width=3, justify="center")
    table.add_column("Price", justify="right", min_width=9)
    table.add_column("Section", min_width=14)
    table.add_column("Row", width=4)
    table.add_column("Seats", min_width=14)

    details = []

    for i, l in enumerate(listings, 1):
        price_str = f"${l['price']:.2f}" if l["price"] is not None else "N/A"
        row_style = "dim" if l["is_sold"] else ""

        table.add_row(
            str(i),
            str(l["num_tickets"]),
            price_str,
            l["section"],
            l["row"] or "-",
            l["seats"] or "-",
            style=row_style,
        )

        details.append({
            "num": i,
            "flow": l["flow"],
            "desc": l["description"],
            "listed": format_listed(l["created"]),
            "link": l["link"],
            "is_sold": l["is_sold"],
        })

    console.print(table)

    # Print details for each listing below
    if details:
        console.print("\n[bold]Details:[/bold]")
        for d in details:
            sold_tag = " [dim]SOLD[/dim]" if d["is_sold"] else ""
            flow = d["flow"].capitalize()
            desc = d["desc"][:120] if d["desc"] else ""
            parts = [f"  [bold]{d['num']:>3}.[/bold]"]
            parts.append(f"[{flow}]")
            if desc:
                parts.append(f"{desc}")
            parts.append(f"[dim]Listed {d['listed']}[/dim]{sold_tag}")
            console.print(" ".join(parts))
            console.print(f"       {d['link']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="CashorTrade Search Tool — paste a URL, get sortable/filterable listings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://cashortrade.org/phish-at-sphere-tickets/event/3d4f8df0-..."
  %(prog)s "URL" --max-price 200 --tickets 2 --sort price
  %(prog)s "URL" --section 108 109 110 --type sale miracle
  %(prog)s "URL" --tickets 2-4 --sort date
  %(prog)s "URL" --sold --sort price-desc
        """,
    )

    parser.add_argument("url", help="CashorTrade event URL")
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

    args = parser.parse_args()

    # Validate tickets arg
    if args.tickets:
        try:
            parse_tickets_arg(args.tickets)
        except ValueError:
            parser.error("--tickets must be a number (e.g. 2) or range (e.g. 2-4)")

    # Extract event info from URL
    console.print("Loading event...")
    event_title, products, page_url = extract_event_from_url(args.url)
    product_uids = [p["uid"] for p in products]
    console.print(f"Event: [bold green]{event_title}[/bold green]")

    # Fetch all listings
    console.print("Fetching listings...")
    raw_listings = fetch_all_listings(product_uids)

    # Parse
    parsed = [parse_listing(r, page_url) for r in raw_listings]

    # Filter
    filtered = apply_filters(parsed, args)

    # Sort
    filtered = sort_listings(filtered, args.sort)

    # Display
    console.print(
        f"\n[bold]{len(filtered)}[/bold] listings"
        f" (from {len(parsed)} total)\n"
    )

    if not filtered:
        console.print("[yellow]No listings match your filters.[/yellow]")
        return

    display_listings(filtered, event_title)

    # Price summary
    prices = [l["price"] for l in filtered if l["price"] is not None and not l["is_sold"]]
    if prices:
        console.print(f"\n[bold]Price summary:[/bold]  "
                       f"Min: ${min(prices):.2f}  |  "
                       f"Max: ${max(prices):.2f}  |  "
                       f"Avg: ${sum(prices)/len(prices):.2f}  |  "
                       f"Median: ${sorted(prices)[len(prices)//2]:.2f}")


if __name__ == "__main__":
    main()
