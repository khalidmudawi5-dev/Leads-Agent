"use strict";
let CFG = null;

function fieldValue(el) {
  if (el.type === "checkbox") return el.checked;
  if (el.type === "number") return Number(el.value);
  if (el.dataset.type === "lines") return el.value.split("\n").map((v) => v.trim()).filter((v, i, a) => v !== "" || false)
    .map((v) => v === CFG.empty_token ? "" : v);
  return el.value;
}
function setField(el, value) {
  if (el.type === "checkbox") el.checked = !!value;
  else if (el.dataset.type === "lines") el.value = (value || []).map((v) => v === "" ? CFG.empty_token : v).join("\n");
  else el.value = value ?? "";
}

async function loadSettings() {
  const headerInfo = CFG && CFG.headerInfo;
  CFG = await api("GET", "/api/settings");
  CFG.headerInfo = headerInfo || null;
  $$("[data-key]").forEach((el) => setField(el, CFG.settings[el.dataset.key]));
  $("#paths").textContent = `data: ${CFG.paths.data} · logs: ${CFG.paths.logs} · browser profile: ${CFG.paths.browser_profile}`;
  renderGoogleStatus(CFG.google);
  renderColumns(CFG.headerInfo || null);
  loadPendingChips();
}

/** Status chips that edit the Pending Status Values textarea (saved with the Google section). */
async function loadPendingChips() {
  const box = $("#pending-chips");
  if (!box) return;
  let options = [];
  try { options = (await api("GET", "/api/queue/filter")).options; } catch (e) { box.innerHTML = ""; return; }
  const area = $('[data-key="pending_status_values"]');
  const current = () => fieldValue(area);
  const draw = () => {
    const sel = current().map((v) => v.trim());
    box.innerHTML = options.map((o, i) => `<button type="button" class="fchip ${sel.includes(o.value) ? "on" : ""} ${o.empty ? "empty-status" : ""}" data-i="${i}">
      <span class="box"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2"><path d="M20 6L9 17l-5-5"/></svg></span>
      <span class="t">${o.empty ? "فارغة (بدون حالة)" : esc(o.value)}</span><span class="n">${o.count}</span></button>`).join("");
    $$(".fchip", box).forEach((b) => b.onclick = () => {
      const v = options[+b.dataset.i].value;
      const list = current();
      const next = list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
      setField(area, next);
      draw();
    });
  };
  area.oninput = draw;
  draw();
}

async function saveSection(name) {
  const panel = $(`[data-panel="${name}"]`);
  const body = {};
  $$("[data-key]", panel).forEach((el) => { body[el.dataset.key] = fieldValue(el); });
  try {
    await api("PUT", "/api/settings", body);
    toast("تم الحفظ", "success");
    await loadSettings();
    refreshStatus();
  } catch (e) { toast(e.message + (e.details && e.details.error ? " — " + e.details.error : ""), "error", 8000); }
}

function renderGoogleStatus(g) {
  const box = $("#google-status");
  if (g.mode === "service_account") {
    box.className = "alert " + (g.configured ? "success" : "warn");
    box.innerHTML = g.configured ? `Service Account: <b class="ltr">${esc(g.service_account_email)}</b> — شارك ملف Google Sheet مع هذا البريد (Editor).`
      : "لم يتم رفع ملف Service Account بعد.";
    return;
  }
  box.className = "alert " + (g.configured ? "success" : "warn");
  box.innerHTML = `Google Connection: <b>${g.configured ? "Connected" : "Not Connected"}</b>
    · ملف OAuth client: ${g.has_client_secret ? "موجود" : "غير مرفوع"}
    ${g.flow && g.flow.running ? " · <span class='spinner'></span> بانتظار الموافقة في المتصفح…" : ""}
    ${g.flow && g.flow.error ? `<div>${esc(g.flow.error)}</div>` : ""}`;
}

