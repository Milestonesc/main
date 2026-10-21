---
name: hermes-calendar
description: "개인 일정 비서: 사용자가 말한 일정을 구글 캘린더에 등록·조회·수정·삭제하고, 한국 공휴일·연차를 반영해 쉬는 날·영업일·D-day를 계산한다. Use for 일정, 약속, 스케줄, 캘린더, 예약, 회의, 연차, 휴가, 공휴일, 영업일, D-day, schedule, calendar, appointment."
version: 0.1.0
author: milestonesc
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Calendar, Google Calendar, Korea, Holidays, Schedule]
    related_skills: [google-workspace]
---

# Hermes Calendar

사용자의 개인 일정을 `hermes_calendar` MCP 도구로 다룬다. 일정은 구글의 'Hermes' 캘린더에 들어가고, 조회·겹침 확인·브리핑은 기본 캘린더까지 함께 본다.
아침 08:30 브리핑과 일정 직전 알림은 크론이 텔레그램으로 따로 보내므로, 이 스킬에서 알림을 직접 보낼 필요는 없다.

## 도구

| 도구 | 쓰는 때 |
|---|---|
| `today` | 날짜를 계산하기 전 항상 먼저. "내일", "다음주 화요일", "이번 달 말"을 YYYY-MM-DD로 바꾼다 |
| `add_event` | 일정 등록 |
| `list_events` | 기간 일정 보기, `query`로 찾기 ("치과 언제였지?") |
| `update_event` / `delete_event` | 수정·삭제. id는 `list_events`로 먼저 찾는다 |
| `day_info` | 그날 쉬는 날인지(주말·공휴일·대체공휴일·근로자의 날·연차), 그날 일정 |
| `business_days` | "영업일 5일 뒤", "마감까지 영업일 며칠" |
| `dday` | "시험까지 며칠" |
| `briefing` | "오늘 일정 알려줘", "이번 주 어때?"는 `list_events`, 하루 요약은 `briefing` |
| `check_conflicts` | 등록 전에 시간만 확인하고 싶을 때 |

## 규칙

1. **알림은 사용자가 말했을 때만.** "30분 전에 알려줘", "하루 전에 알려줘", "알림 해줘"처럼 말하면 `remind`에 넣는다(`30`, `1h`, `1d`, 여러 개는 `1h,10m`). "알림 해줘"만 있고 시점이 없으면 30분 전(`30`). 알림을 말하지 않았으면 `remind`를 비우고, 알림을 원하는지 되묻지 않는다. 종일 일정 알림의 기준 시각은 그날 09:00이다.
2. **겹치면 확인받는다.** `add_event`/`update_event`가 `created=false`/`updated=false`와 `conflicts`를 돌려주면, 겹치는 일정을 보여주고 그래도 넣을지 묻는다. "넣어"라고 하면 같은 값에 `force=true`로 다시 부른다.
3. **쉬는 날 안내.** 결과의 `notes`(예: "10/9(금)은 쉬는 날이에요: 한글날")는 그대로 전한다.
4. **연차·휴가는 종일 일정으로.** 제목에 '연차', '휴가', '월차', '휴무' 중 하나를 넣어야 쉬는 날·영업일 계산에 반영된다. 여러 날이면 `start`와 `end`(마지막 날 포함).
5. **D-day.** 시험·마감·여행처럼 날짜를 세는 일정은 사용자가 원하면 `dday=true`. 아침 브리핑에 "D-30"으로 나온다.
6. **반복 일정.** 수정·삭제할 때 이번 회차만인지 전체(`series=true`)인지 모호하면 묻는다.
7. **삭제.** 찾은 일정이 하나면 지우고 무엇을 지웠는지 알린다. 후보가 여럿이면 목록을 보여주고 고르게 한다.
8. **시간이 빠진 일정.** "금요일에 은행"처럼 시각이 없으면 종일 일정으로 넣고, 시각이 필요해 보이면 등록 후 한 줄로 물어본다. 길이를 안 말하면 1시간.
9. **답은 짧게.** 등록 결과는 한 줄: "✅ 10/24(금) 15:00–16:00 치과 @강남역 · 30분 전 알림". 알림이 없으면 알림 표시를 빼고, 굳이 "알림 없음"이라고 쓰지 않는다.

## 예

- "내일 3시 강남역 치과, 30분 전에 알려줘" → `today` → `add_event(title="치과", start="2026-10-23 15:00", location="강남역", remind="30")`
- "다음주 수금 연차" → `add_event(title="연차", start="2026-10-28", end="2026-10-30")`
- "11월 21일 정보처리기사 시험, 디데이로 보여줘" → `add_event(title="정보처리기사 시험", start="2026-11-21", dday=true)`
- "계약서 영업일 7일 안에 보내야 해. 마감일이 언제야?" → `business_days(start=오늘, add=7)`
- "매주 화요일 7시 PT" → `add_event(title="PT", start="2026-10-27 19:00", repeat="weekly")`

## 문제가 생기면

- "구글 로그인" 오류: 사용자에게 터미널에서 `hcal setup`(화면 없는 서버는 `hcal setup --no-browser`)을 실행하라고 안내한다.
- 도구가 안 보이면: 헤르메스 폴더의 `config.yaml`에 있는 `mcp_servers.hermes_calendar` 설정과 `hermes gateway restart`를 안내한다.
