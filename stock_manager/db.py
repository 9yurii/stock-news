"""데이터 접근 계층. 저장소는 Supabase 한 곳입니다.

읽기는 로그인 없이, 쓰기는 허용 목록에 등록된 계정으로만 가능합니다 (Supabase RLS).
"""

from __future__ import annotations

from . import supa
from .supa import SupabaseError  # noqa: F401  (cli에서 사용)

ENTRY_COLS = "id,date,slot,title,url,raw_text,status,tone,summary,tags,created_at,updated_at"
LIST_COLS = "id,date,slot,title,status,tone,summary"


def init_db() -> str:
    """스키마는 Supabase 마이그레이션으로 이미 만들어져 있습니다. 연결만 확인합니다."""
    supa.select("entries", {"select": "id", "limit": "1"})
    return supa.SUPABASE_URL


# ─────────────────────────── 쓰기 ───────────────────────────

def add_pending(date: str, slot: str, title: str, url: str, raw_text: str,
                source_key: str | None = None) -> int:
    row = {
        "date": date, "slot": slot, "title": title,
        "url": url or "", "raw_text": raw_text, "status": "pending",
    }
    if source_key:
        row["source_key"] = source_key
    rows = supa.insert("entries", row)
    return int(rows[0]["id"])


def save_report(report: dict, entry_id: int | None = None) -> int:
    fields = {
        "date": report["date"],
        "slot": report["slot"],
        "title": report["title"],
        "url": report["url"],
        "status": "done",
        "tone": report["tone"],
        "summary": report["summary"],
        "tags": report.get("tags") or [],
    }
    if report.get("raw_text"):
        fields["raw_text"] = report["raw_text"]

    if entry_id is not None:
        rows = supa.update("entries", {"id": f"eq.{entry_id}"}, fields)
        if not rows:
            raise ValueError(f"{entry_id}번 뉴스를 찾을 수 없거나 수정 권한이 없습니다.")
        # 자식 행은 지우고 새로 씁니다 (재작성 대비)
        for table in ("sections", "terms", "tickers"):
            supa.delete(table, {"entry_id": f"eq.{entry_id}"})
    else:
        fields.setdefault("raw_text", report.get("raw_text") or "")
        rows = supa.insert("entries", fields)
        entry_id = int(rows[0]["id"])

    sections = [
        {"entry_id": entry_id, "idx": i, "title": s["title"], "body": s["body"]}
        for i, s in enumerate(report["sections"], 1)
    ]
    supa.insert("sections", sections, returning=False)

    terms = [
        {"entry_id": entry_id, "term": t["term"], "meaning": t["meaning"], "usage": t["usage"]}
        for t in report["terms"]
    ]
    if terms:
        supa.insert("terms", terms, returning=False)

    tickers = [
        {"entry_id": entry_id, "name": tk["name"], "code": tk["code"], "note": tk["note"]}
        for tk in report.get("tickers") or []
    ]
    if tickers:
        supa.insert("tickers", tickers, returning=False)

    return int(entry_id)


def delete_entry(entry_id: int) -> bool:
    return bool(supa.delete("entries", {"id": f"eq.{entry_id}"}))


# ─────────────────────────── 읽기 ───────────────────────────

def _norm(row: dict) -> dict:
    row = dict(row)
    row.setdefault("tags", [])
    if isinstance(row["tags"], str):
        row["tags"] = [t for t in row["tags"].split(",") if t]
    return row


def list_pending() -> list[dict]:
    rows = supa.select("entries", {
        "select": "id,date,slot,title,url,raw_text,"
                  "attachments(id,path,original_name),comments(sender,at,text)",
        "status": "eq.pending",
        "order": "date.asc,id.asc",
    })
    out = []
    for r in rows:
        r = dict(r)
        for a in r.get("attachments") or []:
            a["url"] = supa.public_image_url(a["path"])
        out.append(r)
    return out


