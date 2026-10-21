import copy
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from hermes_calendar import config
from hermes_calendar.cli import main
from hermes_calendar.core import Calendar, UserError, parse_offsets

KST = ZoneInfo("Asia/Seoul")
HERMES, PRIMARY, HOLI = "hermes-cal", "primary", config.DEFAULTS["holiday_calendar_id"]


class FakeGCal:
    """GCal과 같은 메서드만 흉내 낸 메모리 저장소."""

    def __init__(self):
        self.store: dict[str, dict[str, dict]] = {}
        self.n = 0

    def _bounds(self, ev):
        if "date" in ev["start"]:
            return (datetime.combine(date.fromisoformat(ev["start"]["date"]), time(), KST),
                    datetime.combine(date.fromisoformat(ev["end"]["date"]), time(), KST))
        return datetime.fromisoformat(ev["start"]["dateTime"]), datetime.fromisoformat(ev["end"]["dateTime"])

    def events(self, cal, start, end, query=None, private=None):
        out = []
        for ev in self.store.get(cal, {}).values():
            s, e = self._bounds(ev)
            if not (s < end and e > start):
                continue
            if private:
                k, v = private.split("=")
                if ev.get("extendedProperties", {}).get("private", {}).get(k) != v:
                    continue
            if query and query not in ev.get("summary", "") + ev.get("description", ""):
                continue
            out.append(copy.deepcopy(ev))
        return sorted(out, key=lambda ev: self._bounds(ev)[0])

    def get(self, cal, event_id):
        return copy.deepcopy(self.store.get(cal, {}).get(event_id))

    def insert(self, cal, body):
        self.n += 1
        ev = {**copy.deepcopy(body), "id": f"ev{self.n}"}
        self.store.setdefault(cal, {})[ev["id"]] = ev
        return copy.deepcopy(ev)

    def patch(self, cal, event_id, body):
        ev = self.store[cal][event_id]
        for k, v in body.items():
            if k == "extendedProperties":
                ev.setdefault(k, {}).setdefault("private", {}).update(v["private"])
            else:
                ev[k] = copy.deepcopy(v)
        return copy.deepcopy(ev)

    def delete(self, cal, event_id):
        del self.store[cal][event_id]


def timed(title, start, minutes=60, **extra):
    s = datetime.fromisoformat(start).replace(tzinfo=KST)
    return {"summary": title, "start": {"dateTime": s.isoformat()},
            "end": {"dateTime": (s + timedelta(minutes=minutes)).isoformat()}, **extra}


def allday(title, first, last=None, **extra):
    last = date.fromisoformat(last or first)
    return {"summary": title, "start": {"date": first}, "end": {"date": (last + timedelta(days=1)).isoformat()}, **extra}


@pytest.fixture
def g():
    return FakeGCal()


def make(g, now="2026-10-22 08:30", tmp_path=None):
    cfg = config.Config({**config.DEFAULTS, "hermes_calendar_id": HERMES})
    state = tmp_path / "reminded.json" if tmp_path else None
    return Calendar(cfg, g, now=datetime.fromisoformat(now).replace(tzinfo=KST), state_path=state)


# ---- 쉬는 날 ----

def test_korean_holidays_and_substitutes(g):
    days = make(g).days
    assert "개천절 대체 휴일" in days.off_reasons(date(2026, 10, 5))
    assert days.off_reasons(date(2026, 10, 3)) == ["토요일", "개천절"]
    assert days.is_off(date(2026, 9, 25))  # 추석
    assert not days.is_off(date(2026, 10, 22))


def test_may_day_added_when_library_lacks_it(g):
    cal = make(g)
    assert "근로자의 날" in cal.days.off_reasons(date(2025, 5, 1))
    cal.cfg["may_day_off"] = False
    cal.days._years.clear()
    assert not cal.days.is_off(date(2025, 5, 1))


def test_google_holiday_calendar_fills_late_temporary_holiday(g):
    g.insert(HOLI, allday("임시공휴일", "2026-10-02", description="공휴일"))
    g.insert(HOLI, allday("어버이날", "2026-05-08", description="기념일\n공휴일 아님"))
    days = make(g).days
    assert days.special_off(date(2026, 10, 2)) == ["임시공휴일"]
    assert not days.is_off(date(2026, 5, 8))


def test_leave_events_count_as_off_but_half_day_timed_does_not(g):
    g.insert(PRIMARY, allday("연차", "2026-10-28", "2026-10-30"))
    g.insert(HERMES, timed("오후 연차", "2026-11-02 13:00", 240))
    days = make(g).days
    assert all(days.is_off(date(2026, 10, d)) for d in (28, 29, 30))
    assert not days.is_off(date(2026, 11, 2))


