import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

CREDENTIALS_PATH = _base_dir() / "config" / "calendar_credentials.json"
TOKEN_PATH       = _base_dir() / "config" / "calendar_token.json"
SCOPES           = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    "Google Calendar credentials file not found. "
                    "Please place your OAuth2 client secrets file at config/calendar_credentials.json"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds)


def google_calendar(parameters: dict, player=None) -> str:
    action = parameters.get("action", "list_events")

    try:
        service = _get_service()
    except FileNotFoundError as e:
        return str(e)
    except Exception as e:
        return f"Failed to connect to Google Calendar: {e}"

    if action == "list_events":
        return _list_events(service, parameters, player)
    elif action == "create_event":
        return _create_event(service, parameters, player)
    else:
        return f"Unknown calendar action: {action}"


def _list_events(service, parameters: dict, player) -> str:
    days        = int(parameters.get("days", 7))
    max_results = int(parameters.get("max_results", 10))

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)

    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    if not events:
        return f"No events scheduled in the next {days} day(s)."

    lines = []
    for ev in events:
        start   = ev["start"].get("dateTime", ev["start"].get("date", ""))
        summary = ev.get("summary", "(No title)")
        try:
            if "T" in start:
                dt        = datetime.fromisoformat(start)
                formatted = dt.strftime("%A, %B %d at %I:%M %p")
            else:
                dt        = datetime.fromisoformat(start)
                formatted = dt.strftime("%A, %B %d (all day)")
        except Exception:
            formatted = start
        lines.append(f"{formatted}: {summary}")

    if player:
        player.write_log(f"[Calendar] 📅 {len(events)} event(s) retrieved")

    return f"You have {len(events)} upcoming event(s):\n" + "\n".join(lines)


def _create_event(service, parameters: dict, player) -> str:
    title       = parameters.get("title", "").strip()
    date        = parameters.get("date", "").strip()
    time_str    = parameters.get("time", "").strip()
    duration    = int(parameters.get("duration_minutes", 60))
    description = parameters.get("description", "").strip()

    if not title or not date:
        return "I need at least a title and a date to create a calendar event."

    try:
        if time_str:
            start_dt = datetime.strptime(f"{date} {time_str}", "%Y-%m-%d %H:%M")
            end_dt   = start_dt + timedelta(minutes=duration)
            tz_raw   = datetime.now().astimezone().strftime("%z")
            tz_off   = f"{tz_raw[:3]}:{tz_raw[3:]}"
            body = {
                "summary":     title,
                "description": description,
                "start": {"dateTime": start_dt.strftime("%Y-%m-%dT%H:%M:00") + tz_off},
                "end":   {"dateTime": end_dt.strftime("%Y-%m-%dT%H:%M:00") + tz_off},
            }
            label = start_dt.strftime("%A, %B %d at %I:%M %p")
        else:
            next_day = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            body = {
                "summary":     title,
                "description": description,
                "start": {"date": date},
                "end":   {"date": next_day},
            }
            label = date
    except ValueError:
        return "Couldn't parse the date or time. Please use YYYY-MM-DD for date and HH:MM for time."

    service.events().insert(calendarId="primary", body=body).execute()

    if player:
        player.write_log(f"[Calendar] ✅ Created: {title} — {label}")

    return f"Event '{title}' has been added to your calendar for {label}."
