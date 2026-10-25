"""Explicit, encrypted-at-rest integrations; no cloud AI services."""
from __future__ import annotations

import base64
import email
import hashlib
import imaplib
import re
import smtplib
import socket
import ssl
import tempfile
import threading
from datetime import date, datetime, time, timedelta, timezone
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from icalendar import Calendar, Event
from pydantic import BaseModel, Field, field_validator

from .deps import get_vault

router = APIRouter(prefix="/api")
MAX_AUDIO_BYTES = 100 * 1024 * 1024
MAX_ICS_BYTES = 10 * 1024 * 1024
MAX_MAIL_BYTES = 1024 * 1024
_speech_lock = threading.Lock()
_speech_models: dict[str, Any] = {}


def require_network(vault: Any) -> None:
    if not vault.settings().get("network_enabled", False):
        raise HTTPException(403, "Enable internet integrations in Privacy settings first.")


def _header(value: str) -> str:
    if "\r" in value or "\n" in value or "\x00" in value:
        raise ValueError("Mail headers cannot contain line breaks.")
    return value.strip()


def _host(value: str) -> str:
    value = value.strip().rstrip(".").encode("idna").decode("ascii")
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,251}[a-zA-Z0-9])?", value):
        raise ValueError("Enter a mail server hostname without a URL, path or port.")
    return value


def _addresses(value: str) -> list[str]:
    _header(value)
    recipients = [address for _, address in getaddresses([value])]
    if not recipients or len(recipients) > 20:
        raise ValueError("Enter between one and twenty recipient addresses.")
    for address in recipients:
        if not re.fullmatch(r"[^\s@<>,;:]+@[^\s@<>,;:]+\.[^\s@<>,;:]+", address):
            raise ValueError("Enter valid email addresses separated by commas.")
    return recipients


class MailAccount(BaseModel):
    id: str | None = None
    label: str = Field(default="Mail", max_length=100)
    email: str = Field(max_length=320)
    username: str = Field(default="", max_length=320)
    imap_host: str
    imap_port: int = 993
    smtp_host: str
    smtp_port: int = 465
    password: str = Field(default="", max_length=8192)
    oauth_token: str = Field(default="", max_length=16384)

    @field_validator("imap_host", "smtp_host")
    @classmethod
    def hosts(cls, value: str) -> str:
        return _host(value)

    @field_validator("email")
    @classmethod
    def address(cls, value: str) -> str:
        values = _addresses(value)
        if len(values) != 1:
            raise ValueError("An account needs exactly one email address.")
        return values[0]

    @field_validator("username", "label")
    @classmethod
    def headers(cls, value: str) -> str:
        return _header(value)

    @field_validator("password")
    @classmethod
    def password_value(cls, value: str) -> str:
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError("App passwords cannot contain line breaks or null characters.")
        return value

    @field_validator("imap_port")
    @classmethod
    def imap_tls(cls, value: int) -> int:
        if value != 993:
            raise ValueError("IMAP uses encrypted port 993.")
        return value

    @field_validator("smtp_port")
    @classmethod
    def smtp_tls(cls, value: int) -> int:
        if value not in (465, 587):
            raise ValueError("SMTP uses TLS port 465 or STARTTLS port 587.")
        return value


def public_account(account: dict) -> dict:
    return {key: value for key, value in account.items() if key not in ("password", "oauth_token")} | {
        "has_password": bool(account.get("password")),
        "has_oauth_token": bool(account.get("oauth_token")),
    }


@router.get("/mail/accounts")
def mail_accounts(vault: Any = Depends(get_vault)):
    return [public_account(account) for account in vault.list("mail_account")]