def get_entry(entry_id: int) -> dict | None:
    rows = supa.select("entries", {"select": ENTRY_COLS, "id": f"eq.{entry_id}"})
    if not rows:
        return None
    entry = _norm(rows[0])
    entry["sections"] = supa.select("sections", {
        "select": "idx,title,body", "entry_id": f"eq.{entry_id}", "order": "idx.asc",
    })
    entry["terms"] = supa.select("terms", {
        "select": "term,meaning,usage", "entry_id": f"eq.{entry_id}", "order": "id.asc",
    })
    entry["tickers"] = supa.select("tickers", {
        "select": "name,code,note", "entry_id": f"eq.{entry_id}", "order": "id.asc",
    })
    entry["attachments"] = list_attachments(entry_id)
    entry["comments"] = list_comments(entry_id)
    return entry


def list_entries(
    date_from: str | None = None,
    date_to: str | None = None,
    tone: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    params = {"select": LIST_COLS, "order": "date.desc,id.desc", "limit": str(limit)}
    if date_from:
        params["date"] = f"gte.{date_from}"
    if date_to:
        # 같은 컬럼에 조건이 둘이면 PostgREST는 and= 문법이 필요합니다
        if "date" in params:
            params["and"] = f"(date.gte.{date_from},date.lte.{date_to})"
            del params["date"]
        else:
            params["date"] = f"lte.{date_to}"
    if tone:
        params["tone"] = f"eq.{tone}"
    if status:
        params["status"] = f"eq.{status}"
    return [_norm(r) for r in supa.select("entries", params)]


def search(
    q: str,
    date_from: str | None = None,
    date_to: str | None = None,
    tone: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """제목·요약·본문·섹션·용어·종목을 부분일치로 훑습니다."""
    ids: set[int] = set()
    if q:
        like = f"*{q}*"
        for table, params in (
            ("sections", {"select": "entry_id", "body": f"ilike.{like}", "limit": "500"}),
            ("terms", {"select": "entry_id", "or": f"(term.ilike.{like},meaning.ilike.{like})",
                       "limit": "500"}),
            ("tickers", {"select": "entry_id", "name": f"ilike.{like}", "limit": "500"}),
        ):
            for r in supa.select(table, params):
                ids.add(int(r["entry_id"]))

    params: dict[str, str] = {"select": LIST_COLS, "order": "date.desc,id.desc", "limit": str(limit)}
    if q:
        like = f"*{q}*"
        parts = [f"title.ilike.{like}", f"summary.ilike.{like}", f"raw_text.ilike.{like}"]
        if ids:
            parts.append(f"id.in.({','.join(str(i) for i in sorted(ids))})")
        params["or"] = f"({','.join(parts)})"

    conds = []
    if date_from:
        conds.append(f"date.gte.{date_from}")
    if date_to:
        conds.append(f"date.lte.{date_to}")
    if tone:
        conds.append(f"tone.eq.{tone}")
    if conds:
        params["and"] = f"({','.join(conds)})"

    return [_norm(r) for r in supa.select("entries", params)]


def list_terms(q: str | None = None) -> list[dict]:
    params = {"select": "term,meaning,usage,entry_id,entries(date,title)",
              "order": "term.asc", "limit": "1000"}
    if q:
        params["or"] = f"(term.ilike.*{q}*,meaning.ilike.*{q}*)"
    rows = supa.select("terms", params)

    grouped: dict[str, dict] = {}
    for r in rows:
        g = grouped.setdefault(r["term"], {
            "term": r["term"], "meaning": r["meaning"], "usage": r["usage"],
            "count": 0, "seen": [],
        })
        g["count"] += 1
        ent = r.get("entries") or {}
        g["seen"].append({
            "entry_id": r["entry_id"], "date": ent.get("date", ""), "title": ent.get("title", ""),
        })
    return list(grouped.values())


def list_tickers(q: str | None = None) -> list[dict]:
    params = {"select": "name,code,entry_id,entries(date)", "limit": "2000"}
    if q:
        params["or"] = f"(name.ilike.*{q}*,code.ilike.*{q}*)"
    rows = supa.select("tickers", params)

    agg: dict[str, dict] = {}
    for r in rows:
        g = agg.setdefault(r["name"], {"name": r["name"], "code": r.get("code") or "",
                                       "count": 0, "last_date": ""})
        g["count"] += 1
        if r.get("code") and not g["code"]:
            g["code"] = r["code"]
        d = (r.get("entries") or {}).get("date") or ""
        if d > g["last_date"]:
            g["last_date"] = d
    return sorted(agg.values(), key=lambda g: (-g["count"], g["last_date"]), reverse=False)


def ticker_timeline(name: str) -> list[dict]:
    rows = supa.select("tickers", {"select": "entry_id", "name": f"eq.{name}"})
    ids = sorted({int(r["entry_id"]) for r in rows})
    if not ids:
        return []
    return [_norm(r) for r in supa.select("entries", {
        "select": LIST_COLS,
        "id": f"in.({','.join(str(i) for i in ids)})",
        "order": "date.desc,id.desc",
    })]


def add_comments(entry_id: int, comments: list[dict]) -> None:
    """단톡방에서 오간 대화를 뉴스에 붙여 저장합니다."""
    if not comments:
        return
    supa.insert("comments", [
        {"entry_id": entry_id, "idx": i, "sender": c["sender"],
         "at": c["at"], "text": c["text"]}
        for i, c in enumerate(comments)
    ], returning=False)


def list_comments(entry_id: int) -> list[dict]:
    return supa.select("comments", {
        "select": "sender,at,text", "entry_id": f"eq.{entry_id}", "order": "idx.asc",
    })


def add_attachment(entry_id: int, path: str, original_name: str,
                   taken_at: str | None, source_key: str | None) -> int:
    row = {"entry_id": entry_id, "path": path, "original_name": original_name}
    if taken_at:
        row["taken_at"] = taken_at
    if source_key:
        row["source_key"] = source_key
    rows = supa.insert("attachments", row)
    return int(rows[0]["id"])


def list_attachments(entry_id: int) -> list[dict]:
    rows = supa.select("attachments", {
        "select": "id,path,original_name,taken_at",
        "entry_id": f"eq.{entry_id}",
        "order": "id.asc",
    })
    for r in rows:
        r["url"] = supa.public_image_url(r["path"])
    return rows


def existing_image_digests() -> set[str]:
    """이미 올린 사진의 지문 (같은 사진 재업로드 방지)."""
    rows = supa.select("attachments", {
        "select": "source_key", "source_key": "not.is.null", "limit": "5000",
    })
    return {r["source_key"] for r in rows if r.get("source_key")}


def existing_source_keys() -> set[str]:
    """이미 가져온 뉴스의 지문 목록 (카톡 재수입 시 중복 제거용)."""
    rows = supa.select("entries", {
        "select": "source_key", "source_key": "not.is.null", "limit": "5000",
    })
    return {r["source_key"] for r in rows if r.get("source_key")}


def existing_urls() -> set[str]:
    """이미 저장된 뉴스 주소."""
    rows = supa.select("entries", {"select": "url", "limit": "5000"})
    return {r.get("url") or "" for r in rows}


def stats() -> dict:
    entries = supa.select("entries", {"select": "id,status", "limit": "5000"})
    terms = supa.select("terms", {"select": "term", "limit": "5000"})
    tickers = supa.select("tickers", {"select": "name", "limit": "5000"})
    return {
        "total": sum(1 for e in entries if e["status"] == "done"),
        "pending": sum(1 for e in entries if e["status"] == "pending"),
        "terms": len({t["term"] for t in terms}),
        "tickers": len({t["name"] for t in tickers}),
    }
