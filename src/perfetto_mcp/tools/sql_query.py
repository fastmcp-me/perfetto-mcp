"""SQL query tool for executing arbitrary queries on traces."""

import json
import logging
from typing import Optional
from .base import BaseTool, ToolError
from ..utils.query_helpers import (
    validate_sql_query,
    format_query_result_row,
    approximate_statement_count,
    detect_last_statement_type,
)

logger = logging.getLogger(__name__)


class SqlQueryTool(BaseTool):
    """Tool for executing arbitrary SQL queries on Perfetto traces."""

    def execute_sql_query(self, trace_path: str, sql_query: str, process_name: Optional[str] = None) -> str:
        """Execute a validated PerfettoSQL script and return a unified JSON envelope."""
        # Permissive validation with guardrails (size / statement count)
        if not validate_sql_query(sql_query):
            envelope = self._make_envelope(
                trace_path=trace_path,
                process_name=process_name,
                success=False,
                error=self._error(
                    "INVALID_QUERY",
                    "SQL script rejected by guardrails",
                    sql_query,
                ),
                result={"query": sql_query},
            )
            return json.dumps(envelope, indent=2)

        def _execute_sql_operation(tp):
            """Internal operation to execute SQL query and build result payload."""
            # Execute the script as-is (no automatic LIMIT)
            qr_it = tp.query(sql_query)

            # Collect results
            rows = []
            columns = None

            for row in qr_it:
                if columns is None:
                    columns = list(row.__dict__.keys())
                row_dict = format_query_result_row(row, columns)
                rows.append(row_dict)

            # Compute metadata
            try:
                stmt_count = approximate_statement_count(sql_query)
            except Exception:
                stmt_count = None
            try:
                last_stmt = detect_last_statement_type(sql_query)
            except Exception:
                last_stmt = None

            returns_rows = bool(columns)

            # Result payload only; envelope is added by run_formatted
            payload = {
                "query": sql_query,
                "columns": columns if columns else [],
                "rows": rows,
                "rowCount": len(rows),
                "scriptStatementCount": stmt_count,
                "lastStatementType": last_stmt,
                "returnsRows": returns_rows,
            }
            return payload

        # Use the unified formatter with connection management
        return self.run_formatted(trace_path, process_name, _execute_sql_operation)
