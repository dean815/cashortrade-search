# Portfolio Packaging & Docs — Design Spec

## Goal

Bring `cashortrade-search` (formerly `ticket-tool`) up to hiring-manager-grade "clone and run it" standard: a fresh clone should install cleanly, run on any OS, and explain itself in 30 seconds via README — with no fabricated claims, no scope creep into unrelated refactors.

## Current State

- Single-file CLI (`tickets.py`) — works when `requests` and `rich` happen to already be installed, but the repo declares no dependencies anywhere (no `requirements.txt`, `pyproject.toml`, or `setup.py`).
- No `README.md`, no `LICENSE`, no `.gitignore`.
- Two portability bugs: `tempfile.NamedTemporaryFile(..., dir="/tmp", ...)` hardcodes a POSIX path; `%-I` in strftime calls is glibc/POSIX-only and raises on Windows.
- Repo is public. GitHub repo has already been renamed `ticket-tool` → `cashortrade-search` and its description corrected (done outside this plan, via `gh repo rename`/`gh repo edit`).
- Existing convention in this repo: `docs/superpowers/specs/2026-04-16-multi-event-html-output-design.md` + `docs/superpowers/plans/2026-04-16-multi-event-html-output.md` — this spec/plan pair follows that same convention.

## Changes

### 1. Cross-platform portability fixes

- `tickets.py` — the HTML-output temp file no longer hardcodes `dir="/tmp"`; it uses the system temp dir via `tempfile`'s own default.
- `tickets.py` — every `%-I` strftime usage (`format_listed()` and the HTML-rendering helpers) is replaced with a portable equivalent that doesn't depend on glibc's non-standard `%-I` flag.

### 2. LICENSE

Root `LICENSE` file, MIT, `Copyright (c) 2026 Dean Hicks` — matches the license already used in Dean's other portfolio repos (e.g. `auto-bouncer`).

### 3. .gitignore

Root `.gitignore` covering standard Python artifacts (`__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `.venv/`) plus `docs/demo.html` (a generated-not-committed artifact from the demo script below). Added now, ahead of the follow-up testing/linting PR, so dev-tool cache directories never get committed.

### 4. README.md

What the tool does, why it was built (a personal tool for hunting CashorTrade ticket listings faster than manually refreshing a browser tab), install instructions (`pip install -e .`), a full usage/options reference, a screenshot of the HTML output, and a pointer to `docs/superpowers/` inviting readers to see the design-spec-then-plan workflow this tool is built with. No fabricated metrics, users, or employer claims — everything traces to the code itself or Dean's own stated reason for building it.

### 5. pyproject.toml

Modern Python packaging: `[project]` metadata (name `cashortrade-search`, runtime deps `requests`+`rich`, Python ≥3.11), a `[project.scripts]` console entry point so `pip install -e .` yields a real `cashortrade-search` command, and an explicit `[tool.setuptools] py-modules = ["tickets"]` declaration (required because the module filename doesn't match the normalized project name, so setuptools' automatic single-module discovery won't find it otherwise).

This PR adds only the `[project]`/`[build-system]`/`[project.scripts]`/`[tool.setuptools]` sections. Dev-tooling sections (`[project.optional-dependencies].dev`, `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`) are added in a follow-up PR (see the testing/linting/CI spec) to keep the two PRs' diffs to `pyproject.toml` non-overlapping.

### 6. Demo screenshot generation script

`scripts/gen_demo_html.py` builds synthetic sample listings (fabricated event/prices/sections/sold-status — no live CashorTrade API call) shaped like `parse_listing()`'s real output, and calls the existing `render_html()` to produce `docs/demo.html`. This script is the only thing this PR is responsible for regarding the screenshot — actually capturing `docs/demo-screenshot.png` (referenced from the README) requires driving a real browser, which happens as a manual follow-up after this PR merges, not as part of this PR. The README's screenshot reference is an intentional forward-reference, not a build failure.

## What Stays the Same

- All existing CLI behavior, filters, sorts, and output modes — this PR is purely additive/packaging, no feature changes.
- The `tickets.py` module filename and its internal function names/signatures.

## Architecture

No new runtime code paths. Additions are: two small in-place edits to `tickets.py` (portability fixes only), and five new files (`LICENSE`, `.gitignore`, `README.md`, `pyproject.toml`, `scripts/gen_demo_html.py`).

## Out of Scope

- Testing, linting, type-checking, CI — covered by a separate follow-up spec/plan (`2026-07-14-testing-linting-and-ci-design.md`).
- Splitting `tickets.py` into multiple modules.
- Multi-site support, any backend/server component.
- Capturing the actual `docs/demo-screenshot.png` image (manual follow-up, not part of this PR).
