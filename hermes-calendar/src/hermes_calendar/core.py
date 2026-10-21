"""일정 등록·조회·수정·삭제, 겹침 확인, 아침 브리핑, 직전 알림."""

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from .days import Days, dday_label, wd

REMIND = "hcal_remind"  # "60,10" (분 단위)
HAS_REMIND = "hcal_has_remind"  # "1"이면 알림 대상. 알림 크론이 이 값으로 걸러 읽는다
DDAY = "hcal_dday"  # "1"이면 브리핑에 D-day 표시
ALL_DAY_ANCHOR = time(9, 0)  # 종일 일정 알림의 기준 시각
REMIND_LOOKAHEAD = timedelta(days=32)  # 최대 30일 전 알림까지
REPEAT = {
    "daily": "RRULE:FREQ=DAILY",
    "weekdays": "RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "weekly": "RRULE:FREQ=WEEKLY",
    "biweekly": "RRULE:FREQ=WEEKLY;INTERVAL=2",
    "monthly": "RRULE:FREQ=MONTHLY",
    "yearly": "RRULE:FREQ=YEARLY",
}


class UserError(ValueError):
    pass


def parse_when(s: str, tz) -> date | datetime:
    """'2026-10-22' → 종일, '2026-10-22 15:00' → 그 시각(설정 시간대)."""
    s = s.strip()
    try:
        if len(s) == 10:
            return date.fromisoformat(s)
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise UserError(f"날짜 형식을 모르겠어요: {s!r} (예: 2026-10-22 또는 2026-10-22 15:00)") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def parse_offsets(value) -> list[int]:
    """'1h,10m' / '1d' / '30' / [60, 10] → 분 목록(큰 것부터)."""
    parts = value if isinstance(value, list) else str(value).replace(" ", "").split(",")
    unit = {"m": 1, "h": 60, "d": 1440, "": 1}
    out = set()
    for p in parts:
        m = re.fullmatch(r"(\d+)([mhd]?)", str(p).lower())
        if not m:
            raise UserError(f"알림 시간을 모르겠어요: {p!r} (예: 30, 30m, 1h, 1d)")
        out.add(int(m[1]) * unit[m[2]])
    if max(out) > 30 * 1440:
        raise UserError("알림은 최대 30일 전까지만 돼요.")
    return sorted(out, reverse=True)


def fmt_minutes(m: int) -> str:
    d, rest = divmod(m, 1440)
    h, mm = divmod(rest, 60)
    return " ".join(f"{n}{u}" for n, u in ((d, "일"), (h, "시간"), (mm, "분")) if n) or "0분"


def rrule(repeat: str, until: str | None = None, count: int | None = None) -> str:
    rule = REPEAT.get(repeat) or (repeat if repeat.startswith("RRULE:") else None)
    if not rule:
        raise UserError(f"반복 방식을 모르겠어요: {repeat!r} ({', '.join(REPEAT)} 또는 RRULE:...)")
    if until:
        rule += ";UNTIL=" + date.fromisoformat(until).strftime("%Y%m%dT235959Z")
    if count:
        rule += f";COUNT={count}"
    return rule


