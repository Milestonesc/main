# Hermes Calendar

헤르메스 에이전트에게 말로 전한 개인 일정을 구글 캘린더에 넣고, 한국 공휴일·연차를 반영해서 알려주는 도구입니다.

- **일정 등록·조회·수정·삭제**: 헤르메스 전용 'Hermes' 캘린더에 넣고, 조회와 겹침 확인은 기본 캘린더까지 함께 봅니다.
- **쉬는 날 계산**: 주말, 법정공휴일(설·추석, 대체공휴일, 선거일, 임시공휴일), 근로자의 날, 내 연차·휴가 일정.
- **겹침 경고**: 새 일정이 기존 일정과 겹치면 바로 넣지 않고 먼저 물어봅니다.
- **영업일·D-day**: "영업일 7일 뒤가 언제야?", "시험까지 며칠?"
- **아침 브리핑**: 매일 08:30 텔레그램으로.
- **직전 알림**: 등록할 때 "30분 전에 알려줘"라고 한 일정만 텔레그램으로. 말하지 않은 일정은 알림이 없습니다.

브리핑과 알림은 헤르메스의 스크립트 크론으로 돌아서 LLM 토큰을 쓰지 않습니다.

```
📅 9월 22일 (화) 브리핑

• 10:00–11:00 팀 주간회의
• 10:30–11:30 치과 @강남역 ⏰
• 19:00–20:00 PT
⚠️ 겹침: 10:00 팀 주간회의 ↔ 10:30 치과

내일(수) 일정 1개, 첫 일정 12:00–13:00 엄마랑 점심
🗓 다가오는 쉬는 날: 9/24(목) 추석 전날, 9/25(금) 추석, 9/26(토) 추석 다음날, 9/28(월) 연차, 10/3(토) 개천절, 10/5(월) 개천절 대체 휴일
🎯 정보처리기사 시험 D-60 (11/21)
```

## 설치

헤르메스가 돌아가는 컴퓨터에서 진행합니다. Python 3.11 이상이 필요합니다.

### 1. 내려받고 설치

**윈도우 (PowerShell)**

```powershell
git clone https://github.com/milestonesc/main.git
cd main\hermes-calendar
python -m venv .venv
.venv\Scripts\pip install .
```

**리눅스·맥**

```bash
git clone https://github.com/milestonesc/main.git
cd main/hermes-calendar
python3 -m venv .venv
.venv/bin/pip install .
```

이후 `hcal` 명령은 가상환경 안에 있습니다. 윈도우는 `.venv\Scripts\hcal`, 리눅스·맥은 `.venv/bin/hcal`로 실행하거나, 가상환경을 켠 뒤(`.venv\Scripts\activate` 또는 `source .venv/bin/activate`) `hcal`로 실행하세요.

### 2. 구글 클라우드 준비 (처음 한 번, 10분)

> 헤르메스의 기본 google-workspace 스킬을 이미 설정했다면, 그때 받은 `google_client_secret.json`을 아래 위치에 `credentials.json`이라는 이름으로 복사하고 3단계로 넘어가세요.

