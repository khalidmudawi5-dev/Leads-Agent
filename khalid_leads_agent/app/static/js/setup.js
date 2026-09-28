/* First-run wizard: 9 steps. Every step saves immediately; nothing is written to Odoo/Sheet. */
"use strict";
let W = { step: 1, cfg: null };
const STEPS = ["اسم المستخدم", "ربط Google", "تحديد Tab", "Column Mapping", "Odoo URL", "تسجيل دخول Odoo", "اختبار البحث", "Dry Run Test", "جاهز"];

async function reloadCfg() { W.cfg = await api("GET", "/api/settings"); return W.cfg; }
async function save(values) { await api("PUT", "/api/settings", values); await reloadCfg(); refreshStatus(); }

function drawSteps() {
  $("#steps").innerHTML = STEPS.map((s, i) => `<span class="step-pill ${i + 1 === W.step ? "active" : (i + 1 < W.step ? "done" : "")}">${i + 1}. ${s}</span>`).join("");
}

function frame(title, body, { next = true, back = true, nextLabel = "التالي" } = {}) {
  drawSteps();
  $("#step-card").innerHTML = `<h2>الخطوة ${W.step}: ${title}</h2>${body}<div id="w-msg" style="margin-top:12px"></div>
    <div class="actions" style="margin-top:18px">
      ${back && W.step > 1 ? '<button class="btn" id="w-back">السابق</button>' : ""}
      ${next ? `<button class="btn primary" id="w-next">${nextLabel}</button>` : ""}</div>`;
  if ($("#w-back")) $("#w-back").onclick = () => go(W.step - 1);
}
function msg(html, cls = "info") { $("#w-msg").innerHTML = `<div class="alert ${cls}">${html}</div>`; }
function go(n) { W.step = Math.max(1, Math.min(9, n)); render(); }

