"""Unit tests for the pure functions in tickets.py.

No network calls — all inputs are synthetic, shaped like real
CashorTrade API responses / parsed output.
"""
from types import SimpleNamespace

import pytest

from tickets import (
    apply_filters,
    format_listed,
    parse_listing,
    parse_tickets_arg,
    sort_listings,
)


# ---------------------------------------------------------------------------
# parse_tickets_arg
# ---------------------------------------------------------------------------

def test_parse_tickets_arg_exact():
    assert parse_tickets_arg("2") == (2, 2)


def test_parse_tickets_arg_range():
    assert parse_tickets_arg("2-4") == (2, 4)


def test_parse_tickets_arg_invalid_raises():
    with pytest.raises(ValueError):
        parse_tickets_arg("abc")


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

def make_args(**overrides):
    defaults = dict(type=None, tickets=None, section=None, row=None,
                     min_price=None, max_price=None)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def L(**overrides):
    """Minimal listing dict factory for filter/sort tests."""
    base = dict(flow="sale", num_tickets=2, price=100.0,
                section="Section 108", section_raw="108", row="5")
    base.update(overrides)
    return base


def test_apply_filters_empty_input():
    assert apply_filters([], make_args()) == []


def test_apply_filters_no_filters_returns_unchanged():
    listings = [L(), L(flow="trade")]
    assert apply_filters(listings, make_args()) == listings


def test_apply_filters_by_type():
    listings = [L(flow="sale"), L(flow="trade"), L(flow="miracle")]
    result = apply_filters(listings, make_args(type=["sale"]))
    assert [l["flow"] for l in result] == ["sale"]


def test_apply_filters_by_tickets_exact():
    listings = [L(num_tickets=2), L(num_tickets=3)]
    result = apply_filters(listings, make_args(tickets="2"))
    assert len(result) == 1 and result[0]["num_tickets"] == 2


def test_apply_filters_by_tickets_range():
    listings = [L(num_tickets=1), L(num_tickets=3), L(num_tickets=5)]
    result = apply_filters(listings, make_args(tickets="2-4"))
    assert [l["num_tickets"] for l in result] == [3]


def test_apply_filters_by_section_partial_match_case_insensitive():
    listings = [L(section="Section 108", section_raw="108"),
                L(section="GA - Floor", section_raw="")]
    result = apply_filters(listings, make_args(section=["ga"]))
    assert len(result) == 1 and result[0]["section"] == "GA - Floor"


def test_apply_filters_row_range_includes_ga_regardless():
    listings = [L(row="5"), L(row="15"), L(row="")]  # "" == GA/floor
    result = apply_filters(listings, make_args(row="1-10"))
    assert sorted(l["row"] for l in result) == ["", "5"]


def test_apply_filters_price_bounds_exclude_missing_price():
    listings = [L(price=50.0), L(price=150.0), L(price=None)]
    result = apply_filters(listings, make_args(min_price=100, max_price=200))
    assert [l["price"] for l in result] == [150.0]


# ---------------------------------------------------------------------------
# sort_listings
# ---------------------------------------------------------------------------

def test_sort_listings_price_ascending_none_last():
    listings = [L(price=50.0), L(price=None), L(price=10.0)]
    result = sort_listings(listings, "price")
    assert [l["price"] for l in result] == [10.0, 50.0, None]


def test_sort_listings_price_desc_none_last():
    listings = [L(price=50.0), L(price=None), L(price=10.0)]
    result = sort_listings(listings, "price-desc")
    assert [l["price"] for l in result] == [50.0, 10.0, None]


def test_sort_listings_date_newest_first():
    listings = [L(created="2026-01-01 00:00:00"), L(created="2026-06-01 00:00:00")]
    result = sort_listings(listings, "date")
    assert [l["created"] for l in result] == ["2026-06-01 00:00:00", "2026-01-01 00:00:00"]


def test_sort_listings_date_asc_oldest_first():
    listings = [L(created="2026-06-01 00:00:00"), L(created="2026-01-01 00:00:00")]
    result = sort_listings(listings, "date-asc")
    assert [l["created"] for l in result] == ["2026-01-01 00:00:00", "2026-06-01 00:00:00"]


def test_sort_listings_unknown_key_exits():
    with pytest.raises(SystemExit):
        sort_listings([L()], "not-a-real-sort")


# ---------------------------------------------------------------------------
# format_listed
# ---------------------------------------------------------------------------

def test_format_listed_empty_string():
    assert format_listed("") == ""


def test_format_listed_valid_timestamp_shape():
    # Output is local-time-dependent (astimezone() with no fixed TZ), so
    # assert the *shape*, not an exact string, to stay CI-environment safe
    # (GitHub Actions runs TZ=UTC, which won't match a developer's machine).
    result = format_listed("2026-04-21 01:21:21")
    assert result  # non-empty
    assert any(c in result for c in ("am", "pm"))


