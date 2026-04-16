"""
Scheduler: keeps course data fresh and fires booking jobs at the right moment.

Logic:
- Every 30 min: re-fetch occurrences for the next 14 days and update DB.
- Every minute: check for subscribed occurrences whose booking window just
  opened (start_at - join_open_prior_seconds <= now + 90s) and schedule
  a one-shot booking job for the exact open time.
- Booking job: tries to book within 3 minutes (retry every 20s) to guarantee
  registration in the first 2-3 minutes.
"""
import time
import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

import db
import actinate
import token_store as sec

log = logging.getLogger(__name__)

# IDs of booking jobs we already scheduled (to avoid duplicates)
_scheduled = set()

scheduler = BackgroundScheduler(timezone="Europe/Berlin")


# ── Token management ──────────────────────────────────────────────────────────

def _get_token() -> str | None:
    """Return a valid access token, refreshing if needed."""
    token = sec.get_token("access_token")
    expires = db.get_setting("token_expires")

    if not token:
        return None

    now = int(time.time())
    # Refresh if less than 5 minutes left
    if expires and int(expires) - now < 300:
        refresh = sec.get_token("refresh_token")
        if refresh:
            try:
                data = actinate.refresh_token(refresh)
                _store_tokens(data)
                return data.get("access_token")
            except Exception as e:
                log.warning("Token refresh failed – clearing session: %s", e)
                sec.clear_tokens()
                db.set_setting("token_expires", "")
                db.set_setting("session_expired", "1")
                return None

    return token


def _store_tokens(data: dict):
    sec.set_token("access_token", data["access_token"])
    # Only overwrite refresh_token if a new one was returned
    new_refresh = data.get("refresh_token")
    if new_refresh:
        sec.set_token("refresh_token", new_refresh)
    expires_in = int(data.get("expires_in", 3600))
    db.set_setting("token_expires", str(int(time.time()) + expires_in))
    db.set_setting("session_expired", "")


# ── Fetch job (every 30 min) ───────────────────────────────────────────────────

def job_fetch_courses():
    studio_id_str = db.get_setting("studio_id", "43")
    studio_id = int(studio_id_str)
    log.info("Fetching courses for studio %d…", studio_id)
    try:
        token = _get_token()  # pass token so API returns real 'joined' state
        occurrences = actinate.fetch_upcoming(studio_id, days_ahead=14, access_token=token)
        db.upsert_occurrences(occurrences)
        db.set_setting("last_fetch", str(int(time.time())))
        log.info("Fetched %d occurrences (authenticated=%s).", len(occurrences), bool(token))
    except Exception as e:
        log.error("Course fetch failed: %s", e)


# ── Booking dispatcher (every minute) ─────────────────────────────────────────

def job_check_upcoming():
    now = int(time.time())
    subs = db.get_upcoming_subscriptions(now)

    for occ in subs:
        occ_id = occ["id"]

        # Skip if already booked (via app or previous run)
        if occ.get("joined"):
            log.debug("Skipping '%s' – already joined.", occ["name"])
            continue

        open_at = occ["start_at"] - occ["join_open_prior_seconds"]

        # Skip if too far in future (more than 70s until open)
        if open_at - now > 70:
            continue

        job_id = f"book_{occ_id}"
        if job_id in _scheduled:
            continue

        # The booking window is already open, or opens in <70s
        fire_at = max(now, open_at)
        fire_time = date.fromtimestamp(fire_at)  # just for logging

        log.info(
            "Scheduling booking job for '%s' (id=%d) at %s",
            occ["name"], occ_id, fire_at
        )
        scheduler.add_job(
            _book_with_retry,
            trigger=DateTrigger(run_date=__import__("datetime").datetime.fromtimestamp(fire_at, tz=pytz.timezone("Europe/Berlin"))),
            id=job_id,
            args=[occ_id],
            replace_existing=True,
            misfire_grace_time=300,
        )
        _scheduled.add(job_id)
        db.log_booking(occ_id, "scheduled", f"Booking job scheduled for t={fire_at}")


