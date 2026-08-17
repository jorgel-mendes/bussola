"""HTTP client for the hub."""

from __future__ import annotations

import httpx

from bussola_agent.config import AgentConfig
from bussola_contracts import MetricSpec, SubmissionAck, SubmissionPayload


class HubError(RuntimeError):
    """Raised on any non-success response from the hub."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class HubClient:
    def __init__(self, config: AgentConfig, *, client: httpx.Client | None = None):
        self.config = config
        self._client = client or httpx.Client(timeout=config.timeout_seconds)

    def __enter__(self) -> HubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

    def fetch_metric(self, code: str) -> MetricSpec:
        """Fetch one metric spec from the catalog so we can validate locally."""
        url = f"{self.config.hub_url}/api/v1/metrics/"
        try:
            response = self._client.get(url, headers=self._headers)
        except httpx.RequestError as exc:
            raise HubError(f"Could not reach hub at {url}: {exc}", retryable=True) from exc

        self._raise_for_status(response)

        payload = response.json()
        specs = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
        for item in specs:
            if item["code"] == code:
                return MetricSpec.model_validate(item)

        known = ", ".join(sorted(item["code"] for item in specs)) or "(none)"
        raise HubError(f"Metric '{code}' is not in the hub catalog. Known metrics: {known}")

    def submit(self, payload: SubmissionPayload) -> SubmissionAck:
        url = f"{self.config.hub_url}/api/v1/submissions/"
        try:
            response = self._client.post(
                url,
                headers=self._headers,
                content=payload.model_dump_json(),
            )
        except httpx.RequestError as exc:
            raise HubError(f"Could not reach hub at {url}: {exc}", retryable=True) from exc

        self._raise_for_status(response)
        return SubmissionAck.model_validate(response.json())

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """Translate hub status codes into actionable agent errors.

        The 409/422 split is the important one: 409 means the hub is not ready
        for this period yet and a later retry will work; 422 means the data is
        wrong and retrying it unchanged never will.
        """
        if response.is_success:
            return

        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text

        if response.status_code == 401:
            raise HubError(
                f"Authentication rejected by hub: {detail}\n"
                "Check BUSSOLA_TOKEN. The token may have been revoked.",
                status_code=401,
            )
        if response.status_code == 409:
            raise HubError(
                f"Hub is not accepting submissions for this period: {detail}",
                status_code=409,
                retryable=True,
            )
        if response.status_code == 422:
            raise HubError(f"Hub rejected the value: {detail}", status_code=422)
        if response.status_code >= 500:
            raise HubError(
                f"Hub error ({response.status_code}): {detail}",
                status_code=response.status_code,
                retryable=True,
            )

        raise HubError(f"Hub rejected the request ({response.status_code}): {detail}",
                       status_code=response.status_code)