def test_format_listed_malformed_falls_back_to_first_10_chars():
    assert format_listed("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# parse_listing
# ---------------------------------------------------------------------------

def make_raw_listing(**overrides):
    base = {
        "uid": "raw-1",
        "flow": "sale",
        "status": "active",
        "created": "2026-04-20 10:00:00",
        "description": "<p>Great seats!</p>",
        "prices_by_membership": [
            {"name": "Gold Membership", "price": 150.0},
            {"name": "Free", "price": 175.0},
        ],
        "tickets": [
            {"section": "108", "row": "12", "seat": "5", "ga_section": None,
             "sold": False, "event_product": {"uid": "ep-1"}},
            {"section": "108", "row": "12", "seat": "6", "ga_section": None,
             "sold": False, "event_product": {"uid": "ep-1"}},
        ],
    }
    base.update(overrides)
    return base


PRODUCT_META = {
    "ep-1": {"event_title": "Phish at Sphere", "event_date": "2026-09-04 00:00:00",
              "ticket_type": "3-Day Pass"},
}
PAGE_URL = "https://cashortrade.org/phish-at-sphere-tickets/event/uuid"


def test_parse_listing_numbered_section_and_gold_price_preferred():
    result = parse_listing(make_raw_listing(), PAGE_URL, PRODUCT_META)
    assert result["price"] == 150.0          # Gold preferred over Free
    assert result["section"] == "Section 108"
    assert result["seats"] == "5, 6"
    assert result["num_tickets"] == 2
    assert result["is_sold"] is False
    assert result["link"] == f"{PAGE_URL}?proposal_drawer_uid=raw-1"
    assert result["event_title"] == "Phish at Sphere"
    assert result["ticket_type"] == "3-Day Pass"


def test_parse_listing_ga_section_dict_shape():
    raw = make_raw_listing(tickets=[
        {"section": "", "row": "", "seat": "", "ga_section": {"name": "floor"},
         "sold": False, "event_product": {"uid": "ep-1"}},
    ])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["section"] == "GA - Floor"


def test_parse_listing_ga_section_string_shape():
    raw = make_raw_listing(tickets=[
        {"section": "", "row": "", "seat": "", "ga_section": "floor",
         "sold": False, "event_product": {"uid": "ep-1"}},
    ])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["section"] == "GA - Floor"


def test_parse_listing_no_tickets_is_unknown_and_not_sold():
    raw = make_raw_listing(tickets=[])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["section"] == "Unknown"
    assert result["num_tickets"] == 0
    assert result["is_sold"] is False


def test_parse_listing_all_tickets_sold_via_timestamps():
    raw = make_raw_listing(tickets=[
        {"section": "108", "row": "12", "seat": "5", "ga_section": None,
         "sold": "2026-04-21 01:21:21", "event_product": {"uid": "ep-1"}},
        {"section": "108", "row": "12", "seat": "6", "ga_section": None,
         "sold": "2026-04-21 01:25:00", "event_product": {"uid": "ep-1"}},
    ])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["is_sold"] is True
    assert result["sold_at"] == "2026-04-21 01:25:00"  # max of the two


def test_parse_listing_sold_via_status_field():
    raw = make_raw_listing(status="accepted")
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["is_sold"] is True
    assert result["sold_at"] == ""  # no per-ticket sold timestamps


def test_parse_listing_miracle_flow_forces_zero_price():
    raw = make_raw_listing(flow="miracle")
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["price"] == 0


def test_parse_listing_missing_price_is_none():
    raw = make_raw_listing(prices_by_membership=[], tickets=[
        {"section": "5", "row": "3", "seat": "1", "ga_section": None,
         "sold": False, "event_product": {"uid": "ep-1"}},
    ])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["price"] is None


def test_parse_listing_strips_html_and_collapses_whitespace():
    raw = make_raw_listing(description="<p>Great <b>seats</b>!</p>\n\nRow 12")
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["description"] == "Great seats ! Row 12"


def test_parse_listing_falls_back_to_embedded_event_data_when_meta_missing():
    raw = make_raw_listing(tickets=[
        {"section": "108", "row": "12", "seat": "5", "ga_section": None,
         "sold": False,
         "event_product": {"uid": "ep-1", "start": "2026-09-04 00:00:00",
                            "title": "3-Day Pass"},
         "event": {"title": ["For Sale: Phish at Sphere"]}},
    ])
    result = parse_listing(raw, PAGE_URL, product_meta={})  # empty lookup
    assert result["event_title"] == "Phish at Sphere"       # list unwrapped + prefix stripped
    assert result["event_date"] == "2026-09-04 00:00:00"
    assert result["ticket_type"] == "3-Day Pass"


def test_parse_listing_non_numeric_section_has_no_section_prefix():
    raw = make_raw_listing(tickets=[
        {"section": "FL", "row": "", "seat": "", "ga_section": None,
         "sold": False, "event_product": {"uid": "ep-1"}},
    ])
    result = parse_listing(raw, PAGE_URL, PRODUCT_META)
    assert result["section"] == "FL"  # no "Section" prefix for non-digit sections
