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
    assert body["extendedProperties"]["private"] == {"hcal_status": "planned"}
    assert r["event"]["remind_minutes"] == []


def test_add_with_remind_and_dday(g):
    r = make(g).add("시험", "2026-11-21", remind="1d", dday=True)
    props = g.store[HERMES][r["event"]["id"]]["extendedProperties"]["private"]
    assert props == {"hcal_status": "planned", "hcal_remind": "1440", "hcal_has_remind": "1", "hcal_dday": "1"}


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


# ---- 설명·메모·할 일·기록 ----

from hermes_calendar.notes import Notes  # noqa: E402


def test_notes_round_trip_and_loose_parsing():
    n = Notes.parse("사랑니 상담\n\n[할 일]\n☑ 보험증\n- [ ] 예약\n[x] 서류\n그냥 줄\n\n[메모]\n10/21 사진\n\n[기록]\n10/20 09:00 등록")
    assert n.description == "사랑니 상담"
    assert [(t.text, t.done) for t in n.todos] == [("보험증", True), ("예약", False), ("서류", True), ("그냥 줄", False)]
    assert n.memos == ["10/21 사진"] and n.history == ["10/20 09:00 등록"]
    assert Notes.parse(n.render()) == n


def test_notes_from_google_web_html():
    n = Notes.parse("설명입니다<br><br>[할 일]<br>☐ 우산 &amp; 물<br>☑ 표")
    assert n.description == "설명입니다" and [t.text for t in n.todos] == ["우산 & 물", "표"]


def test_plain_description_without_sections_is_kept():
    assert Notes.parse("회사 앱에서 쓴 설명").description == "회사 앱에서 쓴 설명"


def test_add_with_description_todos_memo(g):
    ev = make(g).add("치과", "2026-10-23 15:00", description="사랑니 상담", todos=["보험증", "예약 잡기"], memo="첫 방문")["event"]
    assert ev["description"] == "사랑니 상담"
    assert ev["todos"] == [{"no": 1, "text": "보험증", "done": False}, {"no": 2, "text": "예약 잡기", "done": False}]
    assert ev["memos"] == ["10/22 첫 방문"] and ev["history"] == ["10/22 08:30 등록"]
    assert ev["status"] == "planned"


def test_edit_notes(g):
    cal = make(g)
    ev = cal.add("여행", "2026-10-30", todos=["여권", "환전", "충전기"])["event"]
    out = cal.edit_notes(ev["id"], check=["1", "환전"], remove_todos=["충전기"], add_todos=["우산"],
                         memo="숙소 체크인 3시", description="부산 1박")["event"]
    assert [(t["text"], t["done"]) for t in out["todos"]] == [("여권", True), ("환전", True), ("우산", False)]
    assert out["memos"] == ["10/22 숙소 체크인 3시"] and out["description"] == "부산 1박"
    assert cal.edit_notes(ev["id"], uncheck=["여권"])["event"]["todos"][0]["done"] is False
    with pytest.raises(UserError):
        cal.edit_notes(ev["id"], check=["없는 항목"])


# ---- 상태·기록 ----

def test_status_done_marks_title_and_logs(g):
    cal = make(g, "2026-10-23 16:40")
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    out = cal.set_status(ev["id"], "완료", note="다음 진료 11/6")["event"]
    assert out["status"] == "done" and out["title"] == "치과"
    assert g.store[HERMES][ev["id"]]["summary"] == "✅ 치과"
    assert out["history"][-1] == "10/23 16:40 완료 · 다음 진료 11/6"
    assert cal.set_status(ev["id"], "못함")["event"]["title"] == "치과"
    assert g.store[HERMES][ev["id"]]["summary"] == "❗ 치과"


def test_delayed_moves_event_and_logs_both_times(g):
    cal = make(g, "2026-10-23 14:50")
    ev = cal.add("미팅", "2026-10-23 15:00", minutes=90)["event"]
    out = cal.set_status(ev["id"], "지연", start="2026-10-23 16:00", note="상대 늦음")["event"]
    assert out["status"] == "delayed" and out["end"].startswith("2026-10-23T17:30")
    assert out["history"][-1] == "10/23 14:50 지연 10/23(금) 15:00–16:30 → 10/23(금) 16:00–17:30 · 상대 늦음"
    assert g.store[HERMES][ev["id"]]["summary"] == "⏳ 미팅"


