"""System Resources

Provides MCP resources for index introspection.
"""

import json


def register_system_tools(
    mcp,
    mpep_index,
    log_info,
    log_error,
):
    """Register system resources with the MCP server."""

    @mcp.resource("mpep://index/stats")
    def get_index_stats() -> str:
        """Statistics about the MPEP index."""
        stats = {
            "total_chunks": len(mpep_index.chunks),
            "total_metadata": len(mpep_index.metadata),
            "index_exists": mpep_index.index is not None,
            "sections": len({m["section"] for m in mpep_index.metadata}),
        }
        return json.dumps(stats, indent=2)