@router.post("/mail/accounts")
def save_mail_account(data: MailAccount, vault: Any = Depends(get_vault)):
    previous = vault.get("mail_account", data.id) if data.id else None
    if data.id and not previous:
        raise HTTPException(404, "Mail account not found.")
    if not previous and len(vault.list("mail_account")) >= 10:
        raise HTTPException(400, "This app supports at most ten mail accounts.")
    account = data.model_dump(exclude_none=True)
    account["username"] = account["username"] or account["email"]
    for key in ("password", "oauth_token"):
        if not account.get(key) and previous:
            account[key] = previous.get(key, "")
    if previous and any(account.get(key) != previous.get(key) for key in ("imap_host", "smtp_host", "username")):
        if not data.password and not data.oauth_token:
            raise HTTPException(400, "Enter the credential again when changing mail servers or username.")
    if not account.get("password") and not account.get("oauth_token"):
        raise HTTPException(400, "Add an app password or an OAuth access token.")
    if "\x01" in account["username"] or "\x01" in account["oauth_token"]:
        raise HTTPException(400, "Invalid authentication value.")
    return public_account(vault.put("mail_account", account))


@router.delete("/mail/accounts/{account_id}")
def delete_mail_account(account_id: str, vault: Any = Depends(get_vault)):
    if not vault.delete("mail_account", account_id):
        raise HTTPException(404, "Mail account not found.")
    for item in vault.list("mail"):
        if item.get("account_id") == account_id:
            vault.delete("mail", item["id"])
    return {"deleted": True}


def _account(vault: Any, account_id: str) -> dict:
    account = vault.get("mail_account", account_id)
    if not account:
        raise HTTPException(404, "Mail account not found.")
    return account


def _message_body(message: EmailMessage) -> str:
    """Prefer plain text; never expose active email HTML or load remote images."""
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        if part.get_content_disposition() == "attachment" or part.is_multipart():
            continue
        content_type = part.get_content_type()
        if content_type not in ("text/plain", "text/html"):
            continue
        raw = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        if content_type == "text/plain":
            plain.append(text)
        else:
            soup = BeautifulSoup(text, "html.parser")
            for element in soup(["script", "style", "noscript", "iframe", "object"]):
                element.decompose()
            html.append(soup.get_text(" ", strip=True))
    return "\n\n".join(plain or html)[:200_000]


def parse_mail(raw: bytes, account: dict, uid: str, validity: str) -> dict:
    message = email.message_from_bytes(raw, policy=policy.default)
    date_value = str(message.get("date", ""))
    try:
        date_value = parsedate_to_datetime(date_value).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    key = f"{account['id']}:{validity}:{uid}"
    return {
        "id": "mail_" + hashlib.sha256(key.encode()).hexdigest()[:32],
        "account_id": account["id"], "uid": uid,
        "message_id": str(message.get("message-id", "")),
        "subject": str(message.get("subject", "(No subject)")),
        "from": str(message.get("from", "")), "to": str(message.get("to", "")),
        "date": date_value, "body": _message_body(message),
        "truncated": len(raw) >= MAX_MAIL_BYTES,
    }


def fetch_mail(account: dict, limit: int = 100, guard=None) -> list[dict]:
    connection = None
    try:
        connection = imaplib.IMAP4_SSL(
            account["imap_host"], account.get("imap_port", 993),
            ssl_context=ssl.create_default_context(), timeout=30,
        )
        token = account.get("oauth_token")
        if token:
            auth = f"user={account['username']}\x01auth=Bearer {token}\x01\x01".encode()
            attempts = iter([auth, b""])
            connection.authenticate("XOAUTH2", lambda _: next(attempts, b""))
        else:
            connection.login(account["username"], account["password"])
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Could not open the inbox.")
        validity_data = connection.response("UIDVALIDITY")[1] or [b"0"]
        validity = (validity_data[0] or b"0").decode(errors="replace")
        status, data = connection.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("Could not list the inbox.")
        result = []
        uids = (data[0] or b"").split()[-limit:]
        for raw_uid in reversed(uids):
            if guard:
                guard()
            uid = raw_uid.decode("ascii")
            status, parts = connection.uid("fetch", raw_uid, f"(BODY.PEEK[]<0.{MAX_MAIL_BYTES}>)")
            if status != "OK":
                continue
            for part in parts:
                if isinstance(part, tuple) and isinstance(part[1], bytes):
                    result.append(parse_mail(part[1][:MAX_MAIL_BYTES], account, uid, validity))
                    break
        return result
    except (imaplib.IMAP4.error, OSError, ssl.SSLError, socket.timeout) as exc:
        raise HTTPException(502, "Mail sync failed. Check server settings, IMAP access and your app password or OAuth token.") from exc
    finally:
        if connection:
            try:
                connection.logout()
            except Exception:
                pass


