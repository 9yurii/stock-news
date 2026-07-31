import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm";
import { SUPABASE_URL, SUPABASE_KEY } from "./config.js";

const sb = createClient(SUPABASE_URL, SUPABASE_KEY);
const app = document.getElementById("app");

const SLOTS = ["아침", "점심", "저녁"];
const TONES = ["호재", "악재", "중립", "해석이 갈림"];
const TONE_CLASS = { "호재": "up", "악재": "down", "중립": "flat", "해석이 갈림": "split" };

let session = null;
let canWrite = false;
let pageCleanup = null;   // 화면을 떠날 때 정리할 것 (붙여넣기 이벤트 등)

/* ───────────────────────── 유틸 ───────────────────────── */

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const today = () => new Date().toLocaleDateString("sv-SE"); // YYYY-MM-DD (현지 시각)

function show(html) { app.innerHTML = html; window.scrollTo(0, 0); }

function loading() { show('<div class="empty">불러오는 중…</div>'); }

function fail(err) {
  console.error(err);
  show(`<div class="note warn">불러오지 못했습니다: ${esc(err?.message || err)}</div>`);
}

/* ─────────────────── 초소형 마크다운 렌더러 ─────────────────── */

const inline = (t) =>
  esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(https?:\/\/[^\s<>"]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');

const isTableSep = (l) => /^\|[\s:|-]+\|$/.test(l.trim());
const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function renderBody(text) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const s = line.trim();

    if (!s) { i++; continue; }

    // 표
    if (s.startsWith("|") && s.endsWith("|")) {
      const block = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) block.push(lines[i++]);
      const hasHeader = block.length > 1 && isTableSep(block[1]);
      const rows = block.filter((b) => !isTableSep(b));
      out.push('<div class="tablewrap"><table>');
      rows.forEach((row, ri) => {
        const tag = hasHeader && ri === 0 ? "th" : "td";
        out.push("<tr>" + cells(row).map((c) => `<${tag}>${inline(c)}</${tag}>`).join("") + "</tr>");
      });
      out.push("</table></div>");
      continue;
    }

    // 불릿 (중첩 1단계)
    if (/^\s*[-*·]\s+/.test(line)) {
      out.push("<ul>");
      let depth = 0;
      while (i < lines.length && /^\s*[-*·]\s+/.test(lines[i])) {
        const cur = lines[i];
        const want = cur.length - cur.trimStart().length >= 2 ? 1 : 0;
        while (want > depth) { out.push("<ul>"); depth++; }
        while (want < depth) { out.push("</ul>"); depth--; }
        out.push("<li>" + inline(cur.replace(/^\s*[-*·]\s+/, "")) + "</li>");
        i++;
      }
      while (depth-- > 0) out.push("</ul>");
      out.push("</ul>");
      continue;
    }

    // 문단
    const para = [];
    while (i < lines.length && lines[i].trim() &&
           !/^\s*[-*·]\s+/.test(lines[i]) && !lines[i].trim().startsWith("|")) {
      para.push(lines[i].trim());
      i++;
    }
    out.push("<p>" + para.map(inline).join("<br>") + "</p>");
  }
  return out.join("\n");
}

/* ───────────────────── 공통 조각 ───────────────────── */

function toneBadge(e) {
  if (e.status === "pending") return '<span class="badge wait">해설 대기</span>';
  return `<span class="badge ${TONE_CLASS[e.tone] || "flat"}">${esc(e.tone || "")}</span>`;
}

function entryCard(e, showDate = false) {
  const d = showDate ? `<span class="badge">${esc(e.date)}</span>` : "";
  return `<div class="card">
  <div class="meta">${d}<span class="badge">${esc(e.slot)}</span>${toneBadge(e)}</div>
  <a class="t" href="#/entry/${e.id}">${esc(e.title)}</a>
  <div class="s">${esc(e.summary || "아직 해설이 작성되지 않았습니다.")}</div>
</div>`;
}

