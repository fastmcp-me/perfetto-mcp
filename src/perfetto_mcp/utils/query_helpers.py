"""Query helper utilities for SQL processing."""

import re
import logging

logger = logging.getLogger(__name__)


def add_limit_to_query(sql_query: str, limit: int = 50) -> str:
    """Add LIMIT clause to SQL query if it doesn't already have one.
    
    Args:
        sql_query: The SQL query string
        limit: Maximum number of rows to return (default: 50)
        
    Returns:
        str: Query with LIMIT clause added
    """
    query_upper = sql_query.upper()
    if 'LIMIT' not in query_upper:
        # Remove trailing semicolon if present
        if sql_query.rstrip().endswith(';'):
            sql_query = sql_query.rstrip()[:-1]
        sql_query = f"{sql_query} LIMIT {limit}"
    
    return sql_query


def validate_sql_query(sql_query: str) -> bool:
    """Basic validation of SQL query for safety.
    
    Args:
        sql_query: The SQL query to validate
        
    Returns:
        bool: True if query appears safe, False otherwise
    """
    if not sql_query or not sql_query.strip():
        return False
    
    # Convert to uppercase for checking
    query_upper = sql_query.upper().strip()
    
    # Only allow SELECT statements for safety
    if not query_upper.startswith('SELECT'):
        logger.warning(f"Non-SELECT query rejected: {sql_query[:50]}...")
        return False
    
    # Block potentially dangerous keywords
    dangerous_keywords = [
        'DROP', 'DELETE', 'INSERT', 'UPDATE', 'ALTER', 'CREATE', 
        'TRUNCATE', 'EXEC', 'EXECUTE', 'PRAGMA'
    ]
    
    for keyword in dangerous_keywords:
        if keyword in query_upper:
            logger.warning(f"Query contains dangerous keyword '{keyword}': {sql_query[:50]}...")
            return False
    
    return True


def format_query_result_row(row, columns: list) -> dict:
    """Format a query result row into a dictionary.
    
    Args:
        row: Query result row object
        columns: List of column names
        
    Returns:
        dict: Row data as dictionary
    """
    row_dict = {}
    for col in columns:
        value = getattr(row, col)
        # Convert any non-JSON-serializable types to strings
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        row_dict[col] = value
    
    return row_dict
