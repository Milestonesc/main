"""헤르메스가 부르는 MCP 서버(stdio). 도구 설명은 헤르메스가 그대로 읽으니 한국어로 쓴다."""

from datetime import date, datetime, timedelta
from functools import cache, wraps

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from . import config
from .core import Calendar, UserError
from .days import dday_label, wd
from .gcal import GCal, NotAuthorized

mcp = FastMCP("hermes-calendar")


def tool(fn):
    """도구 등록. 실패하면 헤르메스가 읽고 사용자에게 전할 수 있게 error 문구로 돌려준다."""
    @wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (UserError, NotAuthorized) as e:
            return {"error": str(e)}
        except Exception as e:  # 구글 API 오류 등
            return {"error": f"{type(e).__name__}: {e}"}
    return mcp.tool()(run)


@cache
def _gcal() -> GCal:
    return GCal.connect(config.home())


def _cal() -> Calendar:  # 매번 새로 만들어 연차 등 최신 상태를 반영
    home = config.home()
    return Calendar(config.load(), _gcal(), state_path=home / "reminded.json")


@tool
def add_event(title: str, start: str, end: str | None = None, minutes: int | None = None, location: str = "",
              description: str = "", memo: str = "", todos: list[str] | None = None, remind: str | None = None,
              repeat: str | None = None, until: str | None = None, count: int | None = None, dday: bool = False,
              track: bool = True, force: bool = False) -> dict:
    """일정을 'Hermes' 캘린더에 등록한다. 상태는 '예정'으로 시작하고 기록에 '등록'이 남는다.

    start: '2026-10-22 15:00'(시각) 또는 '2026-10-22'(종일). end를 안 주면 minutes, 그것도 없으면 60분.
    종일 일정의 end는 마지막 날짜(포함).
    description: 일정의 짧은 설명(사용자가 설명을 말했을 때). memo: 첫 메모 한 줄. todos: 준비물·할 일 목록.
    remind: 사용자가 알림을 말했을 때만 '30', '1h', '1h,10m', '1d'.
    repeat: daily/weekdays/weekly/biweekly/monthly/yearly 또는 RRULE. dday: 브리핑에 D-day로 보여줄 일정.
    track: 생일·기념일·연차처럼 '하는 일'이 아닌 일정은 false (지난 뒤 결과를 묻지 않음).
    겹치는 일정이 있으면 등록하지 않고 created=false와 conflicts를 돌려준다. 사용자에게 확인받은 뒤 force=true로 다시 부른다.
    notes에 공휴일·연차 안내가 있으면 사용자에게 함께 알린다."""
    return _cal().add(title, start, end=end, minutes=minutes, location=location, description=description, memo=memo,
                      todos=todos, remind=remind, repeat=repeat, until=until, count=count, dday=dday, track=track,
                      force=force)


@tool
def list_events(start: str | None = None, end: str | None = None, query: str | None = None,
                status: str | None = None) -> dict:
    """start~end(둘 다 포함, YYYY-MM-DD) 일정과 쉬는 날(off_days), 상태별 개수(counts). 기본은 오늘부터 7일.
    query로 제목·설명 검색. status(예정/진행중/지연됨/완료/못함/취소)로 그 상태만.
    "이번 달 어땠어?"는 이번 달 범위로 불러 counts와 못함·지연됨 목록을 요약한다."""
    cal = _cal()
    s = date.fromisoformat(start) if start else cal.today()
    e = date.fromisoformat(end) if end else s + timedelta(days=6)
    return cal.agenda(s, e, query, status)


@tool
def get_event(event_id: str, calendar_id: str | None = None) -> dict:
    """일정 하나의 전체 내용: 상태, 설명, 할 일(번호 포함), 메모, 기록."""
    return _cal().get(event_id, calendar_id)


@tool
def update_event(event_id: str, calendar_id: str | None = None, title: str | None = None,
                 start: str | None = None, end: str | None = None, minutes: int | None = None,
                 location: str | None = None, description: str | None = None, memo: str | None = None,
                 remind: str | None = None, clear_remind: bool = False, dday: bool | None = None,
                 track: bool | None = None, series: bool = False, force: bool = False) -> dict:
    """사용자가 '계획을 바꿀 때'의 수정. 바꿀 값만 준다. 시간을 바꾸면 기록에 '시간 변경 이전 → 이후'가 남는다.
    원치 않게 밀린 경우는 이 도구가 아니라 set_status(status='지연됨', start=새 시각)를 쓴다.
    시작만 바꾸면 길이 유지. description은 설명 바꿔 쓰기, memo는 메모 한 줄 덧붙이기.
    remind로 알림 추가·변경, clear_remind=true로 끄기. series=true면 반복 일정 전체.
    겹치면 updated=false → 사용자 확인 후 force=true."""
    return _cal().update(event_id, calendar_id, title=title, start=start, end=end, minutes=minutes, location=location,
                         description=description, memo=memo, remind=remind, clear_remind=clear_remind, dday=dday,
                         track=track, series=series, force=force)