function groupedList(entries) {
  if (!entries.length) {
    return '<div class="empty">아직 저장된 뉴스가 없습니다.</div>';
  }
  const out = [];
  let cur = null;
  for (const e of entries) {
    if (e.date !== cur) {
      if (cur !== null) out.push("</div>");
      cur = e.date;
      out.push(`<div class="daygroup"><div class="dayhead">${esc(cur)}</div>`);
    }
    out.push(entryCard(e));
  }
  out.push("</div>");
  return out.join("");
}

function imageUrl(path) {
  return `${SUPABASE_URL}/storage/v1/object/public/news-images/${
    path.split("/").map(encodeURIComponent).join("/")}`;
}

function photoBlock(shots) {
  if (!shots || !shots.length) return "";
  return `<section class="sec"><h2>📷 함께 온 사진</h2><div class="shots">` +
    shots.map((s) => {
      const u = imageUrl(s.path);
      return `<a href="${u}" target="_blank" rel="noopener">
        <img src="${u}" alt="${esc(s.original_name || "뉴스 사진")}" loading="lazy"></a>`;
    }).join("") + `</div></section>`;
}

function commentBlock(rows) {
  if (!rows || !rows.length) return "";
  return `<section class="sec"><h2>💬 단톡방에서 오간 이야기</h2>
<div class="sub" style="margin:0 0 10px">기사 본문이 아니라, 뉴스를 나눌 때 함께 오간 대화입니다.</div>
<div class="talk">` +
    rows.map((c) => `<div class="msg">
      <div class="mh"><b>${esc(c.sender || "―")}</b> <span>${esc(c.at || "")}</span></div>
      <div class="mb">${esc(c.text).replace(/\n/g, "<br>")}</div></div>`).join("") +
    `</div></section>`;
}

function kakaoText(entry) {
  const lines = [`[${entry.date} ${entry.slot}] ${entry.title}`, `성격: ${entry.tone}`, ""];
  for (const s of entry.sections) { lines.push(s.title, s.body, ""); }
  if (entry.url) lines.push(`원문: ${entry.url}`);
  return lines.join("\n").trimEnd() + "\n";
}

/* ───────────────────────── 화면 ───────────────────────── */

async function viewHome() {
  loading();
  const { data, error } = await sb
    .from("entries")
    .select("id,date,slot,title,status,tone,summary")
    .order("date", { ascending: false })
    .order("id", { ascending: false })
    .limit(200);
  if (error) return fail(error);

  const done = data.filter((e) => e.status === "done").length;
  const pending = data.length - done;
  const note = pending
    ? `<div class="note">해설 대기 중인 뉴스가 ${pending}건 있습니다.
       Claude Code에서 <b>/news</b> 를 실행하면 순서대로 해설이 작성됩니다.</div>`
    : "";

  show(`<h1>뉴스 목록</h1>
<div class="sub">최근 저장된 순서입니다.</div>
<div class="stats"><span>해설 완료 ${done}건</span><span>해설 대기 ${pending}건</span></div>
${note}${groupedList(data)}`);
}

