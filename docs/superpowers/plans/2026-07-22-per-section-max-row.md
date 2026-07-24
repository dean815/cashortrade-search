# Per-section max row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `--section` entries carry an optional `:MAXROW` suffix (e.g. `222:7`) so different sections in one query can have independent inclusive row caps, and remove the global `--row` flag which today applies one row range across every section.

**Architecture:** A new `parse_section_arg` helper splits each `--section` string into `(pattern, max_row | None)`. `apply_filters` parses all `--section` entries up front and matches a listing if any entry's pattern matches its section AND (no cap, or the row is non-numeric, or the row is `<= max_row`). The standalone row-filter block and `--row` CLI flag are deleted.

**Tech Stack:** Python 3.11+/3.13, argparse, pytest (existing stack — no new dependencies).

## Global Constraints

- No new runtime dependencies (spec is a pure logic + CLI change).
- `MAXROW` must be a positive integer; malformed suffixes are a usage error surfaced via `parser.error(...)` (existing pattern in `run()`), never a silent misparse.
- Non-numeric rows (GA/Floor/Pit/etc.) always pass a row cap, matching today's row-filter behavior.
- `--row` is removed entirely — no backwards-compatibility shim.
- Follow existing code style in `tickets.py`: comments only where the *why* isn't obvious from the code.

---

### Task 1: `parse_section_arg` helper

**Files:**
- Modify: `tickets.py` — add new function immediately after `parse_tickets_arg` (currently ends at `tickets.py:320`)
- Test: `tests/test_tickets.py` — add tests immediately after the `parse_tickets_arg` tests (currently end at `tests/test_tickets.py:33`), and add `parse_section_arg` to the `from tickets import (...)` block at `tests/test_tickets.py:10-16`

**Interfaces:**
- Produces: `parse_section_arg(value: str) -> tuple[str, int | None]` — returns `(pattern, None)` for a plain pattern, `(pattern, max_row)` for `PATTERN:MAXROW`. Raises `ValueError` with a descriptive message for a malformed suffix (empty pattern before `:`, non-integer max row, or max row `<= 0`).

- [ ] **Step 1: Write the failing tests**

Add `parse_section_arg` to the import block in `tests/test_tickets.py`:

```python
from tickets import (
    apply_filters,
    format_listed,
    parse_listing,
    parse_section_arg,
    parse_tickets_arg,
    sort_listings,
)
```

Add these tests directly after `test_parse_tickets_arg_invalid_raises` (after line 33):

```python
# ---------------------------------------------------------------------------
# parse_section_arg
# ---------------------------------------------------------------------------

def test_parse_section_arg_no_cap():
    assert parse_section_arg("222") == ("222", None)


def test_parse_section_arg_non_numeric_pattern_no_cap():
    assert parse_section_arg("GA") == ("GA", None)


def test_parse_section_arg_with_cap():
    assert parse_section_arg("222:7") == ("222", 7)


@pytest.mark.parametrize("value", ["222:", "222:abc", "222:0", "222:-1", ":7"])
def test_parse_section_arg_malformed_raises(value):
    with pytest.raises(ValueError):
        parse_section_arg(value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tickets.py -k parse_section_arg -v`
Expected: FAIL — `ImportError: cannot import name 'parse_section_arg' from 'tickets'`

- [ ] **Step 3: Implement `parse_section_arg`**

In `tickets.py`, insert immediately after the `parse_tickets_arg` function (after the line `return n, n` that closes it, currently `tickets.py:320`):

```python


def parse_section_arg(value: str) -> tuple[str, int | None]:
    """Parse a --section entry: 'PATTERN' -> (pattern, None), 'PATTERN:MAXROW' -> (pattern, max_row)."""
    if ":" not in value:
        return value, None
    pattern, _, max_row_str = value.rpartition(":")
    if not pattern:
        raise ValueError(f"invalid --section entry {value!r}: missing pattern before ':'")
    try:
        max_row = int(max_row_str)
    except ValueError:
        raise ValueError(f"invalid --section entry {value!r}: max row must be a positive integer") from None
    if max_row <= 0:
        raise ValueError(f"invalid --section entry {value!r}: max row must be a positive integer")
    return pattern, max_row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tickets.py -k parse_section_arg -v`
Expected: PASS (6 tests: `no_cap`, `non_numeric_pattern_no_cap`, `with_cap`, and 5 parametrized `malformed_raises` cases)

- [ ] **Step 5: Commit**

```bash
git add tickets.py tests/test_tickets.py
git commit -m "Add parse_section_arg for PATTERN:MAXROW section entries"
```

---

### Task 2: Combine section matching and row cap in `apply_filters`

**Files:**
- Modify: `tickets.py` — the section filter and row filter blocks inside `apply_filters` (currently `tickets.py:337-363`)
- Test: `tests/test_tickets.py` — `make_args` helper (line 40-44), and the filter tests around lines 82-93

