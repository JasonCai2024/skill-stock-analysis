"""
ServiceHub Tushare Proxy client.

Calls ServiceHub's /api/tushare/query endpoint instead of Tushare directly,
so no Tushare Token is needed on the client side.

Usage:
    from servicehub_tushare_client import ServiceHubTushareClient
    client = ServiceHubTushareClient()
    success, columns, records = client.query("stock_basic", {"name": "华邦健康"})
"""

import os
import httpx
from typing import Dict, Any, List, Tuple, Optional


class ServiceHubTushareClient:
    """
    Client for ServiceHub's Tushare proxy endpoint.

    Requires SERVICETUBER_BASE_URL, SERVICETUBER_USERNAME, SERVICETUBER_PASSTOKEN
    env vars (same credentials as the LLM proxy).
    """

    def __init__(self, timeout: float = 60.0):
        self.base_url = os.environ.get(
            "SERVICETUBER_BASE_URL", "https://www.ccailab.top"
        ).rstrip("/")
        if self.base_url.endswith("/api"):
            self.base_url = self.base_url[:-4]
        self.url = f"{self.base_url}/api/tushare/query"
        self.username = os.environ.get("SERVICETUBER_USERNAME", "")
        self.passtoken = os.environ.get("SERVICETUBER_PASSTOKEN", "")
        self.timeout = timeout

        if not self.username or not self.passtoken:
            raise ValueError(
                "SERVICETUBER_USERNAME and SERVICETUBER_PASSTOKEN must be set."
            )

    def query(
        self,
        api_name: str,
        params: Optional[Dict[str, Any]] = None,
        fields: str = "",
    ) -> Tuple[bool, List[str], List[List[Any]]]:
        """
        Call a Tushare API via ServiceHub proxy.

        Args:
            api_name: Tushare API name, e.g. "stock_basic", "daily", "income"
            params:    Tushare API parameters dict
            fields:    Comma-separated list of fields to return (optional)

        Returns:
            (success, columns, records)
            - success:  bool — True if the call succeeded
            - columns:  list of column names
            - records:  list of rows (each row is a list of values)

        Raises:
            ValueError if credentials are missing.
            httpx.HTTPStatusError on HTTP-level failures.
        """
        payload = {
            "username": self.username,
            "passtoken": self.passtoken,
            "api_name": api_name,
            "params": params or {},
            "fields": fields,
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 200:
            raise RuntimeError(
                f"ServiceHub Tushare proxy error: {data.get('message', data)}"
            )

        result = data.get("data", {})
        columns = result.get("columns", [])
        records = result.get("records", [])
        return True, columns, records

    def search_stock(self, company_name: str) -> Tuple[bool, str, str]:
        """
        Search for a Chinese A-share stock by company name.

        Args:
            company_name: Chinese company name, e.g. "华邦健康"

        Returns:
            (success, ticker, extra_info)
            - success:    bool
            - ticker:    ts_code like "002004.SZ", empty if not found
            - extra_info: "multiple" if >1 result, empty if exact match,
                          error message if failed

        Note:
            Returns the first result if multiple matches are found.
            Ask the user to specify the ticker if precision is needed.
        """
        try:
            success, columns, records = self.query(
                api_name="stock_basic",
                params={
                    "name": company_name,
                    "trade_date": "20260607",
                    "exchange": "",
                    "list_status": "L",
                },
                fields="ts_code,symbol,name,area,industry,market",
            )
        except Exception as e:
            return False, "", str(e)

        if not records:
            return False, "", "no results"

        if len(records) == 1:
            ts_code_idx = columns.index("ts_code")
            return True, records[0][ts_code_idx], ""

        # Multiple results — return first, signal multiple
        ts_code_idx = columns.index("ts_code")
        return True, records[0][ts_code_idx], "multiple"
