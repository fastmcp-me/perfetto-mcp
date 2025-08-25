# Repository Guidelines

## Project Structure & Module Organization
- `main.py`: MCP server entrypoint exposing Perfetto tools (`@mcp.tool`).
- `pyproject.toml`: Project metadata and dependencies (Python `>=3.13`).
- `uv.lock`: Locked dependency set for `uv`.
- `README.md`: Project overview (expand as features grow).
- Tests: Not yet present; prefer `tests/` when added.

## Build, Test, and Development Commands
- Install deps (uv): `uv sync` — creates `.venv` and installs locked deps.
- Run server (dev): `uv run mcp dev main.py` — runs the MCP server over stdio with dev tooling.
- Run server (plain): `uv run python main.py` — starts the MCP server on stdio.
- Add a package: `uv add <pkg>` — updates `pyproject.toml` and `uv.lock`.
- Tests (when added): `uv run pytest -q` — executes the test suite.

## Coding Style & Naming Conventions
- Python style: PEP 8, 4‑space indentation, line length ~100.
- Naming: `snake_case` for functions/vars, `CapWords` for classes, module files in `snake_case`.
- Type hints: Use `typing` annotations and docstrings for public tools.
- MCP tools: Decorate with `@mcp.tool()` and return concise, user‑facing strings or JSON.

## Testing Guidelines
- Framework: Prefer `pytest` with tests under `tests/` mirroring module names.
- Naming: `test_<module>.py` and `test_<behavior>()` function names.
- Coverage: Aim for critical path coverage of tool functions and error handling.
- Running: `uv run pytest -q` (add `-k <expr>` to filter).

## Commit & Pull Request Guidelines
- Commits: Follow Conventional Commits (e.g., `feat: add slice info`, `fix: close TraceProcessor on error`).
- PRs: Include purpose, linked issues, summary of changes, and usage notes or screenshots (when UI/CLI output changes).
- Scope: Keep PRs small and focused; add tests and docs alongside code.

## Security & Configuration Tips
- Python: Use `.python-version` (3.13) to align environments; prefer `uv` for reproducibility.
- Perfetto: Never commit trace files; add large traces to `.gitignore` and reference local paths.
- SQL safety: Avoid interpolating untrusted input into queries; validate/escape user‑provided strings and keep row limits (e.g., `LIMIT 50`).

## Extending the MCP Server
- Add tools in `main.py` or a new module; register with `@mcp.tool()`.
- Ensure resources are closed (`TraceProcessor.close()` in `finally`).
- Provide clear parameter docs and predictable return shapes.
