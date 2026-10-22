"""일정 설명란 = 설명 + [할 일] + [메모] + [기록].

구글 캘린더 앱에서 그대로 읽히는 글로 저장하고, 앱에서 사람이 고쳐도 다시 읽을 수 있게 느슨하게 해석한다.

    사랑니 상담 + 스케일링

    [할 일]
    ☑ 보험증 챙기기
    ☐ 다음 예약 잡기

    [메모]
    10/21 사진 다시 찍자고 함

    [기록]
    10/20 09:12 등록
    10/23 16:40 완료 · 다음 진료 11/6
"""

import html
import re
from dataclasses import dataclass, field

SECTIONS = {"할 일": "todos", "메모": "memos", "기록": "history"}
HEADER = re.compile(r"^\s*\[(할 일|메모|기록)\]\s*$")
TODO = re.compile(r"^\s*(?:-\s*)?(☐|☑|✅|\[ ?\]|\[[xX]\])\s*(.*)$")


class UserError(ValueError):
    """사용자에게 그대로 보여줄 오류."""


HTML = re.compile(r"<(br|p|div|ul|ol|li|b|i|u|a|span)\b[^>]*>|</(p|div|li)>", re.I)


@dataclass
class Todo:
    text: str
    done: bool = False


@dataclass
class Notes:
    description: str = ""
    todos: list[Todo] = field(default_factory=list)
    memos: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str | None) -> "Notes":
        text = text or ""
        if HTML.search(text):  # 구글 캘린더 웹에서 고치면 HTML로 저장된다
            text = re.sub(r"<br\s*/?>|</(p|div|li)>", "\n", text, flags=re.I)
            text = html.unescape(re.sub(r"<[^>]+>", "", text))
        n, section, desc = cls(), None, []
        for line in text.replace("\r\n", "\n").split("\n"):
            if m := HEADER.match(line):
                section = SECTIONS[m[1]]
            elif section is None:
                desc.append(line)
            elif not line.strip():
                continue
            elif section == "todos":
                m = TODO.match(line)
                done, item = (m[1] in ("☑", "✅") or m[1].lower() == "[x]", m[2]) if m else (False, line.strip())
                if item.strip():
                    n.todos.append(Todo(item.strip(), done))
            else:
                getattr(n, section).append(line.strip())
        n.description = "\n".join(desc).strip()
        return n

    def render(self) -> str:
        parts = [self.description] if self.description else []
        if self.todos:
            parts.append("[할 일]\n" + "\n".join(f"{'☑' if t.done else '☐'} {t.text}" for t in self.todos))
        if self.memos:
            parts.append("[메모]\n" + "\n".join(self.memos))
        if self.history:
            parts.append("[기록]\n" + "\n".join(self.history))
        return "\n\n".join(parts)

    def find_todo(self, ref: str | int) -> int:
        """번호(1부터) 또는 글자 일부로 할 일 위치를 찾는다."""
        ref = str(ref).strip()
        if ref.isdigit() and 1 <= int(ref) <= len(self.todos):
            return int(ref) - 1
        hits = [i for i, t in enumerate(self.todos) if ref and ref in t.text]
        if len(hits) == 1:
            return hits[0]
        raise UserError(f"할 일을 특정할 수 없어요: {ref!r} (번호나 더 긴 글자로 주세요)")

    def todo_progress(self) -> str:
        return f"{sum(t.done for t in self.todos)}/{len(self.todos)}" if self.todos else ""