class SyncMail(BaseModel):
    account_id: str
    limit: int = Field(default=100, ge=1, le=250)


@router.post("/mail/sync")
def sync_mail(data: SyncMail, vault: Any = Depends(get_vault)):
    require_network(vault)
    result = fetch_mail(_account(vault, data.account_id), data.limit, lambda: require_network(vault))
    vault.check_unlocked()
    for message in result:
        vault.put("mail", message)
    return {"synced": len(result), "scope": "Latest inbox messages; attachments are not downloaded."}


@router.get("/mail")
def cached_mail(q: str = "", account_id: str = "", vault: Any = Depends(get_vault)):
    query = q.strip().casefold()
    items = []
    for item in vault.list("mail"):
        if account_id and item.get("account_id") != account_id:
            continue
        if query and query not in " ".join(str(item.get(k, "")) for k in ("subject", "from", "to", "body")).casefold():
            continue
        items.append(item)
    return sorted(items, key=lambda item: item.get("date", ""), reverse=True)


@router.get("/mail/{message_id}")
def get_mail(message_id: str, vault: Any = Depends(get_vault)):
    item = vault.get("mail", message_id)
    if not item:
        raise HTTPException(404, "Message not found in the local cache.")
    return item


class SendMail(BaseModel):
    account_id: str
    to: str = Field(max_length=8000)
    subject: str = Field(default="", max_length=998)
    body: str = Field(max_length=500_000)
    confirm: bool = False

    @field_validator("to")
    @classmethod
    def recipients(cls, value: str) -> str:
        _addresses(value)
        return value

    @field_validator("subject")
    @classmethod
    def subject_header(cls, value: str) -> str:
        return _header(value)


def deliver_mail(account: dict, data: SendMail) -> None:
    message = EmailMessage()
    message["From"] = account["email"]
    message["To"] = data.to
    message["Subject"] = data.subject
    message.set_content(data.body)
    connection = None
    try:
        context = ssl.create_default_context()
        if account.get("smtp_port", 465) == 465:
            connection = smtplib.SMTP_SSL(account["smtp_host"], 465, timeout=30, context=context)
        else:
            connection = smtplib.SMTP(account["smtp_host"], 587, timeout=30)
            connection.ehlo()
            connection.starttls(context=context)
            connection.ehlo()
        if account.get("oauth_token"):
            auth = f"user={account['username']}\x01auth=Bearer {account['oauth_token']}\x01\x01".encode()
            status, _ = connection.docmd("AUTH", "XOAUTH2 " + base64.b64encode(auth).decode("ascii"))
            if status != 235:
                raise smtplib.SMTPAuthenticationError(status, b"OAuth authentication failed")
        else:
            connection.login(account["username"], account["password"])
        refused = connection.send_message(message, from_addr=account["email"], to_addrs=_addresses(data.to))
        if refused:
            raise HTTPException(502, "The server rejected one or more recipients; others may have received the message. Check before retrying.")
    except HTTPException:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        raise HTTPException(502, "The SMTP request failed. Delivery may be uncertain; check Sent mail before retrying. Verify server settings and credentials.") from exc
    finally:
        if connection:
            try:
                connection.quit()
            except Exception:
                pass


@router.post("/mail/send")
def send_mail(data: SendMail, vault: Any = Depends(get_vault)):
    if data.confirm is not True:
        raise HTTPException(400, "Review the recipient and message, then explicitly confirm sending.")
    require_network(vault)
    account = _account(vault, data.account_id)
    vault.check_unlocked()
    deliver_mail(account, data)
    return {"sent": True}


def _aware(value: datetime | date, tz: ZoneInfo) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    return datetime.combine(value, time.min, tzinfo=tz)


