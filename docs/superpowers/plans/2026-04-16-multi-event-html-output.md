# Multi-Event Search with HTML Output — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept multiple CashorTrade URLs, extract event date and ticket type, and render results as an interactive HTML file opened in the browser (with terminal fallback).

**Architecture:** Extend `tickets.py` in-place. Add event metadata (date, ticket type) to the parse pipeline, build an HTML renderer alongside the existing rich terminal renderer, and update `main()` to loop over multiple URLs and route to the chosen output mode.

**Tech Stack:** Python 3.13, requests, rich (existing), webbrowser (stdlib), tempfile (stdlib)

---

### Task 1: Update Docstring and Imports

**Files:**
- Modify: `tickets.py:1-24`

- [ ] **Step 1: Update the module docstring to reflect new usage**

```python
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
```

- [ ] **Step 2: Add new stdlib imports**

Add `import tempfile`, `import webbrowser`, and `from datetime import datetime` to the top-level imports. Remove the inline `from datetime import datetime` inside `format_listed()` later (Task 6).

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add tickets.py
git commit -m "chore: update docstring and imports for multi-event HTML support"
```

---

### Task 2: Carry Event Metadata Through the Pipeline

The `extract_event_from_url()` function currently returns `(event_title, event_products, page_url)`. The `event_products` list already contains `title` (ticket type) and `start` (event date) fields from the CashorTrade API — we just need to preserve them and pass them into `parse_listing()`.

**Files:**
- Modify: `tickets.py` — `extract_event_from_url()`, `parse_listing()`, `main()`

- [ ] **Step 1: Write a test script to verify event_products data shape**

Create `test_api_shape.py` to confirm the fields exist:

```python
"""Quick smoke test: fetch one event and print event_products fields."""
import json
import re
import sys
import requests

API_BASE = "https://api-ng.cashortrade.org/frontend"
SITE_BASE = "https://cashortrade.org"

url = sys.argv[1]
path = re.sub(r"https?://[^/]+/", "", url.strip().rstrip("/"))
clean_path = path.split("?")[0]
page_url = f"{SITE_BASE}/{clean_path}"

resp = requests.get(page_url, headers={"Accept": "text/html"}, timeout=15)
html = resp.text.replace('\\"', '"')

products_match = re.search(
    r'"event_products"\s*:\s*(\[.*?\])\s*,\s*"(?:ticket_drop|sold)',
    html, re.DOTALL,
)
if products_match:
    products = json.loads(products_match.group(1))
    for p in products:
        print(f"  uid:   {p.get('uid')}")
        print(f"  title: {p.get('title')}")
        print(f"  start: {p.get('start')}")
        print(f"  end:   {p.get('end')}")
        print()
else:
    print("No event_products found in HTML")
```

- [ ] **Step 2: Run the test script against a real URL to confirm fields exist**

Run: `python test_api_shape.py "https://cashortrade.org/<some-event-url>"`

Expected: Each product prints a `title` (e.g., "3-Day Pass") and `start` (e.g., "2026-09-04 00:00:00").

- [ ] **Step 3: Build a product metadata lookup dict in main()**

After `extract_event_from_url()` returns, build a dict mapping product UID to its metadata. This will be passed to `parse_listing()`.

In `main()`, after the existing event extraction, add:

```python
# Build product metadata lookup: uid -> {event_title, event_date, ticket_type}
product_meta = {}
for p in products:
    uid = p["uid"]
    product_meta[uid] = {
        "event_title": event_title,
        "event_date": p.get("start", ""),
        "ticket_type": p.get("title", ""),
    }
```

- [ ] **Step 4: Update parse_listing() to accept and use product_meta**

Change the signature from `parse_listing(raw, page_url)` to `parse_listing(raw, page_url, product_meta)`.

Add event metadata extraction inside `parse_listing()`. The listing's tickets each have an `event_product.uid` field that maps into our lookup. Add this after the existing `link` assignment:

```python
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
```

Add three new fields to the returned dict:

```python
    return {
        "event_title": meta.get("event_title", ""),
        "event_date": meta.get("event_date", ""),
        "ticket_type": meta.get("ticket_type", ""),
        "flow": raw.get("flow", ""),
        # ... rest unchanged ...
    }
