"""Lead finder: businesses WITHOUT a website, from Google's official Places API.

Uses Places API (New) Text Search - the same business data shown in Google Maps - instead of
scraping the Maps app (fragile and against Google's terms). Needs GOOGLE_MAPS_API_KEY with the
"Places API (New)" enabled. Requesting phone/website fields is billed by Google; see
docs/LEADS_AND_EMAIL.md.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.errors import ConfigurationError, ProviderError, ProviderTimeout

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress", "places.nationalPhoneNumber",
    "places.internationalPhoneNumber", "places.websiteUri", "places.rating", "places.userRatingCount",
    "places.businessStatus", "places.googleMapsUri", "nextPageToken",
])
# A Facebook/Instagram/WhatsApp page or directory listing is not a real website: still a lead.
SOCIAL_HOSTS = (
    "facebook.com", "fb.com", "fb.me", "instagram.com", "wa.me", "whatsapp.com", "linktr.ee",
    "business.site", "justdial.com", "sulekha.com", "indiamart.com", "x.com", "twitter.com",
    "youtube.com", "linkedin.com", "tiktok.com", "g.page", "maps.app.goo.gl", "goo.gl",
)


def is_social_only(url: str | None) -> bool:
    if not url:
        return False
    host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in SOCIAL_HOSTS)


def to_lead(place: dict[str, Any], query: str) -> dict[str, Any]:
    website = place.get("websiteUri")
    return {
        "place_id": place.get("id", ""),
        "name": (place.get("displayName") or {}).get("text", "Unknown business"),
        "phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or "",
        "phone_international": place.get("internationalPhoneNumber") or "",
        "address": place.get("formattedAddress", ""),
        "rating": place.get("rating"),
        "reviews": place.get("userRatingCount"),
        "maps_url": place.get("googleMapsUri", ""),
        "social_url": website if is_social_only(website) else None,
        "query": query,
    }


class LeadsService:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.s = settings
        self.client = client

    async def search(self, query: str, max_leads: int = 20, require_phone: bool = True,
                     language: str | None = None) -> dict[str, Any]:
        if not self.s.google_maps_api_key:
            raise ConfigurationError("Lead finder is not set up: add GOOGLE_MAPS_API_KEY on the server "
                                     "(see docs/LEADS_AND_EMAIL.md).", code="leads_not_configured")
        headers = {"X-Goog-Api-Key": self.s.google_maps_api_key, "X-Goog-FieldMask": FIELD_MASK}
        leads: list[dict[str, Any]] = []
        scanned = 0
        token: str | None = None
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
        try:
            for _ in range(3):  # Google returns at most 60 results (3 pages of 20)
                body: dict[str, Any] = {"textQuery": query, "pageSize": 20}
                if language:
                    body["languageCode"] = language.split("-")[0]
                if token:
                    body["pageToken"] = token
                try:
                    r = await client.post(SEARCH_URL, json=body, headers=headers)
                except httpx.TimeoutException as exc:
                    raise ProviderTimeout("Google Places timed out") from exc
                except httpx.HTTPError as exc:
                    raise ProviderError("Could not reach Google Places") from exc
                if r.status_code >= 400:
                    raise _places_error(r)
                data = r.json()
                for place in data.get("places", []):
                    scanned += 1
                    if place.get("businessStatus") not in (None, "OPERATIONAL"):
                        continue
                    website = place.get("websiteUri")
                    if website and not is_social_only(website):
                        continue
                    lead = to_lead(place, query)
                    if require_phone and not lead["phone"]:
                        continue
                    leads.append(lead)
                    if len(leads) >= max_leads:
                        break
                token = data.get("nextPageToken")
                if len(leads) >= max_leads or not token:
                    break
        finally:
            if owned:
                await client.aclose()
        return {"query": query, "scanned": scanned, "leads": leads}


def _places_error(r: httpx.Response) -> ProviderError:
    try:
        err = r.json().get("error", {})
        msg, status = str(err.get("message", ""))[:200], err.get("status", "")
    except ValueError:
        msg, status = "", ""
    if r.status_code in (401, 403) or status == "PERMISSION_DENIED":
        hint = ("Google rejected the Maps API key. Check GOOGLE_MAPS_API_KEY, enable 'Places API (New)' "
                "and billing in Google Cloud.")
    elif r.status_code == 429:
        hint = "Google Places quota exceeded. Try later or raise the quota in Google Cloud."
    else:
        hint = f"Google Places error (HTTP {r.status_code})."
    return ProviderError(hint + (f" [Google says: {msg}]" if msg else ""), code="places_error")
