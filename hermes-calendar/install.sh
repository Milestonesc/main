#!/usr/bin/env bash
# 헤르메스 캘린더 설치 (리눅스·맥): bash install.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
hcal_home="${HCAL_HOME:-${HERMES_HOME:-$HOME/.hermes}/hcal}"
step() { printf '\n▶ %s\n' "$1"; }
fail() { printf '\n⛔ %s\n' "$1" >&2; exit 1; }

step "1/4 파이썬 확인"
py="$(command -v python3 || true)"
[ -n "$py" ] && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
  || fail "파이썬 3.11 이상이 필요해요. (우분투: sudo apt install python3 python3-venv)"
"$py" --version

step "2/4 프로그램 설치 ($hcal_home)"
mkdir -p "$hcal_home"
[ -x "$hcal_home/venv/bin/python" ] || "$py" -m venv "$hcal_home/venv" || fail "가상환경을 만들지 못했어요. (우분투: sudo apt install python3-venv)"
"$hcal_home/venv/bin/python" -m pip install -q --disable-pip-version-check "$here" || fail "설치에 실패했어요."
export HCAL_HOME="$hcal_home"

step "3/4 구글 연결"
args=()
if [ "$(uname)" != "Darwin" ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then args=(--no-browser); fi
"$hcal_home/venv/bin/python" -m hermes_calendar.cli setup ${args[@]+"${args[@]}"} || fail "구글 연결을 끝내지 못했어요. 다시 실행하면 이어서 할 수 있어요."

step "4/4 헤르메스에 연결"
"$hcal_home/venv/bin/python" -m hermes_calendar.cli install-hermes --apply || fail "헤르메스 연결에 실패했어요."
printf '\n🎉 설치 끝. 텔레그램에서 헤르메스에게 "오늘 일정 알려줘"라고 보내 보세요.\n'
