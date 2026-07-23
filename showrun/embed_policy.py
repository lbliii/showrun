"""Route-scoped framing policy for public Showrun embeds."""

from __future__ import annotations

from dataclasses import replace

from chirp.http.request import Request
from chirp.http.response import FileResponse, Response, StreamingResponse
from chirp.middleware.protocol import AnyResponse, Next

_CSP_HEADER = "content-security-policy"
_FRAME_ANCESTORS = "frame-ancestors"
_X_FRAME_OPTIONS = "x-frame-options"


def _allow_frame_ancestors(policy: str) -> str:
    """Allow public embedding without disturbing the rest of a CSP policy."""

    directives = [directive.strip() for directive in policy.split(";") if directive.strip()]
    updated: list[str] = []
    found = False
    for directive in directives:
        name = directive.split(maxsplit=1)[0].lower()
        if name == _FRAME_ANCESTORS:
            updated.append(f"{_FRAME_ANCESTORS} *")
            found = True
        else:
            updated.append(directive)
    if not found:
        updated.append(f"{_FRAME_ANCESTORS} *")
    return "; ".join(updated)


class PublicEmbedPolicy:
    """Permit framing only for the dedicated public embed surface."""

    async def __call__(self, request: Request, next: Next) -> AnyResponse:
        response = await next(request)
        if not request.path.startswith("/embed/"):
            return response
        if not isinstance(response, (Response, StreamingResponse, FileResponse)):
            return response

        headers: list[tuple[str, str]] = []
        has_csp = False
        for name, value in response.headers:
            normalized = name.lower()
            if normalized == _X_FRAME_OPTIONS:
                continue
            if normalized == _CSP_HEADER:
                value = _allow_frame_ancestors(value)
                has_csp = True
            headers.append((name, value))

        if not has_csp:
            headers.append(("Content-Security-Policy", f"{_FRAME_ANCESTORS} *"))
        return replace(response, headers=tuple(headers))