async function viewEntry(id) {
  loading();
  const { data: entry, error } = await sb
    .from("entries").select("*").eq("id", id).maybeSingle();
  if (error) return fail(error);
  if (!entry) return show('<div class="empty">뉴스를 찾을 수 없습니다.<br><a href="#/">홈으로</a></div>');

  const head = `<div class="meta"><span class="badge">${esc(entry.date)}</span>
    <span class="badge">${esc(entry.slot)}</span>${toneBadge(entry)}</div>`;
  const src = entry.url
    ? `<div class="sub"><a href="${esc(entry.url)}" target="_blank" rel="noopener">원문 기사 열기 ↗</a></div>`
    : "";

  if (entry.status === "pending") {
    const [{ data: shots }, { data: talk }] = await Promise.all([
      sb.from("attachments").select("id,path,original_name").eq("entry_id", id).order("id"),
      sb.from("comments").select("sender,at,text").eq("entry_id", id).order("idx"),
    ]);
    return show(`${head}<h1>${esc(entry.title)}</h1>${src}
<div class="note">아직 해설이 작성되지 않았습니다.
Claude Code에서 <b>/news ${entry.id}</b> 를 실행하세요.</div>
${photoBlock(shots)}
${entry.raw_text ? `<div class="raw">${esc(entry.raw_text)}</div>` : ""}
${commentBlock(talk)}`);
  }

  const [{ data: sections }, { data: tickers }, { data: shots }, { data: talk }] =
    await Promise.all([
      sb.from("sections").select("idx,title,body").eq("entry_id", id).order("idx"),
      sb.from("tickers").select("name,code").eq("entry_id", id).order("id"),
      sb.from("attachments").select("id,path,original_name").eq("entry_id", id).order("id"),
      sb.from("comments").select("sender,at,text").eq("entry_id", id).order("idx"),
    ]);
  entry.sections = sections || [];
  const photos = photoBlock(shots);
  const talkHtml = commentBlock(talk);

  const tick = (tickers || []).length
    ? `<div class="meta" style="margin:14px 0">` +
      tickers.map((t) =>
        `<a class="badge" href="#/tickers?name=${encodeURIComponent(t.name)}">${esc(t.name)}${
          t.code ? " " + esc(t.code) : ""}</a>`).join(" ") + `</div>`
    : "";

  const secs = entry.sections
    .map((s) => `<section class="sec"><h2>${esc(s.title)}</h2>${renderBody(s.body)}</section>`)
    .join("");

  const actions = `<div class="actions">
  <button id="copybtn" class="btn">단톡방용 복사</button>
</div>`;

  show(`${head}<h1>${esc(entry.title)}</h1>${src}${tick}${actions}${photos}${secs}${talkHtml}${actions}`);

  const text = kakaoText(entry);
  document.querySelectorAll("#copybtn").forEach((b) => {
    b.onclick = async () => {
      await navigator.clipboard.writeText(text);
      const old = b.textContent;
      b.textContent = "복사했습니다";
      setTimeout(() => (b.textContent = old), 1600);
    };
  });
}

