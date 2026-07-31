"""카카오톡 '대화 내보내기(.txt)' 파일에서 뉴스를 뽑아옵니다.

카카오톡은 대화방을 바깥에서 읽어가는 공개 API를 제공하지 않습니다.
대신 카톡의 [대화 내보내기] 기능으로 만든 .txt 파일을 여기서 읽어들입니다.

내보내기 방법
  - PC:    대화방 → 오른쪽 위 메뉴 → 대화 내용 → 대화 내용 저장
  - 안드로이드: 대화방 → 메뉴(≡) → 설정(⚙) → 대화 내용 내보내기 → 텍스트만 보내기
  - 아이폰: 대화방 → 메뉴(≡) → 설정(⚙) → 대화 내용 내보내기 → 텍스트 파일로 저장

세 가지 형식(PC / 안드로이드 / 아이폰)을 모두 인식합니다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field

URL_RE = re.compile(r"https?://[^\s]+")

# 같은 기사인데 주소만 달라 보이게 만드는 추적용 꼬리표
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "spm", "from", "ref", "cmpid", "share",
}

# PC 형식: --------------- 2026년 7월 25일 토요일 ---------------
PC_DATE_RE = re.compile(r"^-+\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?-+\s*$")
# PC 형식: [홍길동] [오후 3:24] 내용
PC_MSG_RE = re.compile(r"^\[(?P<sender>[^\]]+)\]\s*\[(?P<ampm>오전|오후)\s*(?P<h>\d{1,2}):(?P<m>\d{2})\]\s?(?P<text>.*)$")

# 안드로이드: 2026년 7월 25일 오후 3:24, 홍길동 : 내용
AND_MSG_RE = re.compile(
    r"^(?P<y>\d{4})년\s*(?P<mo>\d{1,2})월\s*(?P<d>\d{1,2})일\s*(?P<ampm>오전|오후)\s*"
    r"(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*(?P<sender>.+?)\s*:\s?(?P<text>.*)$"
)

# 아이폰: 2026. 7. 25. 오후 3:24, 홍길동 : 내용
IOS_MSG_RE = re.compile(
    r"^(?P<y>\d{4})\.\s*(?P<mo>\d{1,2})\.\s*(?P<d>\d{1,2})\.\s*(?P<ampm>오전|오후)\s*"
    r"(?P<h>\d{1,2}):(?P<mi>\d{2}),\s*(?P<sender>.+?)\s*:\s?(?P<text>.*)$"
)

# 뉴스로 볼 필요가 없는 시스템 메시지
NOISE = (
    "님이 들어왔습니다", "님이 나갔습니다", "저장한 날짜", "님을 초대했습니다",
    "삭제된 메시지입니다", "사진을 보냈습니다", "동영상을 보냈습니다",
    "이모티콘을 보냈습니다", "파일:", "샵검색:",
)


@dataclass
class Message:
    date: str          # YYYY-MM-DD
    minutes: int       # 자정부터 흐른 분 (시간대 판정용)
    sender: str
    text: str


@dataclass
class Candidate:
    date: str
    slot: str
    sender: str
    title: str
    url: str
    raw_text: str
    lines: list[str] = field(default_factory=list)

    @property
    def source_key(self) -> str:
        """이 뉴스의 지문. 같은 대화를 다시 가져와도 같은 값이 나옵니다."""
        return make_source_key(self.date, self.url, self.raw_text)


def normalize_url(url: str) -> str:
    """추적용 꼬리표와 끝 슬래시를 떼어내, 같은 기사면 같은 주소가 되게 합니다."""
    if not url:
        return ""
    url = url.strip().rstrip(").,]>\"'")
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    query = [
        (k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
    return urllib.parse.urlunsplit((
        p.scheme.lower(),
        p.netloc.lower().removeprefix("www."),
        p.path.rstrip("/"),
        urllib.parse.urlencode(query),
        "",  # 앵커(#...)는 버립니다
    ))


def make_source_key(date: str, url: str, text: str) -> str:
    """중복 판정용 지문.

    주소가 있으면 주소만으로 판정합니다 (같은 기사를 다른 날 다시 공유해도 한 건).
    주소가 없으면 날짜 + 본문 앞부분으로 판정합니다.
    """
    norm = normalize_url(url)
    if norm:
        seed = f"url:{norm}"
    else:
        body = re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()[:300]
        seed = f"txt:{date}:{body}"
    return "kakao-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _to_24h(ampm: str, hour: int, minute: int) -> int:
    h = hour % 12
    if ampm == "오후":
        h += 12
    return h * 60 + minute


def _slot_of(minutes: int) -> str:
    if minutes < 12 * 60:
        return "아침"
    if minutes < 18 * 60:
        return "점심"
    return "저녁"


def parse(text: str) -> list[Message]:
    """내보내기 파일 전체를 메시지 목록으로 바꿉니다."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("﻿", ""))
    messages: list[Message] = []
    cur_date: str | None = None

    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            continue

        m = PC_DATE_RE.match(line)
        if m:
            y, mo, d = (int(x) for x in m.groups())
            cur_date = f"{y:04d}-{mo:02d}-{d:02d}"
            continue

        for regex, has_date in ((AND_MSG_RE, True), (IOS_MSG_RE, True), (PC_MSG_RE, False)):
            m = regex.match(line)
            if not m:
                continue
            g = m.groupdict()
            if has_date:
                date = f"{int(g['y']):04d}-{int(g['mo']):02d}-{int(g['d']):02d}"
                minutes = _to_24h(g["ampm"], int(g["h"]), int(g["mi"]))
            else:
                if not cur_date:
                    break
                date = cur_date
                minutes = _to_24h(g["ampm"], int(g["h"]), int(g["m"]))
            messages.append(Message(date, minutes, g["sender"].strip(), g["text"]))
            break
        else:
            # 어떤 형식에도 안 맞으면 직전 메시지의 여러 줄 이어쓰기로 봅니다
            if messages:
                messages[-1].text += "\n" + line

    return messages


