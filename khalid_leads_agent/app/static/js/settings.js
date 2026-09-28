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
  CFG = await api("GET", "/api/settings");
  $$("[data-key]").forEach((el) => setField(el, CFG.settings[el.dataset.key]));
  $("#paths").textContent = `data: ${CFG.paths.data} · logs: ${CFG.paths.logs} · browser profile: ${CFG.paths.browser_profile}`;
  renderGoogleStatus(CFG.google);
  renderColumns([]);
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
function renderColumns(header) {
  const map = CFG.settings.column_mapping;
  $("#columns-form").innerHTML = Object.keys(CFG.column_labels).map((k) => {
    const req = CFG.required_columns.includes(k);
    const opts = [...new Set([map[k] || "", ...header])];
    return `<label class="field"><span>${esc(CFG.column_labels[k])}${req ? " *" : ""} <span class="ltr muted small">(${k})</span></span>
      ${header.length ? `<select data-col="${k}">${opts.map((h) => `<option value="${esc(h)}" ${h === (map[k] || "") ? "selected" : ""}>${h ? esc(h) : "— غير مستخدم —"}</option>`).join("")}</select>`
        : `<input type="text" data-col="${k}" value="${esc(map[k] || "")}">`}</label>`;
  }).join("");
}
async function loadHeaders(btn) {
  await withBusy(btn, async () => {
    try {
      const r = await api("GET", "/api/sheet/headers");
      renderColumns(r.header);
      const missing = r.missing.map((k) => CFG.column_labels[k]);
      $("#columns-msg").innerHTML = missing.length ? `<div class="alert warn">غير مطابقة حاليًا: ${missing.map(esc).join("، ")}</div>` : '<div class="alert success">كل الأعمدة مطابقة.</div>';
    } catch (e) { showError(e, $("#columns-msg")); }
  });
}
async function saveColumns() {
  const mapping = {};
  $$("[data-col]").forEach((el) => { mapping[el.dataset.col] = el.value; });
  try { await api("PUT", "/api/settings", { column_mapping: mapping }); toast("تم حفظ Column Mapping", "success"); await loadSettings(); }
  catch (e) { toast(e.message, "error"); }
}

// ------------------------------------------------------------- status
async function loadStatus() {
  const r = await api("GET", "/api/settings/status-mapping");
  $("#status-rows").innerHTML = r.items.map((i) => `<tr><td class="ltr">${esc(i.code)}</td>
    <td><input type="text" data-label="${i.code}" value="${esc(i.label)}"></td>
    <td><input type="text" data-sv="${i.code}" value="${esc(i.sheet_value)}" list="status-options"></td></tr>`).join("");
  try {
    const o = await api("GET", "/api/sheet/options/followup_status");
    $("#status-options").innerHTML = o.options.map((v) => `<option value="${esc(v)}">`).join("");
  } catch (e) { /* sheet not connected yet */ }
}
async function saveStatus() {
  const items = $$("[data-sv]").map((el, i) => ({ code: el.dataset.sv, sheet_value: el.value, label: $(`[data-label="${el.dataset.sv}"]`).value, sort_order: i }));
  try { await api("PUT", "/api/settings/status-mapping", { items }); toast("تم حفظ Status Mapping", "success"); }
  catch (e) { toast(e.message, "error"); }
}

// ------------------------------------------------------------- source
function renderSources(items) {
  $("#source-rows").innerHTML = items.length ? items.map((i) => `<tr><td>${esc(i.odoo_value)}</td><td>${esc(i.sheet_value)}</td>
    <td><button class="btn sm danger" data-del="${i.id}">حذف</button></td></tr>`).join("") : '<tr><td colspan="3" class="empty">لا يوجد ربط بعد.</td></tr>';
  $$("[data-del]").forEach((b) => b.onclick = async () => { const r = await api("DELETE", `/api/settings/source-mapping/${b.dataset.del}`); renderSources(r.items); });
}
async function loadSources() {
  renderSources((await api("GET", "/api/settings/source-mapping")).items);
  try {
    const o = await api("GET", "/api/sheet/options/source");
    $("#source-options").innerHTML = o.options.map((v) => `<option value="${esc(v)}">`).join("");
  } catch (e) { /* not connected */ }
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
