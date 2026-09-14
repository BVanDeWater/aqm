"""EPA Air Quality System (AQS) API Client Wrapper.

Provides access to the EPA's Air Quality System (AQS) database API (version 2)
according to EPA AQS documentation.

Documentation reference: fetchers/aqs_api_docs.txt
EPA Documentation URL: https://aqs.epa.gov/aqsweb/documents/data_api.html
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Sequence

from dotenv import load_dotenv
import pandas as pd
import requests


class AQSError(Exception):
    """Exception raised when an AQS API request fails or returns an error."""

    def __init__(self, message: str, status_code: int | None = None, errors: list[str] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors or []


def _format_date(d: str | int | date | datetime | None) -> str | None:
    """Format a date/datetime or string into YYYYMMDD string format."""
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y%m%d")
    # Clean string format (e.g., '2025-05-01' -> '20250501')
    return str(d).strip().replace("-", "")


def _format_param(param: str | int | Sequence[str | int] | None) -> str | None:
    """Format parameter code(s) into comma-separated string (up to 5 codes)."""
    if param is None:
        return None
    if isinstance(param, (list, tuple, set)):
        items = [str(p).strip() for p in param if str(p).strip()]
        if len(items) > 5:
            raise ValueError(f"EPA AQS limits queries to at most 5 parameter codes (received {len(items)}).")
        return ",".join(items)
    return str(param).strip()


def _format_code(val: str | int | None, width: int) -> str | None:
    """Zero-pad numeric FIPS or site codes to required length."""
    if val is None:
        return None
    s = str(val).strip()
    if s.isdigit() and len(s) < width:
        return s.zfill(width)
    return s


class AQSClient:
    """EPA Air Quality System (AQS) API client wrapper.

    Handles authentication, query formatting, response validation, and optional
    conversion to pandas DataFrames.

    Parameters
    ----------
    email : str, optional
        Email registered with the EPA AQS API. Defaults to the EMAIL environment variable.
    key : str, optional
        API key registered with the EPA AQS API. Defaults to the AQS_KEY environment variable.
    base_url : str, default "https://aqs.epa.gov/data/api"
        Root endpoint URL for the EPA AQS API.
    session : requests.Session, optional
        Existing requests session for connection pooling.
    return_df : bool, default False
        Whether query methods should return pandas DataFrames by default instead of dicts.
    timeout : int, default 30
        HTTP request timeout in seconds.
    """

    BASE_URL = "https://aqs.epa.gov/data/api"

    def __init__(
        self,
        email: str | None = None,
        key: str | None = None,
        base_url: str = BASE_URL,
        session: requests.Session | None = None,
        return_df: bool = False,
        timeout: int = 30,
    ):
        load_dotenv()
        raw_email = email or os.getenv("EMAIL") or os.getenv("AQS_EMAIL")
        raw_key = key or os.getenv("AQS_KEY") or os.getenv("AQS_API_KEY")
        
        self.email = raw_email.strip('"').strip("'") if raw_email else None
        self.key = raw_key.strip('"').strip("'") if raw_key else None
        
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.return_df = return_df
        self.timeout = timeout

    # -------------------------------------------------------------------------
    # Internal Request & Response Handling
    # -------------------------------------------------------------------------

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        auth_required: bool = True,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Execute a GET request against an EPA AQS endpoint.

        Parameters
        ----------
        endpoint : str
            API path relative to base_url, e.g. "monitors/byState".
        params : dict, optional
            Query parameters for the request.
        auth_required : bool, default True
            Whether to attach email and key credentials.
        return_df : bool, optional
            Override client-level return_df setting for this request.
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query_params: dict[str, Any] = {}

        if auth_required:
            if not self.email or not self.key:
                raise AQSError(
                    "Missing credentials. Set EMAIL and AQS_KEY environment variables "
                    "or pass email and key when instantiating AQSClient."
                )
            query_params["email"] = self.email
            query_params["key"] = self.key

        if params:
            # Filter out None values to prevent unpermitted variable errors
            for k, v in params.items():
                if v is not None:
                    query_params[k] = v

        try:
            resp = self.session.get(url, params=query_params, timeout=self.timeout)
        except requests.RequestException as e:
            raise AQSError(f"Network error when calling {url}: {e}") from e

        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise AQSError(f"Non-JSON response received from {url} (HTTP {resp.status_code})")

        # Check EPA AQS header status
        header_list = data.get("Header", [])
        header = header_list[0] if header_list else {}
        status = str(header.get("status", "")).lower()

        if status == "failed" or resp.status_code >= 400:
            errors = header.get("error", [])
            err_msg = "; ".join(errors) if errors else f"HTTP {resp.status_code}"
            raise AQSError(f"AQS API error: {err_msg}", status_code=resp.status_code, errors=errors)

        should_return_df = self.return_df if return_df is None else return_df
        if should_return_df:
            return self.to_dataframe(data)

        return data

    def to_dataframe(self, response: dict[str, Any] | list[dict[str, Any]]) -> pd.DataFrame:
        """Extract records from an AQS response dict or list into a pandas DataFrame."""
        if isinstance(response, pd.DataFrame):
            return response
        if isinstance(response, list):
            return pd.DataFrame(response)
        if isinstance(response, dict):
            records = response.get("Data", response.get("Body", []))
            return pd.DataFrame(records)
        return pd.DataFrame()

    # -------------------------------------------------------------------------
    # Account & Signup
    # -------------------------------------------------------------------------

    def signup(self, email: str | None = None) -> dict[str, Any]:
        """Register a new account or request a key reset.

        A validation email will be sent from aqsdatamart@epa.gov.
        """
        target_email = email or self.email
        if not target_email:
            raise AQSError("An email address is required to register.")
        return self._request("signup", params={"email": target_email}, auth_required=False)

    # -------------------------------------------------------------------------
    # Metadata Services
    # -------------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check if the AQS API is up and running."""
        try:
            res = self._request("metaData/isAvailable", auth_required=False)
            status = res.get("Header", [{}])[0].get("status", "")
            return status.lower() == "success"
        except Exception:
            return False

    def get_revision_history(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve complete list of revisions to the API in reverse chronological order."""
        return self._request("metaData/revisionHistory", return_df=return_df)

    def get_fields_by_service(self, service: str, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve field names and descriptions for a given service (e.g., 'sampleData', 'list')."""
        return self._request("metaData/fieldsByService", params={"service": service}, return_df=return_df)

    def get_issues(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve known issues with system functionality or data."""
        return self._request("metaData/issues", return_df=return_df)

    # -------------------------------------------------------------------------
    # List Services (Lookup / Reference Data)
    # -------------------------------------------------------------------------

    def get_states(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve states and their 2-digit FIPS codes."""
        return self._request("list/states", return_df=return_df)

    def get_counties(self, state: str | int, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve counties in a state by 2-digit FIPS state code."""
        params = {"state": _format_code(state, 2)}
        return self._request("list/countiesByState", params=params, return_df=return_df)

    def get_sites(
        self, state: str | int, county: str | int, return_df: bool | None = None
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitoring sites in a county."""
        params = {
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
        }
        return self._request("list/sitesByCounty", params=params, return_df=return_df)

    def get_cbsas(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve Core Based Statistical Areas (CBSAs) and codes."""
        return self._request("list/cbsas", return_df=return_df)

    def get_classes(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve parameter classes (e.g. CRITERIA, ALL, HAPS, VOCS)."""
        return self._request("list/classes", return_df=return_df)

    def get_parameters(
        self, pc: str = "CRITERIA", return_df: bool | None = None
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve parameters in a class (defaults to 'CRITERIA')."""
        params = {"pc": pc.strip().upper()}
        return self._request("list/parametersByClass", params=params, return_df=return_df)

    def get_pqaos(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve Primary Quality Assurance Organizations (PQAOs)."""
        return self._request("list/pqaos", return_df=return_df)

    def get_monitoring_agencies(self, return_df: bool | None = None) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitoring agencies (MAs)."""
        return self._request("list/mas", return_df=return_df)

    # -------------------------------------------------------------------------
    # Monitors Service
    # -------------------------------------------------------------------------

    def get_monitors_by_site(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        site: str | int,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitors at a specific site."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "site": _format_code(site, 4),
        }
        return self._request("monitors/bySite", params=params, return_df=return_df)

    def get_monitors_by_county(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitors in a county."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
        }
        return self._request("monitors/byCounty", params=params, return_df=return_df)

    def get_monitors_by_state(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitors within a state."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
        }
        return self._request("monitors/byState", params=params, return_df=return_df)

    def get_monitors_by_box(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        minlat: float | str,
        maxlat: float | str,
        minlon: float | str,
        maxlon: float | str,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitors within a latitude/longitude bounding box."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
        }
        return self._request("monitors/byBox", params=params, return_df=return_df)

    def get_monitors_by_cbsa(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        cbsa: str | int,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve monitors within a Core Based Statistical Area (CBSA)."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbsa": _format_code(cbsa, 5),
        }
        return self._request("monitors/byCBSA", params=params, return_df=return_df)

    def get_monitors(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        cbsa: str | int | None = None,
        minlat: float | str | None = None,
        maxlat: float | str | None = None,
        minlon: float | str | None = None,
        maxlon: float | str | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Unified helper to retrieve monitors using geographical criteria.

        Automatically selects the appropriate endpoint (bySite, byCounty, byState, byCBSA, or byBox).
        """
        if state and county and site:
            return self.get_monitors_by_site(param, bdate, edate, state, county, site, return_df=return_df)
        if state and county:
            return self.get_monitors_by_county(param, bdate, edate, state, county, return_df=return_df)
        if state:
            return self.get_monitors_by_state(param, bdate, edate, state, return_df=return_df)
        if cbsa:
            return self.get_monitors_by_cbsa(param, bdate, edate, cbsa, return_df=return_df)
        if all(c is not None for c in (minlat, maxlat, minlon, maxlon)):
            return self.get_monitors_by_box(
                param, bdate, edate, minlat, maxlat, minlon, maxlon, return_df=return_df  # type: ignore[arg-type]
            )
        raise ValueError("Specify (state), (state, county), (state, county, site), (cbsa), or bounding box coordinates.")

    # -------------------------------------------------------------------------
    # Sample Data (Raw Finest Grain Measurements)
    # -------------------------------------------------------------------------

    def get_sample_data_by_site(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        site: str | int,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve raw sample data by site."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "site": _format_code(site, 4),
            "duration": duration,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("sampleData/bySite", params=params, return_df=return_df)

    def get_sample_data_by_county(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve raw sample data by county."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "duration": duration,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("sampleData/byCounty", params=params, return_df=return_df)

    def get_sample_data_by_state(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve raw sample data by state."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "duration": duration,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("sampleData/byState", params=params, return_df=return_df)

    def get_sample_data_by_box(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        minlat: float | str,
        maxlat: float | str,
        minlon: float | str,
        maxlon: float | str,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve raw sample data within a bounding box."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
            "duration": duration,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("sampleData/byBox", params=params, return_df=return_df)

    def get_sample_data_by_cbsa(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        cbsa: str | int,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve raw sample data by CBSA."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbsa": _format_code(cbsa, 5),
            "duration": duration,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("sampleData/byCBSA", params=params, return_df=return_df)

    def get_sample_data(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        cbsa: str | int | None = None,
        minlat: float | str | None = None,
        maxlat: float | str | None = None,
        minlon: float | str | None = None,
        maxlon: float | str | None = None,
        duration: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Unified helper to retrieve raw sample data."""
        if state and county and site:
            return self.get_sample_data_by_site(
                param, bdate, edate, state, county, site, duration=duration, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state and county:
            return self.get_sample_data_by_county(
                param, bdate, edate, state, county, duration=duration, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state:
            return self.get_sample_data_by_state(
                param, bdate, edate, state, duration=duration, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if cbsa:
            return self.get_sample_data_by_cbsa(
                param, bdate, edate, cbsa, duration=duration, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if all(c is not None for c in (minlat, maxlat, minlon, maxlon)):
            return self.get_sample_data_by_box(
                param, bdate, edate, minlat, maxlat, minlon, maxlon, duration=duration, cbdate=cbdate, cedate=cedate, return_df=return_df  # type: ignore[arg-type]
            )
        raise ValueError("Specify (state), (state, county), (state, county, site), (cbsa), or bounding box coordinates.")

    # -------------------------------------------------------------------------
    # Daily Summary Data
    # -------------------------------------------------------------------------

    def get_daily_data_by_site(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        site: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve daily summary data by site."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "site": _format_code(site, 4),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("dailyData/bySite", params=params, return_df=return_df)

    def get_daily_data_by_county(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve daily summary data by county."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("dailyData/byCounty", params=params, return_df=return_df)

    def get_daily_data_by_state(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve daily summary data by state."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("dailyData/byState", params=params, return_df=return_df)

    def get_daily_data_by_box(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        minlat: float | str,
        maxlat: float | str,
        minlon: float | str,
        maxlon: float | str,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve daily summary data within a bounding box."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("dailyData/byBox", params=params, return_df=return_df)

    def get_daily_data_by_cbsa(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        cbsa: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve daily summary data by CBSA."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbsa": _format_code(cbsa, 5),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("dailyData/byCBSA", params=params, return_df=return_df)

    def get_daily_data(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        cbsa: str | int | None = None,
        minlat: float | str | None = None,
        maxlat: float | str | None = None,
        minlon: float | str | None = None,
        maxlon: float | str | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Unified helper to retrieve daily summary data."""
        if state and county and site:
            return self.get_daily_data_by_site(
                param, bdate, edate, state, county, site, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state and county:
            return self.get_daily_data_by_county(
                param, bdate, edate, state, county, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state:
            return self.get_daily_data_by_state(
                param, bdate, edate, state, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if cbsa:
            return self.get_daily_data_by_cbsa(
                param, bdate, edate, cbsa, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if all(c is not None for c in (minlat, maxlat, minlon, maxlon)):
            return self.get_daily_data_by_box(
                param, bdate, edate, minlat, maxlat, minlon, maxlon, cbdate=cbdate, cedate=cedate, return_df=return_df  # type: ignore[arg-type]
            )
        raise ValueError("Specify (state), (state, county), (state, county, site), (cbsa), or bounding box coordinates.")

    # -------------------------------------------------------------------------
    # Quarterly Summary Data
    # -------------------------------------------------------------------------

    def get_quarterly_data_by_site(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        site: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve quarterly summary data by site."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "site": _format_code(site, 4),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("quarterlyData/bySite", params=params, return_df=return_df)

    def get_quarterly_data_by_county(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve quarterly summary data by county."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("quarterlyData/byCounty", params=params, return_df=return_df)

    def get_quarterly_data_by_state(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve quarterly summary data by state."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("quarterlyData/byState", params=params, return_df=return_df)

    def get_quarterly_data_by_box(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        minlat: float | str,
        maxlat: float | str,
        minlon: float | str,
        maxlon: float | str,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve quarterly summary data within a bounding box."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("quarterlyData/byBox", params=params, return_df=return_df)

    def get_quarterly_data_by_cbsa(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        cbsa: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve quarterly summary data by CBSA."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbsa": _format_code(cbsa, 5),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("quarterlyData/byCBSA", params=params, return_df=return_df)

    def get_quarterly_data(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        cbsa: str | int | None = None,
        minlat: float | str | None = None,
        maxlat: float | str | None = None,
        minlon: float | str | None = None,
        maxlon: float | str | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Unified helper to retrieve quarterly summary data."""
        if state and county and site:
            return self.get_quarterly_data_by_site(
                param, bdate, edate, state, county, site, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state and county:
            return self.get_quarterly_data_by_county(
                param, bdate, edate, state, county, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state:
            return self.get_quarterly_data_by_state(
                param, bdate, edate, state, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if cbsa:
            return self.get_quarterly_data_by_cbsa(
                param, bdate, edate, cbsa, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if all(c is not None for c in (minlat, maxlat, minlon, maxlon)):
            return self.get_quarterly_data_by_box(
                param, bdate, edate, minlat, maxlat, minlon, maxlon, cbdate=cbdate, cedate=cedate, return_df=return_df  # type: ignore[arg-type]
            )
        raise ValueError("Specify (state), (state, county), (state, county, site), (cbsa), or bounding box coordinates.")

    # -------------------------------------------------------------------------
    # Annual Summary Data
    # -------------------------------------------------------------------------

    def get_annual_data_by_site(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        site: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual summary data by site."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "site": _format_code(site, 4),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("annualData/bySite", params=params, return_df=return_df)

    def get_annual_data_by_county(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        county: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual summary data by county."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "county": _format_code(county, 3),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("annualData/byCounty", params=params, return_df=return_df)

    def get_annual_data_by_state(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual summary data by state."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "state": _format_code(state, 2),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("annualData/byState", params=params, return_df=return_df)

    def get_annual_data_by_box(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        minlat: float | str,
        maxlat: float | str,
        minlon: float | str,
        maxlon: float | str,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual summary data within a bounding box."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "minlat": minlat,
            "maxlat": maxlat,
            "minlon": minlon,
            "maxlon": maxlon,
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("annualData/byBox", params=params, return_df=return_df)

    def get_annual_data_by_cbsa(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        cbsa: str | int,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual summary data by CBSA."""
        params = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbsa": _format_code(cbsa, 5),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }
        return self._request("annualData/byCBSA", params=params, return_df=return_df)

    def get_annual_data(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        cbsa: str | int | None = None,
        minlat: float | str | None = None,
        maxlat: float | str | None = None,
        minlon: float | str | None = None,
        maxlon: float | str | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Unified helper to retrieve annual summary data."""
        if state and county and site:
            return self.get_annual_data_by_site(
                param, bdate, edate, state, county, site, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state and county:
            return self.get_annual_data_by_county(
                param, bdate, edate, state, county, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if state:
            return self.get_annual_data_by_state(
                param, bdate, edate, state, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if cbsa:
            return self.get_annual_data_by_cbsa(
                param, bdate, edate, cbsa, cbdate=cbdate, cedate=cedate, return_df=return_df
            )
        if all(c is not None for c in (minlat, maxlat, minlon, maxlon)):
            return self.get_annual_data_by_box(
                param, bdate, edate, minlat, maxlat, minlon, maxlon, cbdate=cbdate, cedate=cedate, return_df=return_df  # type: ignore[arg-type]
            )
        raise ValueError("Specify (state), (state, county), (state, county, site), (cbsa), or bounding box coordinates.")

    # -------------------------------------------------------------------------
    # Quality Assurance (QA) Services
    # -------------------------------------------------------------------------

    def get_qa_data(
        self,
        service: str,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Generic requester for QA services.

        Valid services:
        - 'qaAnnualPerformanceEvaluations'
        - 'qaBlanks'
        - 'qaCollocatedAssessments'
        - 'qaFlowRateVerifications'
        - 'qaFlowRateAudits'
        - 'qaOnePointQcRawData'
        - 'qaPepAudits'
        """
        params: dict[str, Any] = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
        }

        if state and county and site:
            filter_name = "bySite"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
            params["site"] = _format_code(site, 4)
        elif state and county:
            filter_name = "byCounty"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
        elif state:
            filter_name = "byState"
            params["state"] = _format_code(state, 2)
        elif pqao:
            filter_name = "byPQAO"
            params["pqao"] = _format_code(pqao, 4)
        elif ma:
            filter_name = "byMA"
            params["ma"] = _format_code(ma, 4)
        else:
            raise ValueError("Specify (state), (state, county), (state, county, site), (pqao), or (ma).")

        endpoint = f"{service}/{filter_name}"
        return self._request(endpoint, params=params, return_df=return_df)

    def get_qa_annual_performance_evaluations(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA annual performance evaluations data."""
        return self.get_qa_data(
            "qaAnnualPerformanceEvaluations", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df
        )

    def get_qa_blanks(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA blanks sample data."""
        return self.get_qa_data("qaBlanks", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df)

    def get_qa_collocated_assessments(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA collocated assessments data."""
        return self.get_qa_data(
            "qaCollocatedAssessments", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df
        )

    def get_qa_flow_rate_verifications(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA flow rate verification data."""
        return self.get_qa_data(
            "qaFlowRateVerifications", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df
        )

    def get_qa_flow_rate_audits(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA flow rate audit data."""
        return self.get_qa_data(
            "qaFlowRateAudits", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df
        )

    def get_qa_one_point_qc(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA one point quality control check raw data."""
        return self.get_qa_data(
            "qaOnePointQcRawData", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df
        )

    def get_qa_pep_audits(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve QA Performance Evaluation Program (PEP) audit data."""
        return self.get_qa_data("qaPepAudits", param, bdate, edate, state, county, site, pqao, ma, return_df=return_df)

    # -------------------------------------------------------------------------
    # Transaction Formats
    # -------------------------------------------------------------------------

    def get_transactions_sample(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        ma: str | int | None = None,
        cbdate: str | int | date | datetime | None = None,
        cedate: str | int | date | datetime | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve sample data in the AQS submission transaction format (RD)."""
        params: dict[str, Any] = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
            "cbdate": _format_date(cbdate),
            "cedate": _format_date(cedate),
        }

        if state and county and site:
            filter_name = "bySite"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
            params["site"] = _format_code(site, 4)
        elif state and county:
            filter_name = "byCounty"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
        elif state:
            filter_name = "byState"
            params["state"] = _format_code(state, 2)
        elif ma:
            filter_name = "byMA"
            params["ma"] = _format_code(ma, 4)
        else:
            raise ValueError("Specify (state), (state, county), (state, county, site), or (ma).")

        return self._request(f"transactionsSample/{filter_name}", params=params, return_df=return_df)

    def get_transactions_qa_annual_performance_evaluations(
        self,
        param: str | int | Sequence[str | int],
        bdate: str | int | date | datetime,
        edate: str | int | date | datetime,
        state: str | int | None = None,
        county: str | int | None = None,
        site: str | int | None = None,
        pqao: str | int | None = None,
        ma: str | int | None = None,
        return_df: bool | None = None,
    ) -> dict[str, Any] | pd.DataFrame:
        """Retrieve annual performance evaluation data in transaction format."""
        params: dict[str, Any] = {
            "param": _format_param(param),
            "bdate": _format_date(bdate),
            "edate": _format_date(edate),
        }

        if state and county and site:
            filter_name = "bySite"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
            params["site"] = _format_code(site, 4)
        elif state and county:
            filter_name = "byCounty"
            params["state"] = _format_code(state, 2)
            params["county"] = _format_code(county, 3)
        elif state:
            filter_name = "byState"
            params["state"] = _format_code(state, 2)
        elif pqao:
            filter_name = "byPQAO"
            params["pqao"] = _format_code(pqao, 4)
        elif ma:
            filter_name = "byMA"
            params["ma"] = _format_code(ma, 4)
        else:
            raise ValueError("Specify (state), (state, county), (state, county, site), (pqao), or (ma).")

        return self._request(
            f"transactionsQaAnnualPerformanceEvaluations/{filter_name}", params=params, return_df=return_df
        )