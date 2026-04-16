"""Flask web server for VeniceBeach auto-booker."""
import logging
import time
from datetime import date, timedelta, datetime

from flask import Flask, jsonify, request, render_template, abort

import db
import actinate
import scheduler as sched
import token_store as sec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s – %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Bootstrap ─────────────────────────────────────────────────────────────────

db.init_db()
sched.start()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _week_range(offset: int = 0):
    """Return (from_ts, to_ts, label) for week offset from today (0=this week)."""
    today = date.today()
    # Start of the week (Monday)
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    sunday = monday + timedelta(days=6)
    from_ts = int(datetime(monday.year, monday.month, monday.day).timestamp())
    to_ts = int(datetime(sunday.year, sunday.month, sunday.day, 23, 59, 59).timestamp())
    label = f"{monday.strftime('%d.%m.')} – {sunday.strftime('%d.%m.%Y')}"
    return from_ts, to_ts, label


def _ts_to_str(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%a %d.%m. %H:%M")


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── REST API ──────────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    token = sched.get_token()
    last_fetch = db.get_setting("last_fetch")
    return jsonify({
        "logged_in": bool(token),
        "session_expired": db.get_setting("session_expired") == "1",
        "last_fetch": int(last_fetch) if last_fetch else None,
        "studio_id": int(db.get_setting("studio_id", "43")),
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True)
    email = body.get("email", "").strip()
    password = body.get("password", "").strip()
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    try:
        data = actinate.login(email, password)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 500)
        return jsonify({"error": str(e)}), status
    sched.store_tokens(data)
    # Try to get user info
    try:
        me = actinate.get_me(data["access_token"])
        name = me.get("firstname", "") + " " + me.get("lastname", "")
        db.set_setting("user_name", name.strip())
    except Exception:
        pass
    return jsonify({"ok": True, "name": db.get_setting("user_name", "")})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    sec.clear_tokens()
    db.set_setting("token_expires", "")
    db.set_setting("session_expired", "")
    db.set_setting("user_name", "")
    return jsonify({"ok": True})


@app.route("/api/courses")
def api_courses():
    """Return occurrences grouped by day. Query param: week_offset (default 0)."""
    offset = int(request.args.get("week_offset", 0))
    studio_id = int(db.get_setting("studio_id", "43"))
    from_ts, to_ts, label = _week_range(offset)

    rows = db.get_occurrences(from_ts, to_ts, studio_id)

    # Group by day
    days: dict[str, list] = {}
    for r in rows:
        day_key = datetime.fromtimestamp(r["start_at"]).strftime("%Y-%m-%d")
        day_label = datetime.fromtimestamp(r["start_at"]).strftime("%A, %d.%m.%Y")
        if day_key not in days:
            days[day_key] = {"label": day_label, "occurrences": []}
        days[day_key]["occurrences"].append({
            "id": r["id"],
            "name": r["name"],
            "category": r["category"],
            "room": r["room"],
            "start_at": r["start_at"],
            "end_at": r["end_at"],
            "start_str": _ts_to_str(r["start_at"]),
            "end_str": datetime.fromtimestamp(r["end_at"]).strftime("%H:%M"),
            "max_participants": r["max_participants"],
            "attendees_count": r["attendees_count"],
            "join_mandatory": bool(r["join_mandatory"]),
            "subscribed": bool(r["subscribed"]),
            "joined": bool(r["joined"]),  # True = already booked (from API)
            "waitlist_position": r["waitlist_position"],
            "booking_opens_at": r["start_at"] - r["join_open_prior_seconds"],
            "booking_opens_str": _ts_to_str(r["start_at"] - r["join_open_prior_seconds"]),
        })

    return jsonify({
        "week_label": label,
        "week_offset": offset,
        "days": [{"key": k, **v} for k, v in sorted(days.items())],
    })


@app.route("/api/subscribe/<int:occurrence_id>", methods=["POST"])
def api_subscribe(occurrence_id):
    occ = db.get_occurrence(occurrence_id)
    if not occ:
        return jsonify({"error": "occurrence not found"}), 404
    db.add_subscription(occurrence_id)
    return jsonify({"ok": True})


@app.route("/api/unsubscribe/<int:occurrence_id>", methods=["POST"])
def api_unsubscribe(occurrence_id):
    db.remove_subscription(occurrence_id)
    return jsonify({"ok": True})


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    """Manually trigger a course fetch."""
    try:
        sched.manual_fetch()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/log")
def api_log():
    limit = int(request.args.get("limit", 50))
    rows = db.get_recent_log(limit)
    for r in rows:
        r["start_str"] = _ts_to_str(r.get("start_at"))
    return jsonify(rows)


@app.route("/api/book/<int:occurrence_id>", methods=["POST"])
def api_book_now(occurrence_id):
    """Immediately try to book an occurrence (manual trigger)."""
    token = sched.get_token()
    if not token:
        return jsonify({"error": "Not logged in"}), 401
    try:
        result = actinate.join_occurrence(occurrence_id, token)
        db.log_booking(occurrence_id, "booked", f"Manual: {result}")
        db.set_joined(occurrence_id, True)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 500)
        db.log_booking(occurrence_id, "failed", f"Manual: {e}")
        return jsonify({"error": str(e)}), status


