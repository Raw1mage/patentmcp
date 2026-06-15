#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from mcp_server.bigquery_search import BigQueryPatentSearch

    print("Creating BigQueryPatentSearch instance...")
    searcher = BigQueryPatentSearch()

    print("Checking availability...")
    status = searcher.check_availability()

    print("\nStatus:")
    for key, value in status.items():
        print(f"  {key}: {value}")

except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()
