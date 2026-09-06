"""HTTP client for the hub."""

from __future__ import annotations

import httpx

from bussola_agent.config import AgentConfig
from bussola_contracts import MetricSpec, PositionReport, SubmissionAck, SubmissionPayload


class HubError(RuntimeError):
    """Raised on any non-success response from the hub."""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class PositionUnavailable(HubError):
    """The hub has no position to report, and said why in a machine-readable code.

    A subclass of HubError so an existing `except HubError` still catches it,
    but distinct because this is usually NOT a failure: "the operator has not
    released this period yet" is the ordinary state of affairs for most of a
    reporting period, and an agent that logged it as an error would train its
    operator to ignore the log.
    """

    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message, status_code=404, retryable=retryable)
        self.code = code


#: How the hub's refusal codes map onto the agent's exit-code contract.
#: Retryable means "the same call may succeed later without anything changing
#: at this plant" -- which is true only while waiting for the operator.
POSITION_REFUSALS = {
    "not_submitted": False,
    "not_published": True,
    "incomplete_release": False,
}


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

    def fetch_position(self, *, metric: str, period: str) -> PositionReport:
        """Ask the hub where this contributor sits against its cohort (S3-1).

        A GET that costs no privacy budget: the hub reads an already-published
        release and places our own submitted value against it. Safe to call from
        cron, which is exactly why the endpoint refuses to compute anything.
        """
        url = f"{self.config.hub_url}/api/v1/position/"
        try:
            response = self._client.get(
                url, headers=self._headers, params={"metric": metric, "period": period}
            )
        except httpx.RequestError as exc:
            raise HubError(f"Could not reach hub at {url}: {exc}", retryable=True) from exc

        if response.status_code == 404:
            detail, code = self._detail_and_code(response)
            if code in POSITION_REFUSALS:
                raise PositionUnavailable(
                    detail, code=code, retryable=POSITION_REFUSALS[code]
                )

        self._raise_for_status(response)
        return PositionReport.model_validate(response.json())

    @staticmethod
    def _detail_and_code(response: httpx.Response) -> tuple[str, str | None]:
        try:
            body = response.json()
        except ValueError:
            return response.text, None
        return body.get("detail", response.text), body.get("code")

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
