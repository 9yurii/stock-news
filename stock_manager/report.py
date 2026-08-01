"""리포트 형식 정의와 저장 전 검증."""

from __future__ import annotations

import re

# 사용자가 정한 7개 섹션 제목 — 순서와 문구를 그대로 고정합니다.
SECTIONS = [
    "■ ① 30초 요약",
    "■ ② 팩트 정리 — 무슨 일이 있었나",
    "■ ③ 왜 이렇게 움직였나 — 시장의 속마음",
    "■ ④ 찬반 시각 정리",
    "■ ⑤ 앞으로 체크리스트",
    "■ ⑥ 상황별 관점 (투자권유 아님)",
    "■ ⑦ 오늘의 용어 복습",
]

TONES = ["호재", "악재", "중립", "해석이 갈림"]

SLOTS = ["아침", "점심", "저녁"]

DISCLAIMER = "판단과 책임은 본인의 몫"

# ⑥에서 금지되는 투자 권유 표현
SOLICIT_PATTERNS = [
    r"사세요",
    r"사시기\s*바랍",
    r"매수\s*하세요",
    r"매수\s*추천",
    r"매수를?\s*권",
    r"파세요",
    r"팔아라",
    # "사라" 뒤에 다른 한글이 오면 '사라지다' 같은 낱말이므로 권유가 아닙니다
    r"사라(?![가-힣])",
    r"매도\s*하세요",
    r"매도\s*추천",
    r"매도를?\s*권",
    r"추천\s*종목",
    # 개념 설명("목표주가는 방향 지표입니다")은 괜찮고,
    # 실제 목표가를 숫자로 제시하는 경우만 잡습니다
    r"목표\s*주가\s*(는|은|를|가)?\s*[\d,]+\s*(만)?\s*(원|달러)",
    r"지금이\s*기회",
    r"무조건\s*(오릅|사)",
]


def _sentence_count(text: str) -> int:
    """마침표/물음표/느낌표로 끝나는 문장 수를 셉니다.

    숫자 사이의 점(60.5조, 10.8%)은 문장 끝이 아니므로 세지 않습니다.
    """
    return len([s for s in re.split(r"(?<!\d)[.!?](?!\d)\s*", text.strip()) if s.strip()])


def normalize(report: dict) -> dict:
    """입력 JSON을 표준 형태로 다듬습니다 (섹션 제목 공백 정리 등)."""
    out = dict(report)
    out["title"] = str(out.get("title", "")).strip()
    out["url"] = str(out.get("url", "") or "").strip()
    out["date"] = str(out.get("date", "")).strip()
    out["slot"] = str(out.get("slot", "")).strip()
    out["tone"] = str(out.get("tone", "")).strip()
    out["summary"] = str(out.get("summary", "")).strip()
    out["raw_text"] = str(out.get("raw_text", "") or "")

    tags = out.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    out["tags"] = [t for t in (s.strip() for s in tags) if t]

    sections = []
    for i, sec in enumerate(out.get("sections") or []):
        if isinstance(sec, str):
            sec = {"title": SECTIONS[i] if i < len(SECTIONS) else "", "body": sec}
        sections.append(
            {
                "title": str(sec.get("title", "")).strip(),
                "body": str(sec.get("body", "")).rstrip(),
            }
        )
    out["sections"] = sections

    # 종목: "삼성전자" 또는 {"name": "삼성전자", "code": "005930", "note": "..."}
    tickers = []
    for tk in out.get("tickers") or []:
        if isinstance(tk, str):
            tk = {"name": tk}
        name = str(tk.get("name", "")).strip()
        if not name:
            continue
        tickers.append(
            {
                "name": name,
                "code": str(tk.get("code", "") or "").strip(),
                "note": str(tk.get("note", "") or "").strip(),
            }
        )
    out["tickers"] = tickers

    terms = []
    for t in out.get("terms") or []:
        terms.append(
            {
                "term": str(t.get("term", "")).strip(),
                "meaning": str(t.get("meaning", "")).strip(),
                "usage": str(t.get("usage", "")).strip(),
            }
        )
    out["terms"] = terms
    return out


