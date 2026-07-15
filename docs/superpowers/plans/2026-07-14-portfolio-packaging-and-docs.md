# Portfolio Packaging & Docs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `cashortrade-search` installable from a fresh clone on any OS, and explain itself to a reader in 30 seconds via README — no feature changes, no refactors beyond the two portability fixes below.

**Architecture:** Two small in-place edits to `tickets.py` (portability only), plus five new files: `LICENSE`, `.gitignore`, `README.md`, `pyproject.toml`, `scripts/gen_demo_html.py`.

**Tech Stack:** Python 3.11+, setuptools (`pyproject.toml`), existing runtime deps (`requests`, `rich`) — no new runtime dependencies.

---

### Task 1: Cross-platform portability fixes

**Files:**
- Modify: `tickets.py:380-391` (`format_listed`)
- Modify: `tickets.py:491-500` (`format_listed_html`, inside `render_html`)
- Modify: `tickets.py:894-903` (HTML temp-file writer, inside `main`)

- [ ] **Step 1: Replace `%-I` in `format_listed()`**

`%-I` (no leading zero on the hour) is a glibc/BSD strftime extension — it raises `ValueError` on Windows. Replace with a portable computation of the same output.

Before:
```python
        return dt_local.strftime("%m/%d %-I:%M%p").lower()
```

After:
```python
        hour = str(int(dt_local.strftime("%I")))
        return f"{dt_local.strftime('%m/%d')} {hour}:{dt_local.strftime('%M%p').lower()}"
```

- [ ] **Step 2: Apply the identical fix to `format_listed_html()` inside `render_html()`**

Same before/after pattern as Step 1, at `tickets.py:498`.

- [ ] **Step 3: Drop the hardcoded `/tmp` dir from the HTML temp-file writer**

Before:
```python
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="tickets-", dir="/tmp", delete=False
        ) as f:
```

After:
```python
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", prefix="tickets-", delete=False
        ) as f:
```

