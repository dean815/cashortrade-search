#!/usr/bin/env python3
"""Generate a static demo HTML file from synthetic listing data.

Does NOT call the live CashorTrade API — all data below is fabricated,
shaped like tickets.py's parse_listing() output. Used to produce the
screenshot referenced from README.md.

Usage:
    python scripts/gen_demo_html.py
    # then open docs/demo.html in a browser, screenshot it, and save
    # the image as docs/demo-screenshot.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tickets import render_html

ACTIVE_LISTINGS = [
    {
        "event_title": "Phish at Madison Square Garden",
        "event_date": "2026-08-14 19:30:00",
        "ticket_type": "Night 2",
        "flow": "sale",
        "num_tickets": 2,
        "price": 145.00,
        "section": "Section 108",
        "section_raw": "108",
        "row": "12",
        "seats": "5, 6",
        "description": "Great view of the stage, aisle seats.",
        "link": "https://cashortrade.org/example/product/demo1?proposal_drawer_uid=demo-1",
        "created": "2026-07-10 14:22:00",
        "is_sold": False,
        "sold_at": "",
        "uid": "demo-1",
    },
    {
        "event_title": "Phish at Madison Square Garden",
        "event_date": "2026-08-14 19:30:00",
        "ticket_type": "Night 2",
        "flow": "miracle",
        "num_tickets": 1,
        "price": 0,
        "section": "GA - Floor",
        "section_raw": "",
        "row": "",
        "seats": "",
        "description": "Miracle needed — will trade for good karma.",
        "link": "https://cashortrade.org/example/product/demo2?proposal_drawer_uid=demo-2",
        "created": "2026-07-11 09:05:00",
        "is_sold": False,
        "sold_at": "",
        "uid": "demo-2",
    },
    {
        "event_title": "Phish at Madison Square Garden",
        "event_date": "2026-08-14 19:30:00",
        "ticket_type": "Night 1",
        "flow": "trade",
        "num_tickets": 4,
        "price": 89.50,
        "section": "212",
        "section_raw": "212",
        "row": "4",
        "seats": "1, 2, 3, 4",
        "description": "Will trade for Night 2 tickets, similar section.",
        "link": "https://cashortrade.org/example/product/demo3?proposal_drawer_uid=demo-3",
        "created": "2026-07-09 11:47:00",
        "is_sold": False,
        "sold_at": "",
        "uid": "demo-3",
    },
]

SOLD_LISTINGS = [
    {
        "event_title": "Phish at Madison Square Garden",
        "event_date": "2026-08-14 19:30:00",
        "ticket_type": "Night 2",
        "flow": "sale",
        "num_tickets": 2,
        "price": 210.00,
        "section": "Section 104",
        "section_raw": "104",
        "row": "8",
        "seats": "14, 15",
        "description": "Sold within an hour of posting.",
        "link": "https://cashortrade.org/example/product/demo4?proposal_drawer_uid=demo-4",
        "created": "2026-07-08 20:10:00",
        "is_sold": True,
        "sold_at": "2026-07-08 21:02:00",
        "uid": "demo-4",
    },
]


def main() -> None:
    html = render_html(
        ACTIVE_LISTINGS,
        SOLD_LISTINGS,
        title="Phish at Madison Square Garden — Demo",
        group_by_event=False,
    )
    out_path = Path(__file__).resolve().parent.parent / "docs" / "demo.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    print(f"Wrote {out_path}")
    print("Open it in a browser, screenshot it, and save as docs/demo-screenshot.png")


if __name__ == "__main__":
    main()
