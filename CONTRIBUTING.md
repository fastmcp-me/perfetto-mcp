# Contributing to Perfetto MCP

Thanks for your interest in improving Perfetto MCP! This guide helps you set up the project quickly and shows how to add a new MCP tool.

## Quick start: clone and install

```bash
# 1) Fork (recommended), then clone your fork
# Replace with your fork URL if different
git clone https://github.com/antarikshc/perfetto-mcp.git
cd perfetto-mcp

# 2) Install dependencies (creates .venv via uv)
uv sync

# 3) Run the MCP server (stdio)
# Dev mode with extras:
uv run mcp dev main.py
# Plain stdio:
uv run python main.py

# 4) Run tests (when present)
uv run pytest -q
```

Tips
- Add deps: `uv add <package>` (updates `pyproject.toml` and `uv.lock`).
- Target runtime: Python 3.13 (see `.python-version`).

## Development workflow

- Create a feature branch from `main`.
- Use Conventional Commits (e.g., `feat: add thread contention analyzer`, `fix: handle missing frame timeline`).
- Keep PRs focused; include purpose, summary of changes, and usage notes when outputs change.

## Project layout

```
src/perfetto_mcp/
├── server.py                 # MCP server wiring; registers tools via @mcp.tool
├── connection_manager.py     # Persistent TraceProcessor connection management
├── tools/                    # Individual tool implementations
│   ├── base.py               # BaseTool + ToolError + envelope helpers
│   ├── find_slices.py        # Example tool
│   └── ...
└── resource/                 # MCP resources (concept docs, links)
```

## How to add a new MCP tool

Add the tool under `src/perfetto_mcp/tools/` and register it in `src/perfetto_mcp/server.py`.

### 1) Implement the tool class

- Inherit from `BaseTool` (provides connection management and a standard JSON envelope).
- Validate inputs early; raise `ToolError("INVALID_PARAMETERS", ...)` for bad inputs.
- Use `run_formatted(trace_path, process_name, op)` to return the envelope.

Example: `src/perfetto_mcp/tools/my_new_tool.py`

```python
from typing import Optional, Dict, Any
from .base import BaseTool, ToolError

class MyNewTool(BaseTool):
    def my_new_tool(
        self,
        trace_path: str,
        process_name: Optional[str] = None,
        threshold_ms: float = 50.0,
    ) -> str:
        try:
            threshold = float(threshold_ms)
        except Exception:
            raise ToolError("INVALID_PARAMETERS", "threshold_ms must be numeric")

        def _operation(tp) -> Dict[str, Any]:
            # Use tp.query(...) to build your payload (no envelope here)
            return {
                "filters": {"processName": process_name, "thresholdMs": threshold},
                "summary": {"total": 0},
                "items": [],
                "notes": [],
                "dataDependencies": ["slice"],
            }

        return self.run_formatted(trace_path, process_name, _operation)
```

### 2) Register the function in the server

Edit `src/perfetto_mcp/server.py` inside `create_server()`:

```python
from .tools.my_new_tool import MyNewTool

# ... inside create_server()
my_new_tool = MyNewTool(connection_manager)

@mcp.tool()
def my_new_tool_fn(
    trace_path: str,
    process_name: str | None = None,
    threshold_ms: float = 50.0,
) -> str:
    """Explain when to use, parameters, and output at a glance."""
    return my_new_tool.my_new_tool(trace_path, process_name, threshold_ms)
```

Guidelines
- Mirror the existing tools’ docstring style (WHEN TO USE, OUTPUT expectations).
- Return concise, structured results (ids, timestamps in ms) for easy cross‑tool correlation.
- Validate and clamp user inputs (limits, ranges); avoid unsafe SQL.

### 3) Document and test

- Add a short entry to `README.md` describing the new tool.
- Add tests under `tests/test_<tool>.py` covering happy path and input validation.

```bash
uv run pytest -q -k my_new_tool
```

## Code style

- Python (PEP 8), 4‑space indent, ~100‑char lines.
- Type hints for public APIs; clear naming (snake_case for functions/vars, CapWords for classes).
- Use guard clauses and explicit error messages; don’t swallow exceptions.

## PR checklist

- [ ] Feature branch with Conventional Commit history
- [ ] Code compiles and server starts (`uv run mcp dev main.py`)
- [ ] Tests added/updated and passing (`uv run pytest -q`)
- [ ] README/docs updated as needed

## Security & traces

- Do not commit trace files. Use local absolute paths; they’re ignored by VCS.
- Validate inputs and keep row/record limits reasonable.

## References

- MCP Python SDK contributing: https://github.com/modelcontextprotocol/python-sdk/blob/main/CONTRIBUTING.md
- Figma Context MCP contributing: https://github.com/GLips/Figma-Context-MCP/blob/main/CONTRIBUTING.md
- Microsoft Playwright MCP contributing: https://github.com/microsoft/playwright-mcp/blob/main/CONTRIBUTING.md

Thanks again for contributing!
