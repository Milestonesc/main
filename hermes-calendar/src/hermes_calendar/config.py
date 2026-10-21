"""설정 파일과 저장 위치.

모든 파일은 HCAL_HOME(기본: <헤르메스 폴더>/hcal)에 둔다.
헤르메스 폴더 = $HERMES_HOME, 없으면 윈도우 %LOCALAPPDATA%\\hermes, 그 외 ~/.hermes (헤르메스와 같은 규칙).
  credentials.json  구글 클라우드에서 받은 OAuth 클라이언트 파일
  token.json        로그인 후 생기는 토큰
  config.json       아래 DEFAULTS를 덮어쓰는 설정
  reminded.json     이미 보낸 알림 기록
"""

import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULTS = {
    "timezone": "Asia/Seoul",
    "hermes_calendar_name": "Hermes",
    "hermes_calendar_id": None,  # hcal setup 이 채운다
    "read_calendars": ["primary"],  # 브리핑·겹침 확인 때 함께 읽는 캘린더
    "holiday_calendar_id": "ko.south_korea#holiday@group.v.calendar.google.com",
    "may_day_off": True,  # 근로자의 날(5/1) 쉬는 날로 계산
    "leave_keywords": ["연차", "휴가", "월차", "휴무"],  # 이 단어가 든 종일 일정 = 쉬는 날
    "default_duration_minutes": 60,
}


def hermes_home() -> Path:
    if os.environ.get("HERMES_HOME", "").strip():
        return Path(os.path.expandvars(os.environ["HERMES_HOME"])).expanduser()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "hermes"
    return Path.home() / ".hermes"


def home() -> Path:
    if os.environ.get("HCAL_HOME"):
        return Path(os.environ["HCAL_HOME"]).expanduser()
    return hermes_home() / "hcal"


class Config(dict):
    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self["timezone"])

    def calendars(self) -> list[str]:
        """읽을 캘린더 목록. 전용 캘린더가 맨 앞."""
        ids = [self["hermes_calendar_id"], *self["read_calendars"]]
        return list(dict.fromkeys(i for i in ids if i))

    def write_calendar(self) -> str:
        return self["hermes_calendar_id"] or "primary"


def load(path: Path | None = None) -> Config:
    path = path or home() / "config.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return Config({**DEFAULTS, **data})


def save(cfg: Config, path: Path | None = None) -> None:
    path = path or home() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
