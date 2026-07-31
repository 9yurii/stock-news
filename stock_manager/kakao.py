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
import pathlib
import re
import shutil
import tempfile
import unicodedata
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

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

# 시스템 안내문. 어디에 끼어 있든 그 메시지는 버립니다.
NOISE_CONTAINS = (
    "님이 들어왔습니다", "님이 나갔습니다", "님을 초대했습니다", "님이 나갔습니다.",
    "저장한 날짜", "삭제된 메시지입니다", "채팅방 관리자가",
)

# 첨부 파일 자리표시 글자.
# 내보내기 txt에는 사진·동영상 원본이 들어 있지 않고 이런 글자만 남습니다.
# "이 사진 보세요" 같은 정상 메시지를 날리지 않도록 '완전히 일치할 때만' 버립니다.
NOISE_EXACT = {
    "사진", "동영상", "이모티콘", "음성메시지", "보이스톡", "페이스톡",
    "선물", "삭제된 메시지입니다", "지도", "연락처",
    "<사진>", "<동영상>", "[사진]", "[동영상]",
    "사진을 보냈습니다.", "동영상을 보냈습니다.", "이모티콘을 보냈습니다.",
    "사진을 보냈습니다", "동영상을 보냈습니다", "이모티콘을 보냈습니다",
}

# "사진 3장", "파일: 보고서.pdf" 처럼 뒤에 숫자·이름이 붙는 자리표시
NOISE_PATTERNS = (
    re.compile(r"^사진\s*\d+장$"),
    re.compile(r"^파일\s*:\s*.+$"),
    re.compile(r"^샵검색\s*:\s*.+$"),
)


@dataclass
class Message:
    date: str          # YYYY-MM-DD
    minutes: int       # 자정부터 흐른 분 (시간대 판정용)
    sender: str
    text: str


@dataclass
class Comment:
    """뉴스 주변에서 오간 단톡방 대화 한 줄."""
    sender: str
    at: str            # 'HH:MM'
    text: str


@dataclass
class Candidate:
    date: str
    slot: str
    sender: str
    title: str
    url: str
    raw_text: str
    minutes: int = 0
    lines: list[str] = field(default_factory=list)
    photos: list["Photo"] = field(default_factory=list)
    comments: list["Comment"] = field(default_factory=list)
    used: set[int] = field(default_factory=set)   # 본문으로 쓴 메시지 번호

    @property
    def source_key(self) -> str:
        """이 뉴스의 지문. 같은 대화를 다시 가져와도 같은 값이 나옵니다."""
        if not self.url and not self.raw_text.strip() and self.photos:
            # 사진만 있는 건은 사진 내용으로 판정합니다
            return "kakao-" + hashlib.sha1(
                "".join(p.digest for p in self.photos).encode("utf-8")
            ).hexdigest()[:20]
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
    if stripped in NOISE_EXACT:
        return True
    if any(p.match(stripped) for p in NOISE_PATTERNS):
        return True
    return any(n in stripped for n in NOISE_CONTAINS)


def strip_attachment_lines(text: str) -> str:
    """여러 줄 메시지에 섞인 첨부 자리표시 줄만 걷어냅니다."""
    kept = [l for l in text.split("\n") if not _is_noise(l)]
    return "\n".join(kept).strip()


def _make_title(text: str, url: str) -> str:
    """첫 줄에서 제목을 만듭니다. URL만 있는 메시지면 주소로 대신합니다."""
    body = URL_RE.sub("", text).strip()
    first = next((l.strip() for l in body.split("\n") if l.strip()), "")
    first = re.sub(r"\s+", " ", first)
    if len(first) >= 2:
        return first[:80]
    if url:
        # 주소밖에 없으면 마지막 경로 조각이라도 제목으로 씁니다
        tail = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        return (tail or url)[:80]
    return "제목 없음"


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

    for idx, msg in enumerate(messages):
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
            cand.used.add(idx)
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
            minutes=msg.minutes,
            lines=[msg.text],
            used={idx},
        ))
        last = (msg.sender, msg.date, msg.minutes)

    return picked


def collect_comments(
    messages: list[Message],
    candidates: list[Candidate],
    before: int = 5,
    after: int = 40,
) -> list[Candidate]:
    """뉴스 주변에서 오간 대화를 코멘트로 모읍니다.

    뉴스를 전달해 준 사람의 설명, 다른 사람의 반응처럼 기사 본문은 아니지만
    같이 봐두면 좋은 이야기를 기사와 **구분해서** 담아둡니다.
    """
    consumed: set[int] = set()
    for c in candidates:
        consumed |= c.used

    for idx, msg in enumerate(messages):
        if idx in consumed or _is_noise(msg.text):
            continue

        near = [
            c for c in candidates
            if c.date == msg.date and -before <= msg.minutes - c.minutes <= after
        ]
        if not near:
            continue

        # 가장 가까운(직전) 뉴스에 붙입니다
        owner = min(near, key=lambda c: abs(msg.minutes - c.minutes))
        owner.comments.append(Comment(
            sender=msg.sender,
            at=f"{msg.minutes // 60:02d}:{msg.minutes % 60:02d}",
            text=strip_attachment_lines(msg.text) or msg.text.strip(),
        ))

    return candidates


