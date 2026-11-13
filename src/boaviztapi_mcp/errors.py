"""Error types. Every message is written for the model that called the tool."""

from __future__ import annotations

from collections.abc import Sequence


class BoaviztaError(Exception):
    """Base class for errors that are reported back to the caller as tool errors."""


class InputError(BoaviztaError):
    """The request failed local validation (unknown name, criterion, location...)."""


class UpstreamError(BoaviztaError):
    """BoaviztAPI answered with an error."""


class UpstreamNotFound(UpstreamError):
    """BoaviztAPI returned 404."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"BoaviztAPI could not find it: {detail}")
        self.detail = detail


class UpstreamValidationError(UpstreamError):
    """BoaviztAPI returned 422."""

    def __init__(self, problems: Sequence[str]) -> None:
        joined = "; ".join(problems) or "no details given"
        super().__init__(f"BoaviztAPI rejected the request: {joined}")
        self.problems = list(problems)


class UpstreamServerError(UpstreamError):
    """BoaviztAPI returned a 5xx status."""

    def __init__(self, status: int, body: str) -> None:
        snippet = body.strip()[:200] or "empty body"
        super().__init__(f"BoaviztAPI failed with HTTP {status} ({snippet})")
        self.status = status
        self.body = body


class UpstreamUnavailable(UpstreamError):
    """BoaviztAPI could not be reached or did not answer in time."""

    def __init__(self, base_url: str, timeout: float, reason: str) -> None:
        super().__init__(
            f"BoaviztAPI at {base_url} did not respond ({reason};"
            f" timeout {timeout:g} s)."
            " The public instance is a demo; for regular use, self-host it with"
            " `docker run -p 5000:5000 ghcr.io/boavizta/boaviztapi:latest` and set"
            " BOAVIZTAPI_URL=http://localhost:5000."
        )
        self.base_url = base_url
        self.reason = reason


class UnexpectedResponse(UpstreamError):
    """BoaviztAPI answered 200 with a body this client does not understand."""
