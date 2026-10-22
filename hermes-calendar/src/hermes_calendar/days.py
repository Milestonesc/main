"""쉬는 날 판단, 영업일, D-day.

쉬는 날 = 주말 + 법정공휴일(holidays 라이브러리: 대체·임시공휴일, 선거일 포함)
        + 구글 '대한민국의 휴일' 캘린더에만 있는 공휴일(늦게 발표된 임시공휴일 대비)
        + 근로자의 날(설정) + 제목에 연차·휴가 등이 든 종일 일정
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

import holidays

WEEKDAYS = "월화수목금토일"


def wd(d: date) -> str:
    return WEEKDAYS[d.weekday()]


def dday_label(target: date, today: date) -> str:
    diff = (target - today).days
    return "D-Day" if diff == 0 else f"D-{diff}" if diff > 0 else f"D+{-diff}"


class Days:
    def __init__(self, cfg, gcal=None):
        self.cfg, self.gcal = cfg, gcal
        self._years: dict[int, dict[date, list[str]]] = {}

    def off_reasons(self, d: date) -> list[str]:
        """쉬는 이유 목록. 비어 있으면 일하는 날."""
        weekend = ["토요일"] if d.weekday() == 5 else ["일요일"] if d.weekday() == 6 else []
        return weekend + self._year(d.year).get(d, [])

    def special_off(self, d: date) -> list[str]:
        """주말을 뺀 쉬는 이유(공휴일·연차 등)."""
        return self._year(d.year).get(d, [])

    def is_off(self, d: date) -> bool:
        return bool(self.off_reasons(d))

    def add_workdays(self, start: date, n: int) -> date:
        """start에서 영업일 n일 뒤(음수면 앞). start 자체는 세지 않는다."""
        step, d, left = (1 if n >= 0 else -1), start, abs(n)
        while left:
            d += timedelta(days=step)
            left -= not self.is_off(d)
        return d

    def workdays_between(self, a: date, b: date) -> int:
        """a 다음날부터 b까지(b 포함) 영업일 수. b가 앞이면 음수."""
        lo, hi, sign = (a, b, 1) if a <= b else (b, a, -1)
        return sign * sum(not self.is_off(lo + timedelta(days=i)) for i in range(1, (hi - lo).days + 1))

    def _year(self, y: int) -> dict[date, list[str]]:
        if y not in self._years:
            self._years[y] = self._load_year(y)
        return self._years[y]

    def _load_year(self, y: int) -> dict[date, list[str]]:
        out: dict[date, list[str]] = defaultdict(list)
        for d, name in holidays.KR(years=y, language="ko").items():
            out[d] += [n.strip() for n in name.split(";")]
        if self.cfg["may_day_off"] and not out.get(date(y, 5, 1)):
            out[date(y, 5, 1)].append("근로자의 날")
        if self.gcal:
            tz = self.cfg.tz
            start, end = datetime(y, 1, 1, tzinfo=tz), datetime(y + 1, 1, 1, tzinfo=tz)
            self._add_google_holidays(out, start, end)
            self._add_leave(out, y, start, end)
        return dict(out)

    def _add_google_holidays(self, out, start, end):
        try:
            events = self.gcal.events(self.cfg["holiday_calendar_id"], start, end)
        except Exception:  # 오프라인이거나 구독 불가: 라이브러리만으로 충분하다
            return
        for ev in events:
            first_line = (ev.get("description") or "").splitlines()[:1]
            if "date" in ev.get("start", {}) and first_line in (["공휴일"], ["Public holiday"]):
                d = date.fromisoformat(ev["start"]["date"])
                if not out.get(d):
                    out[d].append(ev.get("summary", "공휴일"))

    def _add_leave(self, out, y, start, end):
        keywords = self.cfg["leave_keywords"]
        for cal in self.cfg.calendars():
            for ev in self.gcal.events(cal, start, end):
                title = ev.get("summary", "")
                cancelled = ev.get("extendedProperties", {}).get("private", {}).get("hcal_status") == "cancelled"
                if cancelled or "date" not in ev.get("start", {}) or not any(k in title for k in keywords):
                    continue
                d, last = date.fromisoformat(ev["start"]["date"]), date.fromisoformat(ev["end"]["date"])
                while d < last:
                    if d.year == y and title not in out[d]:
                        out[d].append(title)
                    d += timedelta(days=1)