def _is_noise(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return any(n in stripped for n in NOISE)


def _make_title(text: str, url: str) -> str:
    """첫 줄에서 제목을 만듭니다. URL만 있는 메시지면 주소로 대신합니다."""
    body = URL_RE.sub("", text).strip()
    first = next((l.strip() for l in body.split("\n") if l.strip()), "")
    first = re.sub(r"\s+", " ", first)
    if len(first) >= 6:
        return first[:80]
    if url:
        return url.split("?")[0][:80]
    return first[:80] or "제목 없음"


def extract(
    messages: list[Message],
    sender: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    min_length: int = 120,
    gap_minutes: int = 10,
) -> list[Candidate]:
    """뉴스로 볼 만한 메시지를 골라 묶습니다.

    - 링크가 들어간 메시지는 뉴스로 봅니다.
    - 링크가 없어도 `min_length`자 이상인 긴 메시지는 뉴스로 봅니다.
    - 같은 사람이 `gap_minutes` 안에 이어서 보낸 메시지는 한 건으로 묶습니다.
    """
    picked: list[Candidate] = []
    last: tuple[str, str, int] | None = None  # (sender, date, minutes)

    for msg in messages:
        if _is_noise(msg.text):
            continue
        if sender and sender not in msg.sender:
            continue
        if date_from and msg.date < date_from:
            continue
        if date_to and msg.date > date_to:
            continue

        urls = URL_RE.findall(msg.text)
        body_len = len(URL_RE.sub("", msg.text).strip())
        interesting = bool(urls) or body_len >= min_length

        # 직전 건에 이어붙일지 판단.
        # 단, 자기 링크를 가진 메시지는 별개의 뉴스이므로 절대 합치지 않습니다
        # (합치면 뒤 기사가 앞 기사에 묻혀 사라집니다).
        merges_into_previous = (
            picked
            and last
            and last[0] == msg.sender
            and last[1] == msg.date
            and 0 <= msg.minutes - last[2] <= gap_minutes
            and not (urls and picked[-1].url
                     and normalize_url(urls[0]) != normalize_url(picked[-1].url))
        )
        if merges_into_previous:
            cand = picked[-1]
            cand.lines.append(msg.text)
            cand.raw_text = "\n".join(cand.lines)
            if urls and not cand.url:
                cand.url = urls[0]
            if cand.title in ("제목 없음", "") or cand.title.startswith("http"):
                cand.title = _make_title(cand.raw_text, cand.url)
            last = (msg.sender, msg.date, msg.minutes)
            continue

        if not interesting:
            continue

        url = urls[0] if urls else ""
        picked.append(Candidate(
            date=msg.date,
            slot=_slot_of(msg.minutes),
            sender=msg.sender,
            title=_make_title(msg.text, url),
            url=url,
            raw_text=msg.text,
            lines=[msg.text],
        ))
        last = (msg.sender, msg.date, msg.minutes)

    return picked


def load(path: str) -> list[Message]:
    """인코딩을 자동으로 판단해서 파일을 읽습니다."""
    data = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return parse(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return parse(data.decode("utf-8", "replace"))
