"""SQL query tool for executing arbitrary queries on traces."""

import json
import logging
from .base import BaseTool
from ..utils.query_helpers import add_limit_to_query, validate_sql_query, format_query_result_row

logger = logging.getLogger(__name__)


class SqlQueryTool(BaseTool):
    """Tool for executing arbitrary SQL queries on Perfetto traces."""
    
    def execute_sql_query(self, trace_path: str, sql_query: str) -> str:
        """Implementation for executing SQL queries with validation and result formatting."""
        # Validate query for safety
        if not validate_sql_query(sql_query):
            error_result = {
                "success": False,
                "error": "Query validation failed",
                "message": "Only SELECT queries are allowed for security reasons",
                "query": sql_query
            }
            return json.dumps(error_result, indent=2)
        
        # Add limit if not present
        limited_query = add_limit_to_query(sql_query, limit=50)
        
        def _execute_sql_operation(tp):
            """Internal operation to execute SQL query."""
            # Execute the query
            qr_it = tp.query(limited_query)
            
            # Collect results
            rows = []
            columns = None
            
            for row in qr_it:
                # Get column names from the first row
                if columns is None:
                    columns = list(row.__dict__.keys())
                
                # Convert row to dictionary
                row_dict = format_query_result_row(row, columns)
                rows.append(row_dict)
                
                # Enforce the 50 row limit even if the query had a higher LIMIT
                if len(rows) >= 50:
                    break
            
            # Create result dictionary
            result = {
                "success": True,
                "query": limited_query,
                "columns": columns if columns else [],
                "rows": rows,
                "row_count": len(rows),
                "limited_to_50": len(rows) == 50
            }
            
            return json.dumps(result, indent=2)
        
        try:
            return self.execute_with_connection(trace_path, _execute_sql_operation)
        except FileNotFoundError as fnf:
            error_result = {
                "success": False,
                "error": "File not found",
                "message": f"Failed to open the trace file. Please double-check the trace_path. Error: {str(fnf)}"
            }
            return json.dumps(error_result, indent=2)
        except Exception as e:
            error_result = {
                "success": False,
                "error": type(e).__name__,
                "message": f"Query execution failed: {str(e)}",
                "query": limited_query
            }
            return json.dumps(error_result, indent=2)
