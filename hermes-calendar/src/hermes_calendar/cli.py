"""hcal 명령. 사람이 읽는 글이 기본이고, --json 을 붙이면 기계용 출력."""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from importlib import resources
from pathlib import Path

from . import config
from .core import STATUSES, Calendar, UserError
from .days import dday_label, wd
from .gcal import GCal, NotAuthorized, login


def fmt_event(d: dict) -> str:
    if d["all_day"]:
        s = date.fromisoformat(d["start"])
        when = f"{s}({wd(s)}) 종일" + (f"~{d['end']}" if d["end"] != d["start"] else "")
    else:
        s, e = datetime.fromisoformat(d["start"]), datetime.fromisoformat(d["end"])
        when = f"{s:%Y-%m-%d}({wd(s.date())}) {s:%H:%M}–{e:%H:%M}"
    mark = STATUSES[d["status"]][1]
    extra = (f" @{d['location']}" if d["location"] else "")
    if d["todos"]:
        extra += f" (할 일 {sum(t['done'] for t in d['todos'])}/{len(d['todos'])})"
    extra += f" ⏰{','.join(str(m) for m in d['remind_minutes'])}분 전" if d["remind_minutes"] else ""
    extra += " 🎯D-day" if d["dday"] else ""
    return f"{when} {mark + ' ' if mark else ''}{d['title']}{extra}  [id: {d['id']}]"


def fmt_detail(d: dict) -> str:
    lines = [fmt_event(d), f"상태: {d['status_name']}"]
    if d["description"]:
        lines += ["", d["description"]]
    if d["todos"]:
        lines += ["", "[할 일]"] + [f"{t['no']}. {'☑' if t['done'] else '☐'} {t['text']}" for t in d["todos"]]
    for title, key in (("메모", "memos"), ("기록", "history")):
        if d[key]:
            lines += ["", f"[{title}]"] + d[key]
    return "\n".join(lines)


