/* Dashboard workflow: current lead → Odoo match → call → result → next lead. */
"use strict";

const S = {
  payload: null, lead: null, manual: null, settings: null, statuses: [],
  call: { startedAt: null, endedAt: null, timer: null },
  result: { code: null, key: null, ctx: null },
  options: {}, nextTimer: null, busy: false,
};
const PHONE_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>';
const STRATEGY = { phone: "رقم الهاتف", mobile: "رقم الجوال", "phone+company": "الهاتف + اسم المنشأة", company_exact: "اسم المنشأة (مطابق)", user_choice: "اختيار يدوي" };

// ------------------------------------------------------------------ boot
document.addEventListener("DOMContentLoaded", init);
document.addEventListener("agent-status", (e) => { $("#dry-ribbon").classList.toggle("hidden", !e.detail.dry_run); });

async function init() {
  try {
    const [st, cfg] = await Promise.all([api("GET", "/api/settings/status-mapping"), api("GET", "/api/settings")]);
    S.statuses = st.items; S.settings = cfg.settings;
    $("#dry-ribbon").classList.toggle("hidden", !S.settings.dry_run);
    const sess = await api("GET", "/api/session");
    if (sess.needs_prompt) return askResume(sess.session);
    await api("POST", "/api/session/start", { resume: true });
    await loadCurrent();
  } catch (e) { showError(e, $("#lead-card"), { retry: init }); }
  $("#manual-form").onsubmit = (ev) => { ev.preventDefault(); manualSearch(); };
  $("#btn-refresh-queue").onclick = (ev) => withBusy(ev.currentTarget, refreshQueue);
  $("#btn-end-call").onclick = () => { stopCall(); openResultPanel(); };
  $("#btn-result-from-call").onclick = () => { stopCall(); openResultPanel(); };
}

function askResume(sess) {
  Modal.open({
    title: `استكمال جلسة ${S.settings.agent_owner} السابقة؟`,
    html: `<div class="kv"><div class="k">بدأت</div><div>${esc(sess.started_at)}</div>
      <div class="k">آخر نشاط</div><div>${esc(sess.updated_at)}</div>
      <div class="k">تم إنجازهم</div><div>${sess.completed_count}</div>
      <div class="k">تم تخطيهم</div><div>${sess.skipped_count}</div>
      <div class="k">الأخطاء</div><div>${sess.errors_count}</div></div>`,
    buttons: [
      { label: "استكمال الجلسة", cls: "primary", onClick: async () => { Modal.close(); await api("POST", "/api/session/start", { resume: true }); loadCurrent(); } },
      { label: "بدء جلسة جديدة", onClick: async () => { Modal.close(); await api("POST", "/api/session/start", { resume: false }); loadCurrent(); } },
    ],
  });
}

async function loadCurrent() {
  S.manual = null;
  try { render(await api("GET", "/api/lead/current")); }
  catch (e) { renderFatal(e, loadCurrent); }
}
async function refreshQueue() {
  try { render(await api("POST", "/api/queue/refresh")); toast("تم تحديث القائمة", "success"); }
  catch (e) { renderFatal(e, refreshQueue); }
}
function renderFatal(e, retry) {
  $("#result-card").classList.add("hidden");
  showError(e, $("#lead-card"), { retry });
}