@tool
def set_status(event_id: str, status: str, note: str | None = None, start: str | None = None,
               end: str | None = None, calendar_id: str | None = None, force: bool = False) -> dict:
    """일정 상태를 바꾸고 기록에 남긴다. 구글 캘린더 제목 앞에 표시가 붙는다.

    status: 예정 / 진행중(▶️) / 지연됨(⏳) / 완료(✅) / 못함(❗) / 취소(❌)
    - 지연됨: 원치 않게 밀린 경우. 밀린 새 시각을 알면 start(필요하면 end)도 준다 → 일정이 옮겨지고 '지연 이전 → 이후'로 기록.
    - 못함: 시간이 지났는데 하지 못한 경우. 취소: 하지 않기로 한 경우(겹침·바쁨에서 빠진다).
    note: 결과나 사유 한 줄("다음 진료 11/6", "차가 막힘"). 사용자가 말한 경우에만."""
    return _cal().set_status(event_id, status, note=note, start=start, end=end, calendar_id=calendar_id, force=force)


@tool
def edit_notes(event_id: str, calendar_id: str | None = None, description: str | None = None,
               memo: str | None = None, add_todos: list[str] | None = None, check: list[str] | None = None,
               uncheck: list[str] | None = None, remove_todos: list[str] | None = None) -> dict:
    """설명·메모·할 일 고치기. description은 바꿔 쓰기, memo는 날짜를 붙여 한 줄 덧붙이기.
    할 일은 add_todos로 추가, check/uncheck/remove_todos로 번호('1') 또는 글자 일부('보험증')를 가리켜 체크·해제·삭제."""
    return _cal().edit_notes(event_id, calendar_id, description=description, memo=memo, add_todos=add_todos,
                             check=check, uncheck=uncheck, remove_todos=remove_todos)


@tool
def pending_review(days: int = 14) -> dict:
    """끝났는데 결과(완료·못함·취소)가 안 남은 지난 일정(최근 days일). 사용자가 결과를 말하면 set_status로 기록한다."""
    return {"events": [e.to_dict() for e in _cal().review(days)]}


@tool
def delete_event(event_id: str, calendar_id: str | None = None, series: bool = False) -> dict:
    """일정을 완전히 지운다(기록도 사라짐). 사용자가 '지워/삭제'라고 분명히 말했을 때만 쓰고,
    '취소됐어/안 가'는 set_status(status='취소')로 기록을 남긴다. series=true면 반복 일정 전체."""
    return _cal().delete(event_id, calendar_id, series)


@tool
def check_conflicts(start: str, end: str) -> dict:
    """그 시간(예: '2026-10-22 15:00' ~ '2026-10-22 16:00')에 겹치는 일정."""
    cal = _cal()
    s, e = cal._times(start, end, None)[2:]
    if not hasattr(s, "hour"):
        return {"conflicts": [], "note": "종일 범위는 겹침을 보지 않아요. 시각을 주세요."}
    return {"conflicts": [c.to_dict() for c in cal.conflicts(s, e)]}


@tool
def day_info(day: str | None = None) -> dict:
    """그날(YYYY-MM-DD, 기본 오늘)이 쉬는 날인지와 이유(주말·공휴일·대체공휴일·근로자의 날·연차), 그날 일정."""
    cal = _cal()
    return cal.day_info(date.fromisoformat(day) if day else cal.today())


@tool
def business_days(start: str, add: int | None = None, until: str | None = None) -> dict:
    """영업일 계산(주말·공휴일·연차 제외). add=N: start에서 영업일 N일 뒤 날짜(음수면 앞).
    until=날짜: start 다음날부터 until까지 영업일 수."""
    days = _cal().days
    s = date.fromisoformat(start)
    if add is not None:
        d = days.add_workdays(s, add)
        return {"date": d.isoformat(), "weekday": wd(d)}
    if until:
        return {"workdays": days.workdays_between(s, date.fromisoformat(until))}
    return {"error": "add 또는 until 중 하나를 주세요."}


@tool
def dday(target: str) -> dict:
    """target(YYYY-MM-DD)까지 D-day. 예: D-30, D-Day, D+3."""
    return {"label": dday_label(date.fromisoformat(target), datetime.now(config.load().tz).date())}


@tool
def briefing(day: str | None = None) -> str | dict:
    """그날 브리핑 글(오늘 일정, 겹침, 내일 미리보기, 다가오는 쉬는 날, D-day, 결과가 안 남은 지난 일정).
    매일 08:30 크론과 같은 내용."""
    cal = _cal()
    return cal.brief(date.fromisoformat(day) if day else None)


@tool
def today() -> dict:
    """오늘 날짜·요일·현재 시각. '내일', '다음주 화요일' 같은 말을 날짜로 바꾸기 전에 확인한다."""
    now = datetime.now(config.load().tz)
    return {"date": now.date().isoformat(), "weekday": wd(now.date()), "time": f"{now:%H:%M}", "timezone": str(now.tzinfo)}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
