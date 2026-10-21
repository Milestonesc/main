"""구글 로그인과 캘린더 API를 얇게 감싼 부분. 나머지 코드는 GCal 메서드만 쓴다."""

from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class NotAuthorized(RuntimeError):
    pass


def credentials(home: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = home / "token.json"
    if not token.exists():
        raise NotAuthorized("구글 로그인이 안 돼 있어요. 먼저 `hcal setup`을 실행하세요.")
    creds = Credentials.from_authorized_user_file(str(token), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise NotAuthorized("구글 로그인이 만료됐어요. `hcal setup`을 다시 실행하세요.")
    return creds


def login(home: Path, no_browser: bool = False) -> None:
    """OAuth 로그인 후 token.json 저장.

    no_browser: 화면 없는 서버용. 링크를 다른 기기에서 열고, 로그인 후 열리지 않는
    localhost 페이지의 주소를 통째로 붙여넣으면 된다.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    secret = home / "credentials.json"
    if not secret.exists():
        raise NotAuthorized(f"{secret} 파일이 없어요. README의 '구글 클라우드 준비'를 따라 받아 두세요.")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    if no_browser:
        flow.redirect_uri = "http://localhost:1"
        url, _ = flow.authorization_url(prompt="consent", access_type="offline")
        print("아래 링크를 브라우저에서 열고 로그인하세요:\n" + url)
        pasted = input("\n로그인 후 주소창의 주소(http://localhost:1/?...code=...)를 붙여넣으세요: ").strip()
        code = parse_qs(urlparse(pasted).query).get("code", [pasted])[0]
        flow.fetch_token(code=code)
        creds = flow.credentials
    else:
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    home.mkdir(parents=True, exist_ok=True)
    (home / "token.json").write_text(creds.to_json(), encoding="utf-8")


class GCal:
    def __init__(self, service):
        self.s = service

    @classmethod
    def connect(cls, home: Path) -> "GCal":
        from googleapiclient.discovery import build

        return cls(build("calendar", "v3", credentials=credentials(home), cache_discovery=False))

    def events(self, calendar_id: str, start: datetime, end: datetime, query: str | None = None,
               private: str | None = None) -> list[dict]:
        """반복 일정은 펼친 상태로, 시작 시간 순서대로."""
        items, page = [], None
        while True:
            r = self.s.events().list(
                calendarId=calendar_id, timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", q=query, privateExtendedProperty=private,
                pageToken=page, maxResults=250,
            ).execute()
            items += r.get("items", [])
            page = r.get("nextPageToken")
            if not page:
                return items

    def get(self, calendar_id: str, event_id: str) -> dict | None:
        from googleapiclient.errors import HttpError

        try:
            return self.s.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                return None
            raise

    def insert(self, calendar_id: str, body: dict) -> dict:
        return self.s.events().insert(calendarId=calendar_id, body=body).execute()

    def patch(self, calendar_id: str, event_id: str, body: dict) -> dict:
        return self.s.events().patch(calendarId=calendar_id, eventId=event_id, body=body).execute()

    def delete(self, calendar_id: str, event_id: str) -> None:
        self.s.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    def ensure_calendar(self, name: str, timezone: str) -> str:
        """이름이 같은 캘린더가 있으면 그 id, 없으면 새로 만든다."""
        for c in self.s.calendarList().list().execute().get("items", []):
            if c.get("summary") == name and c.get("accessRole") == "owner":
                return c["id"]
        return self.s.calendars().insert(body={"summary": name, "timeZone": timezone}).execute()["id"]
