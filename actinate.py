"""Actinate API client for VeniceBeach fitness courses."""
import time
import requests
from datetime import datetime, date, timedelta

BASE_URL = "https://widget.actinate.com"
WIDGET_KEY = "dQwvUoeuoACEFD2B"
TENANT = "venicebeach"
OAUTH_VERSION = "v6"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; VeniceBeachBooker/1.0)",
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://widget.actinate.com",
    "Referer": "https://www.venicebeach-fitness.de/",
})


# ── Auth ───────────────────────────────────────────────────────────────────────

def login(email: str, password: str) -> dict:
    """Authenticate and return token dict: {access_token, refresh_token, expires_in}."""
    url = f"{BASE_URL}/oauth/{OAUTH_VERSION}/oauth/token"
    data = {
        "username": email,
        "password": password,
        "grant_type": "password",
        "app_version": "widget",
        "os": "Chrome",
        "os_version": "120",
    }
    resp = SESSION.post(url, data=data, params={"tenant": TENANT})
    resp.raise_for_status()
    return resp.json()


def refresh_token(token: str) -> dict:
    """Refresh access token using refresh token."""
    url = f"{BASE_URL}/oauth/{OAUTH_VERSION}/oauth/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token,
        "app_version": "widget",
        "os": "Chrome",
        "os_version": "120",
    }
    resp = SESSION.post(url, data=data, params={"tenant": TENANT})
    resp.raise_for_status()
    return resp.json()


# ── Courses ────────────────────────────────────────────────────────────────────

def fetch_occurrences(studio_id: int, from_date: date, to_date: date, access_token: str | None = None) -> list[dict]:
    """Fetch course occurrences for a studio between two dates.

    Pass access_token to get accurate per-occurrence 'joined' status.
    Without a token the API returns joined=false for everything.
    """
    url = f"{BASE_URL}/widgets/v1/classes/occurences"
    params = {
        "key": WIDGET_KEY,
        "studioIds[]": studio_id,
        "startAt": int(datetime(from_date.year, from_date.month, from_date.day).timestamp()),
        "endAt": int(datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59).timestamp()),
        "tenant": TENANT,
    }
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    resp = SESSION.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()

    occurrences = []
    for day in data.get("days", {}).get("data", []):
        for occ in day.get("occurences", []):
            occurrences.append({
                "id": occ["id"],
                "name": occ["name"],
                "description": occ.get("description", ""),
                "category": occ.get("course", {}).get("category", {}).get("name", ""),
                "room": occ.get("room", {}).get("name", "") if occ.get("room") else "",
                "start_at": occ["start_at"],
                "end_at": occ["end_at"],
                "max_participants": occ.get("max_participants"),
                "attendees_count": occ.get("attendees_count"),  # None when unauthenticated
                "join_mandatory": occ.get("join_mandatory", False),
                "join_open_prior_seconds": occ.get("join_open_prior_start_seconds", 86400),
                "studio_id": occ.get("studioId", studio_id),
                "canceled_at": occ.get("canceled_at"),
                "joined": occ.get("joined", False),
                "waitlist_position": occ.get("waitlist_position"),
            })
    return occurrences


def fetch_upcoming(studio_id: int, days_ahead: int = 14, access_token: str | None = None) -> list[dict]:
    """Convenience: fetch occurrences for the next N days."""
    today = date.today()
    return fetch_occurrences(studio_id, today, today + timedelta(days=days_ahead), access_token=access_token)


# ── Booking ────────────────────────────────────────────────────────────────────

def join_occurrence(occurrence_id: int, access_token: str) -> dict:
    """Book (join) a course occurrence. Requires valid access_token."""
    url = f"{BASE_URL}/widgets/v1/classes/occurences/{occurrence_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = SESSION.post(url, headers=headers, params={"tenant": TENANT}, json={})
    resp.raise_for_status()
    return resp.json()


def leave_occurrence(occurrence_id: int, access_token: str) -> dict:
    """Cancel (leave) a course occurrence."""
    url = f"{BASE_URL}/widgets/v1/classes/occurences/{occurrence_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = SESSION.delete(url, headers=headers, params={"tenant": TENANT})
    resp.raise_for_status()
    return resp.json()


def join_waitlist(occurrence_id: int, access_token: str) -> dict:
    """Join the waitlist for a full course occurrence."""
    url = f"{BASE_URL}/widgets/v1/classes/occurences/waitlist"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = SESSION.post(url, headers=headers, params={"tenant": TENANT},
                        json={"occurence_id": occurrence_id})
    resp.raise_for_status()
    return resp.json()


def leave_waitlist(occurrence_id: int, access_token: str) -> dict:
    """Leave the waitlist for a course occurrence."""
    url = f"{BASE_URL}/widgets/v1/classes/occurences/waitlist"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = SESSION.delete(url, headers=headers, params={"tenant": TENANT},
                          json={"occurence_id": occurrence_id})
    resp.raise_for_status()
    return resp.json()


def get_me(access_token: str) -> dict:
    """Return currently logged in user info."""
    url = f"{BASE_URL}/widgets/v1/users/me"
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = SESSION.get(url, headers=headers, params={"tenant": TENANT})
    resp.raise_for_status()
    return resp.json()
