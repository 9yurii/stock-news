"""Supabase(PostgREST + Auth) 클라이언트. 표준 라이브러리만 사용합니다.

로그인 정보는 프로젝트 폴더의 `.env` 파일에서 읽습니다 (git에 올라가지 않습니다).

    SUPABASE_EMAIL=iam9yuri@gmail.com
    SUPABASE_PASSWORD=...

읽기는 로그인 없이도 되지만, 쓰기는 허용 목록에 등록된 계정으로 로그인해야 합니다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# docs/config.js 와 같은 값입니다. 공개되어도 안전한 키입니다.
SUPABASE_URL = "https://uvuroizlboirzehiagwb.supabase.co"
SUPABASE_KEY = "sb_publishable_XB0LY9ZH-2gmYNnIRmJr7g_HNAiikqw"

TOKEN_CACHE = ROOT / ".auth_token.json"


class SupabaseError(RuntimeError):
    pass


def load_env() -> dict[str, str]:
    """.env 파일과 환경변수를 합쳐서 돌려줍니다."""
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip().strip('"').strip("'")
    for key in ("SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_EMAIL", "SUPABASE_PASSWORD"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def _base_url() -> str:
    return load_env().get("SUPABASE_URL", SUPABASE_URL).rstrip("/")


def _api_key() -> str:
    return load_env().get("SUPABASE_KEY", SUPABASE_KEY)


def _request(url: str, method: str = "GET", body=None, headers: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", _api_key())
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("message") or parsed.get("error_description") or detail
        except Exception:
            pass
        raise SupabaseError(f"[{e.code}] {detail}") from None
    except urllib.error.URLError as e:
        raise SupabaseError(f"Supabase에 연결하지 못했습니다: {e.reason}") from None


# ─────────────────────────── 로그인 ───────────────────────────

def _cached_token() -> dict | None:
    if TOKEN_CACHE.exists():
        try:
            return json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def _save_token(tok: dict) -> None:
    TOKEN_CACHE.write_text(json.dumps(tok, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(TOKEN_CACHE, 0o600)
    except OSError:
        pass


def _refresh(refresh_token: str) -> dict | None:
    try:
        return _request(
            f"{_base_url()}/auth/v1/token?grant_type=refresh_token",
            "POST",
            {"refresh_token": refresh_token},
        )
    except SupabaseError:
        return None


def sign_in() -> str:
    """access token을 돌려줍니다. 캐시된 토큰이 있으면 재사용합니다."""
    cached = _cached_token()
    if cached and cached.get("refresh_token"):
        fresh = _refresh(cached["refresh_token"])
        if fresh and fresh.get("access_token"):
            _save_token(fresh)
            return fresh["access_token"]

    env = load_env()
    email, password = env.get("SUPABASE_EMAIL"), env.get("SUPABASE_PASSWORD")
    if not email or not password:
        raise SupabaseError(
            "로그인 정보가 없습니다.\n"
            f"  {ROOT / '.env'} 파일에 아래 두 줄을 넣어주세요:\n"
            "    SUPABASE_EMAIL=본인이메일\n"
            "    SUPABASE_PASSWORD=비밀번호\n"
            "  (.env.example 파일을 복사해서 쓰면 됩니다)"
        )
    tok = _request(
        f"{_base_url()}/auth/v1/token?grant_type=password",
        "POST",
        {"email": email, "password": password},
    )
    if not tok or not tok.get("access_token"):
        raise SupabaseError("로그인에 실패했습니다. 이메일과 비밀번호를 확인해 주세요.")
    _save_token(tok)
    return tok["access_token"]


def whoami() -> dict:
    token = sign_in()
    return _request(f"{_base_url()}/auth/v1/user", headers={"Authorization": f"Bearer {token}"})


def can_write() -> bool:
    token = sign_in()
    return _request(
        f"{_base_url()}/rest/v1/rpc/can_write",
        "POST",
        {},
        {"Authorization": f"Bearer {token}"},
    ) is True


# ─────────────────────────── 데이터 ───────────────────────────

def select(table: str, params: dict[str, str] | None = None, auth: bool = False) -> list[dict]:
    qs = urllib.parse.urlencode(params or {}, safe="*.,()")
    url = f"{_base_url()}/rest/v1/{table}" + (f"?{qs}" if qs else "")
    headers = {"Authorization": f"Bearer {sign_in()}"} if auth else {}
    return _request(url, headers=headers) or []


def insert(table: str, rows: list[dict] | dict, returning: bool = True) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {sign_in()}",
        "Prefer": "return=representation" if returning else "return=minimal",
    }
    return _request(f"{_base_url()}/rest/v1/{table}", "POST", rows, headers) or []


def update(table: str, params: dict[str, str], patch: dict) -> list[dict]:
    qs = urllib.parse.urlencode(params, safe="*.,()")
    headers = {
        "Authorization": f"Bearer {sign_in()}",
        "Prefer": "return=representation",
    }
    return _request(f"{_base_url()}/rest/v1/{table}?{qs}", "PATCH", patch, headers) or []


def delete(table: str, params: dict[str, str]) -> list[dict]:
    qs = urllib.parse.urlencode(params, safe="*.,()")
    headers = {
        "Authorization": f"Bearer {sign_in()}",
        "Prefer": "return=representation",
    }
    return _request(f"{_base_url()}/rest/v1/{table}?{qs}", "DELETE", None, headers) or []
