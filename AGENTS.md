# Repository Guidelines

## Project Structure & Module Organization
- `main.py`: MCP server entrypoint exposing Perfetto tools via `@mcp.tool`.
- `pyproject.toml`: Project metadata, dependencies (Python >= 3.13), `uv` config.
- `uv.lock`: Locked dependency set for reproducible installs.
- `README.md`: Project overview and usage notes.
- `tests/`: Add when present; mirror module names (e.g., `test_main.py`).

## Build, Test, and Development Commands
- Install deps: `uv sync` — creates `.venv` and installs locked deps.
- Run server (dev): `uv run mcp dev main.py` — stdio server with dev tooling.
- Run server (plain): `uv run python main.py` — stdio server without extras.
- Add a package: `uv add <pkg>` — updates `pyproject.toml` and `uv.lock`.
- Run tests: `uv run pytest -q` (filter: `-k <expr>`). Example: `uv run pytest -q -k slice`.

## Coding Style & Naming Conventions
- Python (PEP 8): 4-space indent, ~100 char lines.
- Naming: `snake_case` for functions/vars, `CapWords` for classes, files in `snake_case`.
- Types & docs: Add type hints; public MCP tools include short docstrings.
- MCP tools: Decorate with `@mcp.tool()` and return concise strings or JSON.

## Testing Guidelines
- Framework: `pytest` with tests under `tests/` mirroring modules.
- Names: Files `test_<module>.py`; tests `test_<behavior>()`.
- Coverage: Focus on tool happy paths and error handling.
- Run: `uv run pytest -q` (CI-friendly output).

## Commit & Pull Request Guidelines
- Commits: Conventional Commits, e.g., `feat: add slice info`, `fix: close TraceProcessor on error`.
- PRs: Include purpose, linked issues, summary of changes, and usage notes or screenshots when output changes.
- Scope: Keep changes focused; include tests and docs with code.

## Security & Configuration Tips
- Envs: Use `.python-version` (3.13) and `uv` for reproducibility.
- Traces: Do not commit trace files; prefer local paths and add to `.gitignore`.
- SQL safety: Validate input, avoid interpolation, and keep row limits (e.g., `LIMIT 50`).

## Extending the MCP Server
- Add tools in `main.py` or a new module; register with `@mcp.tool()`.
- Manage resources: Close `TraceProcessor` in `finally` blocks.
- UX: Provide clear parameter docs and predictable return shapes.