`tempfile` already resolves the correct system temp directory (`$TMPDIR`, `/tmp`, or Windows' `%TEMP%`) when `dir` is omitted.

- [ ] **Step 4: Verify — run the tool end-to-end**

Run `python tickets.py --help` to confirm no syntax errors. If a real CashorTrade URL is available, run it and confirm the HTML file still opens correctly with the timestamp columns rendering (e.g. `7/14 3:05pm`, no leading zero, no crash).

- [ ] **Step 5: Commit**

```bash
git add tickets.py
git commit -m "fix: cross-platform temp file path and time formatting"
```

---

### Task 2: Add LICENSE

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Write the MIT license text**

```
MIT License

Copyright (c) 2026 Dean Hicks

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Commit**

```bash
git add LICENSE
git commit -m "chore: add MIT license"
```

---

### Task 3: Add .gitignore

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Write the .gitignore**

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.venv/
venv/
docs/demo.html
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

### Task 4: Add README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

```markdown
# cashortrade-search

Search, filter, and sort ticket listings across one or more
[CashorTrade](https://cashortrade.org) events from the command line —
output as a sortable HTML page (default) or a `rich` terminal table.

## Why I built this

Manually refreshing a CashorTrade event page during a ticket drop is slow
and it's easy to miss listings while you're staring at a single page.
This hits the CashorTrade API directly, merges results across as many
event URLs as you give it, and gives me one sortable/filterable view
instead of babysitting a browser tab.

## Install

Requires Python 3.11+.

\```bash
git clone https://github.com/dean815/cashortrade-search.git
cd cashortrade-search
pip install -e .
\```

This installs a `cashortrade-search` command. (You can also run it directly
without installing: `python tickets.py "URL"`.)

## Usage

\```
cashortrade-search "URL1" ["URL2" ...] [options]
\```

\```bash
cashortrade-search "https://cashortrade.org/phish-at-sphere-tickets/event/<uuid>"
cashortrade-search "URL1" "URL2" --max-price 200 --sort price
cashortrade-search "URL" --section 108 109 110 --type sale miracle
cashortrade-search "URL" --tickets 2-4 --sort date
cashortrade-search "URL1" "URL2" --group-by-event
cashortrade-search "URL" --terminal --sold --sort price-desc
\```

### Options

| Flag | Description |
|---|---|
| `urls` | One or more CashorTrade event URLs (required) |
| `--type {sale,trade,miracle}` | Listing types to show (default: `sale miracle`) |
| `--tickets N` or `N-M` | Exact ticket count or range, e.g. `2` or `2-4` |
| `--section ...` | Filter by section(s), partial match, e.g. `108 109 GA` |
| `--row N` or `N-M` | Filter by row, e.g. `5` or `1-10` (GA/floor rows always pass) |
| `--min-price` / `--max-price` | Price bounds per ticket |
| `--show-sold` / `--sold` | Also show a separate "sold" section |
| `--show-only-sold` | Show only sold listings |
| `--sort {price,price-desc,date,date-asc}` | Sort order (default: `price`) |
| `--terminal` | Print a `rich` table instead of opening HTML (default: HTML) |
| `--group-by-event` | Separate tables per event instead of one merged table |

## Output

By default, results open as a self-contained, sortable HTML file in your
browser (click any column header to sort). Pass `--terminal` for a `rich`
table in your terminal instead.

![Sample HTML output](docs/demo-screenshot.png)

## How this was built

This repo follows a spec-then-plan workflow before any feature lands —
see [`docs/superpowers/`](docs/superpowers/) for the design specs and
task-by-task implementation plans this tool was actually built from.

## License

MIT — see [LICENSE](LICENSE).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README"
```

---

### Task 5: Add pyproject.toml

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "cashortrade-search"
version = "0.1.0"
description = "Search, filter, and sort ticket listings from CashorTrade.org across one or more events — sortable HTML output or a rich terminal view."
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Dean Hicks" }]
dependencies = [
    "requests>=2.31",
    "rich>=13.0",
]

[project.scripts]
cashortrade-search = "tickets:main"

[tool.setuptools]
py-modules = ["tickets"]
```

`[tool.setuptools] py-modules = ["tickets"]` is required — `tickets.py`'s filename doesn't match the normalized project name (`tickets` vs `cashortrade-search`), so setuptools' automatic single-module discovery won't find it without this explicit declaration.

- [ ] **Step 2: Verify — install and run the console script**

```bash
pip install -e .
cashortrade-search --help
```

Expected: help text prints with no import errors, and `cashortrade-search` resolves as a real command (not just `python tickets.py`).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add pyproject.toml with console script entry point"
```

---

### Task 6: Add demo screenshot generation script

**Files:**
- Create: `scripts/gen_demo_html.py`

- [ ] **Step 1: Write the script**

```python
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
```

- [ ] **Step 2: Verify — run the script and check its output**

```bash
python scripts/gen_demo_html.py
grep -q "Phish at Madison Square Garden" docs/demo.html && echo OK
```

No browser/screenshot step here — `docs/demo-screenshot.png` is captured manually after this PR merges, not part of this task. `docs/demo.html` is gitignored (Task 3) and should NOT be committed.

- [ ] **Step 3: Commit**

```bash
git add scripts/gen_demo_html.py
git commit -m "chore: add demo HTML generation script"
```

---

### Task 7: Final verification

**Files:** None (testing only)

- [ ] **Step 1: Fresh-install smoke test**

```bash
pip install -e .
cashortrade-search --help
python scripts/gen_demo_html.py
```

Expected: all three succeed with no errors, `docs/demo.html` is created (and remains untracked per `.gitignore`).

- [ ] **Step 2: Confirm README renders sensibly on GitHub**

The `![Sample HTML output](docs/demo-screenshot.png)` link will show as a broken image until the follow-up manual step adds the PNG — this is expected and documented, not a defect to fix in this PR.
