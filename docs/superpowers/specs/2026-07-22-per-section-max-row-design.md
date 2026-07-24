# Per-section max row design

## Problem

`--section` and `--row` are independent filters, combined with AND. There's no
way to express "section 102 in any row, OR section 222 only in rows 1-7" —
the global `--row` cap applies uniformly across every section in the query,
so a query broad enough to include a far-back section (102, no row limit)
also silently caps every other section to the same row range.

## Goals

- Let each `--section` entry optionally carry its own maximum row (inclusive).
- Sections without a max row behave as today: any row (including non-numeric
  rows like GA/Floor/Pit) passes.
- Remove the global `--row` flag — max-row is now expressed per section only.

## CLI interface

`--section` entries become `PATTERN` or `PATTERN:MAXROW`:

```
--section 102 222:7 GA
```

- `102` — section 102, any row.
- `222:7` — section 222, rows 1 through 7 inclusive. Non-numeric rows in
  section 222 (GA/Floor/etc.) still pass, consistent with existing row-filter
  behavior.
- `GA` — substring match on section name, any row (unchanged pattern
  matching for non-numeric patterns).

`MAXROW` must be a positive integer. An entry with a malformed suffix
(`222:`, `222:abc`, `222:-1`) is a usage error: print a one-line message to
stderr and exit non-zero, rather than silently misinterpreting the pattern.

The `--row` flag is removed entirely (argparse will reject it as unrecognized
if someone still passes it).

## Matching semantics

Each `--section` entry is parsed into `(pattern, max_row)`, where `max_row`
is `None` if no suffix was given. A listing matches if **any** entry is
fully satisfied:

1. The pattern matches the listing's section, using existing logic (numeric
   pattern → exact match on `section_raw`; non-numeric pattern → substring
   match against `section`/`section_raw`).
2. AND the listing's row satisfies that entry's `max_row`: either the entry
   has no cap, or the listing's row isn't numeric (GA/Floor/etc. always
   pass), or the numeric row is `<= max_row`.

This means the row cap is scoped to the entry that matched — with
`--section 102 222:7`, a section-222 listing in row 12 is excluded even
though `222` alone (without the suffix) would have matched it, because the
entry that actually matches section 222 is `222:7`, which caps at row 7.

## Implementation

- New helper `parse_section_arg(value: str) -> tuple[str, int | None]` —
  splits on the last `:`, validates and parses `MAXROW` if present, raises
  `ValueError` with a clear message on malformed input. `run()`/`main()`
  catches this the same way other arg-parsing errors are surfaced (usage
  error → stderr + exit code, no traceback).
- `apply_filters`: replace the current two-step "section filter, then row
  filter" with a single step. Parse `args.section` into a list of
  `(pattern, max_row)` tuples up front, then `_section_matches(l)` iterates
  the list, checking pattern + row together per entry as described above.
- Delete the standalone row-filter block (current `tickets.py:355-363`) and
  the `--row` argparse option (current `tickets.py:757-758`).
- `parse_tickets_arg` stays as-is (still used for `--tickets`); the row cap
  parsing is a new, simpler int-only parser since there's no range form for
  max row.

## Docs

- README.md: replace the `--row` table row with an explanation of the
  `SECTION[:MAXROW]` syntax under `--section`.
- CLAUDE.md: update the `apply_filters` bullet (currently says
  "type/tickets-count/section/row/price filters... Row filtering only
  applies to numeric rows") to describe the combined section+row-cap
  behavior instead.

## Testing

In `tests/test_tickets.py`:

- `parse_section_arg`: plain pattern (no cap), valid `PATTERN:N`, malformed
  suffix cases (`:`, `:abc`, `:0`, `:-1`) raise.
- `apply_filters` / `_section_matches` equivalent, via existing test
  patterns:
  - Section with cap excludes higher numeric rows, includes rows at/under
    the cap.
  - Section with cap still includes non-numeric rows (GA/Floor) in that
    section.
  - Mixed query (`102`, `222:7`) — section 102 unrestricted, section 222
    capped — verifies caps don't leak across entries.
  - Section without a cap alongside a capped section — unrestricted section
    is unaffected by the other entry's cap.
  - Existing GA substring-match behavior still works combined with a cap
    suffix on a different entry.
- Remove/replace existing tests that exercise the standalone `--row` filter.
