# Testing, Linting, and CI — Design Spec

## Goal

Add a proportionate engineering-depth signal to `cashortrade-search`: unit test coverage for the pure/testable logic, lint + lenient type-checking, and a CI workflow that runs all three on every push/PR — without a full typing pass or any refactor of working code.

## Current State

- No tests, no CI, no lint config anywhere in the repo.
- `pyproject.toml` exists (added by the preceding "Portfolio Packaging & Docs" PR) with `[project]`/`[build-system]`/`[project.scripts]`/`[tool.setuptools]` sections only — no dev-tooling sections yet.
- One live lint finding, confirmed via a `ruff check` dry-run against the current file: an unnecessary `f` prefix on `f"include_sold=true"` at `tickets.py:151` (ruff rule `F541`) — zero behavior change to fix.
- The file uses `l` as its loop variable for "listing" in ~25 places (ruff rule `E741`, ambiguous variable name) — a real style issue, but renaming all of them is a refactor, not a tooling-addition task; out of scope for this PR (see below).
- The file has partial type hints already (e.g. `list[dict]`, `-> tuple[str, list[dict], str]`) but no full typing coverage — going fully strict is a bigger lift than this pass warrants.

**Precondition:** this PR's `pyproject.toml` changes are purely additive (new top-level tables only) and depend on the "Portfolio Packaging & Docs" PR having already merged to `main` — branching before that merges risks a conflicting/duplicate `pyproject.toml`.

## Changes

### 1. Lint fix

Remove the unnecessary `f` prefix at `tickets.py:151` — the only real finding from the ruff dry-run.

### 2. pyproject.toml — dev tooling (additive)

Add `[project.optional-dependencies].dev` (pytest, ruff, mypy, types-requests), `[tool.pytest.ini_options]`, `[tool.ruff]` + `[tool.ruff.lint]` (with `E741` explicitly ignored, and *why*, as an inline comment), and `[tool.mypy]` in lenient mode (`ignore_missing_imports = true`, not strict). None of this PR's TOML additions touch a line the packaging PR already wrote — see the implementation plan for the exact diff shape.

### 3. Unit tests

`tests/test_tickets.py` — tests for the pure functions only: `parse_tickets_arg`, `apply_filters`, `sort_listings`, `format_listed`, `parse_listing`. All inputs are synthetic/hand-built; no live CashorTrade API calls, no network mocking framework needed since these functions take plain data in and return plain data out.

One test-design detail worth calling out: `format_listed()`'s output depends on the local system timezone (`.astimezone()` with no fixed zone), which differs between a developer's machine and GitHub Actions' `TZ=UTC` runners. Tests for it assert output *shape* (non-empty, contains "am"/"pm"), not an exact string, to avoid flaking in CI.

### 4. CI workflow

`.github/workflows/ci.yml` — on push to `main` and on PRs, across a 2-version Python matrix (3.11, 3.13, matching the pattern already used in Dean's `amsync` CI): install with dev extras, `ruff check`, `mypy tickets.py`, `pytest`.

## What Stays the Same

- All CLI behavior and output — the only functional change in this entire PR is the one-line `F541` fix, which is a no-op.
- `tickets.py`'s `l`-as-listing-variable style (see Out of Scope).

## Architecture

No new runtime code paths. Additions: one file (`tests/test_tickets.py`), one file (`.github/workflows/ci.yml`), one line fixed in `tickets.py`, and additive-only changes to `pyproject.toml`.

## Out of Scope

- Renaming `l` variables to satisfy `E741` — a legitimate readability issue, but a separate, explicitly-scoped refactor if Dean wants it later, not bundled into a tooling-addition PR.
- Full strict mypy typing.
- Any test coverage of the network-calling functions (`search_events`, `extract_event_from_url`, `fetch_all_listings`) — would require a mocking framework and live-API-shaped fixtures; out of scope for this pass.
