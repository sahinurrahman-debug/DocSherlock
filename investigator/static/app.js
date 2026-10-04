"use strict";
/* Document Investigator - single-page UI (no build step, no innerHTML with user/document text). */
const $ = (s, r = document) => r.querySelector(s);
const state = { docs: [], history: [], results: new Map(), status: null, busy: false };

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const store = {
  get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 3200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); msg = j.detail || msg; } catch { /* not json */ }
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return res;
}
const json = async (path, opts) => (await api(path, opts)).json();
const post = (path, body) => json(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/* ---------------------------------------------------------------- status pills */
async function refreshStatus() {
  try { state.status = await json("/api/status"); } catch { return; }
  const s = state.status;
  const pills = $("#pills"); pills.replaceChildren();
  const add = (text, cls, title) => pills.append(h("span", { class: "pill " + (cls || ""), title }, text));
  add(s.llm.available ? `Claude · ${s.llm.model}` : "Offline engine", s.llm.available ? "on" : "", s.llm.available ? "LLM synthesis with verified quotes" : "Deterministic extractive answers (set ANTHROPIC_API_KEY for Claude)");
  add(s.ocr.available ? "OCR on" : "OCR off", s.ocr.available ? "on" : "wait", s.ocr.reason || "RapidOCR (offline)");
  add(s.dense.active ? "Semantic search" : s.dense.loading ? "Embeddings loading…" : s.dense.enabled ? "Keyword search" : "Keyword search",
      s.dense.active ? "on" : s.dense.loading ? "wait" : "", s.dense.model || "BM25 + char n-grams");
  $("#badge-conflicts").textContent = s.conflicts;
  $("#badge-conflicts").classList.toggle("hot", s.conflicts > 0);
  if (s.dense.loading && !refreshStatus._poll) refreshStatus._poll = setInterval(async () => {
    await refreshStatus(); if (!state.status.dense.loading) { clearInterval(refreshStatus._poll); refreshStatus._poll = null; }
  }, 3000);
}

/* ---------------------------------------------------------------- documents */
async function refreshDocs() {
  const d = await json("/api/documents");
  state.docs = d.documents; renderDocs(); refreshStatus();
}
function renderDocs() {
  const ul = $("#doclist"); ul.replaceChildren();
  $("#doc-empty").style.display = state.docs.length ? "none" : "";
  for (const d of state.docs) {
    const meta = h("div", { class: "doc-meta" },
      h("span", { class: "tag" }, `${d.n_pages} ${d.paged ? (d.n_pages === 1 ? "page" : "pages") : "section"}`),
      h("span", { class: "tag" }, `${d.n_chunks} passages`),
      d.ocr_used ? h("span", { class: "tag ocr", title: "Text recovered with OCR" }, `OCR ${d.ocr_conf != null ? Math.round(d.ocr_conf * 100) + "%" : ""}`) : null,
      h("span", { class: "tag date", title: (d.doc_date_source ? `Detected: ${d.doc_date_source}. ` : "") + "Click to set the document date (used to explain conflicts)",
        onclick: (e) => { e.stopPropagation(); editDate(d); } }, d.doc_date ? `dated ${d.doc_date}` : "set date"));
    const li = h("li", { class: "doc", onclick: () => openViewer({ doc_id: d.id, page: 1, title: d.name }) },
      h("div", { class: "doc-top" },
        h("span", { class: "ext" }, d.ext.replace(".", "")),
        h("span", { class: "doc-name" }, d.name),
        h("button", { class: "doc-del", title: "Remove", "aria-label": "Remove " + d.name, onclick: (e) => { e.stopPropagation(); removeDoc(d); } }, "×")),
      meta,
      ...(d.warnings || []).slice(0, 2).map((w) => h("div", { class: "doc-warn" }, "⚠ " + w)),
      d.status === "empty" ? h("div", { class: "doc-warn" }, "⚠ No text extracted - this document cannot be searched.") : null);
    ul.append(li);
  }
}
async function editDate(d) {
  const v = prompt(`Date of "${d.name}" (YYYY, YYYY-MM or YYYY-MM-DD). Leave empty to clear.`, d.doc_date || "");
  if (v === null) return;
  try {
    await json(`/api/documents/${d.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ doc_date: v.trim() || null }) });
    await refreshDocs(); if ($("#pane-conflicts").classList.contains("active")) loadConflicts();
  } catch (e) { toast(e.message); }
}
async function removeDoc(d) {
  if (!confirm(`Remove "${d.name}" from the investigation?`)) return;
  try { await json(`/api/documents/${d.id}`, { method: "DELETE" }); await refreshDocs(); loadConflicts(); } catch (e) { toast(e.message); }
}
async function upload(files) {
  if (!files.length) return;
  const status = $("#upload-status"); status.replaceChildren();
  for (const f of files) {
    const line = h("div", {}, `Reading ${f.name}…`); status.append(line);
    const fd = new FormData(); fd.append("files", f);
    try {
      const r = await json("/api/documents", { method: "POST", body: fd });
      const res = r.results[0];
      if (!res.ok) { line.className = "err"; line.textContent = `✕ ${f.name}: ${res.error}`; }
      else if (res.duplicate) { line.textContent = `= ${f.name}: ${res.message}`; }
      else { line.className = "ok"; line.textContent = `✓ ${f.name}`; }
      state.docs = r.documents; renderDocs();
    } catch (e) { line.className = "err"; line.textContent = `✕ ${f.name}: ${e.message}`; }
  }
  refreshStatus(); loadConflicts();
  setTimeout(() => { if (!status.querySelector(".err")) status.replaceChildren(); }, 6000);
}

/* ---------------------------------------------------------------- rendering helpers */
function inline(text, citeFn) {
  const out = []; const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[S\d+\])/g; let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(h("strong", {}, t.slice(2, -2)));
    else if (t.startsWith("[S")) out.push(citeFn ? citeFn(t.slice(1, -1)) : t);
    else out.push(h("em", {}, t.slice(1, -1)));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
function richText(text, citeFn) {
  const box = h("div", { class: "a-text" }); let ul = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) { ul = null; continue; }
    if (/^\s*-\s+/.test(line)) { if (!ul) { ul = h("ul"); box.append(ul); } ul.append(h("li", {}, inline(line.replace(/^\s*-\s+/, ""), citeFn))); }
    else { ul = null; box.append(h("p", {}, inline(line, citeFn))); }
  }
  return box;
}
const STATUS = {
  answered: ["✓", "Answered from the documents"],
  partial: ["◐", "Partial answer - check the notes"],
  conflict: ["⚠", "Sources conflict"],
  insufficient: ["?", "Not found in the documents"],
};
function loc(c) { return [c.doc_name, c.page ? `p.${c.page}` : null, c.section ? `§ ${c.section}` : null].filter(Boolean).join(" · "); }

function sourceLink(s, label) {
  return h("span", { class: "who", onclick: () => openViewer({ doc_id: s.doc_id, page: s.page || 1, start: s.start, end: s.end, quote: s.sentence, title: s.doc_name }) }, label);
}
function conflictBody(cl, citeFn) {
  const frag = document.createDocumentFragment();
  frag.append(h("div", { class: "positions" }, cl.positions.map((p) =>
    h("div", { class: "pos" },
      h("div", { class: "val" }, cl.kind === "assertion" ? "Position" : p.value),
      ...p.sources.map((s) => h("div", { class: "src" },
        sourceLink(s, s.doc_name), s.doc_date ? h("span", { class: "s-loc" }, ` · ${s.doc_date}`) : null,
        s.cite && citeFn ? citeFn(s.cite) : null,
        h("q", {}, s.sentence),
        h("span", { class: "s-loc" }, [s.page ? `p.${s.page}` : null, s.section ? `§ ${s.section}` : null].filter(Boolean).join(" · ")))))
  )));
  if (cl.resolution) frag.append(h("div", { class: "resolve" }, h("b", { class: "k" }, "What might explain it (inference, not stated)"), richText(cl.resolution, null).childNodes.length ? richText(cl.resolution, null) : cl.resolution));
  if (cl.hints && cl.hints.length) frag.append(h("ul", { class: "hints", style: "margin:0 16px 12px" }, cl.hints.map((x) => h("li", {}, x))));
  return frag;
}

/* ---------------------------------------------------------------- answers */
function renderAnswer(r) {
  state.results.set(r.id, r);
  const cmap = new Map(r.citations.map((c) => [c.id, c]));
  const citeFn = (id) => {
    const c = cmap.get(id); if (!c) return id;
    return h("button", { class: "cite" + (c.role === "lead" ? " lead" : ""), title: `${loc(c)}\n"${c.quote}"`, onclick: () => openCitation(c) }, id.replace("S", ""));
  };
  const [icon, label] = STATUS[r.status] || ["•", r.status];
  const conf = r.confidence || {};
  const pct = Math.round((conf.score || 0) * 100);
  const confLabel = r.status === "conflict" ? "Conflict certainty" : r.status === "insufficient" ? "Evidence" : "Confidence";
  const why = h("ul", { class: "why", hidden: true }, (conf.reasons || []).map((x) => h("li", { dataset: { e: x.effect } }, x.text)));
  const trace = h("div", { class: "trace", hidden: true });
  const el = h("article", { class: `answer st-${r.status}`, dataset: { id: r.id } },
    h("div", { class: "a-banner" }, h("span", {}, icon), h("span", {}, label),
      h("span", { class: "sub" }, r.engine === "claude" ? "Claude · quotes verified" : "Extractive engine")),
    h("div", { class: "a-body" },
      r.headline && r.status !== "insufficient" ? h("div", { class: "headline" }, r.headline) : null,
      richText(r.answer, citeFn)),
    r.conflicts.length ? r.conflicts.map((cl) => conflictBody(cl, citeFn)) : null,
    conf.label ? h("div", { class: "conf" },
      h("div", { class: `meter m-${(conf.label || "").toLowerCase()}` }, h("i", { style: `width:${pct}%` })),
      h("b", {}, `${confLabel}: ${conf.label}`), h("small", {}, `${pct}%`),
      h("button", { class: "linklike", onclick: (e) => { why.hidden = !why.hidden; e.target.textContent = why.hidden ? "why?" : "hide"; } }, "why?")) : null,
    why,
    r.caveats && r.caveats.length ? h("ul", { class: "caveats" }, r.caveats.map((c) => h("li", {}, c))) : null,
    r.citations.length ? h("div", { class: "sources" }, h("h4", {}, "Sources"),
      r.citations.map((c) => h("div", { class: "source", onclick: () => openCitation(c) },
        h("span", { class: "cite" + (c.role === "lead" ? " lead" : "") }, c.id),
        h("div", {}, h("div", { class: "s-doc" }, c.doc_name,
          c.role === "conflict" ? h("span", { class: "tag", style: "margin-left:6px" }, "conflicting") : null,
          c.role === "lead" ? h("span", { class: "tag", style: "margin-left:6px" }, "related, not an answer") : null,
          c.ocr_conf != null ? h("span", { class: "tag ocr", style: "margin-left:6px" }, `OCR ${Math.round(c.ocr_conf * 100)}%`) : null),
          h("div", { class: "s-loc" }, [c.page ? `page ${c.page}` : null, c.section ? `section "${c.section}"` : null].filter(Boolean).join(" · ") || "document"),
          h("div", { class: "s-quote" }, "“" + c.quote + "”"))))) : null,
    trace,
    h("div", { class: "a-actions" },
      h("button", { class: "btn small", onclick: (e) => pin(r, e.target) }, "📌 Pin to notebook"),
      h("button", { class: "btn small ghost", onclick: () => { trace.hidden = !trace.hidden; if (!trace.childNodes.length) fillTrace(trace, r); } }, "How was this found?"),
      h("span", { class: "meta" }, `${r.timings_ms.total} ms`)));
  return el;
}
function fillTrace(box, r) {
  const t = r.trace || {};
  box.append(h("div", {}, `Question type: ${t.question_type || "-"} · key terms: ${(t.query_terms || []).join(", ") || "-"} · ${t.dense ? "hybrid BM25 + semantic retrieval" : "BM25 + character n-gram retrieval"}`
    + (r.effective_question && r.effective_question !== r.question ? ` · interpreted as: "${r.effective_question}"` : "")));
  if (r.missing_terms && r.missing_terms.length) box.append(h("div", {}, "Terms absent from every document: " + r.missing_terms.join(", ")));
  box.append(h("table", {}, h("tr", {}, ["Passage", "Rank", "Relevance", "Term coverage"].map((x) => h("th", {}, x))),
    (t.hits || []).map((x) => h("tr", {}, h("td", {}, `${x.doc}${x.page ? " p." + x.page : ""}${x.section ? " § " + x.section : ""}`), h("td", {}, x.rank.toFixed(2)), h("td", {}, x.relevance.toFixed(2)), h("td", {}, Math.round(x.coverage * 100) + "%")))));
}
function openCitation(c) {
  openViewer({ doc_id: c.doc_id, page: c.page || 1, start: c.start, end: c.end, quote: c.quote, title: c.doc_name });
}
async function pin(r, btn) {
  try { await post("/api/notebook", { result: r, comment: "" }); btn.textContent = "📌 Pinned"; btn.disabled = true; loadNotes(); toast("Pinned to notebook"); }
  catch (e) { toast(e.message); }
}

async function ask(question) {
  question = question.trim(); if (!question || state.busy) return;
  state.busy = true; $("#send").disabled = true;
  $("#welcome")?.remove();
  const thread = $("#thread");
  thread.append(h("div", { class: "q-bubble" }, question));
  const typing = h("div", { class: "typing" }, h("i"), h("i"), h("i"), " Searching documents and checking for conflicts…");
  thread.append(typing); thread.scrollTop = thread.scrollHeight;
  try {
    const r = await post("/api/ask", { question, history: state.history.slice(-4), mode: $("#mode").value });
    typing.remove();
    const card = renderAnswer(r); thread.append(card);
    state.history.push({ question, answer: r.answer.replace(/\*+/g, "").slice(0, 400) });
    card.scrollIntoView({ block: "start" });
    if (r.citations.length && window.innerWidth > 1100) { const c = r.citations.find((x) => x.role !== "lead") || r.citations[0]; openCitation(c); }
  } catch (e) {
    typing.remove(); thread.append(h("div", { class: "answer st-insufficient" }, h("div", { class: "a-banner" }, "✕ Something went wrong"), h("div", { class: "a-body" }, e.message)));
  } finally { state.busy = false; $("#send").disabled = false; $("#q").focus(); }
}

/* ---------------------------------------------------------------- conflict board + notebook */
async function loadConflicts() {
  const box = $("#conflict-list");
  let d; try { d = await json("/api/conflicts"); } catch { return; }
  $("#badge-conflicts").textContent = d.conflicts.length; $("#badge-conflicts").classList.toggle("hot", d.conflicts.length > 0);
  box.replaceChildren();
  if (!d.conflicts.length) { box.append(h("p", { class: "empty" }, state.docs.length < 2 ? "Add at least two related documents to compare them." : "No conflicts detected between the indexed documents.")); return; }
  for (const cl of d.conflicts) {
    box.append(h("article", { class: "conf-card" },
      h("div", { class: "cc-head" }, h("span", { class: `sev ${cl.severity}` }, cl.severity),
        h("span", { class: "cc-topic" }, (cl.topic || []).slice(0, 3).join(" · ") || "Disputed point"),
        h("span", { class: "tag" }, cl.value_kind || cl.kind), cl.same_document ? h("span", { class: "tag" }, "same document") : null,
        cl.time_scoped ? h("span", { class: "tag ocr" }, "time-scoped") : null),
      h("div", { class: "cc-expl" }, cl.explanation),
      conflictBody(cl, null),
      h("div", { class: "a-actions" }, h("button", { class: "btn small", onclick: () => { switchTab("ask"); ask(`What does the documentation say about ${(cl.topic || []).slice(0, 3).join(" ")}?`); } }, "Investigate in Ask"))));
  }
}
async function loadNotes() {
  const d = await json("/api/notebook"); $("#badge-notes").textContent = d.notes.length;
  const box = $("#note-list"); box.replaceChildren();
  if (!d.notes.length) { box.append(h("p", { class: "empty" }, "Nothing pinned yet. Use “Pin to notebook” under an answer.")); return; }
  for (const n of d.notes) {
    const r = n.result; const card = renderAnswer(r); card.classList.add("note");
    const ta = h("textarea", { placeholder: "Add your note…" }); ta.value = n.comment || "";
    ta.addEventListener("change", async () => { await post("/api/notebook", { result: r, comment: ta.value }).catch(() => {}); });
    card.querySelector(".a-actions").replaceChildren(h("button", { class: "btn small ghost danger", onclick: async () => { await api(`/api/notebook/${n.id}`, { method: "DELETE" }); loadNotes(); } }, "Remove"));
    card.insertBefore(ta, card.querySelector(".a-actions"));
    box.append(h("div", {}, h("div", { class: "cc-topic", style: "margin:0 0 6px" }, r.question), card));
  }
}

/* ---------------------------------------------------------------- source viewer */
async function openViewer({ doc_id, page = 1, start = -1, end = -1, quote = "", title = "" }) {
  const app = $("#app"); app.classList.add("viewer-open");
  $("#v-title").textContent = title || "Source";
  const body = $("#v-body"); body.replaceChildren(h("p", { class: "empty" }, "Loading…"));
  let d;
  try { d = await json(`/api/documents/${doc_id}/pages/${page}`); } catch (e) { body.replaceChildren(h("p", { class: "empty" }, e.message)); return; }
  const doc = d.document, pg = d.page;
  const bar = h("div", { class: "v-bar" },
    doc.paged ? h("span", {}, `Page ${pg.number} of ${d.n_pages}`) : h("span", {}, "Whole document"),
    doc.paged && d.n_pages > 1 ? h("button", { class: "btn small", disabled: pg.number <= 1, onclick: () => openViewer({ doc_id, page: pg.number - 1, title }) }, "‹") : null,
    doc.paged && d.n_pages > 1 ? h("button", { class: "btn small", disabled: pg.number >= d.n_pages, onclick: () => openViewer({ doc_id, page: pg.number + 1, title }) }, "›") : null,
    pg.ocr_conf != null ? h("span", { class: "tag ocr" }, `OCR confidence ${Math.round(pg.ocr_conf * 100)}%`) : null,
    doc.doc_date ? h("span", { class: "tag" }, `dated ${doc.doc_date}`) : null,
    h("a", { href: `/api/documents/${doc_id}/file`, class: "linklike" }, "original"));
  const hasQuote = start >= 0 && end > start && end <= pg.text.length;
  const textView = h("div", { class: "v-text" });
  if (hasQuote) { const mark = h("mark", {}, pg.text.slice(start, end)); textView.append(pg.text.slice(0, start), mark, pg.text.slice(end)); }
  else textView.textContent = pg.text || "(no text extracted)";
  const parts = [bar];
  if (quote) parts.push(h("div", { class: "v-quote" }, "“" + quote + "”"));
  if (pg.has_image) {
    const img = h("img", { class: "v-img", alt: `Page ${pg.number} of ${doc.name} with the cited passage highlighted`, src: `/api/documents/${doc_id}/pages/${pg.number}/image?start=${start}&end=${end}` });
    const tg = h("div", { class: "v-toggle" });
    const bi = h("button", { class: "on" }, "Original"), bt = h("button", {}, "Extracted text");
    textView.hidden = true;
    bi.onclick = () => { img.hidden = false; textView.hidden = true; bi.className = "on"; bt.className = ""; };
    bt.onclick = () => { img.hidden = true; textView.hidden = false; bt.className = "on"; bi.className = ""; textView.querySelector("mark")?.scrollIntoView({ block: "center" }); };
    tg.append(bi, bt); parts.push(h("div", { style: "margin-bottom:8px" }, tg), img);
  }
  parts.push(textView);
  body.replaceChildren(...parts);
  if (!pg.has_image) textView.querySelector("mark")?.scrollIntoView({ block: "center" });
}

/* ---------------------------------------------------------------- wiring */
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + name));
  if (name === "conflicts") loadConflicts(); if (name === "notebook") loadNotes();
}
const DEMO_QS = [
  "What are the payment terms?", "What is the termination notice period?", "How many employees does Northwind have?",
  "How often must passwords be rotated?", "Is MFA required for remote access?", "When did the outage start?",
  "What was the root cause of the September outage?", "What marketing budget did the board approve?", "What was the on-time delivery rate in January?",
  "How many days of annual leave do employees get?", "Who is the CFO?", "What is the share price of Northwind?",
];
function renderSuggestions() {
  const box = $("#suggestions"); if (!box) return; box.replaceChildren();
  if (!state.docs.length) { box.append(h("span", { class: "empty" }, "Load the demo corpus on the left to try guided questions.")); return; }
  const demo = state.docs.some((d) => /Vendor_Services|Board_Minutes/.test(d.name));
  const qs = demo ? DEMO_QS : ["Summarise the key obligations in these documents.", "What dates are mentioned?", "What amounts are mentioned?"];
  qs.forEach((q) => box.append(h("button", { class: "chip", onclick: () => ask(q) }, q)));
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#mode").value = store.get("mode", "auto");
  $("#mode").addEventListener("change", (e) => store.set("mode", e.target.value));
  const theme = store.get("theme", ""); if (theme) document.documentElement.dataset.theme = theme;
  $("#btn-theme").addEventListener("click", () => {
    const dark = (document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
    document.documentElement.dataset.theme = dark ? "light" : "dark"; store.set("theme", document.documentElement.dataset.theme);
  });
  const drop = $("#drop"), file = $("#file");
  drop.addEventListener("click", () => file.click());
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); file.click(); } });
  file.addEventListener("change", () => { upload([...file.files]); file.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => upload([...e.dataTransfer.files]));
  document.addEventListener("dragover", (e) => e.preventDefault()); document.addEventListener("drop", (e) => e.preventDefault());

  $("#btn-demo").addEventListener("click", async (e) => {
    e.target.disabled = true; e.target.textContent = "Reading 11 files…";
    try { const r = await json("/api/demo/load", { method: "POST" }); state.docs = r.documents; renderDocs(); renderSuggestions(); loadConflicts(); refreshStatus(); toast(`Loaded ${r.documents.length} documents · ${r.conflicts} conflicts found`); }
    catch (err) { toast(err.message); } finally { e.target.disabled = false; e.target.textContent = "Load demo corpus"; }
  });
  $("#btn-reset").addEventListener("click", async () => {
    if (!state.docs.length || !confirm("Remove all documents from this investigation?")) return;
    await json("/api/documents", { method: "DELETE" }); state.history = []; await refreshDocs(); loadConflicts(); renderSuggestions();
  });
  const exp = () => { window.location.href = "/api/notebook/export"; };
  $("#btn-export").addEventListener("click", exp); $("#btn-export2").addEventListener("click", exp);
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("#v-close").addEventListener("click", () => $("#app").classList.remove("viewer-open"));

  const q = $("#q");
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = Math.min(q.scrollHeight, 140) + "px"; });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); } });
  $("#composer").addEventListener("submit", (e) => { e.preventDefault(); const v = q.value; q.value = ""; q.style.height = "auto"; ask(v); });

  await refreshDocs(); renderSuggestions(); loadConflicts(); loadNotes();
});