def count_attachments(messages: list[Message]) -> int:
    """사진·동영상 등 첨부 자리표시가 몇 개인지 셉니다.

    내보내기 txt에는 원본 파일이 들어 있지 않으므로, 사진으로만 공유된 뉴스는
    가져올 수 없습니다. 사용자에게 알려주기 위한 값입니다.
    """
    media = {"사진", "동영상", "<사진>", "<동영상>", "[사진]", "[동영상]",
             "사진을 보냈습니다", "사진을 보냈습니다.",
             "동영상을 보냈습니다", "동영상을 보냈습니다."}
    count = 0
    for m in messages:
        for line in m.text.split("\n"):
            line = line.strip()
            if line in media:
                count += 1
            else:
                hit = re.match(r"^사진\s*(\d+)장$", line)
                if hit:
                    count += int(hit.group(1))
    return count


def load(path: str) -> list[Message]:
    """인코딩을 자동으로 판단해서 파일을 읽습니다."""
    data = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            return parse(data.decode(enc))
        except UnicodeDecodeError:
            continue
    return parse(data.decode("utf-8", "replace"))


# ─────────────────────────── 사진 ───────────────────────────

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}

MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".heic": "image/heic",
}

# 카톡이 내보내는 이미지 파일 이름에서 찍은 시각을 뽑습니다.
#   2026-07-25 09-10-11.jpg / 20260725_091011.jpg / KakaoTalk_20260725_091011.jpg
FILENAME_TIME_RES = (
    re.compile(r"(?P<y>\d{4})[-_.]?(?P<mo>\d{2})[-_.]?(?P<d>\d{2})[ _-]+(?P<h>\d{2})[-:_]?(?P<mi>\d{2})"),
    re.compile(r"(?P<y>\d{4})[-_.]?(?P<mo>\d{2})[-_.]?(?P<d>\d{2})"),
)


@dataclass
class Photo:
    path: str            # 로컬 파일 경로
    name: str            # 원래 파일 이름
    date: str            # YYYY-MM-DD
    minutes: int | None  # 자정부터 흐른 분 (모르면 None)
    digest: str          # 파일 내용 해시 (중복 방지)

    @property
    def mime(self) -> str:
        return MIME.get(pathlib.Path(self.name).suffix.lower(), "application/octet-stream")


def _photo_time(name: str, fallback_mtime: float) -> tuple[str, int | None]:
    """파일 이름에서 날짜·시각을 뽑고, 없으면 파일 수정 시각을 씁니다."""
    for regex in FILENAME_TIME_RES:
        m = regex.search(name)
        if not m:
            continue
        g = m.groupdict()
        date = f"{g['y']}-{g['mo']}-{g['d']}"
        if "h" in g and g.get("h") is not None:
            return date, int(g["h"]) * 60 + int(g["mi"])
        return date, None
    dt = datetime.fromtimestamp(fallback_mtime)
    return dt.strftime("%Y-%m-%d"), dt.hour * 60 + dt.minute


def find_photos(folder: str) -> list[Photo]:
    """폴더(또는 그 하위)에서 이미지 파일을 모두 찾습니다."""
    root = pathlib.Path(folder)
    photos: list[Photo] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        data = p.read_bytes()
        date, minutes = _photo_time(p.name, p.stat().st_mtime)
        photos.append(Photo(
            path=str(p),
            name=p.name,
            date=date,
            minutes=minutes,
            digest="img-" + hashlib.sha1(data).hexdigest()[:20],
        ))
    return photos


def attach_photos(
    candidates: list[Candidate],
    photos: list[Photo],
    window_minutes: int = 20,
) -> list[Candidate]:
    """사진을 시간이 가까운 뉴스에 붙이고, 짝이 없는 사진은 따로 한 건으로 만듭니다.

    카톡 내보내기 텍스트에는 사진의 파일 이름이 없어서, 어느 메시지의 사진인지
    직접 알 수 없습니다. 그래서 **같은 날짜 + 가장 가까운 시각**으로 짝을 맞춥니다.
    """
    for photo in photos:
        best = None
        if photo.minutes is not None:
            near = [
                c for c in candidates
                if c.date == photo.date and abs(c.minutes - photo.minutes) <= window_minutes
            ]
            if near:
                best = min(near, key=lambda c: abs(c.minutes - photo.minutes))
        if best is not None:
            best.photos.append(photo)
        else:
            candidates.append(Candidate(
                date=photo.date,
                slot=_slot_of(photo.minutes if photo.minutes is not None else 9 * 60),
                sender="",
                title=f"사진 뉴스 ({photo.date})",
                url="",
                raw_text="",
                minutes=photo.minutes if photo.minutes is not None else 9 * 60,
                photos=[photo],
            ))

    candidates.sort(key=lambda c: (c.date, c.minutes))
    return candidates


def open_export(path: str) -> tuple[str | None, str, str | None]:
    """내보내기 파일/폴더/zip 을 받아 (txt경로, 이미지폴더, 임시폴더) 를 돌려줍니다.

    - .txt 를 주면 같은 폴더에서 이미지를 찾습니다
    - 폴더를 주면 그 안의 txt 와 이미지를 찾습니다
    - .zip 을 주면 임시 폴더에 풀어서 같은 방식으로 처리합니다 (호출한 쪽이 정리)
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"경로를 찾을 수 없습니다: {path}")

    tmpdir = None
    if p.suffix.lower() == ".zip":
        tmpdir = tempfile.mkdtemp(prefix="kakao-")
        with zipfile.ZipFile(p) as zf:
            zf.extractall(tmpdir)
        p = pathlib.Path(tmpdir)

    if p.is_file():
        return str(p), str(p.parent), tmpdir

    txts = sorted(p.rglob("*.txt"))
    return (str(txts[0]) if txts else None), str(p), tmpdir


def cleanup(tmpdir: str | None) -> None:
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)