def test_business_days_skip_chuseok_and_leave(g):
    g.insert(HERMES, allday("휴가", "2026-09-28"))
    days = make(g).days
    # 9/23(수) + 1영업일: 9/24~26 추석, 9/27 일요일, 9/28 휴가 → 9/29(화)
    assert days.add_workdays(date(2026, 9, 23), 1) == date(2026, 9, 29)
    assert days.add_workdays(date(2026, 9, 29), -1) == date(2026, 9, 23)
    assert days.workdays_between(date(2026, 9, 23), date(2026, 9, 30)) == 2
    assert days.workdays_between(date(2026, 9, 30), date(2026, 9, 23)) == -2


# ---- 등록·겹침 ----

def test_add_blocks_on_conflict_until_forced(g):
    g.insert(PRIMARY, timed("팀 회의", "2026-10-23 15:00"))
    cal = make(g)
    r = cal.add("치과", "2026-10-23 15:30")
    assert r["created"] is False and r["conflicts"][0]["title"] == "팀 회의"
    assert HERMES not in g.store
    r = cal.add("치과", "2026-10-23 15:30", force=True)
    assert r["created"] and r["event"]["end"].startswith("2026-10-23T16:30")


def test_add_without_remind_has_no_alarm_anywhere(g):
    r = make(g).add("점심", "2026-10-23 12:00")
    body = g.store[HERMES][r["event"]["id"]]
    assert body["reminders"] == {"useDefault": False, "overrides": []}
    assert "extendedProperties" not in body
    assert r["event"]["remind_minutes"] == []


def test_add_with_remind_and_dday(g):
    r = make(g).add("시험", "2026-11-21", remind="1d", dday=True)
    props = g.store[HERMES][r["event"]["id"]]["extendedProperties"]["private"]
    assert props == {"hcal_remind": "1440", "hcal_has_remind": "1", "hcal_dday": "1"}


def test_all_day_end_is_inclusive_and_holiday_note(g):
    r = make(g).add("여행", "2026-10-08", end="2026-10-10")
    assert g.store[HERMES][r["event"]["id"]]["end"] == {"date": "2026-10-11"}
    assert r["event"]["end"] == "2026-10-10"
    assert "한글날" in make(g).add("산책", "2026-10-09 10:00")["notes"][0]


def test_transparent_declined_and_all_day_do_not_conflict(g):
    g.insert(PRIMARY, timed("여유", "2026-10-23 15:00", transparency="transparent"))
    g.insert(PRIMARY, timed("거절", "2026-10-23 15:00", attendees=[{"self": True, "responseStatus": "declined"}]))
    g.insert(PRIMARY, allday("엄마 생일", "2026-10-23"))
    assert make(g).add("치과", "2026-10-23 15:00")["created"]


def test_bad_inputs(g):
    cal = make(g)
    with pytest.raises(UserError):
        cal.add("x", "내일 3시")
    with pytest.raises(UserError):
        cal.add("x", "2026-10-23 15:00", end="2026-10-23 14:00")
    with pytest.raises(UserError):
        parse_offsets("곧")
    assert parse_offsets("10m,1h, 1d") == [1440, 60, 10]


# ---- 수정·삭제 ----

def test_update_moves_and_keeps_length_ignoring_self(g):
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00", minutes=90)["event"]
    r = cal.update(ev["id"], start="2026-10-23 15:30")
    assert r["updated"] and r["event"]["end"].startswith("2026-10-23T17:00")


def test_update_all_day_to_timed_uses_default_length(g):
    cal = make(g)
    ev = cal.add("은행", "2026-10-23")["event"]
    r = cal.update(ev["id"], start="2026-10-23 10:00")
    assert r["event"]["end"].startswith("2026-10-23T11:00")


def test_update_remind_on_and_off(g):
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    assert cal.update(ev["id"], remind="1h")["event"]["remind_minutes"] == [60]
    assert cal.update(ev["id"], clear_remind=True)["event"]["remind_minutes"] == []


def test_update_conflict_and_delete(g):
    g.insert(PRIMARY, timed("회의", "2026-10-23 17:00"))
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    assert cal.update(ev["id"], start="2026-10-23 17:00")["updated"] is False
    assert cal.delete(ev["id"])["deleted"]
    with pytest.raises(UserError):
        cal.delete(ev["id"])


# ---- 알림 ----

def test_remind_fires_once_at_the_right_time(g, tmp_path):
    g.insert(HERMES, timed("치과", "2026-10-22 15:00", location="강남역",
                           extendedProperties={"private": {"hcal_remind": "30", "hcal_has_remind": "1"}}))
    g.insert(HERMES, timed("알림 없는 일정", "2026-10-22 15:00"))
    assert make(g, "2026-10-22 14:29", tmp_path).remind() == ""
    assert make(g, "2026-10-22 14:31", tmp_path).remind() == "⏰ 15:00 치과 — 29분 후 · 강남역"
    assert make(g, "2026-10-22 14:36", tmp_path).remind() == ""


