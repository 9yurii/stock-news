"""명령줄 진입점. /news 슬래시 명령이 이 CLI를 호출합니다."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as _date
from pathlib import Path

from . import db, report as R, supa

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 저장된 리포트를 볼 수 있는 공개 주소. GitHub Pages 주소가 정해지면 .env의
# SITE_URL 로 바꾸면 됩니다.
DEFAULT_SITE = "http://127.0.0.1:8765"


def site_url() -> str:
    return supa.load_env().get("SITE_URL", DEFAULT_SITE).rstrip("/")


def _print_entry(entry: dict) -> None:
    print(R.to_markdown(entry))


def _brief(e: dict) -> str:
    mark = "…해설 대기" if e["status"] == "pending" else (e.get("tone") or "")
    return f"[{e['id']:>4}] {e['date']} {e['slot']} | {mark:<7} | {e['title']}"


def cmd_init(args) -> int:
    url = db.init_db()
    print(f"Supabase 연결 확인: {url}")
    try:
        user = supa.whoami()
        writable = "쓰기 가능" if supa.can_write() else "읽기 전용"
        print(f"로그인 계정: {user.get('email')} ({writable})")
    except supa.SupabaseError as e:
        print(f"로그인 확인 실패: {e}")
        return 1
    return 0


def cmd_whoami(args) -> int:
    user = supa.whoami()
    print(f"{user.get('email')} — {'쓰기 가능' if supa.can_write() else '읽기 전용'}")
    return 0


def cmd_add(args) -> int:
    text = ""
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    entry_id = db.add_pending(
        date=args.date or _date.today().isoformat(),
        slot=args.slot,
        title=args.title,
        url=args.url or "",
        raw_text=text,
    )
    print(f"저장했습니다 (해설 대기). id={entry_id}")
    return 0


def cmd_pending(args) -> int:
    items = db.list_pending()
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def cmd_save(args) -> int:
    raw = json.loads(Path(args.json).read_text(encoding="utf-8"))
    data = R.normalize(raw)
    errors = R.validate(data)
    if errors:
        print("저장하지 않았습니다. 아래 규칙을 지켜서 다시 만들어 주세요:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    entry_id = raw.get("entry_id") or args.entry_id
    saved_id = db.save_report(data, entry_id=int(entry_id) if entry_id else None)
    print(f"저장 완료: id={saved_id}")
    print(f"웹에서 보기: {site_url()}/#/entry/{saved_id}")
    return 0


def cmd_list(args) -> int:
    entries = db.list_entries(args.date_from, args.date_to, args.tone, args.status, args.limit)
    if not entries:
        print("해당하는 뉴스가 없습니다.")
        return 0
    cur = None
    for e in entries:
        if e["date"] != cur:
            cur = e["date"]
            print(f"\n── {cur} ──")
        print(_brief(e))
        if e.get("summary"):
            print(f"       {e['summary']}")
    return 0


def cmd_show(args) -> int:
    entry = db.get_entry(args.id)
    if not entry:
        print(f"{args.id}번 뉴스를 찾을 수 없습니다.", file=sys.stderr)
        return 1
    if entry["status"] == "pending":
        print(f"[{entry['date']} {entry['slot']}] {entry['title']} — 아직 해설 대기 상태입니다.")
        if entry.get("url"):
            print(f"원문: {entry['url']}")
        print("\n--- 원문 붙여넣기 ---")
        print(entry["raw_text"])
        return 0
    if args.kakao:
        print(R.to_kakao_text(entry))
    else:
        _print_entry(entry)
    return 0


def cmd_search(args) -> int:
    entries = db.search(args.query, args.date_from, args.date_to, args.tone, args.limit)
    if not entries:
        print(f"'{args.query}' 검색 결과가 없습니다.")
        return 0
    print(f"'{args.query}' 검색 결과 {len(entries)}건\n")
    for e in entries:
        print(_brief(e))
        if e.get("summary"):
            print(f"       {e['summary']}")
    return 0


def cmd_export(args) -> int:
    entry = db.get_entry(args.id)
    if not entry:
        print(f"{args.id}번 뉴스를 찾을 수 없습니다.", file=sys.stderr)
        return 1
    text = R.to_kakao_text(entry) if args.kakao else R.to_markdown(entry)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"내보냈습니다: {args.out}")
    else:
        print(text)
    return 0


def cmd_terms(args) -> int:
    for t in db.list_terms(args.query):
        print(f"\n● {t['term']}  (등장 {t['count']}회)")
        print(f"  뜻   : {t['meaning']}")
        print(f"  쓰임 : {t['usage']}")
    return 0


def cmd_tickers(args) -> int:
    if args.name:
        entries = db.ticker_timeline(args.name)
        if not entries:
            print(f"'{args.name}' 관련 뉴스가 없습니다.")
            return 0
        print(f"'{args.name}' 관련 뉴스 {len(entries)}건\n")
        for e in entries:
            print(_brief(e))
            if e.get("summary"):
                print(f"       {e['summary']}")
        return 0
    rows = db.list_tickers(args.query)
    if not rows:
        print("아직 기록된 종목이 없습니다.")
        return 0
    for r in rows:
        code = f" ({r['code']})" if r["code"] else ""
        print(f"{r['name']}{code}  — {r['count']}건, 최근 {r['last_date']}")
    return 0


def cmd_delete(args) -> int:
    if db.delete_entry(args.id):
        print(f"{args.id}번 뉴스를 삭제했습니다.")
        return 0
    print(f"{args.id}번 뉴스를 찾을 수 없습니다.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stock_manager", description="주식 뉴스 해설 아카이브")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Supabase 연결·로그인 확인").set_defaults(func=cmd_init)
    sub.add_parser("whoami", help="현재 로그인 계정과 권한 확인").set_defaults(func=cmd_whoami)

    a = sub.add_parser("add", help="뉴스 원문을 해설 대기 상태로 저장")
    a.add_argument("--title", required=True)
    a.add_argument("--url", default="")
    a.add_argument("--date", default="")
    a.add_argument("--slot", default="아침", choices=R.SLOTS)
    a.add_argument("--text", default="")
    a.add_argument("--text-file", default="")
    a.set_defaults(func=cmd_add)

    sub.add_parser("pending", help="해설 대기 목록을 JSON으로 출력").set_defaults(func=cmd_pending)

    s = sub.add_parser("save", help="완성된 리포트 JSON을 검증 후 저장")
    s.add_argument("--json", required=True, help="리포트 JSON 파일 경로")
    s.add_argument("--entry-id", type=int, default=None, help="채워 넣을 pending 항목 id")
    s.set_defaults(func=cmd_save)

    l = sub.add_parser("list", help="날짜별 목록")
    l.add_argument("--date-from", default=None)
    l.add_argument("--date-to", default=None)
    l.add_argument("--tone", default=None, choices=R.TONES)
    l.add_argument("--status", default=None, choices=["pending", "done"])
    l.add_argument("--limit", type=int, default=200)
    l.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="리포트 전문 보기")
    sh.add_argument("id", type=int)
    sh.add_argument("--kakao", action="store_true", help="단톡방용 평문으로 출력")
    sh.set_defaults(func=cmd_show)

    se = sub.add_parser("search", help="키워드 검색")
    se.add_argument("query")
    se.add_argument("--date-from", default=None)
    se.add_argument("--date-to", default=None)
    se.add_argument("--tone", default=None, choices=R.TONES)
    se.add_argument("--limit", type=int, default=200)
    se.set_defaults(func=cmd_search)

    ex = sub.add_parser("export", help="마크다운으로 내보내기")
    ex.add_argument("id", type=int)
    ex.add_argument("--out", default="")
    ex.add_argument("--kakao", action="store_true")
    ex.set_defaults(func=cmd_export)

    t = sub.add_parser("terms", help="누적 용어 사전")
    t.add_argument("query", nargs="?", default=None)
    t.set_defaults(func=cmd_terms)

    tk = sub.add_parser("tickers", help="종목별 언급 집계 / 종목 타임라인")
    tk.add_argument("--name", default=None, help="이 종목이 언급된 뉴스를 시간순으로")
    tk.add_argument("query", nargs="?", default=None)
    tk.set_defaults(func=cmd_tickers)

    d = sub.add_parser("delete", help="뉴스 삭제")
    d.add_argument("id", type=int)
    d.set_defaults(func=cmd_delete)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except supa.SupabaseError as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