def text(result) -> str:
    if isinstance(result, str):
        return result
    lines = []
    if set(result) == {"event"}:
        return fmt_detail(result["event"])
    if result.get("counts"):
        lines.append(" · ".join(f"{k} {v}" for k, v in result["counts"].items()))
    if "events" in result:
        off = result.get("off_days", {})
        lines += [f"🏖 {k}({wd(date.fromisoformat(k))}) {', '.join(v)}" for k, v in off.items()
                  if set(v) - {"토요일", "일요일"}]
        lines += [fmt_event(e) for e in result["events"]] or ([] if result.get("message") else ["일정이 없어요."])
    if "date" in result and "off" in result:
        lines.insert(0, f"{result['date']}({result['weekday']}) " +
                     (f"쉬는 날: {', '.join(result['reasons'])}" if result["off"] else "일하는 날"))
    for key, ok, msg in (("created", "등록했어요", "등록하지 않았어요"), ("updated", "바꿨어요", "바꾸지 않았어요"),
                         ("deleted", "지웠어요", "")):
        if key in result:
            lines.append(("✅ " + ok) if result[key] else ("⛔ " + msg + f": {result.get('reason', '')}"))
            if result.get("event"):
                lines.append("  " + fmt_event(result["event"]))
    if result.get("conflicts"):
        lines.append("⚠️ 겹치는 일정:")
        lines += ["  " + fmt_event(c) for c in result["conflicts"]]
    lines += [f"ℹ️ {n}" for n in result.get("notes", [])]
    if result.get("message"):
        lines.append(result["message"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hcal", description="헤르메스용 구글 캘린더 도구")
    p.add_argument("--json", action="store_true", help="JSON으로 출력")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="구글 로그인 + 'Hermes' 캘린더 준비")
    s.add_argument("--no-browser", action="store_true", help="화면 없는 서버용 로그인")

    def event_opts(a, new: bool):
        a.add_argument("--start", required=new, help="2026-10-22 15:00 (시각) 또는 2026-10-22 (종일)")
        a.add_argument("--end", help="끝 시각. 종일 일정이면 마지막 날짜(포함)")
        a.add_argument("--minutes", type=int, help="끝 대신 길이(분). 기본 60분")
        a.add_argument("--location")
        a.add_argument("--desc", help="일정 설명(짧은 소개). update에서는 바꿔 쓰기")
        a.add_argument("--memo", help="메모 한 줄 덧붙이기(날짜가 붙어요)")
        a.add_argument("--remind", help="알림: 30, 1h, 1h,10m, 1d. 안 주면 알림 없음")
        a.add_argument("--force", action="store_true", help="겹쳐도 진행")

    a = sub.add_parser("add", help="일정 등록")
    a.add_argument("title")
    event_opts(a, True)
    a.add_argument("--repeat", help="daily, weekdays, weekly, biweekly, monthly, yearly 또는 RRULE:...")
    a.add_argument("--until", help="반복 끝 날짜")
    a.add_argument("--count", type=int, help="반복 횟수")
    a.add_argument("--dday", action="store_true", help="브리핑에 D-day 표시")
    a.add_argument("--todo", action="append", help="할 일 (여러 번 쓸 수 있어요)")
    a.add_argument("--no-track", action="store_true", help="지난 뒤 결과를 묻지 않기 (생일·기념일 등)")

    ls = sub.add_parser("list", help="일정 보기 (기본: 오늘부터 7일)")
    ls.add_argument("--date", help="그날 하루")
    ls.add_argument("--from", dest="start")
    ls.add_argument("--to", dest="end")
    ls.add_argument("--days", type=int, default=7)
    ls.add_argument("-q", "--query", help="제목·설명 검색어")
    ls.add_argument("--status", help="그 상태만: 예정, 진행중, 지연됨, 완료, 못함, 취소")

    u = sub.add_parser("update", help="일정 수정")
    u.add_argument("id")
    u.add_argument("--calendar")
    u.add_argument("--title")
    event_opts(u, False)
    u.add_argument("--no-remind", action="store_true", help="알림 끄기")
    u.add_argument("--dday", action=argparse.BooleanOptionalAction, default=None)
    u.add_argument("--track", action=argparse.BooleanOptionalAction, default=None, help="지난 뒤 결과 묻기")
    u.add_argument("--series", action="store_true", help="반복 일정 전체에 적용")

    st = sub.add_parser("status", help="상태 바꾸기: 예정, 진행중, 지연됨, 완료, 못함, 취소")
    st.add_argument("id")
    st.add_argument("status")
    st.add_argument("--note", help="한 줄 사유·결과 (기록에 남아요)")
    st.add_argument("--start", help="지연됨: 밀린 새 시작 시각")
    st.add_argument("--end")
    st.add_argument("--calendar")
    st.add_argument("--force", action="store_true")

    n = sub.add_parser("note", help="설명·메모·할 일 고치기")
    n.add_argument("id")
    n.add_argument("--calendar")
    n.add_argument("--desc", help="설명 바꿔 쓰기")
    n.add_argument("--memo", help="메모 한 줄 덧붙이기")
    n.add_argument("--todo", action="append", help="할 일 추가")
    n.add_argument("--check", action="append", help="할 일 체크 (번호나 글자 일부)")
    n.add_argument("--uncheck", action="append", help="할 일 체크 해제")
    n.add_argument("--remove", action="append", help="할 일 지우기")

    sh = sub.add_parser("show", help="일정 자세히 (설명·할 일·메모·기록)")
    sh.add_argument("id")
    sh.add_argument("--calendar")

    sub.add_parser("review", help="결과가 안 남은 지난 일정").add_argument("--days", type=int, default=14)

    d = sub.add_parser("delete", help="일정 삭제 (기록도 사라져요. 남기려면 status 취소)")
    d.add_argument("id")
    d.add_argument("--calendar")
    d.add_argument("--series", action="store_true", help="반복 일정 전체 삭제")

    c = sub.add_parser("conflicts", help="그 시간에 겹치는 일정")
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)

    sub.add_parser("day", help="그날 쉬는 날인지 + 일정").add_argument("date", nargs="?")
    sub.add_parser("holidays", help="한 해의 쉬는 날(주말 제외)").add_argument("--year", type=int)
    w = sub.add_parser("workday", help="영업일 N일 뒤(음수면 앞) 날짜")
    w.add_argument("date")
    w.add_argument("n", type=int)
    ws = sub.add_parser("workdays", help="두 날짜 사이 영업일 수")
    ws.add_argument("start")
    ws.add_argument("end")
    sub.add_parser("dday", help="D-day 계산").add_argument("date")
    sub.add_parser("brief", help="아침 브리핑 글").add_argument("--date")
    sub.add_parser("remind", help="지금 보낼 알림(없으면 출력 없음)")

    h = sub.add_parser("install-hermes", help="헤르메스에 스킬·크론 스크립트 설치")
    h.add_argument("--hermes-home", help="기본: $HERMES_HOME, 윈도우 %%LOCALAPPDATA%%\\hermes, 그 외 ~/.hermes")
    h.add_argument("--deliver", default="telegram")
    h.add_argument("--brief-time", default="30 8 * * *", help="브리핑 크론 식 (기본 매일 08:30)")
    return p


def install_hermes(args, home: Path) -> str:
    hh = Path(args.hermes_home).expanduser() if args.hermes_home else config.hermes_home()
    skill_dir = hh / "skills" / "productivity" / "hermes-calendar"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        resources.files("hermes_calendar").joinpath("skill/SKILL.md").read_text(encoding="utf-8"), encoding="utf-8")
    scripts = hh / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name, cmd in (("hcal_brief.py", "brief"), ("hcal_remind.py", "remind")):
        (scripts / name).write_text(
            "import os, sys\n"
            f"os.environ.setdefault('HCAL_HOME', {str(home)!r})\n"
            "from hermes_calendar.cli import main\n"
            f"sys.exit(main([{cmd!r}]))\n", encoding="utf-8")
    py = sys.executable
    return f"""✅ 스킬: {skill_dir / 'SKILL.md'}
✅ 크론 스크립트: {scripts / 'hcal_brief.py'}, {scripts / 'hcal_remind.py'}

1) {hh / 'config.yaml'} 에 아래를 추가하세요 (이미 mcp_servers: 가 있으면 그 아래에 hermes_calendar 부분만):

mcp_servers:
  hermes_calendar:
    command: '{py}'
    args: ['-m', 'hermes_calendar.mcp_server']
    env:
      HCAL_HOME: '{home}'

2) 크론 두 개를 등록하세요 (LLM을 쓰지 않아 비용 없음):

hermes cron create "{args.brief_time}" --no-agent --script hcal_brief.py --interpreter "{py}" --deliver {args.deliver} --name hcal-morning-brief
hermes cron create "every 5m" --no-agent --script hcal_remind.py --interpreter "{py}" --deliver {args.deliver} --name hcal-remind

3) 헤르메스를 다시 시작하세요: hermes gateway restart
4) 확인: hermes cron run <브리핑 job id>"""