async function viewNew() {
  if (!canWrite) {
    return show(`<div class="note warn">뉴스 입력은 허용된 계정으로 로그인해야 합니다.</div>
<div class="empty"><a href="#/login">로그인하러 가기</a></div>`);
  }
  show(`<h1>뉴스 입력</h1>
<div class="sub">카톡 화면을 캡쳐해서 붙여넣기만 하면 됩니다.
Claude Code에서 <b>/news</b> 를 실행하면 사진을 읽어 해설을 씁니다.</div>

<form class="box" id="f">
  <label>뉴스 캡쳐 사진</label>
  <div id="drop" class="drop" tabindex="0">
    <div class="dropmsg">
      <b>여기를 눌러 사진을 고르거나</b><br>
      캡쳐한 그림을 <b>Ctrl+V</b> 로 붙여넣으세요<br>
      <span>사진을 끌어다 놓아도 됩니다 · 여러 장 가능</span>
    </div>
    <input type="file" id="file" accept="image/*" multiple hidden>
  </div>
  <div id="preview" class="shots"></div>

  <div class="row">
    <div><label>날짜 <span class="opt">(기사 날짜)</span></label>
      <input type="date" name="date" value="${today()}" required></div>
    <div><label>시간대</label><select name="slot">
      ${SLOTS.map((s) => `<option>${s}</option>`).join("")}</select></div>
  </div>

  <label>제목 <span class="opt">(비워두면 자동)</span></label>
  <input name="title" placeholder="예) 삼성전자 3분기 실적 발표">

  <label>뉴스 주소 <span class="opt">(선택)</span></label>
  <input name="url" placeholder="https://..." type="url">

  <label>글로 온 내용 <span class="opt">(선택 · 사진만 있으면 비워두세요)</span></label>
  <textarea name="raw_text" placeholder="카톡에 글로 온 내용이 있으면 붙여넣으세요."></textarea>

  <button type="submit">저장하기</button>
  <div id="msg" class="sub" style="margin-top:12px"></div>
</form>`);

  const form = document.getElementById("f");
  const drop = document.getElementById("drop");
  const fileInput = document.getElementById("file");
  const preview = document.getElementById("preview");
  const msg = document.getElementById("msg");
  let picked = [];

  function redraw() {
    preview.innerHTML = picked.map((f, i) =>
      `<div class="shot"><img src="${URL.createObjectURL(f)}" alt="">
       <button type="button" class="x" data-i="${i}" title="빼기">×</button></div>`).join("");
    preview.querySelectorAll("button.x").forEach((b) => {
      b.onclick = () => { picked.splice(Number(b.dataset.i), 1); redraw(); };
    });
    drop.classList.toggle("has", picked.length > 0);
  }

  function addFiles(list) {
    for (const f of list) if (f && f.type.startsWith("image/")) picked.push(f);
    redraw();
  }

  drop.onclick = () => fileInput.click();
  fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ""; };

  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    addFiles(e.dataTransfer.files);
  };

  // 화면 어디서든 Ctrl+V 로 캡쳐 붙여넣기
  const onPaste = (e) => {
    const files = [...(e.clipboardData?.items || [])]
      .filter((it) => it.kind === "file" && it.type.startsWith("image/"))
      .map((it) => it.getAsFile());
    if (files.length) { e.preventDefault(); addFiles(files); }
  };
  document.addEventListener("paste", onPaste);
  pageCleanup = () => document.removeEventListener("paste", onPaste);

  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const body = (f.get("raw_text") || "").trim();

    if (!picked.length && !body) {
      msg.innerHTML = '<span class="err">사진을 넣거나 글 내용을 적어주세요.</span>';
      return;
    }

    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    btn.textContent = "저장 중…";

    const date = f.get("date");
    const title = (f.get("title") || "").trim() ||
      (body ? body.split("\n")[0].slice(0, 60) : `뉴스 캡쳐 (${date})`);

    const { data, error } = await sb.from("entries").insert({
      date, slot: f.get("slot"), title,
      url: (f.get("url") || "").trim(),
      raw_text: body, status: "pending",
    }).select("id").single();

    if (error) {
      msg.innerHTML = `<span class="err">저장 실패: ${esc(error.message)}</span>`;
      btn.disabled = false;
      btn.textContent = "저장하기";
      return;
    }

    let failed = 0;
    for (let i = 0; i < picked.length; i++) {
      btn.textContent = `사진 올리는 중… (${i + 1}/${picked.length})`;
      try {
        const file = picked[i];
        const digest = await sha1(file);
        const ext = (file.name.match(/\.[a-z0-9]+$/i) || [".png"])[0].toLowerCase();
        const path = `${date}/${data.id}-${digest.slice(0, 8)}${ext}`;
        const up = await sb.storage.from("news-images")
          .upload(path, file, { upsert: true, contentType: file.type });
        if (up.error) throw up.error;
        const ins = await sb.from("attachments").insert({
          entry_id: data.id, path, original_name: file.name || "capture.png",
          source_key: "img-" + digest.slice(0, 20),
        });
        if (ins.error && !String(ins.error.message).includes("duplicate")) throw ins.error;
      } catch (e) {
        console.error(e);
        failed++;
      }
    }

    if (failed) {
      msg.innerHTML = `<span class="err">사진 ${failed}장을 올리지 못했습니다. 나머지는 저장됐습니다.</span>`;
      setTimeout(() => (location.hash = `#/entry/${data.id}`), 1800);
      return;
    }
    location.hash = `#/entry/${data.id}`;
  };
}

