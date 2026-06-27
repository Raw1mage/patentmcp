"""
Google Patents (patents.google.com) integration.

Uses the public /xhr/query JSON endpoint that backs the Google Patents web UI.
Provides relevance-ranked search (US/CN/TW/...), representative-figure thumbnails,
and full-PDF retrieval — none of which BigQuery offers cheaply.

NOTE: This is an unofficial endpoint. Be a good citizen: throttle requests,
send a browser-like User-Agent, and do not hammer it.
"""

from patent_mcp_server.gpatents.client import GooglePatentsClient

__all__ = ["GooglePatentsClient"]