```

- [ ] **Step 5: Update the parse_listing() call site in main()**

Change:
```python
parsed = [parse_listing(r, page_url) for r in raw_listings]
```
To:
```python
parsed = [parse_listing(r, page_url, product_meta) for r in raw_listings]
```

- [ ] **Step 6: Run the tool with a real URL and verify no errors**

Run: `python tickets.py "https://cashortrade.org/<some-event-url>" --terminal`

Expected: Works exactly as before (new fields exist in the data but aren't displayed yet).

- [ ] **Step 7: Delete test_api_shape.py and commit**

```bash
rm test_api_shape.py
git add tickets.py
git commit -m "feat: carry event date and ticket type through parse pipeline"
```

---

### Task 3: Multi-URL Support

Change the `url` positional arg to accept one or more URLs, and loop over each in `main()`.

**Files:**
- Modify: `tickets.py` — `main()` and arg parser

- [ ] **Step 1: Change the argparse url argument to accept multiple URLs**

Replace:
```python
parser.add_argument("url", help="CashorTrade event URL")
```
With:
```python
parser.add_argument("urls", nargs="+", help="One or more CashorTrade event URLs")
```

- [ ] **Step 2: Add --terminal and --group-by-event flags**

Add these after the existing `--sort` argument:

```python
parser.add_argument("--terminal", action="store_true",
                    help="Output to terminal instead of HTML (default: HTML)")
parser.add_argument("--group-by-event", action="store_true",
                    help="Show separate tables per event instead of one merged table")
```

- [ ] **Step 3: Rewrite main() to loop over multiple URLs**

Replace the single-URL processing block (from "Extract event info" through "Parse") with a loop that collects all listings:

```python
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
```

- [ ] **Step 4: Update the display call and price summary for single-table mode**

For now, keep using the terminal display. Replace the old single-event display call with:

```python
    if args.group_by_event:
        # Group listings by event_title
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
```

- [ ] **Step 5: Update display_listings() to include Event, Date, Ticket Type columns**

Add three new columns to the rich table. Insert them before the existing "Listed" column:

```python
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
```

- [ ] **Step 6: Update the examples in the argparse epilog**

```python
    epilog="""
Examples:
  %(prog)s "URL"
  %(prog)s "URL1" "URL2" --max-price 200 --sort price
  %(prog)s "URL" --section 108 109 110 --type sale miracle
  %(prog)s "URL" --tickets 2-4 --sort date
  %(prog)s "URL1" "URL2" --group-by-event
  %(prog)s "URL" --terminal --sold --sort price-desc
        """,
```

- [ ] **Step 7: Run with a single URL to verify backwards compatibility**

Run: `python tickets.py "https://cashortrade.org/<some-event-url>"`

Expected: Still works, now shows Date and Type columns. Output goes to terminal (HTML not built yet).

- [ ] **Step 8: Commit**

```bash
git add tickets.py
git commit -m "feat: support multiple URLs, add event date/ticket type columns, group-by-event"
```

---

### Task 4: HTML Renderer

Build the `render_html()` function that produces a self-contained HTML file with sortable columns, color-coded types, and hyperlinked prices.

**Files:**
- Modify: `tickets.py` — add `render_html()` and `render_price_summary_html()` functions

- [ ] **Step 1: Write the render_html() function**

Add this after the existing `display_listings()` function:

```python
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
            sold_class = ' class="sold"' if l["is_sold"] else ""
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
```

- [ ] **Step 2: Run a quick manual test to verify the HTML renders**

Temporarily add to the end of `main()`:

```python
html = render_html(filtered, "Test", group_by_event=False)
print(html[:500])
```

Run: `python tickets.py "URL" --terminal`

Expected: First 500 chars of HTML printed, no errors. Then remove the test code.

- [ ] **Step 3: Commit**

```bash
git add tickets.py
git commit -m "feat: add HTML renderer with sortable columns and color-coded types"
```

---

### Task 5: Wire Up Output Routing in main()

Connect the HTML renderer to the main flow: HTML output by default, terminal with `--terminal`.

**Files:**
- Modify: `tickets.py` — `main()` display section

- [ ] **Step 1: Replace the display section in main() with output routing**

Replace the entire display block (after sorting, starting from `if not filtered:`) with:

```python
    if not filtered:
        console.print("[yellow]No listings match your filters.[/yellow]")
        return

    if args.terminal:
        # Terminal output
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
    else:
        # HTML output (default)
        title = "All Events" if len(args.urls) > 1 else (filtered[0]["event_title"] if filtered else "Unknown")
        html = render_html(filtered, title, group_by_event=args.group_by_event)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="tickets-", dir="/tmp", delete=False
        ) as f:
            f.write(html)
            html_path = f.name

        console.print(f"Opening: [link file://{html_path}]{html_path}[/link]")
        webbrowser.open(f"file://{html_path}")