def test_remind_sends_one_message_when_several_were_missed(g, tmp_path):
    g.insert(HERMES, timed("면접", "2026-10-22 15:00",
                           extendedProperties={"private": {"hcal_remind": "60,10", "hcal_has_remind": "1"}}))
    msg = make(g, "2026-10-22 14:55", tmp_path).remind()
    assert msg.count("⏰") == 1 and "5분 후" in msg
    assert set(json.loads((tmp_path / "reminded.json").read_text()).values()) == {"2026-10-22T15:00:00+09:00"}


def test_remind_skips_event_that_already_started(g, tmp_path):
    g.insert(HERMES, timed("회의", "2026-10-22 15:00",
                           extendedProperties={"private": {"hcal_remind": "30", "hcal_has_remind": "1"}}))
    assert make(g, "2026-10-22 15:20", tmp_path).remind() == ""


def test_all_day_remind_day_before_at_nine(g, tmp_path):
    g.insert(HERMES, allday("엄마 생일", "2026-10-23",
                            extendedProperties={"private": {"hcal_remind": "1d", "hcal_has_remind": "1"}}))
    # 1d는 parse_offsets로 1440분, 기준 10/23 09:00 → 10/22 09:00
    assert make(g, "2026-10-22 08:55", tmp_path).remind() == ""
    assert make(g, "2026-10-22 09:02", tmp_path).remind() == "⏰ 내일 종일: 엄마 생일"


def test_cleared_remind_is_ignored(g, tmp_path):
    g.insert(HERMES, timed("치과", "2026-10-22 15:00",
                           extendedProperties={"private": {"hcal_remind": "", "hcal_has_remind": "0"}}))
    assert make(g, "2026-10-22 14:50", tmp_path).remind() == ""


# ---- 브리핑 ----

def test_brief(g):
    g.insert(PRIMARY, timed("팀 회의", "2026-10-22 10:00"))
    g.insert(HERMES, timed("1:1", "2026-10-22 10:30", extendedProperties={"private": {"hcal_remind": "10", "hcal_has_remind": "1"}}))
    g.insert(HERMES, allday("정보처리기사 시험", "2026-11-21", extendedProperties={"private": {"hcal_dday": "1"}}))
    g.insert(PRIMARY, allday("연차", "2026-10-30"))
    out = make(g).brief()
    assert out.splitlines()[0] == "📅 10월 22일 (목) 브리핑"
    assert "• 10:00–11:00 팀 회의" in out and "• 10:30–11:30 1:1 ⏰" in out
    assert "⚠️ 겹침: 10:00 팀 회의 ↔ 10:30 1:1" in out
    assert "내일(금) 일정 0개" in out
    assert "10/30(금) 연차" in out
    assert "🎯 정보처리기사 시험 D-30 (11/21)" in out


def test_brief_on_holiday(g):
    out = make(g, "2026-10-09 08:30").brief()
    assert "🏖 오늘은 쉬는 날: 한글날" in out and "오늘 등록된 일정이 없어요." in out


# ---- CLI ----

def test_cli_text_and_exit_code(g, monkeypatch, capsys):
    import hermes_calendar.cli as cli

    monkeypatch.setattr(cli.GCal, "connect", classmethod(lambda cls, home: g))
    monkeypatch.setattr(cli.config, "load", lambda: config.Config({**config.DEFAULTS, "hermes_calendar_id": HERMES}))
    g.insert(PRIMARY, timed("회의", "2026-10-23 15:00"))
    assert main(["add", "치과", "--start", "2026-10-23 15:00"]) == 2
    out = capsys.readouterr().out
    assert "⛔ 등록하지 않았어요" in out and "회의" in out
    assert main(["--json", "add", "치과", "--start", "2026-10-23 15:00", "--force", "--remind", "30"]) == 0
    assert json.loads(capsys.readouterr().out)["event"]["remind_minutes"] == [30]
    assert main(["add", "x", "--start", "언젠가"]) == 1
    assert main(["workday", "2026-09-23", "1"]) == 0
    assert "2026-09-28(월)" in capsys.readouterr().out


def test_home_follows_hermes_rules(monkeypatch, tmp_path):
    monkeypatch.delenv("HCAL_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert config.home() == tmp_path / "hermes" / "hcal"
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "custom"))
    assert config.home() == tmp_path / "custom" / "hcal"
    monkeypatch.setenv("HCAL_HOME", str(tmp_path / "x"))
    assert config.home() == tmp_path / "x"


def test_install_hermes_writes_skill_and_scripts(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HCAL_HOME", str(tmp_path / "hcal"))
    assert main(["install-hermes", "--hermes-home", str(tmp_path / "h")]) == 0
    assert (tmp_path / "h/skills/productivity/hermes-calendar/SKILL.md").read_text(encoding="utf-8").startswith("---\nname: hermes-calendar")
    script = (tmp_path / "h/scripts/hcal_remind.py").read_text(encoding="utf-8")
    assert "main(['remind'])" in script and str(tmp_path / "hcal") in script
    assert "--no-agent --script hcal_brief.py" in capsys.readouterr().out