1. [console.cloud.google.com](https://console.cloud.google.com)에서 새 프로젝트를 만듭니다 (이름 예: hermes-calendar).
2. **API 및 서비스 → 라이브러리**에서 **Google Calendar API**를 찾아 **사용**을 누릅니다.
3. **Google 인증 플랫폼(OAuth 동의 화면)**에서 시작하기: 앱 이름과 내 이메일을 넣고, 대상은 **외부**로 고릅니다.
4. **대상(Audience)**에서 게시 상태를 **프로덕션(앱 게시)**으로 바꿉니다. *테스트* 상태로 두면 7일마다 로그인이 풀립니다.
5. **클라이언트 → 클라이언트 만들기**에서 유형 **데스크톱 앱**을 고르고 JSON을 내려받습니다.
6. 내려받은 파일을 `credentials.json`이라는 이름으로 아래 폴더에 둡니다 (폴더가 없으면 만드세요).
   - 윈도우: `%LOCALAPPDATA%\hermes\hcal\credentials.json`
   - 리눅스·맥: `~/.hermes/hcal/credentials.json`

### 3. 구글 로그인

```bash
hcal setup
```

브라우저가 열리면 로그인합니다. "Google에서 확인하지 않은 앱" 화면이 나오면 **고급 → (프로젝트 이름)(으)로 이동**을 누르세요. 내가 만든 앱이라 괜찮습니다. 끝나면 구글 캘린더에 'Hermes' 캘린더가 생깁니다.

화면 없는 서버라면 `hcal setup --no-browser`: 출력된 링크를 휴대폰이나 다른 PC에서 열고 로그인한 뒤, 열리지 않는 `http://localhost:1/?...` 페이지의 주소를 통째로 복사해 붙여넣으면 됩니다.

### 4. 헤르메스에 연결

```bash
hcal install-hermes
```

스킬과 크론 스크립트를 헤르메스 폴더에 넣고, 남은 할 일 세 가지를 출력합니다. 출력된 내용을 그대로 따라 하면 됩니다.

1. 헤르메스 `config.yaml`에 `mcp_servers.hermes_calendar` 블록 붙여넣기
2. `hermes cron create ...` 두 줄 실행 (08:30 브리핑, 5분마다 알림 확인)
3. `hermes gateway restart`

브리핑 시간을 바꾸려면 `hcal install-hermes --brief-time "0 7 * * *"`처럼 크론 식을 주세요.

### 5. 확인

텔레그램에서 헤르메스에게 "오늘 일정 알려줘"라고 보내 보세요. 브리핑은 `hermes cron list`에서 job id를 확인한 뒤 `hermes cron run <id>`로 바로 받아볼 수 있습니다.

## 이렇게 말하면 됩니다

| 말 | 헤르메스가 하는 일 |
|---|---|
| 내일 3시 강남역 치과, 30분 전에 알려줘 | 15:00–16:00 등록 + 14:30 텔레그램 알림 |
| 금요일 7시 저녁 약속 | 등록만 (알림 없음) |
| 다음주 수~금 연차 | 종일 일정 3일, 쉬는 날·영업일 계산에 반영 |
| 매주 화요일 7시 PT | 반복 일정 |
| 11월 21일 정보처리기사 시험, 디데이로 보여줘 | 아침 브리핑에 `D-30` 표시 |
| 엄마 생일 10월 23일, 하루 전에 알려줘 | 종일 일정, 전날 09:00 알림 |
| 치과 1시간 뒤로 미뤄줘 | 길이는 유지하고 시간만 이동 |
| 치과 알림 꺼줘 / PT에 10분 전 알림 추가해줘 | 알림만 변경 |
| 계약서 영업일 7일 안에 보내야 해, 마감 언제야? | 주말·공휴일·연차를 뺀 날짜 |
| 10월 9일 쉬는 날이야? | 한글날 |
| 다음주에 뭐 있어? / 치과 언제였지? | 기간 조회 / 검색 |

새 일정이 기존 일정과 겹치면 헤르메스가 겹치는 일정을 보여주고 그래도 넣을지 묻습니다.

## 설정 바꾸기

`hcal` 폴더(`credentials.json`이 있는 곳)의 `config.json`을 고칩니다. 없는 항목은 기본값을 씁니다.

```json
{
  "read_calendars": ["primary", "회사캘린더ID@group.calendar.google.com"],
  "may_day_off": true,
  "leave_keywords": ["연차", "휴가", "월차", "휴무"],
  "default_duration_minutes": 60
}
```

| 항목 | 뜻 |
|---|---|
| `read_calendars` | 브리핑·겹침 확인 때 함께 읽을 캘린더. 캘린더 ID는 구글 캘린더 설정 → 캘린더 통합에 있습니다 |
| `may_day_off` | 근로자의 날(5/1)을 쉬는 날로 계산 (2026년부터는 법정공휴일 '노동절'이라 항상 쉬는 날) |
| `leave_keywords` | 이 단어가 제목에 든 **종일** 일정을 쉬는 날로 계산. 반차처럼 시간이 있는 일정은 세지 않습니다 |
| `default_duration_minutes` | 길이를 말하지 않았을 때 일정 길이 |

## 미니PC 등 다른 컴퓨터로 옮길 때

1. 새 컴퓨터에 헤르메스와 이 도구를 설치합니다 (설치 1단계).
2. 예전 컴퓨터의 `hcal` 폴더를 통째로 복사합니다 (`credentials.json`, `token.json`, `config.json`). 리눅스라면 `~/.hermes/hcal/`에 둡니다.
3. `hcal install-hermes`를 다시 실행하고 출력대로 따라 합니다. 구글 로그인을 다시 할 필요는 없습니다.

## 명령어

헤르메스 없이 터미널에서도 쓸 수 있습니다. 모든 명령에 `--json`을 붙이면 기계용 출력이 나옵니다.

```bash
hcal add "치과" --start "2026-10-23 15:00" --location 강남역 --remind 30
hcal add "연차" --start 2026-10-28 --end 2026-10-30
hcal add "PT" --start "2026-10-27 19:00" --repeat weekly
hcal list                      # 오늘부터 7일
hcal list --date 2026-10-23
hcal list -q 치과 --days 90
hcal update <id> --start "2026-10-23 16:00"
hcal update <id> --remind 1h,10m   # 알림 추가·변경
hcal update <id> --no-remind
hcal delete <id>               # 반복 일정 전체는 --series
hcal day 2026-10-09            # 쉬는 날인지
hcal holidays --year 2027
hcal workday 2026-09-23 5      # 영업일 5일 뒤
hcal workdays 2026-10-01 2026-10-31
hcal dday 2026-12-25
hcal brief
```

알림 시점은 `30`(분), `30m`, `1h`, `1d`처럼 쓰고, 여러 개는 쉼표로 묶습니다(최대 30일 전). 종일 일정의 알림은 그날 09:00을 기준으로 계산합니다.

## 알아둘 점

- **알림은 헤르메스가 켜져 있을 때만 옵니다.** 노트북이 꺼져 있거나 잠들어 있으면 알림이 오지 않고, 깨어난 뒤 아직 시작 전인 일정은 그때 한 번 보냅니다. 늘 켜두는 미니PC가 있으면 더 안정적입니다.
- 이 도구로 넣은 일정은 구글 캘린더 앱 자체 알림을 꺼서 넣습니다. 텔레그램과 폰 알림이 두 번 울리지 않게 하려는 것입니다.
- 공휴일은 [holidays](https://pypi.org/project/holidays/) 라이브러리 기준입니다. 갑자기 정해진 임시공휴일은 구글 '대한민국의 휴일' 캘린더에서 보충하고, 라이브러리를 업데이트(`pip install -U holidays`)하면 반영됩니다.
- 반복 일정은 첫 회차만 겹침을 확인합니다.

## 개발

```bash
pip install -e ".[test]"
pytest
```