@dataclass
class Event:
    id: str
    calendar_id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str = ""
    memo: str = ""
    remind_minutes: list[int] = field(default_factory=list)
    dday: bool = False
    recurring_id: str | None = None
    busy: bool = True

    @classmethod
    def from_api(cls, ev: dict, calendar_id: str, tz) -> "Event":
        s, e = ev["start"], ev["end"]
        if "date" in s:
            start = datetime.combine(date.fromisoformat(s["date"]), time(), tz)
            end = datetime.combine(date.fromisoformat(e["date"]), time(), tz)
        else:
            start = datetime.fromisoformat(s["dateTime"]).astimezone(tz)
            end = datetime.fromisoformat(e["dateTime"]).astimezone(tz)
        props = ev.get("extendedProperties", {}).get("private", {})
        declined = any(a.get("self") and a.get("responseStatus") == "declined" for a in ev.get("attendees", []))
        return cls(
            id=ev["id"], calendar_id=calendar_id, title=ev.get("summary", "(제목 없음)"),
            start=start, end=end, all_day="date" in s,
            location=ev.get("location", ""), memo=ev.get("description", ""),
            remind_minutes=parse_offsets(props[REMIND]) if props.get(HAS_REMIND) == "1" and props.get(REMIND) else [],
            dday=props.get(DDAY) == "1", recurring_id=ev.get("recurringEventId"),
            busy=ev.get("transparency") != "transparent" and not declined,
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = self.start.isoformat(), self.end.isoformat()
        if self.all_day:  # 종일 일정은 날짜만, 끝 날짜는 마지막 날(포함)
            d["start"], d["end"] = self.start.date().isoformat(), (self.end.date() - timedelta(days=1)).isoformat()
        return d

    def line(self, with_date: bool = False) -> str:
        if self.all_day:
            last = self.end.date() - timedelta(days=1)
            when = "종일" if last == self.start.date() else f"종일(~{last.month}/{last.day})"
        else:
            end = f"{self.end:%H:%M}" if self.end.date() == self.start.date() else f"{self.end:%m/%d %H:%M}"
            when = f"{self.start:%H:%M}–{end}"
        if with_date:
            when = f"{self.start.month}/{self.start.day}({wd(self.start.date())}) {when}"
        extra = (f" @{self.location}" if self.location else "") + (" ⏰" if self.remind_minutes else "")
        return f"{when} {self.title}{extra}"


def overlapping(events: list[Event]) -> list[tuple[Event, Event]]:
    timed = [e for e in events if not e.all_day and e.busy]
    return [(a, b) for i, a in enumerate(timed) for b in timed[i + 1:] if a.start < b.end and b.start < a.end]


class Calendar:
    def __init__(self, cfg, gcal, now: datetime | None = None, state_path: Path | None = None):
        self.cfg, self.g, self.tz = cfg, gcal, cfg.tz
        self.days = Days(cfg, gcal)
        self._now, self.state_path = now, state_path

    def now(self) -> datetime:
        return self._now or datetime.now(self.tz)

    def today(self) -> date:
        return self.now().date()

    def _at(self, d: date) -> datetime:
        return datetime.combine(d, time(), self.tz)

    # ---- 조회 ----
    def events(self, start: datetime, end: datetime, query: str | None = None, private: str | None = None) -> list[Event]:
        seen, out = set(), []
        for cal in self.cfg.calendars():
            for ev in self.g.events(cal, start, end, query=query, private=private):
                if ev.get("status") != "cancelled" and ev["id"] not in seen:
                    seen.add(ev["id"])
                    out.append(Event.from_api(ev, cal, self.tz))
        return sorted(out, key=lambda e: (e.start, not e.all_day))

    def day_events(self, d: date) -> list[Event]:
        return self.events(self._at(d), self._at(d + timedelta(days=1)))

    def agenda(self, start: date, end: date, query: str | None = None) -> dict:
        """start부터 end까지(end 포함)."""
        evs = self.events(self._at(start), self._at(end + timedelta(days=1)), query=query)
        off = {}
        for i in range((end - start).days + 1):
            d = start + timedelta(days=i)
            if r := self.days.off_reasons(d):
                off[d.isoformat()] = r
        return {"events": [e.to_dict() for e in evs], "off_days": off}

    def day_info(self, d: date) -> dict:
        reasons = self.days.off_reasons(d)
        return {"date": d.isoformat(), "weekday": wd(d), "off": bool(reasons), "reasons": reasons,
                "events": [e.to_dict() for e in self.day_events(d)]}

    def conflicts(self, start: datetime, end: datetime, exclude: str | None = None) -> list[Event]:
        return [e for e in self.events(start, end)
                if not e.all_day and e.busy and (exclude is None or exclude not in (e.id, e.recurring_id))
                and e.start < end and e.end > start]

    def _off_note(self, d: date) -> list[str]:
        r = self.days.special_off(d)
        return [f"{d.month}/{d.day}({wd(d)})은 쉬는 날이에요: {', '.join(r)}"] if r else []

    # ---- 등록·수정·삭제 ----
    def _times(self, start, end, minutes, keep: timedelta | None = None) -> tuple[dict, dict, date | datetime, date | datetime]:
        """입력 → (start body, end body, start, end). 종일 일정의 end는 마지막 날(포함)."""
        s = parse_when(start, self.tz) if isinstance(start, str) else start
        if isinstance(s, datetime):
            if end:
                e = parse_when(end, self.tz)
                if not isinstance(e, datetime):
                    raise UserError("시작이 시각이면 끝도 시각으로 주세요.")
            else:
                e = s + (timedelta(minutes=minutes) if minutes else keep or timedelta(minutes=self.cfg["default_duration_minutes"]))
            if e <= s:
                raise UserError("끝 시각이 시작보다 빨라요.")
            tzname = self.cfg["timezone"]
            return {"dateTime": s.isoformat(), "timeZone": tzname}, {"dateTime": e.isoformat(), "timeZone": tzname}, s, e
        e = parse_when(end, self.tz) if end else s + (keep or timedelta(days=1)) - timedelta(days=1)
        if isinstance(e, datetime) or e < s:
            raise UserError("종일 일정의 끝은 시작 이후 날짜로 주세요.")
        return {"date": s.isoformat()}, {"date": (e + timedelta(days=1)).isoformat()}, s, e

    @staticmethod
    def _props(remind, clear_remind: bool, dday: bool | None) -> dict:
        p = {}
        if remind:
            p.update({REMIND: ",".join(map(str, parse_offsets(remind))), HAS_REMIND: "1"})
        elif clear_remind:
            p.update({REMIND: "", HAS_REMIND: "0"})
        if dday is not None:
            p[DDAY] = "1" if dday else "0"
        return p

    def add(self, title: str, start: str, end: str | None = None, minutes: int | None = None,
            location: str = "", memo: str = "", remind=None, repeat: str | None = None,
            until: str | None = None, count: int | None = None, dday: bool = False, force: bool = False) -> dict:
        sb, eb, s, e = self._times(start, end, minutes)
        # 알림은 텔레그램으로만: 구글 앱 자체 팝업은 끈다
        body = {"summary": title, "start": sb, "end": eb, "reminders": {"useDefault": False, "overrides": []}}
        if location:
            body["location"] = location
        if memo:
            body["description"] = memo
        if props := self._props(remind, False, dday or None):
            body["extendedProperties"] = {"private": props}
        if repeat:
            body["recurrence"] = [rrule(repeat, until, count)]
        clash = self.conflicts(s, e) if isinstance(s, datetime) else []
        notes = self._off_note(s if isinstance(s, date) and not isinstance(s, datetime) else s.date())
        result = {"conflicts": [c.to_dict() for c in clash], "notes": notes}
        if clash and not force:
            return {"created": False, "reason": "겹치는 일정이 있어요. 그래도 넣으려면 force", **result}
        cal = self.cfg.write_calendar()
        return {"created": True, "event": Event.from_api(self.g.insert(cal, body), cal, self.tz).to_dict(), **result}

    def _find(self, event_id: str, calendar_id: str | None) -> tuple[str, dict]:
        for cal in [calendar_id] if calendar_id else self.cfg.calendars():
            ev = self.g.get(cal, event_id)
            if ev and ev.get("status") != "cancelled":
                return cal, ev
        raise UserError(f"일정을 찾을 수 없어요: {event_id}")

    def update(self, event_id: str, calendar_id: str | None = None, title: str | None = None,
               start: str | None = None, end: str | None = None, minutes: int | None = None,
               location: str | None = None, memo: str | None = None, remind=None, clear_remind: bool = False,
               dday: bool | None = None, series: bool = False, force: bool = False) -> dict:
        cal, ev = self._find(event_id, calendar_id)
        if series and ev.get("recurringEventId"):
            ev = self.g.get(cal, ev["recurringEventId"])
        cur = Event.from_api(ev, cal, self.tz)
        body, clash = {}, []
        for key, val in (("summary", title), ("location", location), ("description", memo)):
            if val is not None:
                body[key] = val
        if start or end or minutes:
            s = parse_when(start, self.tz) if start else (cur.start.date() if cur.all_day else cur.start)
            same_kind = isinstance(s, datetime) != cur.all_day  # 종일↔시간 일정으로 바뀌면 길이를 이어받지 않는다
            sb, eb, s, e = self._times(s, end, minutes, keep=cur.end - cur.start if same_kind and not end else None)
            body["start"], body["end"] = sb, eb
            if isinstance(s, datetime):
                clash = self.conflicts(s, e, exclude=cur.recurring_id if series and cur.recurring_id else cur.id)
                clash = [c for c in clash if c.id != cur.id]
        if props := self._props(remind, clear_remind, dday):
            body["extendedProperties"] = {"private": props}
        if not body:
            raise UserError("바꿀 내용이 없어요.")
        result = {"conflicts": [c.to_dict() for c in clash]}
        if clash and not force:
            return {"updated": False, "reason": "겹치는 일정이 있어요. 그래도 바꾸려면 force", **result}
        return {"updated": True, "event": Event.from_api(self.g.patch(cal, ev["id"], body), cal, self.tz).to_dict(), **result}

    def delete(self, event_id: str, calendar_id: str | None = None, series: bool = False) -> dict:
        cal, ev = self._find(event_id, calendar_id)
        target = ev["recurringEventId"] if series and ev.get("recurringEventId") else ev["id"]
        self.g.delete(cal, target)
        return {"deleted": True, "event": Event.from_api(ev, cal, self.tz).to_dict(), "whole_series": target != ev["id"]}

    # ---- 브리핑·알림 ----
    def dday_events(self, today: date) -> list[tuple[Event, str]]:
        evs = self.events(self._at(today), self._at(today + timedelta(days=366)), private=f"{DDAY}=1")
        seen, out = set(), []
        for e in evs:  # 반복 일정은 가장 가까운 회차만
            if (key := e.recurring_id or e.id) not in seen:
                seen.add(key)
                out.append((e, dday_label(e.start.date(), today)))
        return out

    def brief(self, d: date | None = None) -> str:
        d = d or self.today()
        lines = [f"📅 {d.month}월 {d.day}일 ({wd(d)}) 브리핑"]
        if off := self.days.special_off(d):
            lines.append(f"🏖 오늘은 쉬는 날: {', '.join(off)}")
        evs = self.day_events(d)
        lines.append("")
        lines += [f"• {e.line()}" for e in evs] if evs else ["오늘 등록된 일정이 없어요."]
        for a, b in overlapping(evs):
            lines.append(f"⚠️ 겹침: {a.start:%H:%M} {a.title} ↔ {b.start:%H:%M} {b.title}")
        tmr = d + timedelta(days=1)
        t_evs = self.day_events(tmr)
        t_line = f"내일({wd(tmr)}) 일정 {len(t_evs)}개" + (f", 첫 일정 {t_evs[0].line()}" if t_evs else "")
        if t_off := self.days.special_off(tmr):
            t_line += f" · 쉬는 날: {', '.join(t_off)}"
        lines += ["", t_line]
        upcoming = [(x, r) for i in range(2, 15) if (r := self.days.special_off(x := d + timedelta(days=i)))]
        if upcoming:
            lines.append("🗓 다가오는 쉬는 날: " + ", ".join(f"{x.month}/{x.day}({wd(x)}) {'·'.join(r)}" for x, r in upcoming))
        if dd := self.dday_events(d):
            lines.append("🎯 " + ", ".join(f"{e.title} {label} ({e.start.month}/{e.start.day})" for e, label in dd))
        return "\n".join(lines)

    def remind(self) -> str:
        """지금 보내야 할 알림 문구. 없으면 빈 문자열(헤르메스 크론이 조용히 넘어감)."""
        now = self.now()
        state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path and self.state_path.exists() else {}
        msgs = []
        for e in self.events(now - timedelta(days=1), now + REMIND_LOOKAHEAD, private=f"{HAS_REMIND}=1"):
            anchor = datetime.combine(e.start.date(), ALL_DAY_ANCHOR, self.tz) if e.all_day else e.start
            due = []
            for off in e.remind_minutes:
                trig = anchor - timedelta(minutes=off)
                key = f"{e.calendar_id}|{e.id}|{anchor.isoformat()}|{off}"
                if key not in state and trig <= now < max(anchor, trig + timedelta(minutes=10)):
                    state[key] = anchor.isoformat()
                    due.append(off)
            if due:  # 노트북이 잠들었다 깨서 여러 개가 밀려도 한 번만 보낸다
                msgs.append(self._remind_text(e, anchor, now))
        cutoff = now - timedelta(days=2)
        state = {k: v for k, v in state.items() if datetime.fromisoformat(v) > cutoff}
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return "\n".join(msgs)

    def _remind_text(self, e: Event, anchor: datetime, now: datetime) -> str:
        where = f" · {e.location}" if e.location else ""
        if e.all_day:
            days = (e.start.date() - now.date()).days
            when = "오늘" if days <= 0 else "내일" if days == 1 else f"{days}일 후 {e.start.month}/{e.start.day}({wd(e.start.date())})"
            return f"⏰ {when} 종일: {e.title}{where}"
        left = math.ceil((anchor - now).total_seconds() / 60)
        day = "" if e.start.date() == now.date() else f"{e.start.month}/{e.start.day}({wd(e.start.date())}) "
        return f"⏰ {day}{e.start:%H:%M} {e.title} — " + (f"{fmt_minutes(left)} 후{where}" if left > 0 else f"지금 시작해요{where}")
