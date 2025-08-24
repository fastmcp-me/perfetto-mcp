from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Perfetto MCP")


@mcp.tool()
def test() -> str:
    """Testing whether MCP works"""
    return "MCP works!"


if __name__ == "__main__":
    mcp.run(transport="stdio")
