"""Register Perfetto trace analysis documentation as a URL resource."""

import logging
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_trace_analysis_resource(mcp: FastMCP) -> None:
    """Register URL resource for Perfetto trace analysis getting started guide.
    
    - Points to official Perfetto documentation
      URI: resource://perfetto-docs/trace-analysis-getting-started
    """
    
    @mcp.resource(
        "resource://perfetto-docs/trace-analysis-getting-started",
        name="perfetto-trace-analysis-getting-started",
        title="Perfetto Trace Analysis Getting Started",
        description="Official Perfetto documentation for getting started with trace analysis workflow and tools.",
        mime_type="text/markdown",
    )
    def get_trace_analysis_docs() -> str:
        """Return URL reference to the official Perfetto trace analysis documentation."""
        return """# Perfetto Trace Analysis Getting Started

This resource points to the official Perfetto documentation for trace analysis.

**Official Documentation URL:** https://perfetto.dev/docs/analysis/getting-started

## Quick Summary

The official guide covers:

- **The Challenge**: Making sense of raw trace data
- **The Solution**: Trace Processor and PerfettoSQL
- **Analysis Workflow**: From interactive exploration to automated analysis
- **Tools Overview**: Perfetto UI, trace_processor shell, Python/C++ APIs
- **Next Steps**: Learning PerfettoSQL syntax and exploring tools

## Key Concepts for MCP Usage

When using this MCP server's tools, the official documentation provides essential context for:

1. **PerfettoSQL**: The SQL dialect used by `execute_sql_query` tool
 - https://perfetto.dev/docs/analysis/perfetto-sql-getting-started
2. **Trace Processor**: The engine behind all MCP tools in this server
 - https://perfetto.dev/docs/analysis/trace-processor-python
3. **Analysis Workflow**: How to progress from basic to advanced analysis
4. **Standard Library**: Pre-built functions available in queries. For better sql analysis, use standard library tables and aggregated results rather than querying and processing direct sql results.
 - https://perfetto.dev/docs/analysis/stdlib-docs
 - https://perfetto.dev/docs/analysis/stdlib-docs#package-prelude

## Recommended Reading Order

1. Start with the getting started guid`e (link above)
2. Learn PerfettoSQL syntax and concepts  
3. Explore the standard library modules
4. Try the interactive tools alongside this MCP server

For the most up-to-date information, always refer to the official documentation at https://perfetto.dev/docs/analysis/getting-started
"""