def parse_ics(content: bytes, timezone_name: str = "Asia/Dubai", source: str = "ics", window: tuple[datetime, datetime] | None = None) -> tuple[list[dict], list[str]]:
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(400, "Enter a valid IANA timezone, for example Asia/Dubai.") from exc
    try:
        calendar = Calendar.from_ical(content)
    except Exception as exc:
        raise HTTPException(400, "This file is not a valid iCalendar (.ics) file.") from exc
    components = list(calendar.walk("VEVENT"))
    if len(components) > 2000:
        raise HTTPException(400, "Import at most 2,000 events at a time.")
    warnings = []
    if any("RRULE" in item or "RDATE" in item for item in components):
        try:
            import recurring_ical_events
        except ImportError as exc:
            raise HTTPException(503, "Install recurring-ical-events to import recurring calendars.") from exc
        now = datetime.now(timezone.utc)
        range_start, range_end = window or (now - timedelta(days=30), now + timedelta(days=365))
        try:
            components = recurring_ical_events.of(calendar).between(range_start, range_end)
        except Exception as exc:
            raise HTTPException(400, "Could not expand this calendar's recurrence rules.") from exc
        if window:
            warnings.append(f"Recurring events were expanded from {range_start.date()} through {range_end.date()}. Re-import later to extend the range.")
        else:
            warnings.append("This recurring calendar was expanded from 30 days ago through 365 days ahead. Re-import later to extend the range.")
    if len(components) > 2000:
        raise HTTPException(400, "This calendar expands to more than 2,000 events. Import a smaller calendar.")
    results = []
    for component in components:
        try:
            start_value = component.decoded("DTSTART")
            start = _aware(start_value, tz)
            if "DTEND" in component:
                end = _aware(component.decoded("DTEND"), tz)
            elif "DURATION" in component:
                end = start + component.decoded("DURATION")
            else:
                end = start + (timedelta(days=1) if not isinstance(start_value, datetime) else timedelta(hours=1))
            if end < start:
                raise ValueError("End precedes start")
            uid = str(component.get("UID", "")) or hashlib.sha256(component.to_ical()).hexdigest()
            occurrence = str(component.get("RECURRENCE-ID", ""))
            identity = f"{source}:{uid}:{occurrence}"
            results.append({
                "id": "event_" + hashlib.sha256(identity.encode()).hexdigest()[:32],
                "title": str(component.get("SUMMARY", "Untitled event"))[:500],
                "start": start.isoformat(), "end": end.isoformat(),
                "location": str(component.get("LOCATION", ""))[:2000],
                "description": str(component.get("DESCRIPTION", ""))[:50000],
                "all_day": not isinstance(start_value, datetime),
                "external_uid": uid, "source": source,
            })
        except (TypeError, ValueError, KeyError, AttributeError):
            warnings.append("An event with an invalid or missing date was skipped.")
    return results, list(dict.fromkeys(warnings))


def make_ics(events: list[dict]) -> bytes:
    calendar = Calendar()
    calendar.add("prodid", "-//Sultan Local AI//Calendar//EN")
    calendar.add("version", "2.0")
    for data in events:
        item = Event()
        # Local IDs distinguish imported occurrences when exporting a flattened calendar.
        item.add("uid", data["id"] + "@sultan-local-ai.local")
        item.add("summary", data.get("title", "Untitled event"))
        try:
            start = datetime.fromisoformat(data["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(data["end"].replace("Z", "+00:00"))
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, "An event has an invalid date; correct it before exporting.") from exc
        if data.get("all_day"):
            item.add("dtstart", start.date())
            item.add("dtend", end.date())
        else:
            item.add("dtstart", start)
            item.add("dtend", end)
        item.add("dtstamp", datetime.now(timezone.utc))
        item.add("location", data.get("location", ""))
        item.add("description", data.get("description", ""))
        calendar.add_component(item)
    return calendar.to_ical()


async def bounded_upload(file: UploadFile, limit: int) -> bytes:
    chunks = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"This file exceeds the {limit // (1024 * 1024)} MB limit.")
        chunks.append(chunk)
    if not total:
        raise HTTPException(400, "The uploaded file is empty.")
    return b"".join(chunks)