def test_planned_change_is_logged_differently(g):
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    out = cal.update(ev["id"], start="2026-10-24 11:00")["event"]
    assert out["history"][-1] == "10/22 08:30 시간 변경 10/23(금) 15:00–16:00 → 10/24(토) 11:00–12:00"
    assert out["status"] == "planned"


def test_cancelled_frees_the_slot_and_can_be_restored(g):
    cal = make(g)
    ev = cal.add("회의", "2026-10-23 15:00")["event"]
    cal.set_status(ev["id"], "취소", note="상대 사정")
    assert g.store[HERMES][ev["id"]]["transparency"] == "transparent"
    assert cal.add("치과", "2026-10-23 15:00")["created"]
    cal.set_status(ev["id"], "예정")
    assert g.store[HERMES][ev["id"]]["transparency"] == "opaque"
    assert g.store[HERMES][ev["id"]]["summary"] == "회의"


def test_rename_keeps_status_mark(g):
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    cal.set_status(ev["id"], "진행중")
    assert cal.update(ev["id"], title="치과 진료")["event"]["title"] == "치과 진료"
    assert g.store[HERMES][ev["id"]]["summary"] == "▶️ 치과 진료"


def test_bad_status(g):
    cal = make(g)
    ev = cal.add("치과", "2026-10-23 15:00")["event"]
    with pytest.raises(UserError):
        cal.set_status(ev["id"], "보류")


def test_review_lists_only_unfinished_tracked_past_events(g):
    cal = make(g, "2026-10-20 09:00")
    done = cal.add("헬스", "2026-10-21 07:00")["event"]
    cal.add("치과", "2026-10-21 15:00")
    cal.add("엄마 생일", "2026-10-21", track=False)
    cal.add("연차", "2026-10-21")
    g.insert(PRIMARY, timed("회사 회의", "2026-10-21 10:00"))
    later = make(g, "2026-10-22 08:30")
    later.set_status(done["id"], "완료")
    assert [e.title for e in later.review()] == ["치과"]
    assert "📝 결과가 안 남은 지난 일정 1개" in later.brief()


def test_agenda_status_filter_and_counts(g):
    cal = make(g)
    a = cal.add("A", "2026-10-22 10:00")["event"]
    cal.add("B", "2026-10-22 12:00")
    cal.set_status(a["id"], "완료")
    out = cal.agenda(date(2026, 10, 22), date(2026, 10, 22))
    assert out["counts"] == {"예정": 1, "완료": 1}
    assert [e["title"] for e in cal.agenda(date(2026, 10, 22), date(2026, 10, 22), status="완료")["events"]] == ["A"]


def test_remind_skips_finished_and_lists_open_todos(g, tmp_path):
    cal = make(g, "2026-10-22 08:00", tmp_path)
    a = cal.add("치과", "2026-10-22 15:00", remind="30", todos=["보험증", "칫솔"])["event"]
    b = cal.add("회의", "2026-10-22 15:00", remind="30", force=True)["event"]
    cal.edit_notes(a["id"], check=["칫솔"])
    cal.set_status(b["id"], "취소")
    msg = make(g, "2026-10-22 14:31", tmp_path).remind()
    assert msg == "⏰ 15:00 치과 — 29분 후\n  ☐ 보험증"


def test_cancelled_leave_is_not_a_day_off(g):
    cal = make(g)
    ev = cal.add("연차", "2026-10-28")["event"]
    assert make(g).days.is_off(date(2026, 10, 28))
    cal.set_status(ev["id"], "취소")
    assert not make(g).days.is_off(date(2026, 10, 28))


def test_cli_status_note_show(g, monkeypatch, capsys):
    import hermes_calendar.cli as cli

    monkeypatch.setattr(cli.GCal, "connect", classmethod(lambda cls, home: g))
    monkeypatch.setattr(cli.config, "load", lambda: config.Config({**config.DEFAULTS, "hermes_calendar_id": HERMES}))
    assert main(["add", "치과", "--start", "2026-10-23 15:00", "--desc", "사랑니", "--todo", "보험증"]) == 0
    capsys.readouterr()
    assert main(["note", "ev1", "--check", "1", "--memo", "사진 다시"]) == 0
    assert main(["status", "ev1", "완료", "--note", "다음 11/6"]) == 0
    capsys.readouterr()
    assert main(["show", "ev1"]) == 0
    out = capsys.readouterr().out
    assert "✅ 치과" in out and "상태: 완료" in out and "1. ☑ 보험증" in out and "[기록]" in out and "완료 · 다음 11/6" in out


