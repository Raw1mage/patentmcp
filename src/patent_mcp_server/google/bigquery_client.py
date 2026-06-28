"""
Client for accessing Google Patents Public Datasets via BigQuery.

This module provides async access to Google's comprehensive patent database
containing 90M+ patent publications from 17+ countries.
"""

import asyncio
import logging
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.auth import default
from google.cloud import bigquery

from patent_mcp_server.config import config
from patent_mcp_server.constants import GooglePatentsTables
from patent_mcp_server.util.errors import ApiError

logger = logging.getLogger(__name__)


class BudgetExceededError(Exception):
    """Raised when month-to-date BigQuery billed bytes exceed the configured
    monthly budget. Carries usage context so the tool layer can surface a
    structured, fail-fast error (no silent fallback)."""

    def __init__(self, used_bytes: int, budget_bytes: int, source: str):
        self.used_bytes = used_bytes
        self.budget_bytes = budget_bytes
        self.source = source
        super().__init__(
            f"BigQuery monthly budget exceeded: "
            f"{used_bytes} / {budget_bytes} bytes billed this month "
            f"(usage source: {source}). All BigQuery queries are blocked. "
            f"Use GPSS/EPO/PPUBS instead."
        )


def _current_month_key() -> str:
    """Return the current UTC month key as 'YYYYMM'."""
    return datetime.now(timezone.utc).strftime("%Y%m")


class BigQueryUsageLedger:
    """Local SQLite cache of month-to-date BigQuery billed bytes.

    Cheap, low-latency record of usage the MCP itself generated, plus a slot
    to store the authoritative INFORMATION_SCHEMA reconciled value and the
    timestamp of the last reconcile. Thread-safe (a single lock guards all
    writes; the BigQuery client runs queries in a thread pool)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monthly_usage (
                    month_key TEXT PRIMARY KEY,
                    local_bytes INTEGER NOT NULL DEFAULT 0,
                    reconciled_bytes INTEGER,
                    reconciled_at REAL
                )
                """
            )

    def add_local_usage(self, billed_bytes: int) -> None:
        """Accumulate billed bytes from a query this MCP just executed."""
        if billed_bytes <= 0:
            return
        month_key = _current_month_key()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO monthly_usage (month_key, local_bytes)
                VALUES (?, ?)
                ON CONFLICT(month_key) DO UPDATE SET
                    local_bytes = local_bytes + excluded.local_bytes
                """,
                (month_key, billed_bytes),
            )

    def set_reconciled(self, reconciled_bytes: int) -> None:
        """Store the authoritative INFORMATION_SCHEMA value for this month."""
        month_key = _current_month_key()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO monthly_usage (month_key, reconciled_bytes, reconciled_at)
                VALUES (?, ?, ?)
                ON CONFLICT(month_key) DO UPDATE SET
                    reconciled_bytes = excluded.reconciled_bytes,
                    reconciled_at = excluded.reconciled_at
                """,
                (month_key, reconciled_bytes, time.time()),
            )

    def read_month(self) -> Dict[str, Any]:
        """Return this month's ledger row: local_bytes, reconciled_bytes,
        reconciled_at (all may be 0/None if nothing recorded yet)."""
        month_key = _current_month_key()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "SELECT local_bytes, reconciled_bytes, reconciled_at "
                "FROM monthly_usage WHERE month_key = ?",
                (month_key,),
            )
            row = cur.fetchone()
        if not row:
            return {"local_bytes": 0, "reconciled_bytes": None, "reconciled_at": None}
        return {
            "local_bytes": row[0] or 0,
            "reconciled_bytes": row[1],
            "reconciled_at": row[2],
        }