```

- [ ] **Step 2: Test HTML output mode (default)**

Run: `python tickets.py "URL"`

Expected: Browser opens with an HTML table. Sortable columns work. Prices are hyperlinked.

- [ ] **Step 3: Test terminal output mode**

Run: `python tickets.py "URL" --terminal`

Expected: Rich table in terminal, same as before but with new Date and Ticket Type columns.

- [ ] **Step 4: Test group-by-event in HTML mode**

Run: `python tickets.py "URL1" "URL2" --group-by-event`

Expected: Browser opens with separate tables per event, each with its own price summary.

- [ ] **Step 5: Test group-by-event in terminal mode**

Run: `python tickets.py "URL1" "URL2" --group-by-event --terminal`

Expected: Separate rich tables in terminal, one per event.

- [ ] **Step 6: Commit**

```bash
git add tickets.py
git commit -m "feat: wire up HTML output as default, terminal as --terminal flag"
```

---

### Task 6: Clean Up — Remove Inline Import and Update format_listed

Now that `datetime` is imported at the top level, remove the inline import from `format_listed()`.

**Files:**
- Modify: `tickets.py` — `format_listed()`

- [ ] **Step 1: Remove the inline datetime import**

Change `format_listed()` from:

```python
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
```

To:

```python
def format_listed(created: str) -> str:
    """Format a created timestamp for display."""
    if not created:
        return ""
    try:
        dt = datetime.strptime(created, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m/%d %-I:%M%p").lower()
    except (ValueError, TypeError):
        return created[:10]
```

- [ ] **Step 2: Run a quick smoke test**

Run: `python tickets.py "URL" --terminal`

Expected: Still works, no import errors.

- [ ] **Step 3: Commit**

```bash
git add tickets.py
git commit -m "chore: remove inline datetime import, use top-level import"
```

---

### Task 7: Final Verification

End-to-end tests of all combinations.

**Files:** None (testing only)

- [ ] **Step 1: Single URL, HTML output (default)**

Run: `python tickets.py "URL"`

Expected: Browser opens, table with Date/Ticket Type columns, sortable headers, hyperlinked prices, price summary at bottom.

- [ ] **Step 2: Single URL, terminal output**

Run: `python tickets.py "URL" --terminal`

Expected: Rich table in terminal with Date/Type columns.

- [ ] **Step 3: Single URL with filters**

Run: `python tickets.py "URL" --type sale --max-price 200 --tickets 2`

Expected: HTML opens with filtered results.

- [ ] **Step 4: Multiple URLs, merged table**

Run: `python tickets.py "URL1" "URL2" --sort price`

Expected: HTML with single merged table, Event column visible, sorted by price.

- [ ] **Step 5: Multiple URLs, group-by-event**

Run: `python tickets.py "URL1" "URL2" --group-by-event`

Expected: HTML with separate tables per event.

- [ ] **Step 6: Multiple URLs, group-by-event, terminal**

Run: `python tickets.py "URL1" "URL2" --group-by-event --terminal`

Expected: Separate rich tables in terminal.