def validate(report: dict) -> list[str]:
    """규칙 위반 목록을 돌려줍니다. 빈 리스트면 저장 가능."""
    errors: list[str] = []

    if not report.get("title"):
        errors.append("제목(title)이 비어 있습니다.")

    date = report.get("date", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        errors.append(f"날짜(date)는 YYYY-MM-DD 형식이어야 합니다. 받은 값: {date!r}")

    slot = report.get("slot", "")
    if slot not in SLOTS:
        errors.append(f"시간대(slot)는 {' / '.join(SLOTS)} 중 하나여야 합니다. 받은 값: {slot!r}")

    tone = report.get("tone", "")
    if tone not in TONES:
        errors.append(f"성격(tone)은 {' / '.join(TONES)} 중 하나여야 합니다. 받은 값: {tone!r}")

    summary = report.get("summary", "")
    if not summary:
        errors.append("① 한 문장 요약(summary)이 비어 있습니다.")
    else:
        if _sentence_count(summary) > 1:
            errors.append(
                "① 요약(summary)은 한 문장이어야 합니다. 문장이 2개 이상으로 보입니다: " + summary
            )
        if len(summary) > 150:
            errors.append(f"① 요약(summary)이 너무 깁니다({len(summary)}자). 150자 이내로 줄여주세요.")

    sections = report.get("sections") or []
    if len(sections) != 7:
        errors.append(f"섹션은 정확히 7개여야 합니다. 받은 개수: {len(sections)}개")
    else:
        for i, (sec, expected) in enumerate(zip(sections, SECTIONS), start=1):
            if sec["title"] != expected:
                errors.append(
                    f"{i}번째 섹션 제목이 다릅니다.\n  기대: {expected}\n  받음: {sec['title']}"
                )
            if not sec["body"].strip():
                errors.append(f"{i}번째 섹션({expected}) 본문이 비어 있습니다.")

        body6 = sections[5]["body"]
        if DISCLAIMER not in body6:
            errors.append(f'⑥ 섹션 마지막에 "{DISCLAIMER}" 문구가 반드시 들어가야 합니다.')
        for pat in SOLICIT_PATTERNS:
            m = re.search(pat, body6)
            if m:
                errors.append(
                    f"⑥ 섹션에 투자 권유로 읽히는 표현이 있습니다: {m.group(0)!r} "
                    "— '이런 점을 고려해볼 수 있습니다' 수준으로 바꿔주세요."
                )

    terms = report.get("terms") or []
    if len(terms) != 3:
        errors.append(f"⑦ 용어 복습은 정확히 3개여야 합니다. 받은 개수: {len(terms)}개")
    for i, t in enumerate(terms, start=1):
        missing = [k for k in ("term", "meaning", "usage") if not t.get(k)]
        if missing:
            errors.append(f"⑦ {i}번째 용어에 빠진 항목이 있습니다: {', '.join(missing)}")

    return errors


def to_markdown(entry: dict) -> str:
    """저장된 항목을 마크다운 문서로 만듭니다."""
    lines = [f"# {entry['title']}", ""]
    lines.append(f"- 날짜: {entry['date']} ({entry['slot']})")
    lines.append(f"- 성격: {entry['tone']}")
    if entry.get("url"):
        lines.append(f"- 원문: {entry['url']}")
    if entry.get("tags"):
        lines.append(f"- 태그: {', '.join(entry['tags'])}")
    if entry.get("tickers"):
        names = [tk["name"] + (f"({tk['code']})" if tk.get("code") else "") for tk in entry["tickers"]]
        lines.append(f"- 종목: {', '.join(names)}")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━")
    lines.append("")
    for sec in entry.get("sections", []):
        lines.append(f"## {sec['title']}")
        lines.append("")
        lines.append(sec["body"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_kakao_text(entry: dict) -> str:
    """단톡방에 그대로 붙여넣을 평문."""
    lines = [f"[{entry['date']} {entry['slot']}] {entry['title']}", f"성격: {entry['tone']}", ""]
    for sec in entry.get("sections", []):
        lines.append(sec["title"])
        lines.append(sec["body"])
        lines.append("")
    if entry.get("url"):
        lines.append(f"원문: {entry['url']}")
    return "\n".join(lines).rstrip() + "\n"