# ── Actual booking (with retry) ───────────────────────────────────────────────

def _book_with_retry(occurrence_id: int):
    """Try to book an occurrence. Retry every 20s for up to 3 minutes.
    If course is full, automatically join the waitlist instead."""
    MAX_TRIES = 9   # 9 × 20s = 3 minutes
    RETRY_DELAY = 20

    for attempt in range(1, MAX_TRIES + 1):
        token = _get_token()
        if not token:
            log.error("No valid token – cannot book occurrence %d", occurrence_id)
            db.log_booking(occurrence_id, "failed", "No access token available")
            return

        try:
            result = actinate.join_occurrence(occurrence_id, token)
            log.info("Booked occurrence %d on attempt %d: %s", occurrence_id, attempt, result)
            db.log_booking(occurrence_id, "booked", f"Attempt {attempt}: {result}")
            db.set_joined(occurrence_id, True)
            db.set_waitlist_position(occurrence_id, None)
            _scheduled.discard(f"book_{occurrence_id}")
            return
        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            msg = str(e)
            if status_code == 409:
                # Already booked
                log.info("Occurrence %d already booked (409).", occurrence_id)
                db.log_booking(occurrence_id, "booked", "Already registered (409)")
                db.set_joined(occurrence_id, True)
                _scheduled.discard(f"book_{occurrence_id}")
                return
            if status_code == 422:
                # Course is full – join waitlist
                log.info("Occurrence %d full (422), joining waitlist…", occurrence_id)
                _join_waitlist(occurrence_id, token)
                _scheduled.discard(f"book_{occurrence_id}")
                return
            if status_code == 403:
                log.warning("Occurrence %d not yet open or forbidden (403): %s", occurrence_id, msg)
            else:
                log.warning("Booking attempt %d/%d for %d failed: %s", attempt, MAX_TRIES, occurrence_id, msg)

            db.log_booking(occurrence_id, "failed", f"Attempt {attempt}: {msg}")

            if attempt < MAX_TRIES:
                time.sleep(RETRY_DELAY)

    log.error("All %d booking attempts failed for occurrence %d", MAX_TRIES, occurrence_id)
    _scheduled.discard(f"book_{occurrence_id}")


def _join_waitlist(occurrence_id: int, token: str):
    """Try to join the waitlist for a full occurrence."""
    try:
        result = actinate.join_waitlist(occurrence_id, token)
        position = result.get("waitlist_position") or result.get("position")
        log.info("Joined waitlist for occurrence %d, position: %s", occurrence_id, position)
        db.set_waitlist_position(occurrence_id, position)
        db.log_booking(occurrence_id, "waitlisted",
                       f"Warteliste Platz {position}" if position else "Warteliste (Position unbekannt)")
    except Exception as e:
        log.error("Failed to join waitlist for occurrence %d: %s", occurrence_id, e)
        db.log_booking(occurrence_id, "failed", f"Warteliste fehlgeschlagen: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def job_cleanup_log():
    db.cleanup_log(keep_days=30, max_rows=500)
    log.info("Booking log cleaned up.")


def start():
    scheduler.add_job(job_fetch_courses, IntervalTrigger(minutes=30), id="fetch_courses", replace_existing=True)
    scheduler.add_job(job_check_upcoming, IntervalTrigger(minutes=1), id="check_upcoming", replace_existing=True)
    scheduler.add_job(job_cleanup_log, IntervalTrigger(hours=24), id="cleanup_log", replace_existing=True)
    scheduler.start()
    # Fetch immediately on startup
    scheduler.add_job(job_fetch_courses, id="fetch_courses_startup", replace_existing=True)
    log.info("Scheduler started.")


def store_tokens(data: dict):
    _store_tokens(data)


def manual_fetch():
    job_fetch_courses()


def get_token():
    return _get_token()
