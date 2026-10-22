"""구글 로그인과 캘린더 API를 얇게 감싼 부분. 나머지 코드는 GCal 메서드만 쓴다."""

import json
import shutil
import time
import webbrowser
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
        get_client_secret(home, open_browser=not no_browser)
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


GUIDE = """
구글 클라우드에서 'OAuth 클라이언트 파일'을 하나 받아야 해요. (처음 한 번, 5~10분)
브라우저에서 아래 순서대로 눌러 주세요. 각 화면 맨 위에 방금 만든 프로젝트가 선택돼 있는지 확인하세요.

 1) 프로젝트 만들기   https://console.cloud.google.com/projectcreate
    이름은 아무거나(예: hermes-calendar) → [만들기]
 2) 캘린더 API 켜기   https://console.cloud.google.com/apis/library/calendar-json.googleapis.com
    [사용]
 3) 앱 정보 넣기      https://console.cloud.google.com/auth/overview
    [시작하기] → 앱 이름·내 이메일 → 대상 '외부' → 연락처 이메일 → 동의 → [만들기]
 4) 앱 게시           https://console.cloud.google.com/auth/audience
    게시 상태 [앱 게시] → 확인   (안 하면 7일마다 로그인이 풀려요)
 5) 파일 받기         https://console.cloud.google.com/auth/clients
    [클라이언트 만들기] → 애플리케이션 유형 '데스크톱 앱' → [만들기] → [JSON 다운로드]

파일을 받으면 자동으로 다음 단계로 넘어가요. 다운로드 폴더를 지켜보는 중... (그만두려면 Ctrl+C)
"""


def _is_desktop_client(path: Path) -> bool:
    try:
        return "installed" in json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def find_client_secret() -> Path | None:
    """다운로드 폴더에서 구글이 준 client_secret*.json(데스크톱 앱용) 중 가장 새것."""
    folder = Path.home() / "Downloads"
    if not folder.is_dir():
        return None
    files = [p for p in folder.glob("client_secret*.json") if _is_desktop_client(p)]
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def get_client_secret(home: Path, open_browser: bool = True, wait_minutes: int = 30) -> Path:
    """credentials.json 준비: 다운로드 폴더에 있으면 옮기고, 없으면 안내를 띄우고 받을 때까지 기다린다."""
    target = home / "credentials.json"
    home.mkdir(parents=True, exist_ok=True)
    found = find_client_secret()
    if not found:
        print(GUIDE)
        if open_browser:
            webbrowser.open("https://console.cloud.google.com/projectcreate")
        deadline = time.time() + wait_minutes * 60
        try:
            while not found and not target.exists():
                if time.time() > deadline:
                    raise NotAuthorized("파일을 기다리다 멈췄어요. 받은 뒤 `hcal setup`을 다시 실행하세요.")
                time.sleep(3)
                found = find_client_secret()
        except KeyboardInterrupt:
            raise NotAuthorized("멈췄어요. 파일을 받은 뒤 `hcal setup`을 다시 실행하세요.") from None
    if found:
        shutil.copyfile(found, target)
        print(f"✅ 다운로드 폴더에서 {found.name} 을(를) 찾아 {target} 로 옮겼어요.")
    return target


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