@router.post("/calendar/import")
async def import_calendar(file: UploadFile = File(...), timezone: str = Form("Asia/Dubai"), vault: Any = Depends(get_vault)):
    from starlette.concurrency import run_in_threadpool
    content = await bounded_upload(file, MAX_ICS_BYTES)
    events, warnings = await run_in_threadpool(parse_ics, content, timezone)
    vault.check_unlocked()
    for item in events:
        vault.put("event", item)
    return {"imported": len(events), "warnings": warnings}


@router.get("/calendar/export")
def export_calendar(vault: Any = Depends(get_vault)):
    return Response(make_ics(vault.list("event")), media_type="text/calendar", headers={"Content-Disposition": 'attachment; filename="sultan-calendar.ics"'})


class CalendarSync(BaseModel):
    url: str = Field(max_length=4096)
    username: str = Field(default="", max_length=500)
    password: str = Field(default="", max_length=8192)
    start: str | None = None
    end: str | None = None
    timezone: str = "Asia/Dubai"


@router.get("/calendar/config")
def calendar_config(vault: Any = Depends(get_vault)):
    config = vault.get("calendar_account", "caldav") or {}
    return {"url": config.get("url", ""), "username": config.get("username", ""), "has_password": bool(config.get("password"))}


def fetch_caldav(config: dict, start: datetime, end: datetime) -> bytes:
    """Read a known CalDAV collection without following authenticated redirects."""
    import http.client
    from urllib.parse import urlsplit
    from .browser_core import _PinnedHTTPSConnection, normalize_public_url, resolve_public_addresses

    url = normalize_public_url(config["url"])
    parsed = urlsplit(url)
    addresses = resolve_public_addresses(parsed.hostname or "")
    connection = _PinnedHTTPSConnection(parsed.hostname or "", addresses[0], 20)
    response = None
    start_value = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    end_value = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    body = f'''<?xml version="1.0" encoding="UTF-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter>
<c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
<c:time-range start="{start_value}" end="{end_value}"/>
</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'''.encode()
    headers = {
        "Depth": "1", "Content-Type": "application/xml; charset=utf-8",
        "Accept": "application/xml,text/xml", "Accept-Encoding": "identity",
        "Connection": "close", "User-Agent": "SultanLocalAI/1.0",
        "Authorization": "Basic " + base64.b64encode(f"{config['username']}:{config['password']}".encode()).decode(),
    }
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    try:
        connection.request("REPORT", target, body=body, headers=headers)
        response = connection.getresponse()
        if response.status in (301, 302, 303, 307, 308):
            raise HTTPException(400, "The CalDAV URL redirects. Enter the final calendar collection URL; credentials were not forwarded.")
        if response.status not in (200, 207):
            raise HTTPException(502, "CalDAV import failed. Check the collection URL, username and app password.")
        if (response.getheader("Content-Encoding") or "identity").lower() not in ("", "identity"):
            raise HTTPException(502, "The CalDAV server returned an unsupported compressed response.")
        content = response.read(MAX_ICS_BYTES + 1)
        if len(content) > MAX_ICS_BYTES:
            raise HTTPException(413, "The remote calendar exceeds the 10 MB import limit.")
        return content
    except (http.client.HTTPException, OSError, ssl.SSLError) as exc:
        raise HTTPException(502, "Could not connect securely to this CalDAV calendar.") from exc
    finally:
        if response:
            response.close()
        connection.close()