async function sha1(file) {
  const buf = await file.arrayBuffer();
  const hash = await crypto.subtle.digest("SHA-1", buf);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function viewSearch(params) {
  const q = (params.get("q") || "").trim();
  const from = params.get("from") || "";
  const to = params.get("to") || "";
  const tone = params.get("tone") || "";

  const opts = ['<option value="">전체</option>',
    ...TONES.map((t) => `<option${t === tone ? " selected" : ""}>${t}</option>`)].join("");

  show(`<h1>검색</h1>
<div class="sub">제목·요약·본문·용어·종목을 함께 찾습니다.</div>
<form class="box" id="sf">
  <label>검색어</label>
  <input name="q" value="${esc(q)}" placeholder="예) 반도체, 금리, 삼성전자">
  <div class="row">
    <div><label>시작 날짜</label><input type="date" name="from" value="${esc(from)}"></div>
    <div><label>끝 날짜</label><input type="date" name="to" value="${esc(to)}"></div>
    <div><label>성격</label><select name="tone">${opts}</select></div>
  </div>
  <button type="submit">검색</button>
</form>
<div id="res"></div>`);

  document.getElementById("sf").onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    const p = new URLSearchParams();
    for (const k of ["q", "from", "to", "tone"]) {
      const v = (f.get(k) || "").trim();
      if (v) p.set(k, v);
    }
    location.hash = `#/search?${p.toString()}`;
  };

  if (!q && !from && !to && !tone) return;

  const res = document.getElementById("res");
  res.innerHTML = '<div class="empty">찾는 중…</div>';

  // 제목/요약 + 섹션 본문 + 용어 + 종목을 각각 훑어 id를 모읍니다.
  const like = `%${q}%`;
  const ids = new Set();
  if (q) {
    const [sec, trm, tkr] = await Promise.all([
      sb.from("sections").select("entry_id").ilike("body", like).limit(500),
      sb.from("terms").select("entry_id").or(`term.ilike.${like},meaning.ilike.${like}`).limit(500),
      sb.from("tickers").select("entry_id").ilike("name", like).limit(500),
    ]);
    for (const r of [...(sec.data || []), ...(trm.data || []), ...(tkr.data || [])]) {
      ids.add(r.entry_id);
    }
  }

  let query = sb.from("entries").select("id,date,slot,title,status,tone,summary");
  if (q) {
    const idPart = ids.size ? `,id.in.(${[...ids].join(",")})` : "";
    query = query.or(`title.ilike.${like},summary.ilike.${like},raw_text.ilike.${like}${idPart}`);
  }
  if (from) query = query.gte("date", from);
  if (to) query = query.lte("date", to);
  if (tone) query = query.eq("tone", tone);

  const { data, error } = await query
    .order("date", { ascending: false }).order("id", { ascending: false }).limit(200);

  if (error) {
    res.innerHTML = `<div class="note warn">검색 실패: ${esc(error.message)}</div>`;
    return;
  }
  res.innerHTML = data.length
    ? `<div class="sub" style="margin-top:24px">검색 결과 ${data.length}건</div>` +
      data.map((e) => entryCard(e, true)).join("")
    : '<div class="empty">검색 결과가 없습니다.</div>';
}