def test_status_change_keeps_remind_and_dday_even_if_google_replaces_the_map(g):
    cal = make(g)
    ev = cal.add("시험", "2026-11-21 09:00", remind="1d", dday=True)["event"]
    real_patch = g.patch

    def replacing_patch(cal_id, event_id, body):  # 구글이 private 묶음을 통째로 바꾸는 경우를 흉내
        g.store[cal_id][event_id].pop("extendedProperties", None)
        return real_patch(cal_id, event_id, body)

    g.patch = replacing_patch
    out = cal.set_status(ev["id"], "진행중")["event"]
    assert out["remind_minutes"] == [1440] and out["dday"] and out["status"] == "in_progress"


# ---- 설치 ----

def test_client_secret_found_in_downloads(monkeypatch, tmp_path):
    from hermes_calendar import gcal

    monkeypatch.setattr(gcal.Path, "home", classmethod(lambda cls: tmp_path))
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "client_secret_web.json").write_text('{"web": {}}')  # 웹 앱 유형은 무시
    assert gcal.find_client_secret() is None
    (dl / "client_secret_123.apps.googleusercontent.com.json").write_text('{"installed": {"client_id": "x"}}')
    home = tmp_path / "hcal"
    assert gcal.get_client_secret(home, open_browser=False) == home / "credentials.json"
    assert "installed" in (home / "credentials.json").read_text()


def test_apply_runs_hermes_commands_and_skips_existing_cron(monkeypatch, tmp_path):
    import hermes_calendar.cli as cli

    calls = []

    class R:
        def __init__(self, out="", code=0):
            self.stdout, self.stderr, self.returncode = out, "", code

    def fake_run(argv, input="", **kw):
        calls.append((argv[1:], input))
        if argv[1:3] == ["cron", "list"]:
            return R("ID  hcal-remind  every 5m")
        if argv[1:3] == ["config", "get"]:
            return R("")
        return R("✓ Saved 'hermes_calendar' (14/14 tools enabled)" if argv[1:3] == ["mcp", "add"] else "ok")

    monkeypatch.setattr(cli, "hermes_exe", lambda: "/bin/hermes")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    args = cli.build_parser().parse_args(["install-hermes", "--hermes-home", str(tmp_path / "h"), "--apply"])
    out = cli.install_hermes(args, tmp_path / "hcal")
    ran = [c[0][:2] for c in calls]
    assert ran == [["config", "get"], ["config", "set"], ["cron", "list"], ["mcp", "add"], ["cron", "create"], ["gateway", "restart"]]
    assert calls[1][0] == ["config", "set", "timezone", "Asia/Seoul"]
    mcp = calls[3]
    assert mcp[1] == "y\ny\n" and f"HCAL_HOME={tmp_path / 'hcal'}" in mcp[0] and mcp[0][-2:] == ["-m", "hermes_calendar.mcp_server"]
    assert "--interpreter" in calls[4][0] and "hcal-morning-brief" in calls[4][0]
    assert "⏭ 직전 알림 크론: 이미 있어요" in out and "✅ MCP 서버 등록" in out and "⚠️" not in out


def test_apply_reports_mcp_saved_disabled_as_failure(monkeypatch, tmp_path):
    import hermes_calendar.cli as cli

    class R:
        def __init__(self, out):
            self.stdout, self.stderr, self.returncode = out, "", 0

    def fake_run(argv, input="", **kw):
        if argv[1:3] == ["mcp", "add"]:
            return R("✗ Failed to connect: boom\n✓ Saved 'hermes_calendar' to config (disabled)")
        return R("Asia/Seoul" if argv[1:3] == ["config", "get"] else "")

    monkeypatch.setattr(cli, "hermes_exe", lambda: "/bin/hermes")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    args = cli.build_parser().parse_args(["install-hermes", "--hermes-home", str(tmp_path / "h"), "--apply"])
    out = cli.install_hermes(args, tmp_path / "hcal")
    assert "⚠️ MCP 서버 등록 실패: ✗ Failed to connect: boom" in out and "시간대" not in out


def test_apply_without_hermes(monkeypatch, tmp_path):
    import hermes_calendar.cli as cli

    monkeypatch.setattr(cli, "hermes_exe", lambda: None)
    args = cli.build_parser().parse_args(["install-hermes", "--hermes-home", str(tmp_path / "h"), "--apply"])
    assert "hermes 명령을 찾지 못했어요" in cli.install_hermes(args, tmp_path / "hcal")