async function upload(kind, input) {
  const f = input.files[0];
  if (!f) { toast("اختر ملف JSON أولًا", "warn"); return; }
  const fd = new FormData(); fd.append("file", f);
  try { const r = await api("POST", `/api/google/upload/${kind}`, fd); toast("تم رفع الملف", "success"); renderGoogleStatus(r.google); await loadSettings(); }
  catch (e) { toast(e.message, "error", 7000); }
}

async function connectGoogle(btn) {
  await withBusy(btn, async () => {
    try {
      await api("POST", "/api/google/connect");
      toast("سيفتح المتصفح لتسجيل الدخول إلى Google والموافقة.", "info", 6000);
      for (let i = 0; i < 150; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const st = await api("GET", "/api/google/connect-status");
        renderGoogleStatus(st.google);
        if (!st.flow.running) { st.flow.done ? toast("تم ربط Google بنجاح", "success") : toast(st.flow.error || "لم يكتمل الربط", "error", 8000); break; }
      }
      refreshStatus();
    } catch (e) { toast(e.message, "error", 7000); }
  });
}

async function testGoogle(btn) {
  await withBusy(btn, async () => {
    const out = $("#google-test");
    try {
      const r = await api("POST", "/api/google/test");
      const tabs = r.tabs.map((t) => `<option value="${esc(t)}">`).join("");
      $("#tab-list").innerHTML = tabs;
      const missing = (r.missing || []).map((k) => CFG.column_labels[k] || k);
      out.innerHTML = `<div class="alert ${r.ok && !missing.length ? "success" : "warn"}">
        <div>الملف: <b>${esc(r.title)}</b> · التابات: ${r.tabs.map(esc).join("، ")}</div>
        ${r.message ? `<div>${esc(r.message)}</div>` : ""}
        ${r.header.length ? `<div>عدد الصفوف: ${r.total_rows} · صفوف ${esc(CFG.settings.agent_owner)}: <b>${r.owner_rows}</b></div>` : ""}
        ${missing.length ? `<div>أعمدة غير موجودة: ${missing.map(esc).join("، ")} — عدّل Column Mapping.</div>` : ""}</div>`;
      refreshStatus();
    } catch (e) { showError(e, out); refreshStatus(); }
  });
}

async function loadTabs(btn) {
  await withBusy(btn, async () => {
    try {
      const r = await api("GET", "/api/sheet/tabs");
      $("#tab-list").innerHTML = r.sheets.map((t) => `<option value="${esc(t)}">`).join("");
      toast("التابات: " + r.sheets.join("، "), "info", 6000);
    } catch (e) { toast(e.message, "error", 7000); }
  });
}