class GoogleBigQueryClient:
    """Client for accessing Google Patents Public Datasets via BigQuery."""

    def __init__(self):
        """Initialize BigQuery client with authentication."""
        self.project_id = config.GOOGLE_CLOUD_PROJECT
        self.dataset_id = config.BIGQUERY_DATASET
        self.location = config.BIGQUERY_LOCATION
        self.query_timeout = config.BIGQUERY_QUERY_TIMEOUT
        self.max_results = config.BIGQUERY_MAX_RESULTS
        self.max_bytes_billed = config.BIGQUERY_MAX_BYTES_BILLED
        self.monthly_budget_bytes = config.BIGQUERY_MONTHLY_BUDGET_BYTES
        self.reconcile_ttl_seconds = config.BIGQUERY_RECONCILE_TTL_SECONDS

        # Local month-to-date usage ledger (cheap cache). Best-effort: if the
        # ledger cannot be created we degrade to no local accounting rather
        # than failing the whole client.
        try:
            self.usage_ledger: Optional[BigQueryUsageLedger] = BigQueryUsageLedger(
                config.BIGQUERY_USAGE_DB_PATH
            )
        except Exception as e:
            logger.warning(f"BigQuery usage ledger unavailable: {str(e)}")
            self.usage_ledger = None

        # BigQuery client (sync API, we'll wrap in executor)
        try:
            # Set timeout for GCE metadata server queries to prevent hanging
            # when Google Cloud credentials are not available
            if "GCE_METADATA_TIMEOUT" not in os.environ:
                os.environ["GCE_METADATA_TIMEOUT"] = "5"

            credentials, project = default()
            self.client = bigquery.Client(
                credentials=credentials,
                project=self.project_id or project,
            )
            logger.info(
                f"Initialized Google BigQuery client for project: {self.project_id or project}"
            )
        except Exception as e:
            logger.warning(
                f"Google BigQuery client not available: {str(e)}. "
                "Google Patents features will be disabled. "
                "To enable, configure GOOGLE_CLOUD_PROJECT and GOOGLE_APPLICATION_CREDENTIALS "
                "environment variables. See README for setup instructions."
            )
            self.client = None

        # Thread pool for async execution
        self.executor = ThreadPoolExecutor(max_workers=4)

    async def query_async(
        self, query: str, parameters: Optional[List] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute BigQuery query asynchronously.

        Args:
            query: SQL query string
            parameters: Optional list of query parameters

        Returns:
            List of dictionaries representing query results
        """
        if not self.client:
            raise ValueError(
                "BigQuery client not initialized. Check Google Cloud credentials."
            )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            self.executor, self._execute_query, query, parameters
        )
        return result

    def _execute_query(
        self, query: str, parameters: Optional[List] = None,
        skip_budget_gate: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Execute BigQuery query (sync).

        Args:
            query: SQL query string
            parameters: Optional list of query parameters
            skip_budget_gate: Internal-only. Set True for the reconcile query
                (INFORMATION_SCHEMA), which is itself free and must run even
                when the budget is exhausted, otherwise we could never recover
                the authoritative usage number.

        Returns:
            List of dictionaries representing query results

        Raises:
            BudgetExceededError: if month-to-date billed bytes exceed the
                configured monthly budget. Hard-blocks ALL billable queries
                (fail-fast, no silent fallback).
        """
        # ── Budget gate (DD-3): hard-block when month-to-date usage exceeds
        #    the configured monthly budget. ──
        if not skip_budget_gate:
            usage = self._get_monthly_usage_sync()
            if usage["exceeded"]:
                raise BudgetExceededError(
                    used_bytes=usage["used_bytes"],
                    budget_bytes=usage["budget_bytes"],
                    source=usage["source"],
                )

        job_config = bigquery.QueryJobConfig(
            query_parameters=parameters or [],
            maximum_bytes_billed=self.max_bytes_billed,
        )

        try:
            query_job = self.client.query(
                query, job_config=job_config, location=self.location
            )

            results = query_job.result(timeout=self.query_timeout)

            # Convert to list of dicts
            rows = [dict(row) for row in results]

            # Record billed bytes into the local ledger (total_bytes_billed is
            # the billing-accurate figure; falls back to processed if absent).
            billed = getattr(query_job, "total_bytes_billed", None)
            if billed is None:
                billed = query_job.total_bytes_processed or 0
            if self.usage_ledger is not None and not skip_budget_gate:
                try:
                    self.usage_ledger.add_local_usage(int(billed))
                except Exception as e:
                    logger.warning(f"Failed to record BigQuery usage: {str(e)}")

            logger.info(
                f"Query executed successfully, returned {len(rows)} rows, "
                f"processed {query_job.total_bytes_processed} bytes, "
                f"billed {billed} bytes"
            )

            return rows

        except Exception as e:
            logger.error(f"BigQuery query failed: {str(e)}")
            raise

    def _reconcile_usage_sync(self) -> Optional[int]:
        """Query INFORMATION_SCHEMA.JOBS_BY_PROJECT for this month's authoritative
        SUM(total_bytes_billed). This query scans metadata only and is FREE.

        Returns the reconciled byte count, or None if the query fails
        (e.g. the service account lacks bigquery.jobs.list). Never raises;
        callers degrade to the local ledger on None."""
        if not self.client:
            return None
        month_key = _current_month_key()
        # JOBS_BY_PROJECT is region-qualified; self.location drives the view.
        region = (self.location or "US").lower()
        sql = f"""
        SELECT COALESCE(SUM(total_bytes_billed), 0) AS billed
        FROM `region-{region}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
        WHERE creation_time >= TIMESTAMP(@month_start)
          AND job_type = 'QUERY'
          AND state = 'DONE'
        """
        month_start = f"{month_key[:4]}-{month_key[4:]}-01"
        params = [
            bigquery.ScalarQueryParameter("month_start", "STRING", month_start)
        ]
        try:
            rows = self._execute_query(sql, params, skip_budget_gate=True)
            if rows:
                reconciled = int(rows[0].get("billed", 0) or 0)
                if self.usage_ledger is not None:
                    self.usage_ledger.set_reconciled(reconciled)
                return reconciled
        except Exception as e:
            logger.warning(
                f"BigQuery usage reconcile (INFORMATION_SCHEMA) failed: {str(e)}. "
                "Degrading to local ledger."
            )
        return None

    def _get_monthly_usage_sync(self) -> Dict[str, Any]:
        """Compute month-to-date usage with the hybrid strategy (DD-1/DD-2):
        trust the local ledger as a cheap cache, reconcile against the
        authoritative INFORMATION_SCHEMA view when the cache is stale (older
        than the reconcile TTL) or has never been reconciled.

        Returns:
            {
              used_bytes: int,            # the figure the gate acts on
              budget_bytes: int,
              exceeded: bool,
              source: str,                # authoritative | cached | cached-degraded | none
              last_reconciled_at: float|None,
            }
        """
        budget = self.monthly_budget_bytes
        if self.usage_ledger is None:
            # No ledger: try a live reconcile; if that fails too, we cannot
            # know usage. Per no-silent-fallback, treat unknown as NOT exceeded
            # but mark source=none so callers can see the blind spot.
            reconciled = self._reconcile_usage_sync()
            if reconciled is not None:
                return {
                    "used_bytes": reconciled, "budget_bytes": budget,
                    "exceeded": reconciled >= budget,
                    "source": "authoritative", "last_reconciled_at": time.time(),
                }
            return {
                "used_bytes": 0, "budget_bytes": budget, "exceeded": False,
                "source": "none", "last_reconciled_at": None,
            }

        row = self.usage_ledger.read_month()
        reconciled_at = row.get("reconciled_at")
        stale = (
            reconciled_at is None
            or (time.time() - reconciled_at) > self.reconcile_ttl_seconds
        )

        if stale:
            reconciled = self._reconcile_usage_sync()
            if reconciled is not None:
                return {
                    "used_bytes": reconciled, "budget_bytes": budget,
                    "exceeded": reconciled >= budget,
                    "source": "authoritative", "last_reconciled_at": time.time(),
                }
            # Reconcile failed — degrade to the local ledger. Use the max of
            # local accumulation and the last known reconciled value so we
            # never UNDER-count after a restart.
            degraded = max(row.get("local_bytes", 0), row.get("reconciled_bytes") or 0)
            return {
                "used_bytes": degraded, "budget_bytes": budget,
                "exceeded": degraded >= budget,
                "source": "cached-degraded", "last_reconciled_at": reconciled_at,
            }

        # Fresh cache: trust reconciled baseline + any local accrual since.
        used = max(
            row.get("reconciled_bytes") or 0,
            row.get("local_bytes", 0),
        )
        return {
            "used_bytes": used, "budget_bytes": budget,
            "exceeded": used >= budget,
            "source": "cached", "last_reconciled_at": reconciled_at,
        }

    async def get_monthly_usage(self, force_reconcile: bool = False) -> Dict[str, Any]:
        """Async wrapper around the usage computation. When force_reconcile is
        True, always hit INFORMATION_SCHEMA first."""
        loop = asyncio.get_event_loop()
        if force_reconcile:
            await loop.run_in_executor(self.executor, self._reconcile_usage_sync)
        return await loop.run_in_executor(
            self.executor, self._get_monthly_usage_sync
        )

    async def get_patent_by_number(
        self, publication_number: str
    ) -> Dict[str, Any]:
        """
        Get patent details by publication number.

        Args:
            publication_number: Patent publication number (e.g., US-9876543-B2)

        Returns:
            Dictionary containing complete patent details
        """
        try:
            sql = f"""
            SELECT
                publication_number, title_localized, abstract_localized,
                publication_date, filing_date, grant_date,
                inventor_harmonized, assignee_harmonized,
                cpc, ipc, family_id, country_code, application_number
            FROM `{self.dataset_id}.{GooglePatentsTables.PUBLICATIONS}`
            WHERE publication_number = @publication_number
            LIMIT 1
            """

            parameters = [
                bigquery.ScalarQueryParameter(
                    "publication_number", "STRING", publication_number
                )
            ]

            results = await self.query_async(sql, parameters)

            if not results:
                return ApiError.not_found("Patent", publication_number)

            return {"success": True, "patent": results[0]}

        except Exception as e:
            logger.error(
                f"Error fetching patent {publication_number}: {str(e)}"
            )
            return ApiError.create(
                message=f"Failed to fetch patent: {str(e)}", status_code=500
            )

    async def get_patent_claims(
        self, publication_number: str
    ) -> Dict[str, Any]:
        """
        Get patent claims by publication number.

        Args:
            publication_number: Patent publication number (e.g., US-9876543-B2)

        Returns:
            Dictionary containing claim number and text for each claim
        """
        try:
            # Claims are nested within the publications table
            sql = f"""
            SELECT
                publication_number,
                claims_localized
            FROM `{self.dataset_id}.{GooglePatentsTables.PUBLICATIONS}`
            WHERE publication_number = @publication_number
            LIMIT 1
            """

            parameters = [
                bigquery.ScalarQueryParameter(
                    "publication_number", "STRING", publication_number
                )
            ]

            results = await self.query_async(sql, parameters)

            if not results:
                return ApiError.not_found("Patent claims", publication_number)

            # Extract claims from nested structure
            patent = results[0]
            claims_data = patent.get('claims_localized', [])

            # Format claims for easier consumption
            claims = []
            for i, claim in enumerate(claims_data, 1):
                claims.append({
                    "claim_num": i,
                    "claim_text": claim.get('text', ''),
                    "language": claim.get('language', 'en')
                })

            return {
                "success": True,
                "publication_number": publication_number,
                "claims_count": len(claims),
                "claims": claims,
            }

        except Exception as e:
            logger.error(
                f"Error fetching claims for {publication_number}: {str(e)}"
            )
            return ApiError.create(
                message=f"Failed to fetch claims: {str(e)}", status_code=500
            )

    async def get_patent_description(
        self, publication_number: str
    ) -> Dict[str, Any]:
        """
        Get patent description by publication number.

        Args:
            publication_number: Patent publication number (e.g., US-9876543-B2)

        Returns:
            Dictionary containing patent description text
        """
        try:
            # Description is nested within the publications table
            sql = f"""
            SELECT
                publication_number,
                description_localized
            FROM `{self.dataset_id}.{GooglePatentsTables.PUBLICATIONS}`
            WHERE publication_number = @publication_number
            LIMIT 1
            """

            parameters = [
                bigquery.ScalarQueryParameter(
                    "publication_number", "STRING", publication_number
                )
            ]

            results = await self.query_async(sql, parameters)

            if not results:
                return ApiError.not_found(
                    "Patent description", publication_number
                )

            # Extract description from nested structure
            patent = results[0]
            descriptions = patent.get('description_localized', [])

            # Combine all description texts (usually just one)
            description_text = ""
            for desc in descriptions:
                description_text += desc.get('text', '')

            return {
                "success": True,
                "publication_number": publication_number,
                "description": description_text,
                "description_length": len(description_text)
            }

        except Exception as e:
            logger.error(
                f"Error fetching description for {publication_number}: {str(e)}"
            )
            return ApiError.create(
                message=f"Failed to fetch description: {str(e)}",
                status_code=500,
            )

    async def close(self):
        """Clean up resources."""
        try:
            self.executor.shutdown(wait=True)
            if self.client:
                self.client.close()
            logger.info("Google BigQuery client closed successfully")
        except Exception as e:
            logger.error(f"Error closing BigQuery client: {str(e)}")