async function viewTerms(params) {
  const q = (params.get("q") || "").trim();
  loading();
  let query = sb.from("terms")
    .select("term,meaning,usage,entry_id,entries(date,title)")
    .order("term");
  if (q) query = query.or(`term.ilike.%${q}%,meaning.ilike.%${q}%`);
  const { data, error } = await query.limit(1000);
  if (error) return fail(error);

  const grouped = new Map();
  for (const r of data) {
    if (!grouped.has(r.term)) {
      grouped.set(r.term, { term: r.term, meaning: r.meaning, usage: r.usage, seen: [] });
    }
    grouped.get(r.term).seen.push({ id: r.entry_id, date: r.entries?.date || "" });
  }
  const terms = [...grouped.values()];

  const cards = terms.length
    ? terms.map((t) => `<div class="term">
        <div class="n">${esc(t.term)} <span class="badge">${t.seen.length}회</span></div>
        <div class="m">${esc(t.meaning)}</div>
        <div class="u">이 뉴스에서: ${esc(t.usage)}</div>
        <div class="u" style="margin-top:6px">${
          t.seen.slice(0, 5).map((s) => `<a href="#/entry/${s.id}">${esc(s.date)}</a>`).join(" · ")
        }</div></div>`).join("")
    : '<div class="empty">아직 쌓인 용어가 없습니다.</div>';

  show(`<h1>용어 사전</h1>
<div class="sub">해설에 나온 용어가 자동으로 쌓입니다. 총 ${terms.length}개.</div>
<form class="box" id="tf" style="margin-bottom:20px">
  <label>용어 찾기</label>
  <input name="q" value="${esc(q)}" placeholder="예) 어닝쇼크, 변동성">
  <button type="submit">찾기</button>
</form>${cards}`);

  document.getElementById("tf").onsubmit = (ev) => {
    ev.preventDefault();
    const v = new FormData(ev.target).get("q").trim();
    location.hash = v ? `#/terms?q=${encodeURIComponent(v)}` : "#/terms";
  };
}

async function viewTickers(params) {
  const name = params.get("name");
  loading();

  if (name) {
    const { data: rows, error } = await sb
      .from("tickers").select("entry_id").eq("name", name);
    if (error) return fail(error);
    const ids = [...new Set(rows.map((r) => r.entry_id))];
    let entries = [];
    if (ids.length) {
      const { data } = await sb.from("entries")
        .select("id,date,slot,title,status,tone,summary")
        .in("id", ids)
        .order("date", { ascending: false }).order("id", { ascending: false });
      entries = data || [];
    }
    return show(`<h1>${esc(name)}</h1>
<div class="sub">이 종목이 언급된 뉴스 ${entries.length}건 (최신순)</div>
<div class="sub"><a href="#/tickers">← 전체 종목 목록</a></div>
${entries.length ? entries.map((e) => entryCard(e, true)).join("")
               : '<div class="empty">관련 뉴스가 없습니다.</div>'}`);
  }

  const { data, error } = await sb
    .from("tickers").select("name,code,entries(date)").limit(2000);
  if (error) return fail(error);

  const agg = new Map();
  for (const r of data) {
    const g = agg.get(r.name) || { name: r.name, code: r.code, count: 0, last: "" };
    g.count++;
    if (r.code && !g.code) g.code = r.code;
    const d = r.entries?.date || "";
    if (d > g.last) g.last = d;
    agg.set(r.name, g);
  }
  const rows = [...agg.values()].sort((a, b) => b.count - a.count || b.last.localeCompare(a.last));

  show(`<h1>종목</h1>
<div class="sub">해설에 언급된 종목별로 뉴스가 모입니다.</div>
<div class="note">종목별 기록이 쌓이면, 이 데이터를 바탕으로 종목 단위 분석 기능을 붙일 수 있습니다.</div>
${rows.length ? rows.map((r) => `<div class="card">
  <a class="t" href="#/tickers?name=${encodeURIComponent(r.name)}">${esc(r.name)}${
    r.code ? ` (${esc(r.code)})` : ""}</a>
  <div class="s">뉴스 ${r.count}건 · 최근 ${esc(r.last)}</div></div>`).join("")
              : '<div class="empty">아직 기록된 종목이 없습니다.<br>해설이 쌓이면 자동으로 모입니다.</div>'}`);
}