@router.post("/calendar/sync")
def sync_calendar(data: CalendarSync, vault: Any = Depends(get_vault)):
    from .browser_core import normalize_public_url
    from defusedxml import ElementTree
    from defusedxml.common import DefusedXmlException

    require_network(vault)
    previous = vault.get("calendar_account", "caldav") or {}
    url = normalize_public_url(data.url)
    if ":" in data.username or any(c in data.username for c in ("\r", "\n", "\x00")):
        raise HTTPException(400, "Invalid CalDAV username.")
    password = data.password
    if not password and previous.get("url") == url and previous.get("username") == data.username:
        password = previous.get("password", "")
    if not password or not data.username:
        raise HTTPException(400, "Enter your CalDAV username and app password. Re-enter the password when changing the calendar URL.")
    now = datetime.now(timezone.utc)
    try:
        start = datetime.fromisoformat(data.start.replace("Z", "+00:00")) if data.start else now - timedelta(days=30)
        end = datetime.fromisoformat(data.end.replace("Z", "+00:00")) if data.end else now + timedelta(days=365)
        if not start.tzinfo or not end.tzinfo or end <= start or end - start > timedelta(days=730):
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, "Choose timezone-aware start/end dates spanning at most 730 days.") from exc
    config = {"id": "caldav", "url": url, "username": data.username, "password": password}
    content = fetch_caldav(config, start, end)
    try:
        tree = ElementTree.fromstring(content)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise HTTPException(502, "The CalDAV server returned invalid or unsafe XML.") from exc
    events = []
    warnings = []
    for node in tree.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data"):
        if not node.text:
            continue
        parsed, notes = parse_ics(node.text.encode("utf-8"), data.timezone, source=url, window=(start, end))
        events.extend(parsed)
        warnings.extend(notes)
        if len(events) > 2000:
            raise HTTPException(400, "The remote calendar contains more than 2,000 events in this range.")
    vault.check_unlocked()
    vault.put("calendar_account", config)
    for item in events:
        vault.put("event", item)
    return {"imported": len(events), "warnings": list(dict.fromkeys(warnings)), "direction": "read-only", "message": "Imported remote events into your local calendar. Remote deletions and local edits are not synced back."}


def _speech_model(path: str):
    if not path:
        raise HTTPException(503, "Download a speech model with scripts/download_speech.py, then select its folder in Settings.")
    model_dir = Path(path).expanduser().resolve()
    if not model_dir.is_dir() or not (model_dir / "model.bin").is_file():
        raise HTTPException(503, "Speech model folder must contain a downloaded faster-whisper model.bin file.")
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise HTTPException(503, "Speech is not installed. Run python -m pip install -r requirements-speech.txt.") from exc
    key = str(model_dir)
    if key not in _speech_models:
        try:
            model = WhisperModel(key, device="cpu", compute_type="int8", local_files_only=True, cpu_threads=4)
        except Exception as exc:
            raise HTTPException(503, "Could not load the local speech model. Check that its downloaded files are complete.") from exc
        _speech_models.clear()
        _speech_models[key] = model
    return _speech_models[key]


def transcribe_audio(path: Path, model_path: str, language: str = "auto") -> dict:
    if language != "auto" and not re.fullmatch(r"[a-z]{2,3}", language):
        raise HTTPException(400, "Choose auto or a language code such as en or ar.")
    with _speech_lock:
        model = _speech_model(model_path)
        try:
            segments, info = model.transcribe(
                str(path), language=None if language == "auto" else language,
                beam_size=5, vad_filter=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise HTTPException(400, "Could not transcribe this audio. Try a clear WAV, MP3, M4A or WebM recording and check the language code.") from exc
        return {"text": text, "language": info.language}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), language: str = Form("auto"), vault: Any = Depends(get_vault)):
    from starlette.concurrency import run_in_threadpool
    model_path = vault.settings().get("speech_model_path", "")
    if not model_path:
        raise HTTPException(503, "Set the downloaded speech model folder in Settings first.")
    content = await bounded_upload(file, MAX_AUDIO_BYTES)
    # Only the audio decoder sees this temporary plaintext file; deletion runs on every exit path.
    with tempfile.TemporaryDirectory(prefix="sultan-audio-") as directory:
        path = Path(directory) / "recording.audio"
        path.write_bytes(content)
        path.chmod(0o600)
        result = await run_in_threadpool(transcribe_audio, path, model_path, language)
    vault.check_unlocked()
    return result