// ------------------------------------------------------------ columns
function colLetter(i) { let n = i + 1, out = ""; while (n) { const r = (n - 1) % 26; out = String.fromCharCode(65 + r) + out; n = Math.floor((n - 1) / 26); } return out; }
const normH = (v) => String(v || "").replace(/[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, "").replace(/\s+/g, " ").trim();

/** One dropdown per field with *every* sheet column (letter + title). Headers load automatically. */
function renderColumns(info) {
  const map = CFG.settings.column_mapping;
  const header = info ? info.header : null;
  const resolved = info ? info.columns : {};
  $("#columns-form").innerHTML = Object.keys(CFG.column_labels).map((k) => {
    const req = CFG.required_columns.includes(k);
    const current = map[k] || "";
    let control;
    let status = "";
    if (header && header.length) {
      const cols = header.map((h, i) => ({ i, h: normH(h) })).filter((c) => c.h);
      const found = resolved[k] ? normH(resolved[k]) : "";
      const selected = found || (cols.some((c) => c.h === normH(current)) ? normH(current) : "");
      const lost = current && !selected;
      control = `<select data-col="${k}" ${lost ? 'class="needs-choice"' : ""}>
        <option value="">— غير مستخدم —</option>
        ${lost ? `<option value="${esc(current)}" selected>⚠ ${esc(current)} (غير موجود في الـSheet)</option>` : ""}
        ${cols.map((c) => `<option value="${esc(c.h)}" ${c.h === selected ? "selected" : ""}>${colLetter(c.i)} — ${esc(c.h)}</option>`).join("")}
      </select>`;
      const idx = cols.find((c) => c.h === selected);
      status = idx ? `<div class="help" style="color:var(--success)">✓ العمود ${colLetter(idx.i)}</div>`
        : (lost || (req && !current)) ? `<div class="help" style="color:var(--danger)">✗ غير موجود في صف العناوين${req ? " — حقل مطلوب" : ""}</div>` : "";
    } else {
      control = `<input type="text" data-col="${k}" value="${esc(current)}">`;
    }
    return `<label class="field"><span>${esc(CFG.column_labels[k])}${req ? " *" : ""} <span class="ltr muted small">(${k})</span></span>${control}${status}</label>`;
  }).join("");
}
async function loadHeaders(btn) {
  const run = async () => {
    try {
      const r = await api("GET", "/api/sheet/headers");
      CFG.headerInfo = r;
      renderColumns(r);
      const missing = r.missing.map((k) => CFG.column_labels[k]);
      $("#columns-msg").innerHTML = `<div class="alert ${missing.length ? "warn" : "success"}">تم تحميل ${r.header.filter((h) => normH(h)).length} عمود من صف العناوين رقم ${CFG.settings.header_row}.
        ${missing.length ? ` غير مطابقة حاليًا: <b>${missing.map(esc).join("، ")}</b> — اختر العمود الصحيح من القائمة ثم احفظ.` : " كل الأعمدة مطابقة."}</div>`;
    } catch (e) {
      renderColumns(null);
      showError(e, $("#columns-msg"));
    }
  };
  if (btn) await withBusy(btn, run); else await run();
}
async function saveColumns() {
  const mapping = {};
  $$("[data-col]").forEach((el) => { mapping[el.dataset.col] = el.value; });
  try { await api("PUT", "/api/settings", { column_mapping: mapping }); toast("تم حفظ Column Mapping", "success"); await loadSettings(); await loadHeaders(); }
  catch (e) { toast(e.message, "error"); }
}

// ------------------------------------------------------------- status
async function loadStatus() {
  const r = await api("GET", "/api/settings/status-mapping");
  let options = null;
  try { options = (await api("GET", "/api/sheet/options/followup_status")).options; } catch (e) { /* sheet not connected yet */ }
  $("#status-rows").innerHTML = r.items.map((i) => {
    let ctl;
    if (options && options.length) {
      const lost = i.sheet_value && !options.includes(i.sheet_value);
      ctl = `<select data-sv="${i.code}" ${lost ? 'class="needs-choice"' : ""}><option value="">— اختر —</option>
        ${lost ? `<option value="${esc(i.sheet_value)}" selected>⚠ ${esc(i.sheet_value)} (غير موجود في القائمة)</option>` : ""}
        ${options.map((o) => `<option value="${esc(o)}" ${o === i.sheet_value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    } else {
      ctl = `<input type="text" data-sv="${i.code}" value="${esc(i.sheet_value)}">`;
    }
    return `<tr><td class="ltr">${esc(i.code)}</td><td><input type="text" data-label="${i.code}" value="${esc(i.label)}"></td><td>${ctl}</td></tr>`;
  }).join("");
}
async function saveStatus() {
  const items = $$("[data-sv]").map((el, i) => ({ code: el.dataset.sv, sheet_value: el.value, label: $(`[data-label="${el.dataset.sv}"]`).value, sort_order: i }));
  try { await api("PUT", "/api/settings/status-mapping", { items }); toast("تم حفظ Status Mapping", "success"); }
  catch (e) { toast(e.message, "error"); }
}

// ------------------------------------------------------------- source
let SHEET_SOURCES = null;
/** Same normalization as the server (case, spaces and the separators / | || \ › > - are ignored). */
function srcKey(v) {
  return String(v || "").normalize("NFKC").toLowerCase().split(/\s*(?:\|\||\||\/|\\|›|>|-)\s*/)
    .map((p) => p.replace(/\s+/g, " ").trim()).filter(Boolean).join(" / ");
}
function sheetMatch(value) {
  if (!SHEET_SOURCES || !SHEET_SOURCES.length) return { known: null, option: value };
  if (SHEET_SOURCES.includes(value)) return { known: true, option: value };
  const same = SHEET_SOURCES.filter((o) => srcKey(o) === srcKey(value));
  return same.length === 1 ? { known: true, option: same[0], respelled: true } : { known: false, option: "" };
}
function renderSources(items) {
  $("#source-rows").innerHTML = items.length ? items.map((i, n) => {
    const m = sheetMatch(i.sheet_value);
    let cell;
    if (SHEET_SOURCES && SHEET_SOURCES.length) {
      cell = `<select data-edit="${n}" ${m.known ? "" : 'class="needs-choice"'}>
        ${m.known ? "" : '<option value="" selected>— اختر القيمة الصحيحة من قائمة الـSheet —</option>'}
        ${SHEET_SOURCES.map((o) => `<option value="${esc(o)}" ${o === m.option ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>
        ${m.known === false ? `<div class="help" style="color:var(--danger)">القيمة المحفوظة «${esc(i.sheet_value)}» غير موجودة في قائمة الـSheet — اختر القيمة الصحيحة وسيُحفظ تلقائيًا.</div>`
          : m.respelled ? `<div class="help" style="color:var(--success)">✓ ستُكتب كما في الـSheet: «${esc(m.option)}»</div>` : ""}`;
    } else {
      cell = esc(i.sheet_value);
    }
    return `<tr><td><b>${esc(i.odoo_value)}</b></td><td>${cell}</td>
      <td><button class="btn sm danger" data-del="${i.id}">حذف</button></td></tr>`;
  }).join("") : '<tr><td colspan="3" class="empty">لا يوجد ربط بعد.</td></tr>';
  $$("[data-del]").forEach((b) => b.onclick = async () => { const r = await api("DELETE", `/api/settings/source-mapping/${b.dataset.del}`); renderSources(r.items); });
  $$("select[data-edit]").forEach((sel) => sel.onchange = async () => {
    if (!sel.value) return;
    const item = items[+sel.dataset.edit];
    try {
      const r = await api("POST", "/api/settings/source-mapping", { odoo_value: item.odoo_value, sheet_value: sel.value });
      renderSources(r.items); toast(`تم الحفظ: ${item.odoo_value} ← ${sel.value}`, "success");
    } catch (e) { toast(e.message, "error"); }
  });
}
async function loadSources() {
  try {
    const o = await api("GET", "/api/sheet/options/source");
    SHEET_SOURCES = o.options;
    if (o.options.length) {
      const old = $("#src-sheet");
      const sel = document.createElement("select");
      sel.id = "src-sheet";
      sel.innerHTML = '<option value="">— اختر قيمة من قائمة الـSheet —</option>' + o.options.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
      old.replaceWith(sel);
    }
  } catch (e) { /* not connected */ }
  renderSources((await api("GET", "/api/settings/source-mapping")).items);
}
async function addSource() {
  try {
    const r = await api("POST", "/api/settings/source-mapping", { odoo_value: $("#src-odoo").value, sheet_value: $("#src-sheet").value });
    renderSources(r.items); $("#src-odoo").value = ""; $("#src-sheet").value = ""; toast("تم الحفظ", "success");
  } catch (e) { toast(e.message, "error"); }
}

// --------------------------------------------------------------- odoo
async function odooLogin() { try { await api("POST", "/api/odoo/open-login"); toast("تم فتح Odoo. سجّل الدخول ثم اضغط Test Session.", "info", 6000); } catch (e) { toast(e.message, "error", 7000); } }
async function odooTest(btn) {
  await withBusy(btn, async () => {
    try { const r = await api("POST", "/api/odoo/check-login");
      $("#odoo-test").innerHTML = `<div class="alert ${r.logged_in ? "success" : "warn"}">${r.logged_in ? `Odoo متصل${r.user ? " — " + esc(r.user) : ""}` : "تسجيل الدخول إلى Odoo مطلوب"}</div>`;
      refreshStatus();
    } catch (e) { showError(e, $("#odoo-test")); }
  });
}
async function odooSearch(btn) {
  await withBusy(btn, async () => {
    try {
      const r = await api("POST", "/api/odoo/test-search", { query: $("#odoo-q").value });
      $("#odoo-test").innerHTML = r.candidates.length ? `<table class="table"><thead><tr><th>ID</th><th>Company</th><th>Phone</th><th>Mobile</th><th>Salesperson</th><th>Source</th><th>Stage</th></tr></thead><tbody>
        ${r.candidates.map((c) => `<tr><td>${c.id ?? "—"}</td><td>${esc(c.company_name || c.name)}</td><td class="ltr">${esc(c.phone)}</td><td class="ltr">${esc(c.mobile)}</td><td>${esc(c.salesperson)}</td><td>${esc(c.source)}</td><td>${esc(c.stage)}</td></tr>`).join("")}</tbody></table>`
        : '<div class="alert warn">لا توجد نتائج.</div>';
    } catch (e) { showError(e, $("#odoo-test")); }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  $$(".tab").forEach((t) => t.onclick = () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === t.dataset.tab));
    if (t.dataset.tab === "status") loadStatus().catch((e) => toast(e.message, "error"));
    if (t.dataset.tab === "source") loadSources().catch((e) => toast(e.message, "error"));
    if (t.dataset.tab === "columns" && !CFG.headerInfo) loadHeaders($("#btn-load-headers"));
  });
  const hash = location.hash.replace("#", "");
  $$("[data-save]").forEach((b) => b.onclick = () => saveSection(b.dataset.save));
  $("#btn-up-oauth").onclick = () => upload("oauth", $("#f-oauth"));
  $("#btn-up-sa").onclick = () => upload("service_account", $("#f-sa"));
  $("#btn-connect").onclick = (ev) => connectGoogle(ev.currentTarget);
  $("#btn-disconnect").onclick = async () => { await api("POST", "/api/google/disconnect"); toast("تم فصل Google", "info"); loadSettings(); refreshStatus(); };
  $("#btn-test-google").onclick = (ev) => testGoogle(ev.currentTarget);
  $("#btn-load-tabs").onclick = (ev) => loadTabs(ev.currentTarget);
  $("#btn-load-headers").onclick = (ev) => loadHeaders(ev.currentTarget);
  $("#btn-save-columns").onclick = saveColumns;
  $("#btn-save-status").onclick = saveStatus;
  $("#btn-add-source").onclick = addSource;
  $("#btn-odoo-login").onclick = odooLogin;
  $("#btn-odoo-test").onclick = (ev) => odooTest(ev.currentTarget);
  $("#btn-odoo-search").onclick = (ev) => odooSearch(ev.currentTarget);
  try { await loadSettings(); } catch (e) { toast(e.message, "error"); }
  if (hash) { const t = $(`.tab[data-tab="${hash}"]`); if (t) t.click(); }
});

Shortcuts.register([
  { code: "KeyS", label: "S", ctrl: true, allowInInputs: true, title: "حفظ القسم الحالي في الإعدادات", group: "الإعدادات",
    run: () => { const b = $(".tab-panel.active [data-save], .tab-panel.active .actions .btn.primary"); if (b) b.click(); } },
]);