const RENDER = {
  1() {
    frame("اسم المستخدم", `<p class="muted">الاسم كما يظهر في عمود «المسؤول الحالي» في Google Sheet. الـAgent يتعامل فقط مع صفوف هذا الاسم.</p>
      <label class="field"><span>اسم المستخدم</span><input type="text" id="w-owner" value="${esc(W.cfg.settings.agent_owner)}"></label>`);
    $("#w-next").onclick = async () => { await save({ agent_owner: $("#w-owner").value.trim() }); go(2); };
  },
  2() {
    const g = W.cfg.google;
    frame("ربط Google Sheet", `
      <label class="field"><span>طريقة الربط</span><select id="w-mode"><option value="oauth">Google OAuth Desktop App (مفضل)</option><option value="service_account">Service Account</option></select></label>
      <div id="w-oauth">
        <ol class="small"><li>من Google Cloud Console فعّل <b>Google Sheets API</b>.</li><li>أنشئ OAuth Client ID من نوع <b>Desktop app</b> ونزّل ملف JSON.</li><li>ارفع الملف هنا ثم اضغط Connect Google.</li></ol>
        <div class="row"><input type="file" id="w-file" accept=".json"><button class="btn" id="w-up">رفع ملف OAuth</button>
        <button class="btn primary" id="w-connect">Connect Google</button></div></div>
      <div id="w-sa" class="hidden"><p class="small">ارفع ملف Service Account ثم شارك Google Sheet مع بريد الحساب (Editor).</p>
        <div class="row"><input type="file" id="w-safile" accept=".json"><button class="btn" id="w-saup">رفع ملف Service Account</button></div></div>
      <div id="w-gstatus" style="margin-top:12px"></div>`);
    $("#w-mode").value = W.cfg.settings.google_auth_mode;
    const toggle = () => { const sa = $("#w-mode").value === "service_account"; $("#w-oauth").classList.toggle("hidden", sa); $("#w-sa").classList.toggle("hidden", !sa); };
    $("#w-mode").onchange = async () => { toggle(); await save({ google_auth_mode: $("#w-mode").value }); showG(); };
    toggle();
    const showG = () => {
      const s = W.cfg.google;
      $("#w-gstatus").innerHTML = `<div class="alert ${s.configured ? "success" : "warn"}">Google Connection: <b>${s.configured ? "Connected" : "Not Connected"}</b>
        ${s.mode === "oauth" ? ` · ملف OAuth: ${s.has_client_secret ? "موجود" : "غير مرفوع"}` : (s.service_account_email ? ` · <span class="ltr">${esc(s.service_account_email)}</span>` : "")}</div>`;
    };
    showG();
    const up = async (kind, input) => {
      if (!input.files[0]) return toast("اختر ملف JSON", "warn");
      const fd = new FormData(); fd.append("file", input.files[0]);
      try { await api("POST", `/api/google/upload/${kind}`, fd); await reloadCfg(); showG(); toast("تم رفع الملف", "success"); } catch (e) { toast(e.message, "error", 7000); }
    };
    $("#w-up").onclick = () => up("oauth", $("#w-file"));
    $("#w-saup").onclick = () => up("service_account", $("#w-safile"));
    $("#w-connect").onclick = (ev) => withBusy(ev.currentTarget, async () => {
      try {
        await api("POST", "/api/google/connect");
        msg("سيفتح المتصفح لتسجيل الدخول إلى Google والموافقة على الصلاحيات…");
        for (let i = 0; i < 150; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const st = await api("GET", "/api/google/connect-status");
          if (!st.flow.running) { await reloadCfg(); showG(); st.flow.done ? msg("تم ربط Google بنجاح", "success") : msg(esc(st.flow.error || "لم يكتمل الربط"), "error"); break; }
        }
      } catch (e) { showError(e, $("#w-msg")); }
    });
    $("#w-next").onclick = () => go(3);
  },
  3() {
    frame("تحديد الملف والـTab", `
      <label class="field"><span>Spreadsheet ID (الجزء بين /d/ و /edit في رابط الملف)</span><input type="text" id="w-sid" class="ltr" style="width:100%" value="${esc(W.cfg.settings.spreadsheet_id)}"></label>
      <div class="row"><button class="btn" id="w-tabs">تحميل التابات</button></div>
      <label class="field" style="margin-top:12px"><span>Sheet/Tab Name</span><select id="w-tab"><option value="${esc(W.cfg.settings.sheet_name)}">${esc(W.cfg.settings.sheet_name || "— اختر —")}</option></select></label>`);
    const extract = (v) => { const m = v.match(/\/d\/([a-zA-Z0-9-_]+)/); return m ? m[1] : v.trim(); };
    $("#w-tabs").onclick = (ev) => withBusy(ev.currentTarget, async () => {
      try {
        await save({ spreadsheet_id: extract($("#w-sid").value) });
        $("#w-sid").value = W.cfg.settings.spreadsheet_id;
        const r = await api("GET", "/api/sheet/tabs");
        $("#w-tab").innerHTML = r.sheets.map((t) => `<option ${t === W.cfg.settings.sheet_name ? "selected" : ""}>${esc(t)}</option>`).join("");
        msg(`الملف: <b>${esc(r.title)}</b>`, "success");
      } catch (e) { showError(e, $("#w-msg")); }
    });
    $("#w-next").onclick = async () => { await save({ spreadsheet_id: extract($("#w-sid").value), sheet_name: $("#w-tab").value }); go(4); };
  },
  async 4() {
    frame("Column Mapping", `<p class="muted">الأعمدة تُحدد بنص العنوان. تأكد أن كل حقل مطلوب (*) مرتبط بعنوان صحيح.</p><div class="form-grid" id="w-cols"><span class="spinner"></span></div>`);
    const labels = W.cfg.column_labels, map = W.cfg.settings.column_mapping;
    let header = [];
    try { const r = await api("GET", "/api/sheet/headers"); header = r.header; } catch (e) { showError(e, $("#w-msg")); }
    $("#w-cols").innerHTML = Object.keys(labels).map((k) => {
      const opts = [...new Set([map[k] || "", ...header])];
      return `<label class="field"><span>${esc(labels[k])}${W.cfg.required_columns.includes(k) ? " *" : ""}</span>
        <select data-col="${k}">${opts.map((h) => `<option value="${esc(h)}" ${h === (map[k] || "") ? "selected" : ""}>${h ? esc(h) : "— غير مستخدم —"}</option>`).join("")}</select></label>`;
    }).join("");
    $("#w-next").onclick = async () => {
      const mapping = {}; $$("[data-col]").forEach((el) => { mapping[el.dataset.col] = el.value; });
      await save({ column_mapping: mapping });
      try {
        const t = await api("POST", "/api/google/test");
        const req = (t.missing || []).filter((k) => W.cfg.required_columns.includes(k));
        if (req.length) return msg("أعمدة مطلوبة غير مطابقة: " + req.map((k) => esc(labels[k])).join("، "), "error");
        toast(`تم العثور على ${t.owner_rows} صف لـ ${W.cfg.settings.agent_owner}`, "success", 6000);
        go(5);
      } catch (e) { showError(e, $("#w-msg")); }
    };
  },
  5() {
    frame("رابط Odoo", `<label class="field"><span>Odoo Base URL</span><input type="url" id="w-odoo" class="ltr" style="width:100%" value="${esc(W.cfg.settings.odoo_base_url)}"></label>
      <p class="help">مثال: https://worldofss.odoo.com — يعمل مع Odoo 18 أو 19 عبر المتصفح.</p>`);
    $("#w-next").onclick = async () => { try { await save({ odoo_base_url: $("#w-odoo").value.trim() }); go(6); } catch (e) { showError(e, $("#w-msg")); } };
  },
  6() {
    frame("تسجيل الدخول إلى Odoo", `<p>سيفتح متصفح خاص بالـAgent (Profile محفوظ في <span class="ltr">data/browser-profile</span>). سجّل الدخول يدويًا مرة واحدة؛ لا يتم حفظ كلمة المرور في الـAgent.</p>
      <div class="actions"><button class="btn primary" id="w-login">فتح Odoo لتسجيل الدخول</button><button class="btn success" id="w-check">تحقق من تسجيل الدخول</button></div>`);
    $("#w-login").onclick = (ev) => withBusy(ev.currentTarget, async () => { try { await api("POST", "/api/odoo/open-login"); msg("تم فتح Odoo. سجّل الدخول ثم اضغط «تحقق من تسجيل الدخول»."); } catch (e) { showError(e, $("#w-msg")); } });
    $("#w-check").onclick = (ev) => withBusy(ev.currentTarget, async () => {
      try { const r = await api("POST", "/api/odoo/check-login"); refreshStatus();
        r.logged_in ? msg(`Odoo متصل${r.user ? " — " + esc(r.user) : ""}`, "success") : msg("تسجيل الدخول إلى Odoo مطلوب", "warn");
      } catch (e) { showError(e, $("#w-msg")); }
    });
    $("#w-next").onclick = () => go(7);
  },
  7() {
    frame("اختبار البحث في Odoo", `<div class="search-bar"><input type="search" id="w-q" placeholder="اسم عميل أو رقم جوال"><button class="btn primary" id="w-search">بحث</button></div><div id="w-res"></div>`);
    $("#w-search").onclick = (ev) => withBusy(ev.currentTarget, async () => {
      try {
        const r = await api("POST", "/api/odoo/test-search", { query: $("#w-q").value });
        $("#w-res").innerHTML = r.candidates.length ? `<table class="table"><thead><tr><th>Company</th><th>Phone</th><th>Mobile</th><th>Source</th><th>Stage</th></tr></thead><tbody>
          ${r.candidates.map((c) => `<tr><td>${esc(c.company_name || c.name)}</td><td class="ltr">${esc(c.phone)}</td><td class="ltr">${esc(c.mobile)}</td><td>${esc(c.source)}</td><td>${esc(c.stage)}</td></tr>`).join("")}</tbody></table>`
          : '<div class="alert warn">لا توجد نتائج.</div>';
      } catch (e) { showError(e, $("#w-res")); }
    });
    $("#w-next").onclick = () => go(8);
  },
  8() {
    frame("Dry Run Test", `<p>Dry Run: <b>${W.cfg.settings.dry_run ? "ON (آمن)" : "OFF"}</b>. هذا الاختبار يقرأ أول عميل في قائمتك ويعرض ما <b>كان سيتم</b> تحديثه دون أي كتابة.</p>
      <div class="actions"><button class="btn primary" id="w-dry">تشغيل Dry Run Test</button></div><div id="w-dryres" style="margin-top:12px"></div>`);
    $("#w-dry").onclick = (ev) => withBusy(ev.currentTarget, async () => {
      const out = $("#w-dryres");
      try {
        await api("POST", "/api/session/start", { resume: true });
        const cur = await api("GET", "/api/lead/current");
        if (!cur.lead) { out.innerHTML = '<div class="alert warn">لا يوجد عملاء بانتظار التواصل حسب Pending Status Values.</div>'; return; }
        const res = await api("POST", "/api/result/preview", { idempotency_key: uuid(), fingerprint: cur.lead.fingerprint, result_code: "NO_ANSWER", note: "اختبار Dry Run" });
        const p = res.preview;
        out.innerHTML = `<div class="alert info">أول عميل: <b>${esc(cur.lead.company_name)}</b> — صف ${cur.lead.sheet_row}</div>
          <p><b>Would update:</b></p>${p.sheet_error ? `<div class="alert error">${esc(p.sheet_error)}</div>` : ""}
          <table class="table"><tbody>${(p.sheet || []).map((c) => `<tr><td>Sheet ${esc(c.column)}</td><td class="pre">${orDash(c.old)}</td><td class="pre">${orDash(c.new)}</td></tr>`).join("")}</tbody></table>
          ${(res.warnings || []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("")}`;
      } catch (e) { showError(e, out); }
    });
    $("#w-next").onclick = () => go(9);
  },
  9() {
    frame("جاهز", `<p>تم الإعداد. يمكنك تعديل أي شيء لاحقًا من صفحة الإعدادات. Dry Run سيبقى مفعّلًا حتى توقفه بنفسك من الإعدادات > Automation.</p>`, { nextLabel: "فتح لوحة العمل" });
    $("#w-next").onclick = async () => {
      try { await api("POST", "/api/setup/complete"); location.href = "/"; } catch (e) { showError(e, $("#w-msg")); }
    };
  },
};

async function render() { await reloadCfg(); await RENDER[W.step](); }
document.addEventListener("DOMContentLoaded", () => render().catch((e) => showError(e, $("#step-card"))));