// ---------------------------------------------------------------- render
function render(payload) {
  S.payload = payload;
  S.lead = payload.lead;
  renderStats(payload.stats);
  renderSession(payload.session);
  $("#global-msg").innerHTML = (payload.warnings || []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("");
  $("#result-card").classList.add("hidden");
  if (payload.done || !payload.lead) return renderDone();
  renderLead(payload.lead);
  renderOdoo(payload.lead.odoo);
  if (payload.lead.match_status === "unknown") searchOdoo();
}

function renderStats(st) {
  if (!st) return;
  $$("#stats .value").forEach((el) => { el.textContent = st[el.dataset.k] ?? "–"; });
}

function renderSession(sess) {
  if (!sess) return;
  $("#session-card").innerHTML = `<h2>الجلسة الحالية</h2>
    <div class="kv"><div class="k">بدأت</div><div>${esc(sess.started_at)}</div>
    <div class="k">تم إنجازهم</div><div>${sess.completed_count}</div>
    <div class="k">تم تخطيهم في الجلسة</div><div>${sess.skipped_count}</div>
    <div class="k">الأخطاء</div><div>${sess.errors_count}</div></div>
    <div class="actions" style="margin-top:12px"><button class="btn sm" id="btn-new-session">بدء جلسة جديدة</button></div>`;
  $("#btn-new-session").onclick = () => Modal.open({
    title: "بدء جلسة جديدة؟", html: "سيتم إغلاق الجلسة الحالية، وستظهر العملاء الذين تم تخطيهم في الجلسة مرة أخرى.",
    buttons: [{ label: "نعم، جلسة جديدة", cls: "primary", onClick: async () => { Modal.close(); await api("POST", "/api/session/start", { resume: false }); loadCurrent(); } }, { label: "إلغاء" }],
  });
}

function renderDone() {
  $("#lead-card").innerHTML = `<div class="empty"><div class="big">لا يوجد عملاء بانتظار التواصل</div>
    <div>تم الانتهاء من قائمة ${esc(S.settings.agent_owner)} الحالية، أو أن كل العملاء المتبقين تم تخطيهم مؤقتًا.</div>
    <div class="actions" style="justify-content:center;margin-top:16px"><button class="btn primary" id="btn-reload">تحديث القائمة</button>
    <a class="btn" href="/skipped">العملاء المتخطون</a></div></div>`;
  $("#btn-reload").onclick = (ev) => withBusy(ev.currentTarget, refreshQueue);
  renderOdoo(null);
}

function statusBadge(status) {
  return status ? `<span class="badge indigo">${esc(status)}</span>` : '<span class="badge">فارغ</span>';
}

function renderLead(lead) {
  const o = lead.odoo || {};
  $("#lead-card").innerHTML = `
    <div class="lead-head"><div>
      <div class="row small"><span class="badge blue">صف ${lead.sheet_row} (مرجع فقط)</span>${statusBadge(lead.followup_status)}</div>
      <h2 class="lead-name">${esc(lead.company_name || "(بدون اسم)")}</h2>
      <div class="lead-phone"><span class="ltr">${esc(lead.phone)}</span></div></div>
    </div>
    <div class="info-grid">
      <div class="info"><div class="k">المصدر في Google Sheet</div><div class="v">${orDash(lead.sheet_source)}</div></div>
      <div class="info"><div class="k">Source من Odoo</div><div class="v">${orDash(o.source)}</div></div>
      <div class="info"><div class="k">Medium</div><div class="v">${orDash(o.medium)}</div></div>
      <div class="info"><div class="k">Campaign</div><div class="v">${orDash(o.campaign)}</div></div>
      <div class="info"><div class="k">حالة المتابعة الحالية</div><div class="v">${orDash(lead.followup_status)}</div></div>
      <div class="info"><div class="k">ربط المصدر</div><div class="v">${sourceBadge(lead)}</div></div>
      <div class="info wide"><div class="k">آخر ملاحظة</div><div class="v note-box">${orDash(lead.last_note)}</div></div>
    </div>
    <div id="match-area"></div>
    <div class="actions">
      <button class="btn call" id="btn-call">${PHONE_ICON} اتصال الآن</button>
      <button class="btn primary" id="btn-open">فتح في Odoo</button>
      <button class="btn" id="btn-result">تسجيل النتيجة</button>
      <button class="btn" id="btn-research">إعادة البحث</button>
      <button class="btn" id="btn-refresh">تحديث البيانات</button>
      <span class="spacer"></span>
      <button class="btn" id="btn-skip">تخطي مؤقتًا</button>
    </div>
    <div id="lead-msg" style="margin-top:12px"></div>`;
  renderMatch(lead);
  const fp = lead.fingerprint;
  $("#btn-call").onclick = (ev) => startCall(ev.currentTarget);
  $("#btn-open").onclick = (ev) => withBusy(ev.currentTarget, () => leadAction(`/api/lead/${fp}/open`));
  $("#btn-research").onclick = () => searchOdoo();
  $("#btn-refresh").onclick = (ev) => withBusy(ev.currentTarget, () => leadAction(`/api/lead/${fp}/refresh`, {}, "تم تحديث البيانات"));
  $("#btn-skip").onclick = () => askSkip(fp);
  $("#btn-result").onclick = () => openResultPanel();
}

function sourceBadge(lead) {
  const s = lead.source || {};
  if (!lead.odoo) return '<span class="muted">بانتظار Odoo</span>';
  if (s.mapped) return `<span class="badge green">مربوط → ${esc(s.sheet_value)}</span>`;
  if (s.odoo_value) return `<span class="badge amber">المصدر غير مربوط</span>`;
  return '<span class="muted">لا يوجد Source في Odoo</span>';
}

function renderMatch(lead) {
  const area = $("#match-area");
  if (!area) return;
  const st = lead.match_status;
  if (st === "matched") {
    area.innerHTML = `<div class="alert success">تمت المطابقة مع Odoo: <b>${esc((lead.odoo || {}).name || "")}</b>
      ${lead.odoo && lead.odoo.salesperson ? ` · المسؤول: ${esc(lead.odoo.salesperson)}` : ""}</div>`;
  } else if (st === "multiple") {
    area.innerHTML = `<div class="alert warn"><b>وجدنا أكثر من عميل محتمل في Odoo.</b> لن يتم الاختيار تلقائيًا.
      <div class="actions"><button class="btn primary sm" id="btn-choose">اختيار العميل الصحيح</button></div></div>`;
    $("#btn-choose").onclick = () => chooseCandidate(lead);
  } else if (st === "not_found") {
    area.innerHTML = `<div class="alert error"><b>لم يتم العثور على العميل في Odoo</b>
      <div class="row" style="margin-top:10px"><input type="text" id="custom-q" placeholder="بحث باسم أو رقم آخر" style="max-width:320px">
      <button class="btn sm" id="btn-re">إعادة البحث</button><button class="btn sm" id="btn-crm">فتح CRM</button>
      <button class="btn sm" id="btn-skip2">تخطي العميل</button></div></div>`;
    $("#btn-re").onclick = () => searchOdoo($("#custom-q").value);
    $("#btn-crm").onclick = openCrm;
    $("#btn-skip2").onclick = () => askSkip(lead.fingerprint);
  } else if (st === "error") {
    area.innerHTML = `<div class="alert error">تعذر البحث في Odoo. <button class="btn sm" id="btn-re">إعادة المحاولة</button></div>`;
    $("#btn-re").onclick = () => searchOdoo();
  } else {
    area.innerHTML = `<div class="alert info"><span class="spinner"></span> جاري البحث عن العميل في Odoo…</div>`;
  }
}

function renderLoginRequired(retry) {
  const area = $("#match-area") || $("#lead-msg");
  area.innerHTML = `<div class="alert warn"><b>تسجيل الدخول إلى Odoo مطلوب</b>
    <div class="small">سيفتح متصفح Odoo الخاص بالـAgent. سجّل الدخول مرة واحدة وسيتم حفظ الجلسة.</div>
    <div class="actions"><button class="btn primary sm" id="btn-login">فتح Odoo لتسجيل الدخول</button>
    <button class="btn sm" id="btn-check">تحقق من تسجيل الدخول</button></div></div>`;
  $("#btn-login").onclick = (ev) => withBusy(ev.currentTarget, async () => {
    try { await api("POST", "/api/odoo/open-login"); toast("تم فتح Odoo. سجّل الدخول ثم اضغط تحقق.", "info"); }
    catch (e) { toast(e.message, "error"); }
  });
  $("#btn-check").onclick = (ev) => withBusy(ev.currentTarget, async () => {
    try {
      const r = await api("POST", "/api/odoo/check-login");
      refreshStatus();
      if (r.logged_in) { toast("تم تسجيل الدخول إلى Odoo", "success"); retry(); }
      else toast("لم يتم تسجيل الدخول بعد.", "warn");
    } catch (e) { toast(e.message, "error"); }
  });
}

function renderOdoo(o) {
  const card = $("#odoo-card");
  if (!o) { card.innerHTML = `<h2>بيانات Odoo</h2><div class="muted">لم تتم المطابقة بعد.</div>`; return; }
  const rows = [
    ["Lead", o.name], ["الشركة", o.company_name], ["جهة الاتصال", o.contact_name], ["Phone", o.phone],
    ["Mobile", o.mobile], ["Email", o.email], ["Salesperson", o.salesperson], ["Stage", o.stage],
    ["Source", o.source], ["Medium", o.medium], ["Campaign", o.campaign], ["UTM Source", o.utm_source],
    ["UTM Medium", o.utm_medium], ["UTM Campaign", o.utm_campaign], ["Service Type", o.service_type],
  ];
  const notes = (o.latest_notes || []).map((n) => `<div class="info note-box" style="min-height:0;margin-top:6px">${esc(n)}</div>`).join("");
  card.innerHTML = `<h2>بيانات Odoo <span class="badge blue small">#${o.id ?? "—"}</span></h2>
    <div class="kv">${rows.map(([k, v]) => `<div class="k">${k}</div><div>${["Phone", "Mobile", "Email"].includes(k) ? `<span class="ltr">${orDash(v)}</span>` : orDash(v)}</div>`).join("")}</div>
    <h3 style="margin-top:14px">آخر ملاحظات Chatter</h3>${notes || '<div class="muted">—</div>'}`;
}

// ----------------------------------------------------------- odoo actions
function handleOdooError(e, retry) {
  if (e.code === "ODOO_LOGIN_REQUIRED") { renderLoginRequired(retry); refreshStatus(); return; }
  showError(e, $("#lead-msg"), { retry, open_odoo: () => leadAction(`/api/lead/${S.lead.fingerprint}/open`), skip: () => askSkip(S.lead.fingerprint) });
}

async function searchOdoo(query = "") {
  if (!S.lead) return;
  const fp = S.lead.fingerprint;
  S.lead.match_status = "searching"; renderMatch(S.lead);
  $("#lead-msg").innerHTML = "";
  try {
    const payload = await api("POST", `/api/lead/${fp}/search`, { query });
    render(payload);
    refreshStatus();
  } catch (e) {
    if (e.code !== "ODOO_LOGIN_REQUIRED") { S.lead.match_status = "error"; renderMatch(S.lead); }
    handleOdooError(e, () => searchOdoo(query));
  }
}

async function leadAction(url, body = {}, okMsg = "") {
  try {
    const payload = await api("POST", url, body);
    render(payload);
    if (okMsg) toast(okMsg, "success");
  } catch (e) { handleOdooError(e, () => leadAction(url, body, okMsg)); }
}

async function openCrm() {
  try { await api("POST", "/api/odoo/open-crm"); } catch (e) { handleOdooError(e, openCrm); }
}

function candidateTable(cands, btnLabel) {
  return `<div class="table-wrap"><table class="table"><thead><tr><th>Company</th><th>Phone</th><th>Mobile</th>
    <th>Salesperson</th><th>Source</th><th>Lead Status</th><th></th></tr></thead><tbody>
    ${cands.map((c, i) => `<tr><td><b>${esc(c.company_name || c.name)}</b>${c.company_name && c.name && c.name !== c.company_name ? `<div class="small muted">${esc(c.name)}</div>` : ""}</td>
      <td class="ltr">${orDash(c.phone)}</td><td class="ltr">${orDash(c.mobile)}</td><td>${orDash(c.salesperson)}</td>
      <td>${orDash([c.source, c.medium].filter(Boolean).join(" / "))}</td><td>${orDash(c.stage)}${c.active === false ? ' <span class="badge red">مؤرشف</span>' : ""}</td>
      <td><button class="btn primary sm" data-i="${i}">${btnLabel}</button></td></tr>`).join("")}
    </tbody></table></div>`;
}

function chooseCandidate(lead) {
  const cands = lead.candidates || [];
  Modal.open({
    title: "وجدنا أكثر من عميل", wide: true,
    html: `<p class="muted">اختر الـLead الصحيح. لن يتم الاختيار تلقائيًا ولن يتم إنشاء Lead جديد.</p>${candidateTable(cands, "اختيار")}`,
    buttons: [{ label: "إغلاق" }],
    onOpen: (m) => $$("button[data-i]", m).forEach((b) => b.onclick = () => withBusy(b, async () => {
      const c = cands[+b.dataset.i];
      Modal.close();
      await leadAction(`/api/lead/${lead.fingerprint}/select`, { odoo_id: c.id, ui_index: c.ui_index, ui_query: c.ui_query || "" }, "تم اختيار العميل");
    })),
  });
}

function askSkip(fp) {
  const modes = [["10m", "10 دقائق"], ["30m", "30 دقيقة"], ["today", "اليوم"], ["session", "تخطي للجلسة الحالية"]];
  Modal.open({
    title: "تخطي مؤقتًا",
    html: `<p class="muted">لن يتم تعديل Google Sheet. سيظهر العميل مرة أخرى لاحقًا.</p>
      <label class="field"><span>السبب (اختياري)</span><input type="text" id="skip-reason"></label>
      <div class="actions">${modes.map(([m, l]) => `<button class="btn lg" data-m="${m}">${l}</button>`).join("")}</div>`,
    buttons: [{ label: "إلغاء" }],
    onOpen: (m) => $$("button[data-m]", m).forEach((b) => b.onclick = async () => {
      const reason = $("#skip-reason").value;
      Modal.close();
      stopCall();
      try { render(await api("POST", `/api/lead/${fp}/skip`, { mode: b.dataset.m, reason })); toast("تم التخطي", "info"); }
      catch (e) { toast(e.message, "error"); }
    }),
  });
}

// -------------------------------------------------------------------- call
async function startCall(btn) {
  const manual = S.manual;
  if (!manual && (!S.lead || !S.lead.odoo_lead_id)) {
    toast("اربط العميل بـLead في Odoo أولًا (إعادة البحث).", "warn"); return;
  }
  await withBusy(btn, async () => {
    try {
      const r = manual ? await api("POST", "/api/manual/call", { odoo_id: manual.id })
                       : await api("POST", `/api/lead/${S.lead.fingerprint}/call`);
      S.call.startedAt = new Date(); S.call.endedAt = null;
      $("#call-banner").classList.remove("hidden");
      clearInterval(S.call.timer);
      S.call.timer = setInterval(() => { $("#call-timer").textContent = fmtDuration((Date.now() - S.call.startedAt) / 1000); }, 500);
      $("#call-timer").textContent = "00:00";
      toast(`تم تشغيل الاتصال من Odoo (${r.phone_field === "mobile" ? "Mobile" : "Phone"}). أكمل المكالمة من Phone Link.`, "success", 6000);
    } catch (e) { handleOdooError(e, () => startCall(btn)); }
  });
}
function stopCall() {
  if (S.call.startedAt && !S.call.endedAt) S.call.endedAt = new Date();
  clearInterval(S.call.timer);
  $("#call-banner").classList.add("hidden");
}

// ------------------------------------------------------------ result panel
async function loadOptions(key) {
  if (S.options[key]) return S.options[key];
  try { S.options[key] = (await api("GET", `/api/sheet/options/${key}`)).options; } catch (e) { S.options[key] = []; }
  return S.options[key];
}

function resultContext() {
  if (S.manual) {
    const o = S.manual;
    return { manual: true, fingerprint: null, odooId: o.id, company: o.company_name || o.name, phone: o.phone || o.mobile, source: null, lead: null };
  }
  const l = S.lead;
  return { manual: false, fingerprint: l.fingerprint, odooId: l.odoo_lead_id, company: l.company_name, phone: l.phone, source: l.source, lead: l };
}

async function openResultPanel() {
  if (!S.lead && !S.manual) return;
  const ctx = resultContext();
  S.result = { code: null, key: uuid(), ctx };
  const card = $("#result-card");
  const src = ctx.source || {};
  card.classList.remove("hidden");
  card.innerHTML = `<h2>تسجيل النتيجة — ${esc(ctx.company)}</h2>
    ${ctx.odooId ? "" : '<div class="alert warn">العميل غير مربوط بـLead في Odoo؛ لن تتم إضافة Log Note.</div>'}
    <div class="result-buttons">${S.statuses.map((s) => `<button type="button" class="result-btn" data-code="${s.code}">${esc(s.label)}</button>`).join("")}</div>
    <div style="margin-top:16px">
      <label class="field"><span>ملاحظة حرة</span><textarea id="r-note" placeholder="مثال: العميل مهتم بنظام رصد التواجد ويرغب في عرض سعر."></textarea></label>
      <div id="r-followup" class="form-grid hidden">
        <label class="field"><span>تاريخ المتابعة</span><input type="date" id="r-fdate"></label>
        <label class="field"><span>الوقت</span><input type="time" id="r-ftime"></label>
        <label class="field full"><span>ملاحظة المتابعة</span><input type="text" id="r-fnote"></label>
      </div>
      <div id="r-expiry" class="hidden"><label class="field"><span>تاريخ انتهاء الاشتراك (اختياري)</span><input type="date" id="r-exp"></label></div>
      <div id="r-reason" class="hidden"><label class="field"><span>سبب عدم الاشتراك (اختياري)</span>
        <input type="text" id="r-reason-in" list="reason-list"><datalist id="reason-list"></datalist></label></div>
      ${ctx.manual ? "" : `<label class="field"><span>مصدر العميل في Google Sheet</span><select id="r-source"><option value="">— بدون تغيير —</option></select></label>
      ${src.odoo_value && !src.mapped ? `<div class="alert warn"><b>المصدر غير مربوط:</b> Odoo = «${esc(src.odoo_value)}». اختر القيمة المناسبة من قائمة Sheet.
        <label class="check" style="display:flex;margin-top:8px"><input type="checkbox" id="r-save-map" checked> حفظ هذا الربط للاستخدام مستقبلًا</label></div>` : ""}`}
      <div class="row" style="margin:6px 0 12px">
        <label class="check"><input type="checkbox" id="r-sheet" ${ctx.manual ? "disabled" : "checked"}> تحديث Google Sheet</label>
        <label class="check"><input type="checkbox" id="r-odoo" ${ctx.odooId ? "checked" : "disabled"}> إضافة Log Note في Odoo</label>
      </div>
      ${ctx.manual ? '<div class="alert info small">وضع يدوي: العميل غير مربوط بصف مؤكد في Google Sheet، لذلك لن يتم تحديث Sheet.</div>' : ""}
      <div id="r-msg"></div>
      <div class="actions">
        <button class="btn success lg" id="r-save">${S.settings.dry_run ? "حفظ (Dry Run – معاينة)" : "حفظ النتيجة"}</button>
        <button class="btn" id="r-preview">معاينة التغييرات</button>
        <button class="btn ghost" id="r-cancel">إلغاء</button>
      </div>
    </div>`;
  $$(".result-btn", card).forEach((b) => b.onclick = () => selectResult(b.dataset.code));
  $("#r-cancel").onclick = () => card.classList.add("hidden");
  $("#r-save").onclick = (ev) => saveResult(ev.currentTarget, false);
  $("#r-preview").onclick = (ev) => saveResult(ev.currentTarget, true);
  card.scrollIntoView({ behavior: "smooth", block: "start" });
  if (!ctx.manual) {
    const opts = await loadOptions("source");
    const sel = $("#r-source");
    const all = [...opts];
    if (src.sheet_current && !all.includes(src.sheet_current)) all.unshift(src.sheet_current);
    all.forEach((v) => { const o = document.createElement("option"); o.value = v; o.textContent = v; sel.appendChild(o); });
    sel.value = src.prefill || "";
  }
  const reasons = await loadOptions("not_subscribed_reason");
  $("#reason-list").innerHTML = reasons.map((r) => `<option value="${esc(r)}">`).join("");
}

function selectResult(code) {
  S.result.code = code;
  $$(".result-btn").forEach((b) => b.classList.toggle("selected", b.dataset.code === code));
  $("#r-followup").classList.toggle("hidden", code !== "FOLLOW_UP");
  $("#r-expiry").classList.toggle("hidden", code !== "SUBSCRIBED");
  $("#r-reason").classList.toggle("hidden", code !== "NOT_INTERESTED");
  if (code === "FOLLOW_UP" && !$("#r-fdate").value) {
    const d = new Date(Date.now() + 86400000);
    $("#r-fdate").value = d.toISOString().slice(0, 10);
    $("#r-ftime").value = "10:00";
  }
}

function buildResultBody(previewOnly) {
  const ctx = S.result.ctx;
  const srcSel = $("#r-source");
  const mapBox = $("#r-save-map");
  return {
    idempotency_key: previewOnly ? uuid() : S.result.key,
    fingerprint: ctx.fingerprint, odoo_lead_id: ctx.odooId || null, result_code: S.result.code,
    note: $("#r-note").value,
    source_value: srcSel ? srcSel.value : "",
    save_source_mapping: !!(mapBox && mapBox.checked && srcSel && srcSel.value),
    source_odoo_value: ctx.source ? (ctx.source.odoo_value || "") : "",
    not_subscribed_reason: S.result.code === "NOT_INTERESTED" ? $("#r-reason-in").value : "",
    subscription_expiry: S.result.code === "SUBSCRIBED" ? $("#r-exp").value : "",
    followup_date: S.result.code === "FOLLOW_UP" ? $("#r-fdate").value : "",
    followup_time: S.result.code === "FOLLOW_UP" ? $("#r-ftime").value : "",
    followup_note: S.result.code === "FOLLOW_UP" ? $("#r-fnote").value : "",
    update_sheet: $("#r-sheet").checked, add_odoo_note: $("#r-odoo").checked,
    call_started_at: S.call.startedAt ? S.call.startedAt.toISOString() : null,
    call_ended_at: S.call.startedAt ? (S.call.endedAt || new Date()).toISOString() : null,
    manual_company: ctx.manual ? ctx.company || "" : "", manual_phone: ctx.manual ? ctx.phone || "" : "",
  };
}

async function saveResult(btn, previewOnly) {
  if (!S.result.code) { toast("اختر نتيجة التواصل أولًا", "warn"); return; }
  if (S.busy) return;               // double-click protection (plus server idempotency key)
  S.busy = true;
  $("#r-save").disabled = true;
  $("#r-msg").innerHTML = "";
  try {
    await withBusy(btn, async () => {
      const res = await api("POST", previewOnly ? "/api/result/preview" : "/api/result", buildResultBody(previewOnly));
      if (previewOnly) { showPreview(res, "معاينة التغييرات (Would update)"); return; }
      if (res.dry_run) { showPreview(res, "Dry Run — لم يتم تعديل أي نظام", () => afterSave(res)); return; }
      toast(res.message, res.status === "done" ? "success" : "warn", 6000);
      (res.warnings || []).forEach((w) => toast(w, "warn", 8000));
      afterSave(res);
    });
  } catch (e) {
    showError(e, $("#r-msg"), { retry: () => saveResult(btn, previewOnly) });
  } finally {
    S.busy = false;
    const b = $("#r-save"); if (b) b.disabled = false;
  }
}

function showPreview(res, title, onClose) {
  const p = res.preview || {};
  const sheet = (p.sheet || []).map((c) => `<tr><td><b>Sheet ${esc(c.column)}</b></td><td class="pre">${orDash(c.old)}</td><td class="pre">${orDash(c.new)}</td></tr>`).join("");
  const html = `<p><b>Would update:</b></p>
    ${p.sheet_error ? `<div class="alert error">${esc(p.sheet_error)}</div>` : ""}
    ${sheet ? `<div class="table-wrap"><table class="table"><thead><tr><th>الحقل</th><th>القيمة الحالية</th><th>القيمة الجديدة</th></tr></thead><tbody>${sheet}</tbody></table></div>` : (p.sheet_error ? "" : '<div class="muted">لا تغييرات على Google Sheet.</div>')}
    <h3 style="margin-top:16px">Odoo Note</h3>${p.odoo_note ? `<div class="info note-box">${esc(p.odoo_note)}</div>` : '<div class="muted">لن تتم إضافة ملاحظة.</div>'}
    ${p.activity ? `<h3 style="margin-top:16px">Odoo Activity</h3><div class="info">${esc(p.activity.date_deadline)} — ${esc(p.activity.summary)}<div class="small muted">${esc(p.activity.note || "")}</div></div>` : ""}
    ${(res.warnings || []).map((w) => `<div class="alert warn" style="margin-top:10px">${esc(w)}</div>`).join("")}`;
  Modal.open({ title, html, wide: true, buttons: [{ label: onClose ? "متابعة" : "إغلاق", cls: "primary", onClick: () => { Modal.close(); if (onClose) onClose(); } }] });
}

// ------------------------------------------------------------- next lead
function afterSave(res) {
  stopCall();
  S.call = { startedAt: null, endedAt: null, timer: null };
  $("#result-card").classList.add("hidden");
  if (S.manual) { S.manual = null; loadCurrent(); return; }
  const card = $("#next-card");
  card.classList.remove("hidden");
  if (res.next_delay === null || res.next_delay === undefined) {
    card.innerHTML = `<div class="row between"><b>${esc(res.message)}</b><button class="btn primary" id="btn-next">العميل التالي</button></div>`;
    $("#btn-next").onclick = goNext;
    return;
  }
  let left = res.next_delay;
  const draw = () => {
    card.innerHTML = `<div class="countdown"><b>${esc(res.message)}</b><span class="spacer"></span>
      <span>الانتقال للعميل التالي خلال <b>${left}</b> ثوانٍ</span>
      <button class="btn" id="btn-cancel-next">إلغاء الانتقال</button><button class="btn primary" id="btn-next">الانتقال الآن</button></div>`;
    $("#btn-cancel-next").onclick = () => {
      clearInterval(S.nextTimer);
      card.innerHTML = `<div class="row between"><span>تم إلغاء الانتقال التلقائي.</span><button class="btn primary" id="btn-next">العميل التالي</button></div>`;
      $("#btn-next").onclick = goNext;
    };
    $("#btn-next").onclick = goNext;
  };
  draw();
  clearInterval(S.nextTimer);
  S.nextTimer = setInterval(() => { left -= 1; if (left <= 0) { goNext(); } else draw(); }, 1000);
}

async function goNext() {
  clearInterval(S.nextTimer);
  $("#next-card").classList.add("hidden");
  $("#lead-card").innerHTML = '<div class="empty"><span class="spinner"></span> جاري تحميل العميل التالي…</div>';
  try { render(await api("POST", "/api/lead/next")); } catch (e) { renderFatal(e, goNext); }
}

// ------------------------------------------------------------ manual mode
async function manualSearch() {
  const q = $("#manual-q").value.trim();
  if (!q) return;
  try {
    const r = await api("POST", "/api/manual/search", { query: q });
    const cands = r.candidates || [];
    Modal.open({
      title: `نتائج البحث في Odoo: ${q}`, wide: true,
      html: cands.length ? candidateTable(cands, "فتح") : '<div class="empty">لم يتم العثور على نتائج.</div>',
      buttons: [{ label: "إغلاق" }],
      onOpen: (m) => $$("button[data-i]", m).forEach((b) => b.onclick = () => withBusy(b, () => manualOpen(cands[+b.dataset.i]))),
    });
  } catch (e) {
    if (e.code === "ODOO_LOGIN_REQUIRED") { renderLoginRequired(manualSearch); return; }
    toast(e.message, "error");
  }
}

async function manualOpen(c) {
  if (c.id === null || c.id === undefined) { toast("افتح هذا العميل من Odoo مباشرة.", "warn"); return; }
  try {
    const r = await api("POST", "/api/manual/open", { odoo_id: c.id });
    Modal.close();
    if (r.linked) { S.manual = null; render(r); (r.warnings || []).forEach((w) => toast(w, "info")); return; }
    S.manual = r.odoo;
    renderManual(r.odoo, r.warnings || []);
  } catch (e) { toast(e.message, "error"); }
}

function renderManual(o, warnings) {
  $("#result-card").classList.add("hidden");
  $("#lead-card").innerHTML = `
    <div class="row small"><span class="badge amber">وضع البحث اليدوي</span></div>
    <h2 class="lead-name">${esc(o.company_name || o.name)}</h2>
    <div class="lead-phone"><span class="ltr">${esc(o.phone || o.mobile || "")}</span></div>
    ${warnings.map((w) => `<div class="alert warn" style="margin-top:12px">${esc(w)}</div>`).join("")}
    <div class="info-grid">
      <div class="info"><div class="k">Source</div><div class="v">${orDash(o.source)}</div></div>
      <div class="info"><div class="k">Medium</div><div class="v">${orDash(o.medium)}</div></div>
      <div class="info"><div class="k">Campaign</div><div class="v">${orDash(o.campaign)}</div></div>
    </div>
    <div class="actions">
      <button class="btn call" id="btn-call">${PHONE_ICON} اتصال الآن</button>
      <button class="btn" id="btn-result">تسجيل النتيجة</button>
      <button class="btn ghost" id="btn-exit-manual">العودة لقائمة العمل</button>
    </div><div id="lead-msg" style="margin-top:12px"></div>`;
  renderOdoo(o);
  $("#btn-call").onclick = (ev) => startCall(ev.currentTarget);
  $("#btn-result").onclick = () => openResultPanel();
  $("#btn-exit-manual").onclick = () => { stopCall(); loadCurrent(); };
}