def run(args) -> object:
    home = config.home()
    cfg = config.load()
    if args.cmd == "install-hermes":
        return install_hermes(args, home)
    if args.cmd == "setup":
        login(home, args.no_browser)
        g = GCal.connect(home)
        cfg["hermes_calendar_id"] = g.ensure_calendar(cfg["hermes_calendar_name"], cfg["timezone"])
        config.save(cfg)
        return {"message": f"✅ 로그인 완료. '{cfg['hermes_calendar_name']}' 캘린더 준비됨.\n다음: hcal install-hermes"}

    cal = Calendar(cfg, GCal.connect(home), state_path=home / "reminded.json")
    today = cal.today()
    as_date = lambda s: date.fromisoformat(s) if s else today  # noqa: E731

    match args.cmd:
        case "add":
            return cal.add(args.title, args.start, end=args.end, minutes=args.minutes, location=args.location or "",
                           description=args.desc or "", memo=args.memo or "", todos=args.todo, remind=args.remind,
                           repeat=args.repeat, until=args.until, count=args.count, dday=args.dday,
                           track=not args.no_track, force=args.force)
        case "list":
            if args.date:
                start = end = as_date(args.date)
            else:
                start = as_date(args.start)
                end = date.fromisoformat(args.end) if args.end else start + timedelta(days=args.days - 1)
            return cal.agenda(start, end, args.query, args.status)
        case "update":
            return cal.update(args.id, args.calendar, title=args.title, start=args.start, end=args.end,
                              minutes=args.minutes, location=args.location, description=args.desc, memo=args.memo,
                              remind=args.remind, clear_remind=args.no_remind, dday=args.dday, track=args.track,
                              series=args.series, force=args.force)
        case "status":
            return cal.set_status(args.id, args.status, note=args.note, start=args.start, end=args.end,
                                  calendar_id=args.calendar, force=args.force)
        case "note":
            return cal.edit_notes(args.id, args.calendar, description=args.desc, memo=args.memo, add_todos=args.todo,
                                  check=args.check, uncheck=args.uncheck, remove_todos=args.remove)
        case "show":
            return cal.get(args.id, args.calendar)
        case "review":
            found = cal.review(args.days)
            return {"events": [e.to_dict() for e in found], "message": "" if found else "정리할 지난 일정이 없어요."}
        case "delete":
            return cal.delete(args.id, args.calendar, args.series)
        case "conflicts":
            s, e = cal._times(args.start, args.end, None)[2:]
            found = [c.to_dict() for c in cal.conflicts(s, e)] if isinstance(s, datetime) else []
            return {"conflicts": found, "message": "" if found else "겹치는 일정이 없어요."}
        case "day":
            return cal.day_info(as_date(args.date))
        case "holidays":
            y = args.year or today.year
            days = [date(y, 1, 1) + timedelta(days=i) for i in range((date(y + 1, 1, 1) - date(y, 1, 1)).days)]
            off = {d: r for d in days if (r := cal.days.special_off(d))}
            return {"holidays": {d.isoformat(): r for d, r in off.items()},
                    "message": "\n".join(f"{d}({wd(d)}) {', '.join(r)}" for d, r in off.items())}
        case "workday":
            d = cal.days.add_workdays(as_date(args.date), args.n)
            return {"date": d.isoformat(), "message": f"{args.date}에서 영업일 {args.n}일 → {d}({wd(d)})"}
        case "workdays":
            n = cal.days.workdays_between(as_date(args.start), as_date(args.end))
            return {"workdays": n, "message": f"{args.start} 다음날부터 {args.end}까지 영업일 {n}일"}
        case "dday":
            label = dday_label(as_date(args.date), today)
            return {"label": label, "message": f"{args.date}: {label}"}
        case "brief":
            return cal.brief(as_date(args.date))
        case "remind":
            return cal.remind()


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # 윈도우에서 한글·이모지가 깨지지 않게
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (UserError, NotAuthorized) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False) if args.json else f"⛔ {e}", file=sys.stdout if args.json else sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result if not isinstance(result, str) else {"text": result}, ensure_ascii=False, indent=2))
    elif out := text(result):
        print(out)
    return 2 if isinstance(result, dict) and (result.get("created") is False or result.get("updated") is False) else 0


if __name__ == "__main__":
    sys.exit(main())
