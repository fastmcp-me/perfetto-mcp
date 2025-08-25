"""Base tool class for all Perfetto MCP tools."""

import logging
from typing import Callable, Any
from ..connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class BaseTool:
    """Base class for all Perfetto tools with connection management."""
    
    def __init__(self, connection_manager: ConnectionManager):
        """Initialize the tool with a connection manager.
        
        Args:
            connection_manager: Shared connection manager instance
        """
        self.connection_manager = connection_manager
    
    def execute_with_connection(self, trace_path: str, operation: Callable) -> Any:
        """Execute operation with managed connection and auto-reconnection.
        
        Args:
            trace_path: Path to the trace file
            operation: Function that takes a TraceProcessor and returns a result
            
        Returns:
            Any: Result from the operation
            
        Raises:
            FileNotFoundError: If trace file doesn't exist
            ConnectionError: If connection fails
            Exception: Any other errors from the operation
        """
        try:
            tp = self.connection_manager.get_connection(trace_path)
            return operation(tp)
        except (ConnectionError, Exception) as e:
            # Check if this is a connection-related error that might benefit from reconnection
            if self._should_retry_on_error(e):
                logger.info(f"Attempting reconnection due to error: {e}")
                try:
                    tp = self.connection_manager._reconnect(trace_path)
                    return operation(tp)
                except Exception as reconnect_error:
                    logger.error(f"Reconnection attempt failed: {reconnect_error}")
                    # Raise the original error if reconnection fails
                    raise e
            else:
                # Don't retry for errors like FileNotFoundError
                raise e
    
    def _should_retry_on_error(self, error: Exception) -> bool:
        """Determine if an error should trigger a reconnection attempt.
        
        Args:
            error: The exception that occurred
            
        Returns:
            bool: True if reconnection should be attempted
        """
        # Don't retry for file not found errors
        if isinstance(error, FileNotFoundError):
            return False
            
        # Retry for connection errors or other exceptions that might be connection-related
        if isinstance(error, ConnectionError):
            return True
            
        # Check if error message suggests connection issues
        error_str = str(error).lower()
        connection_indicators = [
            'connection', 'broken pipe', 'socket', 'network', 'timeout',
            'disconnected', 'closed', 'reset', 'refused'
        ]
        
        for indicator in connection_indicators:
            if indicator in error_str:
                return True
                
        return False
