from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SEOUL = ZoneInfo("Asia/Seoul")
DB_HOST = "dbgroup.recruiter.co.kr"
DB_APPLY = f"https://{DB_HOST}/career/apply"


def now() -> datetime:
    return datetime.now(SEOUL)


def check_url(url: str, *, application: bool = False) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Use an HTTPS URL without credentials or a custom port.")
    allowed = parts.hostname == DB_HOST
    if not application:
        allowed |= parts.hostname in {"app.notion.com", "www.notion.so", "notion.so"}
        allowed |= bool(parts.hostname and parts.hostname.endswith(".notion.site"))
    if not allowed:
        raise ValueError("This MVP supports public Notion pages and DB Group recruitment only.")
    return url
