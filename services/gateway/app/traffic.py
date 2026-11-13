"""Anonymous traffic counting and Yandex Metrika support (#85).

The public beacon never stores or forwards an IP address, user agent or raw
visitor id.  The browser sends a random device-local id; the gateway HMACs it
with ``TRAFFIC_HASH_SECRET`` (fallback: ``JWT_SECRET``) and the library keeps
only ``(visitor_hash, UTC day, path_group)``.  Automated user agents are
ignored so crawler traffic cannot be mistaken for real visitors.

Yandex Metrika is a build-time frontend integration (``YANDEX_METRIKA_ID``).
This module only documents the server-side CSP/beacon side of the feature; it
does not expose the counter id through the API.
"""

from __future__ import annotations

import hashlib
import hmac
import re

from fastapi import APIRouter, Depends, Request
from manga_common.schemas import TrafficSummaryOut, TrafficVisitIn, TrafficVisitOut
from manga_common.security import UserClaims, require_admin

router = APIRouter(prefix="/api/v1")

_TRAFFIC_DOMAIN = b"mangapoisk-traffic-v1\x00"

# Match common crawlers and link previews, but not a real Yandex.Browser UA
# (which contains "YaBrowser", not "YandexBot").
_AUTOMATED = re.compile(
    r"(?:"
    r"bot\b|bot/|crawler|spider|slurp|headless|phantom|lighthouse|pagespeed|"
    r"googlebot|yandexbot|bingbot|duckduckbot|baiduspider|ahrefsbot|semrushbot|"
    r"telegrambot|whatsapp|facebookexternalhit|twitterbot|discordbot|"
    r"python-requests|curl/|wget/|go-http-client|libwww-perl"
    r")",
    re.IGNORECASE,
)


def visitor_hash(secret: str, visitor_id: str) -> str:
    """Stable, domain-separated HMAC-SHA256 of a random device id."""

    return hmac.new(
        secret.encode("utf-8"), _TRAFFIC_DOMAIN + visitor_id.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def is_automated(user_agent: str) -> bool:
    """Best-effort crawler filter; the UA is inspected transiently, not stored."""

    return bool(user_agent and _AUTOMATED.search(user_agent))


@router.post("/traffic/visit", response_model=TrafficVisitOut)
async def traffic_visit(request: Request, payload: TrafficVisitIn) -> TrafficVisitOut:
    """Record one public page view.

    Deduplication is per visitor and UTC day in the library database, so
    several calls from one reader on the same day produce a single unique
    visitor.  The endpoint is intentionally public and does not require a
    session; it carries no account or personal data.
    """

    user_agent = request.headers.get("User-Agent", "")
    if is_automated(user_agent):
        return TrafficVisitOut(recorded=False)

    settings = request.app.state.settings
    library = request.app.state.library
    digest = visitor_hash(settings.traffic_secret, payload.visitor_id)
    recorded = await library.record_traffic_visit(digest, payload.path_group)
    return TrafficVisitOut(recorded=bool(recorded))


@router.get("/admin/traffic", response_model=TrafficSummaryOut)
async def admin_traffic(
    request: Request, user: UserClaims = Depends(require_admin)
) -> TrafficSummaryOut:
    """Unique visitors for the admin overview; never returns visitor hashes."""

    return await request.app.state.library.traffic_summary()