function viewLogin() {
  if (session) {
    show(`<h1>계정</h1>
<div class="sub">${esc(session.user.email)} 으로 로그인되어 있습니다.</div>
<div class="note">${canWrite
  ? "이 계정은 뉴스 입력·수정 권한이 있습니다."
  : "이 계정은 <b>읽기 전용</b>입니다. 쓰기 권한은 허용 목록에 등록된 이메일에만 부여됩니다."}</div>
<button id="out" class="btn ghost">로그아웃</button>`);
    document.getElementById("out").onclick = async () => {
      await sb.auth.signOut();
      location.hash = "#/";
    };
    return;
  }

  show(`<h1>로그인</h1>
<div class="sub">읽기는 로그인 없이 가능합니다. 뉴스 입력에만 로그인이 필요합니다.</div>
<form class="box" id="lf">
  <label>이메일</label><input type="email" name="email" required autocomplete="username">
  <label>비밀번호</label>
  <input type="password" name="password" required autocomplete="current-password" minlength="6">
  <button type="submit">로그인</button>
  <button type="button" id="signup" class="btn ghost">처음이신가요? 가입하기</button>
  <div id="msg" class="sub" style="margin-top:12px"></div>
</form>`);

  const form = document.getElementById("lf");
  const msg = document.getElementById("msg");

  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const f = new FormData(form);
    const { error } = await sb.auth.signInWithPassword({
      email: f.get("email").trim(), password: f.get("password"),
    });
    if (error) {
      msg.innerHTML = `<span style="color:#b91c1c">로그인 실패: ${esc(error.message)}</span>`;
      return;
    }
    location.hash = "#/";
  };

  document.getElementById("signup").onclick = async () => {
    const f = new FormData(form);
    const email = (f.get("email") || "").trim();
    const password = f.get("password") || "";
    if (!email || password.length < 6) {
      msg.textContent = "이메일과 6자 이상 비밀번호를 입력한 뒤 눌러주세요.";
      return;
    }
    const { error } = await sb.auth.signUp({ email, password });
    msg.innerHTML = error
      ? `<span style="color:#b91c1c">가입 실패: ${esc(error.message)}</span>`
      : "가입 확인 메일을 보냈습니다. 메일의 링크를 누른 뒤 로그인해 주세요.";
  };
}

/* ───────────────────────── 라우터 ───────────────────────── */

const ROUTES = [
  [/^\/$/,               () => viewHome()],
  [/^\/new$/,            () => viewNew()],
  [/^\/entry\/(\d+)$/,   (m) => viewEntry(m[1])],
  [/^\/search$/,         (m, p) => viewSearch(p)],
  [/^\/terms$/,          (m, p) => viewTerms(p)],
  [/^\/tickers$/,        (m, p) => viewTickers(p)],
  [/^\/login$/,          () => viewLogin()],
];

async function route() {
  if (pageCleanup) { pageCleanup(); pageCleanup = null; }
  const raw = location.hash.replace(/^#/, "") || "/";
  const [pathRaw, queryRaw = ""] = raw.split("?");
  const path = pathRaw.replace(/\/+$/, "") || "/";
  const params = new URLSearchParams(queryRaw);

  document.querySelectorAll("nav a.tab").forEach((a) =>
    a.classList.toggle("on", a.dataset.tab === path));

  for (const [re, handler] of ROUTES) {
    const m = path.match(re);
    if (m) {
      try { await handler(m, params); } catch (e) { fail(e); }
      return;
    }
  }
  show('<div class="empty">페이지를 찾을 수 없습니다.<br><a href="#/">홈으로</a></div>');
}

/* ───────────────────────── 세션 ───────────────────────── */

async function refreshAuthUI() {
  const who = document.getElementById("who");
  const loginlink = document.getElementById("loginlink");
  const newTab = document.querySelector('nav a[data-writer]');

  if (session) {
    const { data } = await sb.rpc("can_write");
    canWrite = data === true;
    who.textContent = session.user.email + (canWrite ? "" : " (읽기 전용)");
    loginlink.textContent = "계정";
  } else {
    canWrite = false;
    who.textContent = "";
    loginlink.textContent = "로그인";
  }
  newTab.hidden = !canWrite;
}

sb.auth.onAuthStateChange(async (_event, s) => {
  session = s;
  await refreshAuthUI();
  route();
});

window.addEventListener("hashchange", route);

(async () => {
  const { data } = await sb.auth.getSession();
  session = data.session;
  await refreshAuthUI();
  route();
})();