@app.route("/api/waitlist/<int:occurrence_id>", methods=["POST"])
def api_waitlist_join(occurrence_id):
    """Join the waitlist for a full occurrence."""
    token = sched.get_token()
    if not token:
        return jsonify({"error": "Not logged in"}), 401
    try:
        result = actinate.join_waitlist(occurrence_id, token)
        position = result.get("waitlist_position") or result.get("position")
        db.set_waitlist_position(occurrence_id, position)
        db.log_booking(occurrence_id, "waitlisted",
                       f"Warteliste Platz {position}" if position else "Warteliste beigetreten")
        return jsonify({"ok": True, "waitlist_position": position})
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 500)
        db.log_booking(occurrence_id, "failed", f"Warteliste fehlgeschlagen: {e}")
        return jsonify({"error": str(e)}), status


@app.route("/api/waitlist/<int:occurrence_id>", methods=["DELETE"])
def api_waitlist_leave(occurrence_id):
    """Leave the waitlist for an occurrence."""
    token = sched.get_token()
    if not token:
        return jsonify({"error": "Not logged in"}), 401
    try:
        result = actinate.leave_waitlist(occurrence_id, token)
        db.set_waitlist_position(occurrence_id, None)
        db.log_booking(occurrence_id, "canceled", f"Warteliste verlassen: {result}")
        return jsonify({"ok": True})
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 500)
        db.log_booking(occurrence_id, "failed", f"Warteliste verlassen fehlgeschlagen: {e}")
        return jsonify({"error": str(e)}), status


@app.route("/api/leave/<int:occurrence_id>", methods=["POST"])
def api_leave(occurrence_id):
    """Cancel (leave) a booked occurrence."""
    token = sched.get_token()
    if not token:
        return jsonify({"error": "Not logged in"}), 401
    try:
        result = actinate.leave_occurrence(occurrence_id, token)
        db.log_booking(occurrence_id, "canceled", f"Manual leave: {result}")
        # Mark as no longer joined in DB so scheduler won't rebook immediately
        db.set_joined(occurrence_id, False)
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", 500)
        db.log_booking(occurrence_id, "failed", f"Manual leave: {e}")
        return jsonify({"error": str(e)}), status


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify({
        "studio_id": db.get_setting("studio_id", "43"),
        "user_name": db.get_setting("user_name", ""),
    })


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    body = request.get_json(force=True)
    if "studio_id" in body:
        db.set_setting("studio_id", str(int(body["studio_id"])))
    return jsonify({"ok": True})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    # Start the server on a generally accessible IP (0.0.0.0) and port 5000
    app.run(host="0.0.0.0", port=port, debug=False)
