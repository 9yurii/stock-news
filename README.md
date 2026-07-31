# 📈 주식 뉴스 해설 아카이브

하루 3번 들어오는 뉴스를 **왕초보용 7단계 해설**로 정리하고, 날짜별로 쌓아 나중에 찾아볼 수 있게 하는 프로그램입니다.

- **웹사이트**: GitHub Pages (HTML/CSS/JS, 정적)
- **데이터베이스**: Supabase (Postgres)
- **해설 작성**: Claude Code의 `/news` 명령
- 파이썬 외부 라이브러리 0개 — `pip install` 필요 없음

---

## 권한 구조

| | 누구나 | 허용된 계정 |
|---|---|---|
| 해설 읽기 | ✅ | ✅ |
| 뉴스 입력·수정·삭제 | ❌ | ✅ |

단톡방에 사이트 링크를 공유하면 상대방은 **로그인 없이 바로 읽을 수 있습니다.**
쓰기는 Supabase의 `allowed_writers` 목록에 등록된 이메일(현재 `iam9yuri@gmail.com`)로 로그인했을 때만 가능하며, 이는 데이터베이스 정책(RLS)으로 강제됩니다. 다른 사람이 회원가입해도 읽기만 됩니다.

---

## 최초 1회 준비

### 1. 웹사이트에서 계정 만들기

사이트 → **로그인** → 이메일·비밀번호 입력 → **가입하기** → 메일로 온 확인 링크 클릭.

### 2. `.env` 파일 만들기

`.env.example` 을 복사해 `.env` 로 이름을 바꾸고 위에서 만든 정보를 넣습니다.

```
SUPABASE_EMAIL=iam9yuri@gmail.com
SUPABASE_PASSWORD=비밀번호
SITE_URL=https://9yurii.github.io/stock-news
```

`.env` 는 git에 올라가지 않습니다.

### 3. 확인

```bash
python -m stock_manager.cli init
```
`로그인 계정: ... (쓰기 가능)` 이 나오면 준비 끝입니다.

---

## 매일 쓰는 법

### 방법 A — 웹에서 넣고, Claude Code로 해설

1. 사이트 → **뉴스 입력** → 날짜·시간대·제목·주소·본문 저장 (= "해설 대기")
2. Claude Code에서 `/news` 실행 → 대기 중인 뉴스를 순서대로 해설하고 저장
3. 사이트에서 바로 읽고, **단톡방용 복사** 버튼으로 공유

### 방법 B — Claude Code에 바로 붙여넣기

```
/news            ← 대기 중인 뉴스 전부 처리
/news 3          ← 3번 뉴스만 처리
/news <기사 본문 + URL 붙여넣기>   ← 웹 입력 없이 바로 해설
```

---

## 해설 구조

모든 해설은 아래 7단계를 그대로 따릅니다.

| | 섹션 | 내용 |
|---|---|---|
| ① | 30초 요약 | 중학생도 아는 한 문장 + 성격(호재/악재/중립/해석이 갈림) |
| ② | 팩트 정리 | 숫자와 사실만, 해석 금지 |
| ③ | 시장의 속마음 | 표면적 이유 vs 진짜 이유, 일상 비유 |
| ④ | 찬반 시각 | 낙관론 / 비관론 / 갈리는 핵심 |
| ⑤ | 체크리스트 | 오늘 밤 → 내일 → 이번 주 → 이번 달 |
| ⑥ | 상황별 관점 | 현금 / 보유 / 신규 (투자권유 아님) |
| ⑦ | 용어 복습 | 꼭 알아야 할 용어 3개 |

저장할 때 자동으로 검사합니다. 7개 섹션이 빠지거나, ⑥에 "사세요/파세요" 같은 권유 표현이 들어가거나, "판단과 책임은 본인의 몫" 문구가 없으면 **저장이 거부**되고 다시 쓰게 됩니다.

---

## 화면

| 탭 | 하는 일 |
|---|---|
| 홈 | 날짜별 뉴스 목록. 성격 뱃지로 한눈에 |
| 뉴스 입력 | 기사 붙여넣기 (로그인 필요) |
| 검색 | 키워드 + 날짜 범위 + 성격 (본문·용어·종목까지 검색) |
| 용어 사전 | 해설에 나온 용어가 자동으로 쌓임 |
| 종목 | 종목별로 뉴스가 모임 |

---

## 터미널에서 쓰기 (선택)

```bash
python -m stock_manager.cli list                    # 목록
python -m stock_manager.cli show 3                  # 3번 리포트 보기
python -m stock_manager.cli show 3 --kakao          # 단톡방용 평문
python -m stock_manager.cli search 반도체            # 검색
python -m stock_manager.cli terms                   # 용어 사전
python -m stock_manager.cli tickers                 # 종목 집계
python -m stock_manager.cli tickers --name 삼성전자   # 종목 타임라인
python -m stock_manager.cli export 3 --out 리포트.md
python -m stock_manager.cli whoami                  # 내 권한 확인
```

---

## 개발

```bash
python -m stock_manager.web     # docs/ 로컬 미리보기 (미리보기_실행.bat 더블클릭도 가능)
```

`docs/` 폴더가 GitHub Pages로 그대로 배포됩니다. `main` 브랜치에 push하면 몇 분 안에 반영됩니다.

| 파일 | 역할 |
|---|---|
| `docs/index.html` | 페이지 뼈대 |
| `docs/style.css` | 스타일 (라이트/다크 모드 자동) |
| `docs/app.js` | 화면·라우팅·Supabase 연동 |
| `docs/config.js` | Supabase 주소와 공개 키 |
| `stock_manager/report.py` | 7단계 형식 정의와 검증 규칙 |
| `stock_manager/db.py` | Supabase 데이터 접근 |
| `.claude/commands/news.md` | `/news` 명령 (해설 작성 지침) |

---

## 앞으로

종목별 뉴스가 쌓이면(`종목` 탭), 그 기록을 바탕으로 종목 단위 분석 기능을 얹을 수 있도록 `tickers` 테이블을 미리 만들어 두었습니다.

다만 매수·매도 적정가는 누구도 정확히 맞출 수 없는 영역입니다. **정답을 내려주는 도구**가 아니라 **근거와 시나리오를 정리해 판단을 돕는 도구** 방향으로 확장하는 것을 권합니다.
