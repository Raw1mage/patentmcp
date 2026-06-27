"""
EPO Open Patent Services (OPS) v3.2 integration.

Official, ToS-clean global patent API. Fills patentmcp's gaps that Google/GPSS
don't cover in-band: INPADOC patent family (unifies US/CN/TW members of one
invention — better than BigQuery's split family_id), forward/backward citations,
official bibliographic data + abstract, and legal status.

Auth: OAuth2 client_credentials with a Consumer Key + Secret (read from
EPO_CONSUMER_KEY / EPO_CONSUMER_SECRET). Free "Non-paying" tier = 3.5 GB/week.
"""

from patent_mcp_server.epo.client import EPOClient

__all__ = ["EPOClient"]
