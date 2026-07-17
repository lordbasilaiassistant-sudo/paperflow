/* paperflow front-end: queue + review. No build step, no dependencies. */
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const api = {
  async list() { return (await fetch("/api/documents")).json(); },
  async get(id) { return (await fetch(`/api/documents/${id}`)).json(); },
  async upload(file) {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/documents", { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail || "Upload failed");
    return r.json();
  },
  async patch(id, extraction) {
    const r = await fetch(`/api/documents/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(extraction),
    });
    if (!r.ok) throw new Error((await r.json()).detail || "Save failed");
    return r.json();
  },
  async approve(id) {
    const r = await fetch(`/api/documents/${id}/approve`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json()).detail || "Approve failed");
    return r.json();
  },
};

const state = { docs: [], filter: "all", current: null, seenDone: new Set() };

/* ---------- helpers ---------- */

const STATUS_STAMP = {
  processing: ["stamp-grey", "processing…"],
  needs_review: ["stamp-red", "needs review"],
  auto_accepted: ["stamp-green", "auto-accepted"],
  approved: ["stamp-ink", "approved"],
  failed: ["stamp-red", "failed"],
};

function stampEl(status, animate = false) {
  const [cls, label] = STATUS_STAMP[status] || ["stamp-grey", status];
  const s = document.createElement("span");
  s.className = `stamp ${cls}${animate ? " stamp-in" : ""}`;
  s.textContent = label;
  return s;
}

function confBar(v) {
  const wrap = document.createElement("span");
  if (v == null) return wrap;
  const band = v >= 0.8 ? "" : v >= 0.5 ? "mid" : "low";
  wrap.innerHTML = `<span class="ink-bar ${band}"><i style="width:${Math.round(v * 100)}%"></i></span>` +
    `<span class="conf-num">${v.toFixed(2)}</span>`;
  wrap.style.display = "inline-flex";
  wrap.style.gap = "6px";
  wrap.style.alignItems = "center";
  return wrap;
}

function money(v, cur) {
  if (v == null) return "—";
  const sym = { USD: "$", EUR: "€", GBP: "£", JPY: "¥" }[cur] || "";
  return sym + v.toLocaleString("en-US", {
    minimumFractionDigits: cur === "JPY" ? 0 : 2,
    maximumFractionDigits: cur === "JPY" ? 0 : 2,
  });
}

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = `toast${isError ? " error" : ""}`;
  t.hidden = false;
  clearTimeout(toast._h);
  toast._h = setTimeout(() => { t.hidden = true; }, 3000);
}

/* ---------- queue view ---------- */

function renderSummary() {
  const done = state.docs.filter((d) => d.status !== "processing" && d.status !== "failed");
  const auto = state.docs.filter((d) => d.status === "auto_accepted").length;
  const approved = state.docs.filter((d) => d.status === "approved").length;
  $("#summary").hidden = state.docs.length === 0;
  $("#s-total").textContent = done.length;
  $("#s-auto").textContent = done.length ? `${Math.round((auto / done.length) * 100)}%` : "0%";
  $("#s-review").textContent = state.docs.filter((d) => d.status === "needs_review").length;
  $("#s-approved").textContent = approved;
}

function renderQueue() {
  const ledger = $("#ledger");
  const docs = state.docs.filter((d) => state.filter === "all" || d.status === state.filter);
  ledger.querySelectorAll(".entry").forEach((e) => e.remove());
  $("#ledger-empty").style.display = docs.length ? "none" : "";

  for (const d of docs) {
    const ex = d.extraction || {};
    const row = document.createElement("button");
    row.type = "button";
    row.className = "entry";
    row.addEventListener("click", () => openDoc(d.id));

    const v = document.createElement("span");
    v.innerHTML = `<span class="entry-vendor">${escapeHtml(ex.vendor || "—")}</span>` +
      `<span class="entry-file">${escapeHtml(d.filename)}</span>`;
    const date = document.createElement("span");
    date.className = "entry-date";
    date.textContent = ex.date || "";
    const total = document.createElement("span");
    total.className = "entry-total";
    total.textContent = money(ex.total, ex.currency);
    const conf = document.createElement("span");
    conf.className = "entry-conf";
    if (d.doc_confidence != null) conf.appendChild(confBar(d.doc_confidence));
    const st = document.createElement("span");
    const animate = state.seenDone.has(`anim:${d.id}`);
    if (animate) state.seenDone.delete(`anim:${d.id}`);
    st.appendChild(stampEl(d.status, animate));

    row.append(v, date, total, conf, st);
    ledger.appendChild(row);
  }
  renderSummary();
}

async function refresh() {
  const docs = await api.list();
  // Newly finished docs get their stamp animated in once.
  for (const d of docs) {
    if (d.status !== "processing" && !state.seenDone.has(d.id)) {
      const wasProcessing = state.docs.some((p) => p.id === d.id && p.status === "processing");
      state.seenDone.add(d.id);
      if (wasProcessing) state.seenDone.add(`anim:${d.id}`);
    }
  }
  state.docs = docs;
  renderQueue();
  const anyProcessing = docs.some((d) => d.status === "processing");
  clearTimeout(refresh._h);
  if (anyProcessing) refresh._h = setTimeout(refresh, 1500);
}

/* ---------- upload ---------- */

function setupDropzone() {
  const dz = $("#dropzone");
  const input = $("#file-input");
  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
  input.addEventListener("change", () => { uploadFiles([...input.files]); input.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("is-over"); }));
  dz.addEventListener("drop", (e) => uploadFiles([...e.dataTransfer.files]));
}

async function uploadFiles(files) {
  for (const f of files) {
    try {
      await api.upload(f);
    } catch (err) {
      toast(`${f.name}: ${err.message}`, true);
    }
  }
  if (files.length) refresh();
}

/* ---------- review view ---------- */

const SCALARS = [
  ["vendor", "Vendor", "span-2"],
  ["invoice_no", "Invoice #", ""],
  ["date", "Date (YYYY-MM-DD)", ""],
  ["subtotal", "Subtotal", ""],
  ["tax", "Tax", ""],
  ["total", "Total", ""],
  ["currency", "Currency", ""],
];

async function openDoc(id) {
  const doc = await api.get(id);
  state.current = doc;
  location.hash = `#doc/${id}`;
  $("#view-queue").hidden = true;
  $("#view-doc").hidden = false;
  window.scrollTo(0, 0);

  $("#doc-filename").textContent = doc.filename;
  $("#doc-meta").textContent =
    `${doc.id} · ${doc.source_type || "?"} · ${doc.page_count || "?"}p · ` +
    `${(doc.prompt_tokens || 0) + (doc.completion_tokens || 0)} tokens`;
  const stampBox = $("#doc-status-stamp");
  stampBox.replaceChildren(stampEl(doc.status));

  const img = $("#doc-image");
  img.src = `/api/documents/${id}/image`;
  img.onerror = () => { img.hidden = true; $("#image-missing").hidden = false; };
  img.onload = () => { img.hidden = false; $("#image-missing").hidden = true; };
  $("#doc-rawtext").textContent = doc.raw_text || "(no text captured)";

  renderIssues(doc.validation_issues || []);
  renderFields(doc);
  renderItems((doc.extraction || {}).line_items || []);
  renderDocConf(doc);
  $("#approve-btn").disabled = !["needs_review", "auto_accepted"].includes(doc.status);
}

function renderIssues(issues) {
  const box = $("#issues");
  box.replaceChildren(...issues.map((i) => {
    const el = document.createElement("div");
    el.className = `issue ${i.severity}`;
    el.innerHTML = `<b>${escapeHtml(i.field)}</b> — ${escapeHtml(i.message)}`;
    return el;
  }));
}

function renderFields(doc) {
  const ex = doc.extraction || {};
  const conf = doc.field_confidence || {};
  const errorFields = new Set((doc.validation_issues || []).filter((i) => i.severity === "error").map((i) => i.field));
  const grid = $("#field-grid");
  grid.replaceChildren(...SCALARS.map(([key, label, span]) => {
    const wrap = document.createElement("div");
    wrap.className = `field ${span}${errorFields.has(key) ? " has-error" : ""}`;
    const lab = document.createElement("label");
    lab.htmlFor = `f-${key}`;
    lab.innerHTML = `<span>${label}</span>`;
    const tag = document.createElement("span");
    tag.className = "conf-tag";
    tag.appendChild(confBar(conf[key]));
    lab.appendChild(tag);
    const input = document.createElement("input");
    input.id = `f-${key}`;
    input.name = key;
    input.value = ex[key] ?? "";
    if (["subtotal", "tax", "total"].includes(key)) input.inputMode = "decimal";
    wrap.append(lab, input);
    return wrap;
  }));
}

function itemRow(it = {}) {
  const tr = document.createElement("tr");
  const cells = [
    ["description", it.description ?? "", ""],
    ["quantity", it.quantity ?? "", "num"],
    ["unit_price", it.unit_price ?? "", "num"],
    ["amount", it.amount ?? "", "num"],
  ];
  for (const [name, val, cls] of cells) {
    const td = document.createElement("td");
    const input = document.createElement("input");
    input.className = cls;
    input.dataset.name = name;
    input.value = val;
    input.setAttribute("aria-label", name.replace("_", " "));
    if (cls) input.inputMode = "decimal";
    input.addEventListener("input", updateItemSum);
    td.appendChild(input);
    tr.appendChild(td);
  }
  const rm = document.createElement("td");
  rm.className = "rm";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "rm-btn";
  btn.textContent = "✕";
  btn.setAttribute("aria-label", "Remove line item");
  btn.addEventListener("click", () => { tr.remove(); updateItemSum(); });
  rm.appendChild(btn);
  tr.appendChild(rm);
  return tr;
}

function renderItems(items) {
  const body = $("#items-body");
  body.replaceChildren(...items.map(itemRow));
  updateItemSum();
}

function updateItemSum() {
  const rows = [...$("#items-body").children];
  let sum = 0;
  let any = false;
  for (const tr of rows) {
    const v = parseFloat(tr.querySelector('input[data-name="amount"]').value);
    if (!Number.isNaN(v)) { sum += v; any = true; }
  }
  $("#item-sum").textContent = any ? `Σ ${sum.toFixed(2)}` : "";
}

function renderDocConf(doc) {
  const el = $("#doc-conf");
  el.replaceChildren();
  if (doc.doc_confidence != null) {
    const label = document.createElement("span");
    label.textContent = "document confidence";
    el.append(label, confBar(doc.doc_confidence));
  }
}

function collectExtraction() {
  const num = (v) => {
    const s = String(v).trim();
    if (!s) return null;
    const n = parseFloat(s.replace(/[$€£¥,]/g, ""));
    return Number.isNaN(n) ? null : n;
  };
  const str = (v) => (String(v).trim() ? String(v).trim() : null);
  const form = $("#field-form");
  const ex = {
    vendor: str(form.vendor.value),
    invoice_no: str(form.invoice_no.value),
    date: str(form.date.value),
    subtotal: num(form.subtotal.value),
    tax: num(form.tax.value),
    total: num(form.total.value),
    currency: str(form.currency.value),
    line_items: [],
  };
  for (const tr of $("#items-body").children) {
    const get = (n) => tr.querySelector(`input[data-name="${n}"]`).value;
    const item = {
      description: str(get("description")),
      quantity: num(get("quantity")),
      unit_price: num(get("unit_price")),
      amount: num(get("amount")),
    };
    if (item.description || item.amount != null) ex.line_items.push(item);
  }
  return ex;
}

function setupReview() {
  $("#back-btn").addEventListener("click", () => {
    location.hash = "";
    $("#view-doc").hidden = true;
    $("#view-queue").hidden = false;
    state.current = null;
    refresh();
  });

  $("#add-item").addEventListener("click", () => {
    $("#items-body").appendChild(itemRow());
  });

  $("#field-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!state.current) return;
    try {
      const doc = await api.patch(state.current.id, collectExtraction());
      state.current = doc;
      renderIssues(doc.validation_issues || []);
      renderFields(doc);
      renderItems((doc.extraction || {}).line_items || []);
      renderDocConf(doc);
      const errs = (doc.validation_issues || []).filter((i) => i.severity === "error").length;
      toast(errs ? `Saved — ${errs} validation ${errs === 1 ? "issue" : "issues"} remain` : "Saved — all checks pass");
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("#approve-btn").addEventListener("click", async () => {
    if (!state.current) return;
    try {
      await api.patch(state.current.id, collectExtraction());
      await api.approve(state.current.id);
      const overlay = $("#stamp-overlay");
      overlay.hidden = false;
      setTimeout(() => {
        overlay.hidden = true;
        $("#back-btn").click();
      }, 700);
    } catch (err) {
      toast(err.message, true);
    }
  });
}

/* ---------- filters, routing, init ---------- */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function setupFilters() {
  document.querySelectorAll(".filter").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      state.filter = btn.dataset.filter;
      renderQueue();
    });
  });
}

async function init() {
  setupDropzone();
  setupFilters();
  setupReview();
  await refresh();
  const m = location.hash.match(/^#doc\/(\w+)$/);
  if (m) openDoc(m[1]);
}

init();