**Interfaces:**
- Consumes: `parse_section_arg(value: str) -> tuple[str, int | None]` from Task 1.
- Produces: `apply_filters(listings: list[dict], args) -> list[dict]` keeps its existing signature and behavior for every filter except section/row, which are now combined. `args.row` is no longer read. `args.section` entries may include a `:MAXROW` suffix.

- [ ] **Step 1: Write the failing tests**

In `tests/test_tickets.py`, remove the `row` key from `make_args` (it's no longer a real CLI arg):

```python
def make_args(**overrides):
    defaults = dict(type=None, tickets=None, section=None,
                     min_price=None, max_price=None)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)
```

Replace `test_apply_filters_row_range_includes_ga_regardless` (lines 89-92) with these tests (keep `test_apply_filters_by_section_partial_match_case_insensitive` as-is, it still applies):

```python
def test_apply_filters_section_with_max_row_excludes_higher_rows():
    listings = [L(section_raw="222", row="5"), L(section_raw="222", row="12")]
    result = apply_filters(listings, make_args(section=["222:7"]))
    assert [l["row"] for l in result] == ["5"]


def test_apply_filters_section_with_max_row_includes_ga_rows_in_that_section():
    listings = [L(section="GA - Floor", section_raw="", row="")]
    result = apply_filters(listings, make_args(section=["ga:7"]))
    assert len(result) == 1


def test_apply_filters_mixed_capped_and_uncapped_sections():
    listings = [
        L(section_raw="102", row="20"),   # uncapped section, high row: included
        L(section_raw="222", row="5"),    # capped section, within cap: included
        L(section_raw="222", row="12"),   # capped section, over cap: excluded
        L(section_raw="309", row="3"),    # not requested at all: excluded
    ]
    result = apply_filters(listings, make_args(section=["102", "222:7"]))
    assert sorted((l["section_raw"], l["row"]) for l in result) == [
        ("102", "20"), ("222", "5"),
    ]


def test_apply_filters_uncapped_entry_unaffected_by_other_entrys_cap():
    listings = [L(section_raw="102", row="99")]
    result = apply_filters(listings, make_args(section=["102", "222:1"]))
    assert len(result) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tickets.py -k "apply_filters" -v`
Expected: FAIL — `AttributeError: 'types.SimpleNamespace' object has no attribute 'row'`. Every `apply_filters` test fails at this checkpoint (not just the new ones), because `make_args` no longer sets a `row` default but the still-unmodified `apply_filters` unconditionally evaluates `if args.row:` near the end of its filter chain. This confirms both halves of the change are needed together: the old code depends on `args.row` existing, and it will be deleted in Step 3.

- [ ] **Step 3: Implement the combined filter**

In `tickets.py`, replace the section filter and row filter blocks (currently lines 337-363, from the `# Section filter` comment through the closing of the row-filter `if args.row:` block) with:

```python
    # Section filter (multiple entries, each optionally capped by a max row
    # via "PATTERN:MAXROW", e.g. "222:7"). Numeric patterns (e.g. "108")
    # match the section number exactly — otherwise short patterns like "1"
    # would substring-match "113", "211", etc. Non-numeric patterns (e.g.
    # "GA") still do a partial match against the section strings. A listing
    # without a numeric row (GA/Floor/Pit/etc.) always passes the row cap.
    if args.section:
        entries = [(p.lower(), max_row) for p, max_row in
                   (parse_section_arg(s) for s in args.section)]

        def _section_matches(l):
            for pattern, max_row in entries:
                if pattern.isdigit():
                    if l["section_raw"].lower() != pattern:
                        continue
                elif pattern not in l["section"].lower() and pattern not in l["section_raw"].lower():
                    continue
                if max_row is None or not l["row"].isdigit() or int(l["row"]) <= max_row:
                    return True
            return False

        filtered = [l for l in filtered if _section_matches(l)]
```

This removes the old standalone `if args.row:` block entirely — row capping is now expressed only through `--section PATTERN:MAXROW`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tickets.py -v`
Expected: PASS — full suite green, including all `apply_filters` tests and the untouched `parse_listing`/`sort_listings`/`format_listed` tests.

- [ ] **Step 5: Commit**

```bash
git add tickets.py tests/test_tickets.py
git commit -m "Combine section matching and row cap into a single --section entry"
```

---

### Task 3: Remove `--row` CLI flag, validate `--section` entries in `run()`

**Files:**
- Modify: `tickets.py` — `--section`/`--row` argparse definitions (currently `tickets.py:755-758`), the tickets-arg validation block in `run()` (currently `tickets.py:776-781`), and the epilog example (currently `tickets.py:740`)

**Interfaces:**
- Consumes: `parse_section_arg(value: str) -> tuple[str, int | None]` from Task 1.

- [ ] **Step 1: Remove the `--row` argument and update `--section` help text**

In `tickets.py`, replace:

```python
    parser.add_argument("--section", nargs="+",
                        help="Filter by section(s), partial match (e.g. 108 109 GA)")
    parser.add_argument("--row",
                        help="Filter by row: exact (e.g. 5) or range (e.g. 1-10)")
```

with:

```python
    parser.add_argument("--section", nargs="+",
                        help="Filter by section(s), partial match (e.g. 108 109 GA); "
                             "add :MAXROW to cap a section's row (e.g. 222:7)")
```

- [ ] **Step 2: Update the epilog example**

In `tickets.py`, replace the epilog line (currently `tickets.py:740`):

```python
  %(prog)s "URL" --section 108 109 110 --type sale miracle
```

with:

```python
  %(prog)s "URL" --section 108 109 220:7 --type sale miracle
```

- [ ] **Step 3: Validate `--section` entries eagerly in `run()`**

In `tickets.py`, immediately after the existing tickets-arg validation block:

```python
    # Validate tickets arg
    if args.tickets:
        try:
            parse_tickets_arg(args.tickets)
        except ValueError:
            parser.error("--tickets must be a number (e.g. 2) or range (e.g. 2-4)")
```

add:

```python

    # Validate section args
    if args.section:
        for s in args.section:
            try:
                parse_section_arg(s)
            except ValueError as e:
                parser.error(str(e))
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: PASS — no test references `--row` or `args.row` anymore (confirmed by Task 2's edits), so nothing should break.

- [ ] **Step 5: Manually verify the CLI**

Run: `python3 tickets.py --help`
Expected: Output shows the updated `--section` help text and no `--row` option.

Run:
```bash
python3 -c "
import sys
sys.argv = ['tickets.py', 'https://example.com', '--section', '222:abc']
import tickets
tickets.run()
"
```
Expected: Exits non-zero with a usage error mentioning `--section entry '222:abc'` and "max row must be a positive integer" — printed before any network call happens (validation runs right after `parse_args()`, ahead of the URL-fetching loop).

- [ ] **Step 6: Commit**

```bash
git add tickets.py
git commit -m "Remove --row flag; validate --section :MAXROW entries in run()"
```

---

### Task 4: Update README.md and CLAUDE.md

**Files:**
- Modify: `README.md` — the options table (currently has a `--row` row around line 53)
- Modify: `CLAUDE.md` — the `apply_filters` bullet in the Architecture section (currently `CLAUDE.md:43`)

**Interfaces:**
- None (documentation only).

- [ ] **Step 1: Update README.md**

Read `README.md` to find the exact current options table, then replace the `--row N` or `N-M` row:

```
| `--row N` or `N-M` | Filter by row, e.g. `5` or `1-10` (GA/floor rows always pass) |
```

with a row describing the new syntax:

```
| `--section ... PATTERN:MAXROW` | Cap a section's row, e.g. `222:7` (rows 1-7 inclusive; GA/floor rows in that section always pass) |
```

Remove the now-inaccurate row entirely if the table already has a `--section` row elsewhere — merge into a single `--section` explanation rather than having two rows describing the same flag. Read the surrounding table context before editing to keep formatting (column widths/pipes) consistent with the rest of the table.

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md`, replace the sentence (currently line 43):

```
4. **Filter** (`apply_filters`): type/tickets-count/section/row/price filters. Row filtering only applies to numeric rows — GA/Floor/Pit-style listings always pass through.
```

with:

```
4. **Filter** (`apply_filters`): type/tickets-count/section/price filters. Each `--section` entry can carry an optional `:MAXROW` suffix (e.g. `222:7`) capping that section's row — non-numeric rows (GA/Floor/Pit-style) always pass the cap.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Update docs for --section :MAXROW syntax, remove --row references"
```

---

### Task 5: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: All tests pass.

- [ ] **Step 2: Run lint**

Run: `ruff check .`
Expected: No errors.

- [ ] **Step 3: Run type check**

Run: `mypy tickets.py`
Expected: No errors. (If `parse_section_arg`'s `tuple[str, int | None]` return type trips mypy on the `apply_filters` unpacking, check the reported line and add a narrow type annotation on `entries` rather than loosening the function signature.)

- [ ] **Step 4: Smoke-test the original use case**

Run:
```bash
python3 tickets.py "https://cashortrade.org/phish-at-madison-square-garden-tickets/event/1fa62c93-60c6-4f3e-b318-70d25d76d0d7" --section 102 222:7 --terminal --sort price
```
Expected: Runs without a usage error (network access required — if the event/section data isn't available, confirm at minimum that argument parsing and validation succeed and the tool proceeds to the fetch step rather than failing on `--section`).
