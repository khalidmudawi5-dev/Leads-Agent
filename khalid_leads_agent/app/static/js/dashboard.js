/* Dashboard workflow: current lead → Odoo match → call → result → next lead. */
"use strict";

const S = {
  payload: null, lead: null, manual: null, settings: null, statuses: [],
  call: { startedAt: null, endedAt: null, timer: null },
  result: { code: null, key: null, ctx: null },
  options: {}, nextTimer: null, busy: false,
  chatterFilter: "all", seenChatter: { key: null, ids: new Set() },
};
const ICON = {
  wa: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2a8.2 8.2 0 0 1-4.2-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2zm4.5-6.1c-.2-.1-1.5-.7-1.7-.8-.2-.1-.4-.1-.6.1l-.8 1c-.1.2-.3.2-.5.1a6.7 6.7 0 0 1-3.3-2.9c-.2-.4.2-.4.7-1.3.1-.2 0-.3 0-.4l-.8-1.8c-.2-.5-.4-.4-.6-.4h-.5a1 1 0 0 0-.7.3 3 3 0 0 0-.9 2.2 5.2 5.2 0 0 0 1.1 2.7 11.8 11.8 0 0 0 4.5 4c1.7.7 2.4.8 3.2.6.5-.1 1.5-.6 1.8-1.2.2-.6.2-1.1.1-1.2l-.5-.2z"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  note: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v12H8l-4 4z"/><path d="M8 9h8M8 12h5"/></svg>',
  message: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></svg>',
  email: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>',
  tracking: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12h16M14 6l6 6-6 6"/></svg>',
  system: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16v.5"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  open: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 3h7v7M21 3l-9 9"/><path d="M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/></svg>',
  skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 5l7 7-7 7M13 5l7 7-7 7"/></svg>',
  result: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3 8-8"/><path d="M20 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
};
const KIND_LABEL = { note: "ملاحظة داخلية", message: "رسالة", email: "بريد", tracking: "تغيير", system: "نظام" };
const FILTERS = [["all", "الكل"], ["note", "الملاحظات"], ["message", "الرسائل"], ["tracking", "التغييرات"]];
const PHONE_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/></svg>';
const STRATEGY = { phone: "رقم الهاتف", mobile: "رقم الجوال", "phone+company": "الهاتف + اسم المنشأة", company_exact: "اسم المنشأة (مطابق)", user_choice: "اختيار يدوي" };

// ------------------------------------------------------------------ boot
document.addEventListener("DOMContentLoaded", init);
document.addEventListener("agent-status", (e) => {
  $("#dry-ribbon").classList.toggle("hidden", !e.detail.dry_run);
  S.remote = !!e.detail.remote;  // opened from the phone / another device (Tailscale)
});
document.addEventListener("dry-run-changed", (e) => {
  if (S.settings) S.settings.dry_run = e.detail.dry_run;
  const b = $("#r-save");
  if (b) b.innerHTML = `${e.detail.dry_run ? "حفظ (Dry Run – معاينة)" : "حفظ النتيجة"} <kbd>Ctrl ↵</kbd>`;
  updateWriteSummary();
});

let handlersBound = false;
function bindPageHandlers() {
  // Bound once and before any early return (e.g. the "resume session?" dialog).
  if (handlersBound) return;
  handlersBound = true;
  $("#manual-form").onsubmit = (ev) => { ev.preventDefault(); manualSearch(); };
  $$("#stats .stat").forEach((b) => b.onclick = () => openCard(b.dataset.go));
  $("#btn-refresh-queue").onclick = (ev) => withBusy(ev.currentTarget, refreshQueue);
  $("#btn-end-call").onclick = () => { stopCall(); openResultPanel(); };
  $("#btn-result-from-call").onclick = () => { stopCall(); openResultPanel(); };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) Live.poll(); });
}

async function init() {
  bindPageHandlers();
  try {
    const [st, cfg] = await Promise.all([api("GET", "/api/settings/status-mapping"), api("GET", "/api/settings")]);
    S.statuses = st.items; S.settings = cfg.settings;
    $("#dry-ribbon").classList.toggle("hidden", !S.settings.dry_run);
    SheetWatch.start();
    const updateId = new URLSearchParams(location.search).get("update");
    const sess = await api("GET", "/api/session");
    if (sess.needs_prompt && !updateId) return askResume(sess.session);
    await api("POST", "/api/session/start", { resume: true });
    await loadCurrent();
    loadFilter();
    if (updateId) {
      history.replaceState(null, "", "/");
      await openUpdate(updateId);
    }
  } catch (e) { showError(e, $("#lead-card"), { retry: init }); }
}

// ------------------------------------------------------------- shortcuts
const hasLead = () => !!(S.manual || S.lead);
const resultOpen = () => !$("#result-card").classList.contains("hidden");
const nextVisible = () => !$("#next-card").classList.contains("hidden") && !!$("#btn-next");
const clickIf = (sel) => { const b = $(sel); if (b && !b.disabled) b.click(); };
Shortcuts.register([
  { code: "KeyC", label: "C", title: "اتصال الآن", group: "العميل الحالي", when: hasLead, run: () => clickIf("#btn-call") },
  { code: "KeyO", label: "O", title: "فتح العميل في Odoo", group: "العميل الحالي", when: () => !!S.lead && !S.manual, run: () => clickIf("#btn-open") },
  { code: "KeyR", label: "R", shift: false, title: "تسجيل النتيجة", group: "العميل الحالي", when: () => hasLead() && !resultOpen(), run: () => { stopCall(); openResultPanel(); } },
  { code: "KeyF", label: "F", title: "إعادة البحث في Odoo", group: "العميل الحالي", when: () => !!S.lead && !S.manual, run: () => searchOdoo() },
  { code: "KeyU", label: "U", title: "تحديث من Google Sheet (عملاء جدد + بيانات العميل)", group: "العميل الحالي", when: () => !S.manual && !resultOpen(),
    run: () => { if ($("#btn-refresh")) clickIf("#btn-refresh"); else clickIf("#btn-refresh-queue"); } },
  { code: "KeyS", label: "S", title: "تخطي مؤقتًا", group: "العميل الحالي", when: () => !!S.lead && !S.manual, run: () => askSkip(S.lead.fingerprint) },
  { code: "KeyA", label: "A", title: "إضافة العميل غير الموجود إلى Odoo", group: "العميل الحالي", when: () => !!S.lead && !S.manual && !!$("#btn-create"), run: () => clickIf("#btn-create") },
  { code: "KeyW", label: "W", title: "رسالة واتساب للعميل", group: "العميل الحالي", when: () => !!S.lead && !S.manual && !resultOpen(), run: () => clickIf("#btn-wa") },
  { code: "KeyP", label: "P", title: "نسخ رقم الجوال", group: "العميل الحالي", when: hasLead, run: copyPhone },
  { code: "KeyN", label: "N", title: "العميل التالي (بعد الحفظ)", group: "العميل الحالي", when: nextVisible, run: goNext },
  { code: "KeyR", label: "R", shift: true, title: "تحديث القائمة من Google Sheet", group: "عام", run: () => $("#btn-refresh-queue").click() },
  { code: "Slash", label: "/", shift: false, title: "البحث اليدوي في Odoo", group: "عام", run: () => { $("#manual-q").focus(); $("#manual-q").select(); } },
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({ code: `Digit${n}`, label: String(n), title: n === 1 ? "اختيار النتيجة (1 … 6)" : "",
    group: "لوحة النتيجة", when: () => resultOpen() && !!S.statuses[n - 1], run: () => selectResult(S.statuses[n - 1].code) })),
  ...[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => ({ code: `Numpad${n}`, label: String(n),
    when: () => resultOpen() && !!S.statuses[n - 1], run: () => selectResult(S.statuses[n - 1].code) })),
  { code: "KeyT", label: "T", title: "الانتقال لحقل الملاحظة", group: "لوحة النتيجة", when: resultOpen, run: () => $("#r-note").focus() },
  { code: "KeyM", label: "M", title: "إملاء الملاحظة بالصوت (تشغيل / إيقاف)", group: "لوحة النتيجة", when: () => resultOpen() && !!$("#r-mic"), run: () => clickIf("#r-mic") },
  { code: "Enter", label: "Enter", ctrl: true, allowInInputs: true, title: "حفظ النتيجة", group: "لوحة النتيجة", when: resultOpen, run: () => clickIf("#r-save") },
  { code: "Escape", label: "Esc", allowInInputs: true, title: "إلغاء لوحة النتيجة / إلغاء الانتقال التلقائي", group: "لوحة النتيجة",
    when: () => resultOpen() || !!$("#btn-cancel-next"), run: () => { if ($("#btn-cancel-next")) $("#btn-cancel-next").click(); else $("#r-cancel").click(); } },
]);

async function copyPhone() {
  const phone = S.manual ? (S.manual.phone || S.manual.mobile) : (S.lead && S.lead.phone);
  if (!phone) return;
  try { await navigator.clipboard.writeText(phone); toast("تم نسخ الرقم: " + phone, "info", 2500); }
  catch (e) { toast("تعذر النسخ", "warn"); }
}

// ------------------------------------------------------------- live sync
/** Polls Odoo for changes on the open lead; any edit made in Odoo shows up here within seconds. */
const Live = {
  target: null, sig: "", timer: null, inflight: false, state: "off", lastOk: null,
  enabled() { return !!(S.settings && S.settings.live_sync_enabled); },
  interval() { return Math.max(2, (S.settings && S.settings.live_sync_interval_seconds) || 5) * 1000; },
  watch(target) {
    const key = target ? `${target.kind}:${target.id}` : null;
    if (key && this.target && `${this.target.kind}:${this.target.id}` === key) return;
    this.stop();
    if (!target) { this.pill("off", "غير مربوط"); return; }
    if (!this.enabled()) { this.pill("off", "المزامنة المباشرة متوقفة"); return; }
    this.target = target; this.sig = "";
    this.pill("on", "مباشر");
    this.poll();
    this.timer = setInterval(() => this.poll(), this.interval());
  },
  stop() { clearInterval(this.timer); this.timer = null; this.target = null; this.sig = ""; },
  pill(state, text) {
    this.state = state;
    const p = $("#live-pill"); if (!p) return;
    p.className = "live-pill" + (state === "on" ? "" : state === "err" ? " err" : " off");
    $(".t", p).textContent = text;
    p.title = state === "on" ? "أي تعديل على العميل في Odoo (حقول، ملاحظات، أنشطة) يظهر هنا تلقائيًا." : "";
  },
  async poll() {
    const t = this.target;
    if (!t || this.inflight || document.hidden) return;
    this.inflight = true;
    const url = t.kind === "queue" ? `/api/lead/${t.id}/live` : `/api/manual/${t.id}/live`;
    try {
      const r = await api("GET", `${url}?since=${encodeURIComponent(this.sig)}`);
      if (this.target !== t) return;  // user moved to another lead meanwhile
      this.sig = r.signature || this.sig;
      if (r.login_required) this.pill("err", "تسجيل الدخول مطلوب");
      else if (r.error) this.pill("err", "تعذر الفحص");
      else { this.lastOk = new Date(); this.pill("on", "مباشر"); }
      if (r.changed) applyLiveUpdate(t, r);
    } catch (e) { this.pill("err", "غير متصل"); }
    finally { this.inflight = false; }
  },
};

function applyLiveUpdate(target, r) {
  if (target.kind === "queue") {
    if (!r.lead || !S.lead || r.lead.fingerprint !== S.lead.fingerprint) return;
    S.lead = r.lead;
    if (S.payload) S.payload.lead = r.lead;
    renderStats(r.stats);
    if (!resultOpen() && !S.call.startedAt) renderLead(r.lead);
    renderOdoo(r.lead.odoo);
    renderChatter(r.lead.odoo, true);
    (r.notices || []).forEach((n) => toast(n, "success", 7000));
  } else {
    if (!S.manual || !r.odoo || r.odoo.id !== S.manual.id) return;
    S.manual = r.odoo;
    renderOdoo(r.odoo);
    renderChatter(r.odoo, true);
  }
  toast("تم تحديث بيانات العميل من Odoo تلقائيًا", "info", 3000);
  ["#chatter-card", "#odoo-card"].forEach((sel) => { const el = $(sel); el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash"); });
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
      { label: "استكمال الجلسة", cls: "primary", onClick: async () => { Modal.close(); await api("POST", "/api/session/start", { resume: true }); await loadCurrent(); loadFilter(); } },
      { label: "بدء جلسة جديدة", onClick: async () => { Modal.close(); await api("POST", "/api/session/start", { resume: false }); await loadCurrent(); loadFilter(); } },
    ],
  });
}

async function loadCurrent() {
  S.manual = null;
  try { render(await api("GET", "/api/lead/current")); }
  catch (e) { renderFatal(e, loadCurrent); }
}
async function refreshQueue() { return refreshAll(null); }

/**
 * «تحديث» (U) / «تحديث القائمة» (Shift+R): reconnect to Google, read new customers from the sheet,
 * refresh counts, the status filter, the connection chips and the current lead — no page reload.
 */
async function refreshAll(fp) {
  let payload;
  try {
    payload = fp ? await api("POST", `/api/lead/${fp}/refresh`) : await api("POST", "/api/queue/refresh");
  } catch (e) {
    refreshStatus();
    if (fp) handleOdooError(e, () => refreshAll(fp)); else renderFatal(e, refreshQueue);
    return;
  }
  render(payload);
  if (payload.filter) renderFilter(payload.filter.options);
  refreshStatus();
  const r = payload.refresh || {};
  if ((payload.warnings || []).length) toast("تم التحديث مع تنبيهات — راجع أعلى الصفحة.", "warn", 6000);
  else toast(r.new ? `تم التحديث — ${r.new} ${r.new === 1 ? "عميل جديد" : "عملاء جدد"} في الملف · بانتظار التواصل: ${r.pending}`
                   : `تم التحديث من Google Sheet · بانتظار التواصل: ${r.pending ?? "–"}`, "success", 5000);
}

// ---------------------------------------------------------- status filter
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2"><path d="M20 6L9 17l-5-5"/></svg>';
S.filter = { options: [], busy: false };

async function loadFilter() {
  try { renderFilter((await api("GET", "/api/queue/filter")).options); }
  catch (e) { $("#fb-chips").innerHTML = `<span class="small muted">${esc(e.message)}</span>`; }
}

function renderFilter(options) {
  // Stable, aligned order: «فارغة» first, then by number of leads (most first).
  const list = (options || []).map((o, i) => ({ ...o, _i: i }));
  list.sort((a, b) => (b.empty - a.empty) || (b.count - a.count) || (a._i - b._i));
  S.filter.options = list;
  const sel = list.filter((o) => o.selected);
  const sum = $("#fb-sum");
  if (sum) sum.textContent = sel.length ? `(${sel.length} حالة مختارة · ${sel.reduce((n, o) => n + o.count, 0)} عميل)` : "";
  $("#fb-chips").innerHTML = list.map((o, i) => `<button type="button" class="fchip ${o.selected ? "on" : ""} ${o.empty ? "empty-status" : ""}" data-i="${i}"
      title="${o.empty ? "الصفوف التي خلية «حالة المتابعة» فيها فارغة" : esc(o.value)}"><span class="box">${CHECK}</span>
      <span class="t">${o.empty ? "فارغة (بدون حالة)" : esc(o.value)}</span><span class="n">${o.count}</span></button>`).join("")
    || '<span class="small muted">لا توجد حالات بعد. حدّث القائمة من Google Sheet.</span>';
  $$("#fb-chips .fchip").forEach((b) => b.onclick = () => toggleFilter(+b.dataset.i));
}

// ------------------------------------------------------------ stat cards
const LIST_TITLES = { pending: "العملاء بانتظار التواصل", all: "كل العملاء المسندين إليك", match_errors: "عملاء لم تتم مطابقتهم في Odoo",
  followups: "المتابعات المجدولة", duplicates: "أرقام مكررة في Google Sheet" };
const FU_STATE = { overdue: ["red", "متأخرة"], due: ["amber", "اليوم"], upcoming: ["blue", "قادمة"] };
const MATCH_AR = { matched: ["green", "مطابق"], multiple: ["amber", "أكثر من نتيجة"], not_found: ["red", "غير موجود"], error: ["red", "خطأ"], unknown: ["", "لم يُبحث"] };

function openCard(go) {
  const [type, arg] = (go || "").split(":");
  if (type === "hist") { location.href = "/history?period=today" + (arg ? `&result=${encodeURIComponent(arg)}` : ""); return; }
  if (type === "list") showLeadList(arg);
}

async function showLeadList(kind) {
  let r;
  try { r = await api("GET", `/api/queue/list?kind=${kind}`); } catch (e) { toast(e.message, "error"); return; }
  const items = r.items || [];
  Modal.open({
    title: `${LIST_TITLES[kind] || "العملاء"} (${items.length})`, wide: true,
    html: items.length ? `<input type="search" id="ll-q" placeholder="بحث بالاسم أو الرقم…" style="margin-bottom:12px">
      <div class="table-wrap"><table class="table hist"><thead><tr>${LIST_HEAD[kind] || LIST_HEAD.default}</tr></thead><tbody>
      ${kind === "followups" ? followupRows(items) : kind === "duplicates" ? duplicateRows(items) : items.map((i, n) => { const [mc, ml] = MATCH_AR[i.match] || MATCH_AR.unknown; return `<tr data-s="${esc((i.company + " " + i.phone).toLowerCase())}">
        <td class="muted">${i.row}</td><td><b>${esc(i.company || "—")}</b>${i.current ? ' <span class="badge indigo">الحالي</span>' : ""}${!i.pending && kind !== "pending" ? ' <span class="badge">خارج الفلتر/تم</span>' : ""}</td>
        <td><span class="phone">${orDash(i.phone)}</span></td><td>${i.status ? `<span class="pill">${esc(i.status)}</span>` : '<span class="muted">فارغة</span>'}</td>
        <td><span class="badge ${mc}">${ml}</span></td><td><button class="btn sm primary" data-i="${n}">فتح</button></td></tr>`; }).join("")}
      </tbody></table></div>` : '<div class="empty">لا يوجد عملاء في هذه القائمة.</div>',
    buttons: [{ label: "إغلاق" }],
    onOpen: (m) => {
      const q = $("#ll-q", m);
      if (q) q.oninput = () => { const v = q.value.trim().toLowerCase(); $$("tbody tr", m).forEach((tr) => { tr.style.display = !v || tr.dataset.s.includes(v) ? "" : "none"; }); };
      $$("button[data-i]", m).forEach((b) => b.onclick = () => withBusy(b, async () => {
        try {
          const payload = await api("POST", `/api/lead/${items[+b.dataset.i].fingerprint}/goto`);
          Modal.close(); stopCall(); S.manual = null; render(payload);
          $("#lead-card").scrollIntoView({ behavior: "smooth", block: "start" });
        } catch (e) { toast(e.message, "error"); }
      }));
    },
  });
}

const LIST_HEAD = {
  default: "<th>#</th><th>العميل</th><th>الهاتف</th><th>حالة المتابعة</th><th>Odoo</th><th></th>",
  followups: "<th>#</th><th>العميل</th><th>الهاتف</th><th>موعد المتابعة</th><th>ملاحظة</th><th></th>",
  duplicates: "<th>#</th><th>العميل</th><th>الهاتف</th><th>نفس الرقم في</th><th></th><th></th>",
};
function followupRows(items) {
  return items.map((i, n) => { const [c, l] = FU_STATE[i.state] || ["", ""]; return `<tr data-s="${esc((i.company + " " + i.phone).toLowerCase())}">
    <td class="muted">${i.row}</td><td><b>${esc(i.company || "—")}</b></td><td><span class="phone">${orDash(i.phone)}</span></td>
    <td><span class="badge ${c}">${l}</span> <span class="ltr">${esc(i.followup_at)}</span></td><td class="small">${orDash(i.note)}</td>
    <td><button class="btn sm primary" data-i="${n}">فتح</button></td></tr>`; }).join("");
}
function duplicateRows(items) {
  return items.map((i, n) => `<tr data-s="${esc((i.company + " " + i.phone).toLowerCase())}">
    <td class="muted">${i.row}</td><td><b>${esc(i.company || "—")}</b></td><td><span class="phone">${orDash(i.phone)}</span></td>
    <td class="small">${i.others.map((o) => `صف ${o.row}: ${esc(o.company || "—")} <span class="muted">(${esc(o.owner || "بدون مسؤول")}${o.status ? " · " + esc(o.status) : ""})</span>`).join("<br>")}</td>
    <td></td><td><button class="btn sm primary" data-i="${n}">فتح</button></td></tr>`).join("");
}

// ------------------------------------------------------------ new customers in the sheet
/** Every «sheet_poll_minutes» (tab visible): re-read the sheet and announce new customers. */
const SheetWatch = {
  timer: null, unseen: 0, title: document.title,
  start() {
    const min = (S.settings && S.settings.sheet_poll_minutes) || 0;
    clearInterval(this.timer);
    if (!min) return;
    this.timer = setInterval(() => this.tick(), min * 60000);
    window.addEventListener("focus", () => { this.unseen = 0; document.title = this.title; });
  },
  async tick() {
    if (document.hidden) return;
    let r;
    try { r = await api("GET", "/api/queue/check"); } catch (e) { return; }  // quiet: next tick retries
    if (!r.checked || !r.new) return;
    renderStats(r.stats);
    renderBanner(r.stats);
    const names = (r.names || []).join("، ");
    toast(`🆕 ${r.new === 1 ? "عميل جديد" : `${r.new} عملاء جدد`} في Google Sheet${names ? `: ${names}` : ""}`, "info", 9000);
    if (!document.hasFocus()) { this.unseen += r.new; document.title = `(${this.unseen} جديد) ${this.title}`; }
    if (S.payload && S.payload.done && !resultOpen()) loadCurrent();  // the list was finished: show the new one
  },
};

// ------------------------------------------------------------ voice dictation
const MIC_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>';
/**
 * Dictate the result note (Arabic) with the browser's speech recognition (Chrome / Edge).
 * It only fills the note: the user reads it, fixes it and chooses the result before saving.
 * Browsers allow the microphone only on https or localhost, so on the PC it works; on the phone
 * (plain http over Tailscale) the keyboard's own microphone is used instead.
 */
const Dictation = {
  rec: null, target: null, btn: null, base: "",
  supported() { return !!(window.SpeechRecognition || window.webkitSpeechRecognition) && window.isSecureContext; },
  toggle(target, btn) { if (this.rec) this.stop(); else this.start(target, btn); },
  start(target, btn) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.lang = "ar-SA"; rec.continuous = true; rec.interimResults = true;
    this.rec = rec; this.target = target; this.btn = btn;
    this.base = target.value.trim() ? target.value.trim() + " " : "";
    rec.onresult = (ev) => {
      let finalText = "", interim = "";
      for (let i = 0; i < ev.results.length; i++) {
        const r = ev.results[i];
        if (r.isFinal) finalText += r[0].transcript + " "; else interim += r[0].transcript;
      }
      target.value = (this.base + finalText + interim).replace(/\s+/g, " ").trimStart();
      target.dispatchEvent(new Event("input"));
    };
    rec.onerror = (ev) => {
      const msg = ev.error === "not-allowed" || ev.error === "service-not-allowed" ? "اسمح للمتصفح باستخدام الميكروفون ثم أعد المحاولة."
        : ev.error === "network" ? "الإملاء يحتاج اتصال إنترنت." : ev.error === "no-speech" ? "لم يُسمع كلام." : "";
      if (msg) toast(msg, "warn", 6000);
    };
    rec.onend = () => this.stop();
    try { rec.start(); } catch (e) { this.stop(); return; }
    btn.classList.add("recording");
    $("span", btn).textContent = "جاري الاستماع… اضغط للإيقاف";
    target.focus();
  },
  stop() {
    if (this.rec) { const r = this.rec; this.rec = null; try { r.stop(); } catch (e) { /* already stopped */ } }
    if (this.btn) { this.btn.classList.remove("recording"); const s = $("span", this.btn); if (s) s.textContent = "إملاء بالصوت"; }
  },
};

// ------------------------------------------------------------ daily goal
function renderGoal(st) {
  const box = $("#goal");
  if (!box) return;
  const goal = st.goal || 0, done = st.contacted || 0;
  box.classList.toggle("hidden", !goal);
  if (!goal) return;
  const pctDone = Math.min(100, Math.round((done / goal) * 100));
  const reached = done >= goal;
  box.classList.toggle("done", reached);
  box.setAttribute("aria-valuemax", goal); box.setAttribute("aria-valuenow", done);
  box.innerHTML = `<span class="g-label">هدف اليوم</span><span class="g-track"><span class="g-fill" style="width:${pctDone}%"></span></span>
    <span class="g-num">${done} / ${goal} ${reached ? "🎉 تم تحقيق الهدف" : `(${pctDone}%)`}</span>`;
  if (reached && S.goalShown !== new Date().toDateString()) {
    if (S.goalShown !== undefined) toast(`أحسنت! وصلت لهدف اليوم (${goal}).`, "success", 6000);
    S.goalShown = new Date().toDateString();
  } else if (!reached && S.goalShown === undefined) S.goalShown = null;
}

// ------------------------------------------------ follow-ups / duplicates banner
function renderBanner(st) {
  const box = $("#fu-banner");
  if (!box || !st) return;
  const parts = [];
  if (st.followups_due) {
    parts.push(`<div class="alert ${st.followups_overdue ? "error" : "info"} banner-row"><span>📅 <b>لديك ${st.followups_due} ${st.followups_due === 1 ? "متابعة" : "متابعات"} اليوم</b>${st.followups_overdue ? ` (منها ${st.followups_overdue} متأخرة)` : ""} — تظهر أولًا في القائمة.</span>
      <button class="btn sm" data-list="followups">عرض المتابعات</button></div>`);
  }
  if (st.duplicates) {
    parts.push(`<div class="alert warn banner-row"><span>⚠ <b>${st.duplicates} ${st.duplicates === 1 ? "رقم مكرر" : "أرقام مكررة"}</b> في Google Sheet (نفس الرقم في أكثر من صف).</span>
      <button class="btn sm" data-list="duplicates">عرض</button></div>`);
  }
  box.innerHTML = parts.join("");
  $$("[data-list]", box).forEach((b) => b.onclick = () => showLeadList(b.dataset.list));
}

// ---------------------------------------------- no answer / follow-up / duplicates on the card
function outcomeAlerts(lead) {
  const o = lead.outcome || {};
  const out = [];
  if (o.followup_state) {
    const [c, l] = FU_STATE[o.followup_state];
    out.push(`<div class="alert ${o.followup_state === "overdue" ? "error" : o.followup_state === "due" ? "warn" : "info"}">
      📅 <b>متابعة ${l === "قادمة" ? "مجدولة" : l}:</b> <span class="ltr">${esc(o.followup_at)}</span>${o.followup_note ? ` — ${esc(o.followup_note)}` : ""}</div>`);
  }
  if (o.no_answer_streak) {
    if (o.attempts_reached) {
      out.push(`<div class="alert warn"><b>العميل لم يرد ${o.no_answer_streak} ${o.no_answer_streak <= 10 ? "مرات" : "مرة"} متتالية</b> (آخرها ${esc(o.last_at)}).
        <div class="actions"><button class="btn sm wa" data-oc="wa">${ICON.wa} إرسال واتساب</button>
        <button class="btn sm" data-oc="invalid">تسجيل: بيانات التواصل غير صحيحة</button></div></div>`);
    } else {
      out.push(`<div class="alert info">لم يرد ${o.no_answer_streak === 1 ? "مرة واحدة" : `${o.no_answer_streak} مرات`} (آخرها ${esc(o.last_at)})${o.max_attempts ? ` · المحاولة ${o.no_answer_streak + 1} من ${o.max_attempts}` : ""}</div>`);
    }
  }
  if ((lead.duplicates || []).length) {
    out.push(`<div class="alert warn">⚠ <b>هذا الرقم مكرر في Google Sheet:</b> ${lead.duplicates.map((d) => `صف ${d.row} — ${esc(d.company || "—")} (${esc(d.owner || "بدون مسؤول")}${d.status ? " · " + esc(d.status) : ""})`).join("، ")}</div>`);
  }
  return out.join("");
}
function bindOutcomeButtons(lead) {
  const wa = $('[data-oc="wa"]');
  if (wa) wa.onclick = () => askWhatsApp(lead);
  const inv = $('[data-oc="invalid"]');
  if (inv) inv.onclick = async () => { stopCall(); await openResultPanel(); selectResult("INVALID_NUMBER"); };
}

// ------------------------------------------------------------------ WhatsApp
async function askWhatsApp(lead) {
  let o;
  try { o = await api("GET", `/api/lead/${lead.fingerprint}/whatsapp`); } catch (e) { toast(e.message, "error"); return; }
  const nums = o.numbers || [];
  const tpls = o.templates || [];
  Modal.open({
    title: "رسالة واتساب", wide: false,
    html: `${o.dry_run && o.log ? '<div class="alert warn">Dry Run مفعّل: ستفتح الرسالة في واتساب، لكن لن تُسجَّل في Odoo أو Google Sheet.</div>' : ""}
      <label class="field"><span>الرقم</span>
        ${nums.length ? `<div class="row" style="gap:6px;flex-wrap:wrap;margin-bottom:6px">${nums.map((n, i) => `<button type="button" class="btn sm ${i === 0 ? "primary" : ""}" data-num="${i}">${esc(n.label)}: <span class="ltr">${esc(n.raw)}</span></button>`).join("")}</div>` : '<div class="small muted">لا يوجد رقم جوال صالح للواتساب؛ اكتبه يدويًا.</div>'}
        <input type="text" inputmode="tel" id="wa-tel" class="ltr" value="${esc(nums[0] ? nums[0].raw : "")}"></label>
      ${tpls.length ? `<div class="field"><span>القالب</span><div class="row" style="gap:6px;flex-wrap:wrap">${tpls.map((tp, i) => `<button type="button" class="btn sm ${i === 0 ? "primary" : ""}" data-tpl="${i}">${esc(tp.name || "قالب " + (i + 1))}</button>`).join("")}</div></div>` : ""}
      <label class="field"><span>نص الرسالة (يمكنك تعديله)</span><textarea id="wa-text" rows="6">${esc(tpls[0] ? tpls[0].text : "")}</textarea></label>
      <label class="check"><input type="checkbox" id="wa-log" ${o.log ? "checked" : ""}> تسجيل الرسالة في Odoo (Log note) وملاحظات Google Sheet</label>
      <div class="small muted">سيفتح واتساب والرسالة جاهزة؛ اضغط «إرسال» داخل واتساب.</div><div id="wa-msg"></div>`,
    buttons: [{ label: "فتح واتساب", cls: "primary", onClick: (btn) => sendWhatsApp(lead, btn) }, { label: "إلغاء" }],
    onOpen: (m) => {
      let tplName = tpls[0] ? tpls[0].name : "";
      $("#wa-text", m).dataset.tpl = tplName;
      $$("[data-num]", m).forEach((b) => b.onclick = () => {
        $$("[data-num]", m).forEach((x) => x.classList.toggle("primary", x === b));
        $("#wa-tel", m).value = nums[+b.dataset.num].raw;
      });
      $$("[data-tpl]", m).forEach((b) => b.onclick = () => {
        $$("[data-tpl]", m).forEach((x) => x.classList.toggle("primary", x === b));
        const tp = tpls[+b.dataset.tpl];
        $("#wa-text", m).value = tp.text;
        $("#wa-text", m).dataset.tpl = tp.name;
      });
    },
  });
}

async function sendWhatsApp(lead, btn) {
  const body = { tel: $("#wa-tel").value.trim(), text: $("#wa-text").value, template: $("#wa-text").dataset.tpl || "",
                 log: $("#wa-log").checked };
  // Open the tab now (inside the click) so the browser does not block it, then point it at WhatsApp.
  const win = S.remote ? null : window.open("about:blank", "_blank");
  await withBusy(btn, async () => {
    let r;
    try { r = await api("POST", `/api/lead/${lead.fingerprint}/whatsapp`, body); }
    catch (e) { if (win) win.close(); $("#wa-msg").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; return; }
    if (win) win.location.href = r.url; else window.location.href = r.url;
    Modal.close();
    const logged = r.logged && !r.dry_run ? " وتم تسجيلها في Odoo والـSheet" : r.dry_run && r.logged ? " (Dry Run: لم تُسجَّل)" : "";
    toast(`تم فتح واتساب${logged}. بعد الإرسال سجّل النتيجة.`, "success", 6000);
    (r.warnings || []).forEach((w) => toast(w, "warn", 8000));
  });
}

async function toggleFilter(i) {
  if (S.filter.busy) return;
  const opts = S.filter.options.map((o, j) => (j === i ? { ...o, selected: !o.selected } : o));
  const values = opts.filter((o) => o.selected).map((o) => o.value);
  if (!values.length) { toast("اختر حالة متابعة واحدة على الأقل.", "warn"); return; }
  S.filter.busy = true;
  $$("#fb-chips .fchip").forEach((b) => { b.disabled = true; });
  try {
    const payload = await api("PUT", "/api/queue/filter", { values });
    renderFilter(payload.filter.options);
    const sameLead = payload.lead && S.lead && payload.lead.fingerprint === S.lead.fingerprint;
    if (sameLead && (resultOpen() || S.call.startedAt)) renderStats(payload.stats);  // keep the open result panel
    else if (!S.manual) render(payload);
    else renderStats(payload.stats);
    toast(`سيتم البحث عن: ${opts.filter((o) => o.selected).map((o) => o.empty ? "فارغة" : o.value).join("، ")} (${payload.stats.pending} عميل)`, "info", 3500);
  } catch (e) {
    toast(e.message, "error");
    renderFilter(S.filter.options);
  } finally { S.filter.busy = false; }
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
  renderBanner(payload.stats);
  renderSession(payload.session);
  $("#global-msg").innerHTML = (payload.warnings || []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("");
  (payload.notices || []).forEach((n) => toast(n, "success", 7000));
  $("#result-card").classList.add("hidden");
  if (payload.done || !payload.lead) { Live.watch(null); return renderDone(); }
  renderLead(payload.lead);
  renderOdoo(payload.lead.odoo);
  renderChatter(payload.lead.odoo);
  Live.watch(payload.lead.odoo_lead_id ? { kind: "queue", id: payload.lead.fingerprint, odoo: payload.lead.odoo_lead_id } : null);
  if (payload.lead.match_status === "unknown") searchOdoo();
}

function renderStats(st) {
  if (!st) return;
  $$("#stats .value").forEach((el) => { el.textContent = st[el.dataset.k] ?? "–"; });
  renderGoal(st);
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
  $("#lead-card").innerHTML = `<div class="empty"><div class="ill">${ICON.done}</div><div class="big">لا يوجد عملاء بانتظار التواصل</div>
    <div>تم الانتهاء من قائمة ${esc(S.settings.agent_owner)} الحالية، أو أن كل العملاء المتبقين تم تخطيهم مؤقتًا.</div>
    <div class="actions" style="justify-content:center;margin-top:16px"><button class="btn primary" id="btn-reload">تحديث القائمة</button>
    <a class="btn" href="/skipped">العملاء المتخطون</a></div></div>`;
  $("#btn-reload").onclick = (ev) => withBusy(ev.currentTarget, refreshQueue);
  renderOdoo(null);
  renderChatter(null);
}

function statusBadge(status) {
  return status ? `<span class="badge indigo">${esc(status)}</span>` : '<span class="badge">فارغ</span>';
}

function initials(name) {
  const w = String(name || "").replace(/^(شركة|مؤسسة|مكتب|مجموعة|مصنع)\s+/, "").trim();
  return esc(w.charAt(0) || "؟");
}

function latestOdooNote(o) {
  const n = ((o && o.chatter) || []).find((m) => (m.kind === "note" || m.kind === "message") && m.body);
  if (n) return `${n.body}\n— ${n.author || ""}${n.date ? " · " + fmtDate(n.date) : ""}`;
  return ((o && o.latest_notes) || [])[0] || "";
}

function renderLead(lead) {
  const o = lead.odoo || {};
  $("#lead-card").innerHTML = `
    <div class="lead-hero"><div class="lead-head">
      <div class="lead-title"><div class="avatar">${initials(lead.company_name)}</div><div style="min-width:0">
        <div class="row small" style="gap:6px"><span class="badge blue">صف ${lead.sheet_row} (مرجع فقط)</span>${statusBadge(lead.followup_status)}
          ${o.stage ? `<span class="badge indigo">${esc(o.stage)}</span>` : ""}</div>
        <h2 class="lead-name">${esc(lead.company_name || "(بدون اسم)")}</h2>
        <div class="lead-phone"><span class="ltr">${esc(lead.phone)}</span>
          <button class="icon-btn" id="btn-copy" title="نسخ الرقم (P)">${ICON.copy}</button>${phoneBadge(lead.phone_check)}</div></div></div>
    </div></div>
    <div class="lead-body">
    <div class="info-grid">
      <div class="info"><div class="k">المصدر في Google Sheet</div><div class="v">${orDash(lead.sheet_source)}</div></div>
      <div class="info"><div class="k">UTM Source من Odoo</div><div class="v">${orDash(o.utm_source)}</div></div>
      <div class="info"><div class="k">UTM Medium</div><div class="v">${orDash(o.utm_medium || o.medium)}</div></div>
      <div class="info"><div class="k">UTM Campaign</div><div class="v">${orDash(o.utm_campaign || o.campaign)}</div></div>
      <div class="info"><div class="k">حالة المتابعة الحالية</div><div class="v">${orDash(lead.followup_status)}</div></div>
      <div class="info"><div class="k">ربط المصدر</div><div class="v">${sourceBadge(lead)}</div></div>
      <div class="info wide"><div class="k">آخر ملاحظة في Google Sheet</div><div class="v note-box">${orDash(lead.last_note)}</div></div>
      ${lead.odoo ? `<div class="info wide"><div class="k">آخر ملاحظة في Odoo Chatter</div><div class="v note-box">${orDash(latestOdooNote(o))}</div></div>` : ""}
    </div>
    ${phoneProblems(lead.phone_check)}
    ${outcomeAlerts(lead)}
    <div id="match-area"></div>
    <div id="lead-msg"></div>
    </div>
    <div class="action-bar">
      <button class="btn call" id="btn-call">${PHONE_ICON} اتصال الآن <kbd>C</kbd></button>
      <button class="btn wa" id="btn-wa">${ICON.wa} واتساب <kbd>W</kbd></button>
      <button class="btn primary" id="btn-open">${ICON.open} فتح في Odoo <kbd>O</kbd></button>
      <button class="btn" id="btn-result">${ICON.result} تسجيل النتيجة <kbd>R</kbd></button>
      <button class="btn" id="btn-research">${ICON.search} إعادة البحث <kbd>F</kbd></button>
      <button class="btn" id="btn-refresh">${ICON.refresh} تحديث <kbd>U</kbd></button>
      <span class="spacer"></span>
      <button class="btn ghost" id="btn-skip">${ICON.skip} تخطي مؤقتًا <kbd>S</kbd></button>
    </div>`;
  renderMatch(lead);
  const fp = lead.fingerprint;
  bindPhoneProblemButtons();
  $("#btn-copy").onclick = copyPhone;
  $("#btn-call").onclick = (ev) => startCall(ev.currentTarget);
  $("#btn-wa").onclick = () => askWhatsApp(lead);
  bindOutcomeButtons(lead);
  $("#btn-open").onclick = (ev) => withBusy(ev.currentTarget, () => openInOdoo(fp));
  $("#btn-research").onclick = () => searchOdoo();
  $("#btn-refresh").onclick = (ev) => withBusy(ev.currentTarget, () => refreshAll(fp));
  $("#btn-skip").onclick = () => askSkip(fp);
  $("#btn-result").onclick = () => openResultPanel();
}

function sourceBadge(lead) {
  const s = lead.source || {};
  if (!lead.odoo) return '<span class="muted">بانتظار Odoo</span>';
  if (s.mapped) return `<span class="badge green">مربوط → ${esc(s.sheet_value)}</span>`;
  if (s.odoo_value) return `<span class="badge amber">المصدر غير مربوط</span>`;
  return '<span class="muted">لا يوجد UTM Source في Odoo</span>';
}

function renderMatch(lead) {
  const area = $("#match-area");
  if (!area) return;
  const st = lead.match_status;
  if (st === "matched") {
    area.innerHTML = `<div class="alert success">تمت المطابقة مع Odoo: <b>${esc((lead.odoo || {}).name || "")}</b>
      ${lead.odoo && lead.odoo.salesperson ? ` · المسؤول: ${esc(lead.odoo.salesperson)}` : ""}</div>`;
  } else if (st === "multiple" && WEAK_MATCH.includes(lead.match_strategy)) {
    area.innerHTML = `<div class="alert error"><b>هذا العميل غير موجود في Odoo</b>
      <div class="small">لا يوجد Lead بنفس رقم الجوال أو نفس اسم المنشأة. وجدنا ${(lead.candidates || []).length} ${(lead.candidates || []).length > 2 ? "أسماء مشابهة" : "اسم مشابه"} فقط — تأكد أنه ليس منها، أو أضفه إلى Odoo.</div>
      <div class="actions"><button class="btn primary sm" id="btn-create">${ICON.plus} إضافة العميل إلى Odoo <kbd>A</kbd></button>
      <button class="btn sm" id="btn-choose">عرض الأسماء المشابهة</button><button class="btn sm" id="btn-skip2">تخطي العميل</button></div></div>`;
    $("#btn-create").onclick = () => askCreateLead(lead);
    $("#btn-choose").onclick = () => chooseCandidate(lead);
    $("#btn-skip2").onclick = () => askSkip(lead.fingerprint);
  } else if (st === "multiple") {
    area.innerHTML = `<div class="alert warn"><b>وجدنا أكثر من عميل محتمل في Odoo.</b> لن يتم الاختيار تلقائيًا.
      <div class="actions"><button class="btn primary sm" id="btn-choose">اختيار العميل الصحيح</button>
      <button class="btn sm" id="btn-create">${ICON.plus} ليس منهم؟ إضافته كعميل جديد</button></div></div>`;
    $("#btn-choose").onclick = () => chooseCandidate(lead);
    $("#btn-create").onclick = () => askCreateLead(lead);
  } else if (st === "not_found") {
    area.innerHTML = `<div class="alert error"><b>هذا العميل غير موجود في Odoo</b>
      <div class="small">لم نجد Lead بنفس رقم الجوال أو اسم المنشأة. يمكنك إضافته الآن إلى Odoo، أو البحث باسم أو رقم آخر.</div>
      <div class="actions"><button class="btn primary sm" id="btn-create">${ICON.plus} إضافة العميل إلى Odoo <kbd>A</kbd></button></div>
      <div class="row" style="margin-top:10px"><input type="text" id="custom-q" placeholder="بحث باسم أو رقم آخر" style="max-width:320px">
      <button class="btn sm" id="btn-re">إعادة البحث</button><button class="btn sm" id="btn-crm">فتح CRM</button>
      <button class="btn sm" id="btn-skip2">تخطي العميل</button></div></div>`;
    $("#btn-create").onclick = () => askCreateLead(lead);
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
  let open = true;
  try { open = localStorage.getItem("kla-odoo-open") !== "0"; } catch (e) { /* ignore */ }
  card.innerHTML = `<details class="odoo-details" ${open ? "open" : ""}><summary><h2 style="margin:0">بيانات Odoo</h2>
      <span class="badge indigo">#${o.id ?? "—"}</span><svg class="chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></summary>
    <div class="kv" style="margin-top:14px">${rows.map(([k, v]) => `<div class="k">${k}</div><div>${["Phone", "Mobile", "Email"].includes(k) ? `<span class="ltr">${orDash(v)}</span>` : orDash(v)}</div>`).join("")}</div></details>`;
  $("details", card).addEventListener("toggle", (ev) => { try { localStorage.setItem("kla-odoo-open", ev.target.open ? "1" : "0"); } catch (e) { /* ignore */ } });
}

/** Odoo datetimes are UTC "YYYY-MM-DD HH:MM:SS"; show them in local time as dd/mm/yyyy HH:MM. */
function parseOdooDate(v) {
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(v);
  if (!m) return null;
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)));
}
function fmtDate(v) {
  const d = parseOdooDate(v);
  if (!d) return v || "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getDate())}/${p(d.getMonth() + 1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtAgo(v) {
  const d = parseOdooDate(v);
  if (!d) return "";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 60) return "الآن";
  const m = Math.round(s / 60); if (m < 60) return `قبل ${m} د`;
  const h = Math.round(m / 60); if (h < 24) return `قبل ${h} س`;
  const days = Math.round(h / 24); if (days < 30) return days === 1 ? "أمس" : `قبل ${days} يوم`;
  const mo = Math.round(days / 30); return mo < 12 ? `قبل ${mo} شهر` : `قبل ${Math.round(mo / 12)} سنة`;
}
function activityClass(date) {
  if (!date) return "";
  const today = new Date(); const p = (n) => String(n).padStart(2, "0");
  const t = `${today.getFullYear()}-${p(today.getMonth() + 1)}-${p(today.getDate())}`;
  return date < t ? "overdue" : date === t ? "today" : "";
}

function chatterItem(m, isNew) {
  const kind = KIND_LABEL[m.kind] ? m.kind : "system";
  const changes = (m.tracking || []).map((t) => `<div class="tl-change">${t.field ? `<span class="muted">${esc(t.field)}:</span>` : ""}
      ${t.old ? `<span class="old">${esc(t.old)}</span><span class="arrow">←</span>` : ""}<span class="new">${esc(t.new || "—")}</span></div>`).join("");
  const long = (m.body || "").length > 320 || (m.body || "").split("\n").length > 5;
  const body = m.body ? `<div class="tl-body ${long ? "clamp" : ""}">${esc(m.body)}</div>${long ? '<button class="tl-more" type="button">عرض المزيد</button>' : ""}` : "";
  const subtype = m.subtype && !body && !changes ? `<div class="tl-body muted">${esc(m.subtype)}</div>` : "";
  return `<li class="tl-item ${kind}${isNew ? " new" : ""}" data-kind="${kind}"><div class="tl-icon">${ICON[kind]}</div><div class="tl-card">
    <div class="tl-meta"><b>${esc(m.author || "—")}</b><span class="badge">${KIND_LABEL[kind]}</span><span class="spacer"></span>
      <span title="${esc(fmtDate(m.date))}">${esc(fmtAgo(m.date) || fmtDate(m.date))}</span></div>
    ${body}${changes}${subtype}</div></li>`;
}

function renderChatter(o, live = false) {
  const box = $("#chatter-body");
  if (!o) { box.className = "muted"; box.innerHTML = "لم تتم المطابقة بعد."; S.seenChatter = { key: null, ids: new Set() }; return; }
  box.className = "";
  const items = o.chatter || [];
  const acts = o.activities || [];
  const key = String(o.id);
  const prev = S.seenChatter.key === key ? S.seenChatter.ids : null;
  const isNew = (m) => live && prev && !prev.has(m.id);
  S.seenChatter = { key, ids: new Set(items.map((m) => m.id)) };
  const count = (f) => items.filter((m) => f === "all" || m.kind === f || (f === "message" && m.kind === "email")).length;
  const visible = items.filter((m) => S.chatterFilter === "all" || m.kind === S.chatterFilter || (S.chatterFilter === "message" && m.kind === "email"));
  const actsHtml = acts.length ? `<h3 style="margin:4px 0 0">الأنشطة المجدولة</h3><div class="activity-list">${acts.map((a) => `
      <div class="activity ${activityClass(a.date_deadline)}"><span class="when">${esc(a.date_deadline || "—")}</span>
      <div style="min-width:0"><b>${esc(a.summary || a.type || "نشاط")}</b>${a.type && a.summary ? ` <span class="badge">${esc(a.type)}</span>` : ""}
      <div class="small muted">${esc([a.user, a.note].filter(Boolean).join(" · "))}</div></div></div>`).join("")}</div>` : "";
  box.innerHTML = `${actsHtml}
    <div class="row" style="margin-top:${acts.length ? 16 : 0}px"><div class="seg" id="chatter-filter">${FILTERS.map(([f, l]) =>
      `<button type="button" data-f="${f}" class="${S.chatterFilter === f ? "active" : ""}">${l}<span class="n">${count(f)}</span></button>`).join("")}</div></div>
    ${visible.length ? `<ul class="timeline">${visible.map((m) => chatterItem(m, isNew(m))).join("")}</ul>`
      : `<div class="empty" style="padding:26px 10px">${items.length ? "لا توجد عناصر من هذا النوع." : "لا يوجد سجل Chatter على هذا العميل بعد."}</div>`}`;
  $$("#chatter-filter button", box).forEach((b) => b.onclick = () => { S.chatterFilter = b.dataset.f; renderChatter(S.manual || (S.lead && S.lead.odoo)); });
  $$(".tl-more", box).forEach((b) => b.onclick = () => { const body = b.previousElementSibling; body.classList.toggle("clamp"); b.textContent = body.classList.contains("clamp") ? "عرض المزيد" : "عرض أقل"; });
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
    if (isMissing(payload.lead)) toast("العميل غير موجود في Odoo — يمكنك إضافته إليه من الـAgent.", "warn", 6000);
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
    <th>Salesperson</th><th>UTM Source</th><th>Lead Status</th><th></th></tr></thead><tbody>
    ${cands.map((c, i) => `<tr><td><b>${esc(c.company_name || c.name)}</b>${c.company_name && c.name && c.name !== c.company_name ? `<div class="small muted">${esc(c.name)}</div>` : ""}</td>
      <td class="ltr">${orDash(c.phone)}</td><td class="ltr">${orDash(c.mobile)}</td><td>${orDash(c.salesperson)}</td>
      <td>${orDash(c.utm_source || c.source)}</td><td>${orDash(c.stage)}${c.active === false ? ' <span class="badge red">مؤرشف</span>' : ""}</td>
      <td><button class="btn primary sm" data-i="${i}">${btnLabel}${i < 9 ? ` <kbd>${i + 1}</kbd>` : ""}</button></td></tr>`).join("")}
    </tbody></table></div>`;
}

/** In a modal: digit N clicks the N-th [data-i] / [data-m] button. */
function digitPicker(ev) {
  const m = /^(?:Digit|Numpad)([1-9])$/.exec(ev.code);
  if (!m || ev.ctrlKey || ev.altKey || ev.metaKey) return false;
  const btns = $$("#modal-backdrop button[data-i], #modal-backdrop button[data-m]");
  const b = btns[+m[1] - 1];
  if (b) b.click();
  return !!b;
}

function chooseCandidate(lead) {
  const cands = lead.candidates || [];
  Modal.open({
    title: "وجدنا أكثر من عميل", wide: true,
    html: `<p class="muted">اختر الـLead الصحيح. لن يتم الاختيار تلقائيًا ولن يتم إنشاء Lead جديد. <span class="small">(اضغط رقم الصف <kbd>1</kbd>…<kbd>9</kbd> للاختيار)</span></p>${candidateTable(cands, "اختيار")}`,
    buttons: [{ label: "إغلاق" }],
    onKey: digitPicker,
    onOpen: (m) => $$("button[data-i]", m).forEach((b) => b.onclick = () => withBusy(b, async () => {
      const c = cands[+b.dataset.i];
      Modal.close();
      await leadAction(`/api/lead/${lead.fingerprint}/select`, { odoo_id: c.id, ui_index: c.ui_index, ui_query: c.ui_query || "" }, "تم اختيار العميل");
    })),
  });
}

// ------------------------------------------------------ add missing customer to Odoo
const NEW_TYPE_AR = { lead: "Lead جديد (قائمة Leads)", opportunity: "فرصة جديدة (Pipeline)" };
/** Found only by similar names (never by phone or the exact name): the customer itself is missing. */
const WEAK_MATCH = ["company_partial", "ui_search"];
function isMissing(lead) {
  return !!lead && (lead.match_status === "not_found" || (lead.match_status === "multiple" && WEAK_MATCH.includes(lead.match_strategy)));
}

/** «فتح في Odoo»: open the linked lead; a customer missing from Odoo is offered to be added (never a bare CRM page). */
async function openInOdoo(fp) {
  const url = S.lead && S.lead.fingerprint === fp && S.lead.odoo && S.lead.odoo.url;
  if (S.remote && url) { window.open(url, "_blank", "noopener"); return; }  // on the phone: Odoo in its own browser
  let payload;
  try { payload = await api("POST", `/api/lead/${fp}/open`); } catch (e) { handleOdooError(e, () => openInOdoo(fp)); return; }
  render(payload);
  refreshStatus();
  if (payload.open) promptLink(payload.lead);
}

/** The customer is not linked to a lead: ask to add it, or to pick the right one. */
function promptLink(lead) {
  if (!lead) return;
  if (isMissing(lead)) {
    toast("هذا العميل غير موجود في Odoo — أضفه إلى Odoo.", "warn", 6000);
    askCreateLead(lead);
  } else if (lead.match_status === "multiple") {
    chooseCandidate(lead);
  } else {
    toast("العميل غير مربوط بـLead في Odoo. اضغط «إعادة البحث».", "warn", 6000);
  }
}

function askCreateLead(lead) {
  const dry = !!(S.settings && S.settings.dry_run);
  const typeAr = NEW_TYPE_AR[(S.settings && S.settings.odoo_new_record_type) || "lead"];
  Modal.open({
    title: `إضافة العميل إلى Odoo كـ${typeAr}`,
    html: `<p class="muted">سيتم البحث في Odoo مرة أخرى بالاسم والرقم قبل الإضافة حتى لا يتكرر العميل. ستكون أنت المسؤول (Salesperson).</p>
      ${dry ? '<div class="alert warn">Dry Run مفعّل: ستظهر معاينة فقط ولن تتم الإضافة فعليًا. عطّله من الإعدادات للإضافة الحقيقية.</div>' : ""}
      <label class="field"><span>اسم الشركة *</span><input type="text" id="new-company" maxlength="200" value="${esc(lead.company_name)}"></label>
      <label class="field"><span>رقم الجوال *</span><input type="text" inputmode="tel" id="new-phone" class="ltr" maxlength="40" value="${esc(lead.phone)}"></label>
      <label class="field"><span>اسم الشخص المسؤول لدى العميل (اختياري)</span><input type="text" id="new-contact" maxlength="120"></label>
      <label class="field"><span>المصدر (UTM Source) — من Google Sheet</span><input type="text" id="new-source" maxlength="200" value="${esc(lead.sheet_source)}" placeholder="مثال: Meta || Leads"></label>
      <div class="small muted" style="margin-top:-6px">يُكتب في UTM Source بمصدر موجود في Odoo بنفس الاسم أو حسب Source Mapping في الإعدادات.</div>
      <div id="new-msg"></div>`,
    buttons: [
      { label: dry ? "معاينة الإضافة (Dry Run)" : "إضافة إلى Odoo", cls: "primary", onClick: (btn) => withBusy(btn, () => submitCreateLead(lead, false)) },
      { label: "إلغاء" },
    ],
    onOpen: () => $("#new-company").focus(),
  });
}

async function submitCreateLead(lead, force) {
  const body = { company: $("#new-company").value.trim(), phone: $("#new-phone").value.trim(),
                 contact_name: $("#new-contact").value.trim(), source: $("#new-source").value.trim(), force };
  if (!body.company || !body.phone) {
    $("#new-msg").innerHTML = '<div class="alert error">اسم الشركة ورقم الجوال مطلوبان.</div>';
    return;
  }
  let payload;
  try {
    payload = await api("POST", `/api/lead/${lead.fingerprint}/create-odoo`, body);
  } catch (e) {
    if (e.code === "ODOO_LOGIN_REQUIRED") { Modal.close(); handleOdooError(e, () => askCreateLead(lead)); return; }
    $("#new-msg").innerHTML = `<div class="alert error">${esc(e.message)}</div>`;
    return;
  }
  const cr = payload.create || {};
  if (cr.status === "dry_run") {
    const v = cr.values || {};
    $("#new-msg").innerHTML = `<div class="alert warn"><b>Dry Run — لم تتم الإضافة إلى Odoo.</b>
      <div class="kv" style="margin-top:8px"><div class="k">Name</div><div>${orDash(v.name)}</div>
      <div class="k">Company</div><div>${orDash(v.partner_name)}</div><div class="k">Phone</div><div class="ltr">${orDash(v.phone)}</div>
      <div class="k">Contact</div><div>${orDash(v.contact_name)}</div><div class="k">Type</div><div>${orDash(v.type)}</div>
      <div class="k">UTM Source</div><div>${orDash(v.source_name)}</div><div class="k">Medium</div><div>${orDash(v.medium_name)}</div></div></div>`;
    return;
  }
  if (cr.status === "created") {
    Modal.close();
    render(payload);
    toast(`تمت إضافة العميل إلى Odoo كـ${NEW_TYPE_AR[cr.type] || "Lead جديد"} (#${cr.id})`, "success", 6000);
    (payload.warnings || []).forEach((w) => toast(w, "warn", 9000));
    return;
  }
  if (cr.status === "exists") {
    const cands = (payload.lead && payload.lead.candidates) || [];
    if (cr.match === "matched" || !cr.can_force) {
      Modal.close();
      render(payload);
      toast(cr.match === "matched" ? "العميل موجود بالفعل في Odoo، وتم ربطه بدل إنشاء عميل مكرر."
                                   : "يوجد أكثر من عميل بنفس البيانات في Odoo؛ اختر الصحيح بدل إنشاء عميل مكرر.", "warn", 7000);
      return;
    }
    render(payload);
    Modal.open({
      title: "وجدنا عملاء بأسماء مشابهة في Odoo", wide: true,
      html: `<p class="muted">تأكد أن العميل ليس واحدًا منهم. إذا وجدته اختره، وإلا أضفه كعميل جديد.</p>${candidateTable(cands, "هذا هو")}
        <input type="hidden" id="new-company" value="${esc(body.company)}"><input type="hidden" id="new-phone" value="${esc(body.phone)}">
        <input type="hidden" id="new-contact" value="${esc(body.contact_name)}"><input type="hidden" id="new-source" value="${esc(body.source)}"><div id="new-msg"></div>`,
      buttons: [
        { label: "ليس منهم — إضافة كعميل جديد", cls: "primary", onClick: (btn) => withBusy(btn, () => submitCreateLead(lead, true)) },
        { label: "إلغاء" },
      ],
      onKey: digitPicker,
      onOpen: (m) => $$("button[data-i]", m).forEach((b) => b.onclick = () => withBusy(b, async () => {
        const c = cands[+b.dataset.i];
        Modal.close();
        await leadAction(`/api/lead/${lead.fingerprint}/select`, { odoo_id: c.id, ui_index: c.ui_index, ui_query: c.ui_query || "" }, "تم اختيار العميل");
      })),
    });
  }
}

function askSkip(fp) {
  const modes = [["10m", "10 دقائق"], ["30m", "30 دقيقة"], ["today", "اليوم"], ["session", "تخطي للجلسة الحالية"]];
  Modal.open({
    title: "تخطي مؤقتًا",
    html: `<p class="muted">لن يتم تعديل Google Sheet. سيظهر العميل مرة أخرى لاحقًا.</p>
      <label class="field"><span>السبب (اختياري)</span><input type="text" id="skip-reason"></label>
      <div class="actions">${modes.map(([m, l], i) => `<button class="btn lg" data-m="${m}">${l} <kbd>${i + 1}</kbd></button>`).join("")}</div>`,
    buttons: [{ label: "إلغاء" }],
    onKey: digitPicker,
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
const KIND_AR = { mobile: "جوال", landline: "هاتف ثابت", unified: "رقم موحد", international: "رقم دولي" };
const FIELD_AR = { phone: "Phone", mobile: "Mobile", sheet: "Google Sheet" };

function phoneBadge(pc) {
  if (!pc || !pc.target) return "";
  const t = pc.target;
  const label = `${FIELD_AR[t.field] || t.field} في Odoo`;
  if (pc.status === "ok") return `<span class="badge green" title="سيتم الاتصال بـ ${esc(t.tel)}">✓ ${label} صحيح (${KIND_AR[t.kind] || ""})</span>`;
  if (pc.status === "warning") return `<span class="badge amber">⚠ راجع رقم Odoo</span>`;
  return `<span class="badge red">✗ رقم Odoo غير صحيح</span>`;
}

function phoneProblems(pc) {
  if (!pc || !pc.problems || !pc.problems.length) return "";
  const canSheet = pc.sheet && pc.sheet.valid && !(pc.fields || []).some((f) => f.matches_sheet);
  return `<div class="alert ${pc.status === "error" ? "error" : "warn"}" id="phone-problems"><b>${pc.status === "error" ? "خطأ في رقم العميل في Odoo" : "تنبيه على رقم العميل"}</b>
    <ul style="margin:6px 0 0;padding-inline-start:20px">${pc.problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>
    <div class="actions">${canSheet ? `<button class="btn sm success" data-call="sheet">${PHONE_ICON} اتصال برقم الـSheet: <span class="ltr">${esc(pc.sheet.raw)}</span></button>` : ""}
      <button class="btn sm" data-fix="odoo">${ICON.open} فتح Odoo لتصحيح الرقم</button></div></div>`;
}

function bindPhoneProblemButtons() {
  $$("#phone-problems [data-call]").forEach((b) => b.onclick = () => startCall($("#btn-call"), { target: b.dataset.call }));
  $$("#phone-problems [data-fix]").forEach((b) => b.onclick = (ev) => withBusy(ev.currentTarget, () => leadAction(`/api/lead/${S.lead.fingerprint}/open`)));
}

function showPhoneInvalid(e, btn) {
  const d = e.details || {};
  const acts = e.actions || [];
  const buttons = [];
  if (acts.includes("call_sheet") && d.sheet_phone) {
    buttons.push({ label: `اتصال برقم الـSheet (${d.sheet_phone})`, cls: "success", onClick: () => { Modal.close(); startCall(btn, { target: "sheet" }); } });
  }
  if (acts.includes("call_anyway")) {
    buttons.push({ label: "اتصال على أي حال", onClick: () => { Modal.close(); startCall(btn, { force: true }); } });
  }
  if (!S.manual && S.lead) {
    buttons.push({ label: "فتح Odoo لتصحيح الرقم", cls: "primary", onClick: () => { Modal.close(); leadAction(`/api/lead/${S.lead.fingerprint}/open`); } });
  }
  buttons.push({ label: "إلغاء" });
  Modal.open({
    title: "تنبيه: رقم العميل في Odoo غير صحيح",
    html: `<div class="alert error"><b>${esc(e.message)}</b></div>
      ${d.number ? `<div class="kv"><div class="k">الرقم في Odoo</div><div><span class="ltr">${esc(d.number)}</span></div>
      ${d.sheet_phone ? `<div class="k">الرقم في Google Sheet</div><div><span class="ltr">${esc(d.sheet_phone)}</span></div>` : ""}</div>` : ""}
      <p class="muted small" style="margin-top:12px">لم يتم الاتصال. صحّح الرقم في Odoo (سيظهر التصحيح هنا تلقائيًا) أو اختر رقمًا آخر.</p>`,
    buttons,
  });
}

async function startCall(btn, opts = {}) {
  const manual = S.manual;
  if (!manual && (!S.lead || !S.lead.odoo_lead_id)) {
    toast("اربط العميل بـLead في Odoo أولًا (إعادة البحث).", "warn"); return;
  }
  if (S.calling) return;  // no double dial
  S.calling = true;
  try {
    await withBusy(btn, async () => {
      try {
        const body = { target: opts.target || "auto", force: !!opts.force, client_dial: !!S.remote };
        const r = manual ? await api("POST", "/api/manual/call", { ...body, odoo_id: manual.id })
                         : await api("POST", `/api/lead/${S.lead.fingerprint}/call`, body);
        S.call.startedAt = new Date(); S.call.endedAt = null;
        $("#call-banner").classList.remove("hidden");
        clearInterval(S.call.timer);
        S.call.timer = setInterval(() => { $("#call-timer").textContent = fmtDuration((Date.now() - S.call.startedAt) / 1000); }, 500);
        $("#call-timer").textContent = "00:00";
        if (r.method === "client_tel") window.location.href = `tel:${r.tel}`;  // the phone dials itself
        const via = r.method === "client_tel" ? "من هذا الجوال" : r.method === "fast_tel" ? "مباشرة إلى Phone Link" : "من Odoo";
        toast(`جاري الاتصال بـ ${r.tel || r.phone} (${FIELD_AR[r.phone_field] || r.phone_field}) ${via}. أكمل المكالمة من الجوال.`, "success", 6000);
        (r.warnings || []).forEach((w) => toast(w, "warn", 8000));
      } catch (e) {
        if (e.code === "NO_PHONE_IN_ODOO" && (e.actions || []).includes("call_sheet")) {
          const pc = (e.details || {}).phone_check || {};
          e.details = { ...(e.details || {}), sheet_phone: pc.sheet ? pc.sheet.raw : "" };
          e.actions = ["call_sheet"];
          showPhoneInvalid(e, btn);
        } else if (e.code === "PHONE_INVALID") {
          showPhoneInvalid(e, btn);
        } else if (e.code === "NOT_MATCHED" && S.lead && !manual && ["not_found", "multiple"].includes((e.details || {}).match_status)) {
          promptLink(S.lead);
        } else handleOdooError(e, () => startCall(btn, opts));
      }
    });
  } finally { S.calling = false; }
}
function stopCall() {
  if (S.call.startedAt && !S.call.endedAt) S.call.endedAt = new Date();
  clearInterval(S.call.timer);
  $("#call-banner").classList.add("hidden");
}

// ------------------------------------------------------- update from history
/** «تحديث العميل» from the history page: reopen the lead with its previous result pre-selected. */
async function openUpdate(resultId) {
  let prev;
  try { prev = (await api("GET", `/api/history/${resultId}`)).result; } catch (e) { toast(e.message, "error"); return; }
  try {
    if (prev.fingerprint) {
      stopCall(); S.manual = null;
      render(await api("POST", `/api/lead/${prev.fingerprint}/goto`));
    } else if (prev.odoo_lead_id) {
      await manualOpen({ id: prev.odoo_lead_id });
    } else { toast("لا يمكن فتح هذا السجل.", "warn"); return; }
  } catch (e) {
    toast(e.code === "LEAD_NOT_IN_QUEUE" ? "العميل لم يعد ضمن عملائك في Google Sheet (ربما تم تحويله لموظف آخر)." : e.message, "error", 8000);
    return;
  }
  await openResultPanel(prev);
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
  return { manual: false, fingerprint: l.fingerprint, odooId: l.odoo_lead_id, company: l.company_name, phone: l.phone, source: l.source, lead: l,
    trialCurrent: l.trial_registered || "" };
}

async function openResultPanel(prev = null) {
  if (!S.lead && !S.manual) return;
  const ctx = resultContext();
  S.result = { code: null, key: uuid(), ctx, trial: "" };
  const card = $("#result-card");
  const src = ctx.source || {};
  card.classList.remove("hidden");
  card.innerHTML = `<div class="card-head"><h2>تسجيل النتيجة — ${esc(ctx.company)}</h2><span class="spacer"></span>
      <span class="small muted">اختر بالأرقام <kbd>1</kbd>…<kbd>${Math.min(S.statuses.length, 9)}</kbd> · <kbd>T</kbd> للملاحظة</span></div>
    ${ctx.odooId ? "" : '<div class="alert warn">العميل غير مربوط بـLead في Odoo؛ لن تتم إضافة Log Note.</div>'}
    ${prev ? `<div class="alert info"><b>تحديث عميل سابق</b> — آخر نتيجة: <b>${esc(prev.result)}</b> (${esc(prev.time)})${prev.dry_run ? " · كانت Dry Run" : ""}
      ${prev.note ? `<div class="small" style="margin-top:4px">الملاحظة السابقة: ${esc(prev.note)}</div>` : ""}
      <div class="small muted" style="margin-top:4px">اختر النتيجة الجديدة واكتب ملاحظة؛ سيتم إضافة Log Note جديد في Odoo وتحديث الصف في Google Sheet مع الحفاظ على الملاحظات القديمة.</div></div>` : ""}
    <div class="result-buttons">${S.statuses.map((s, i) => `<button type="button" class="result-btn" data-code="${s.code}">${i < 9 ? `<span class="num">${i + 1}</span>` : ""}${esc(s.label)}</button>`).join("")}</div>
    <div class="more-status hidden" id="r-more"><div class="small muted" style="margin-bottom:6px">حالات أخرى من قائمة «حالة المتابعة» في الـSheet:</div>
      <div class="more-chips" id="r-more-chips"></div></div>
    <div style="margin-top:16px">
      <label class="field"><span class="note-head">ملاحظة حرة ${Dictation.supported() ? `<button type="button" class="btn sm mic" id="r-mic" title="إملاء الملاحظة بالصوت (M)">${MIC_ICON}<span>إملاء بالصوت</span></button>`
        : S.remote ? '<span class="small muted">للإملاء: اضغط ميكروفون لوحة مفاتيح الجوال 🎤</span>' : ""}</span>
        <textarea id="r-note" placeholder="مثال: العميل مهتم بنظام رصد التواجد ويرغب في عرض سعر."></textarea></label>
      <div id="r-followup" class="form-grid hidden">
        <label class="field"><span>تاريخ المتابعة</span><input type="date" id="r-fdate"></label>
        <label class="field"><span>الوقت</span><input type="time" id="r-ftime"></label>
        <label class="field full"><span>ملاحظة المتابعة</span><input type="text" id="r-fnote"></label>
      </div>
      <div id="r-expiry" class="hidden"><label class="field"><span>تاريخ انتهاء الاشتراك (اختياري)</span><input type="date" id="r-exp"></label></div>
      <div id="r-reason" class="hidden"><label class="field"><span>سبب عدم الاشتراك (اختياري)</span>
        <input type="text" id="r-reason-in" list="reason-list"><datalist id="reason-list"></datalist></label></div>
      ${ctx.manual ? "" : `<label class="field"><span>مصدر العميل في Google Sheet</span><select id="r-source"><option value="">— بدون تغيير —</option></select></label>
      ${src.odoo_value && !src.mapped ? `<div class="alert warn"><b>المصدر غير مربوط:</b> UTM Source في Odoo = «${esc(src.odoo_value)}». اختر القيمة المناسبة من قائمة Sheet.
        <label class="check" style="display:flex;margin-top:8px"><input type="checkbox" id="r-save-map" checked> حفظ هذا الربط للاستخدام مستقبلًا</label></div>` : ""}`}
      ${ctx.manual ? "" : `<div class="field"><span class="small"><b>هل تم التسجيل بالنسخة التجريبية؟</b>
        <span class="muted">(الحالية في الـSheet: ${esc(ctx.trialCurrent || "فارغة")})</span></span>
        <div class="seg" id="r-trial" style="margin-top:6px"><button type="button" data-v="" class="active">بدون تغيير</button></div></div>`}
      <div class="row" style="margin:6px 0 12px">
        <label class="check"><input type="checkbox" id="r-sheet" ${ctx.manual ? "disabled" : "checked"}> تحديث Google Sheet</label>
        <label class="check"><input type="checkbox" id="r-odoo" ${ctx.odooId ? "checked" : "disabled"}> إضافة Log Note في Odoo</label>
      </div>
      ${ctx.manual ? '<div class="alert info small">وضع يدوي: العميل غير مربوط بصف مؤكد في Google Sheet، لذلك لن يتم تحديث Sheet.</div>' : ""}
      <div id="r-summary" class="write-summary"></div>
      <div id="r-msg"></div>
      <div class="actions">
        <button class="btn success lg" id="r-save">${S.settings.dry_run ? "حفظ (Dry Run – معاينة)" : "حفظ النتيجة"} <kbd>Ctrl ↵</kbd></button>
        <button class="btn" id="r-preview">معاينة التغييرات</button>
        <button class="btn ghost" id="r-cancel">إلغاء <kbd>Esc</kbd></button>
      </div>
    </div>`;
  $$(".result-btn", card).forEach((b) => b.onclick = () => selectResult(b.dataset.code));
  ["#r-sheet", "#r-odoo"].forEach((sel) => { $(sel).onchange = updateWriteSummary; });
  updateWriteSummary();
  $("#r-cancel").onclick = () => { Dictation.stop(); card.classList.add("hidden"); };
  if ($("#r-mic")) $("#r-mic").onclick = () => Dictation.toggle($("#r-note"), $("#r-mic"));
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
    if (prev && prev.source_value && [...sel.options].some((o) => o.value === prev.source_value)) sel.value = prev.source_value;
    sel.onchange = updateWriteSummary;
    updateWriteSummary();
  }
  if (!ctx.manual) {
    let trialOpts = await loadOptions("trial_registered");
    // Yes/No always offered (a column without a dropdown may only contain «لا» so far).
    trialOpts = ["نعم", "لا", ...trialOpts];
    const seg = $("#r-trial");
    seg.innerHTML = '<button type="button" data-v="" class="active">بدون تغيير</button>' +
      [...new Set(trialOpts)].map((v) => `<button type="button" data-v="${esc(v)}">${esc(v)}${v === ctx.trialCurrent ? " ✓" : ""}</button>`).join("");
    $$("button", seg).forEach((b) => b.onclick = () => {
      S.result.trial = b.dataset.v;
      $$("button", seg).forEach((x) => x.classList.toggle("active", x === b));
      updateWriteSummary();
    });
  }
  // Every other value of the sheet's follow-up dropdown, written to the sheet as-is ("S:<value>").
  const statusOpts = await loadOptions("followup_status");
  const mainValues = new Set(S.statuses.map((x) => (x.sheet_value || "").trim()));
  const extra = statusOpts.filter((v) => v && !mainValues.has(v.trim()));
  if (extra.length) {
    $("#r-more").classList.remove("hidden");
    $("#r-more-chips").innerHTML = extra.map((v) => `<button type="button" class="result-btn mini" data-code="S:${esc(v)}">${esc(v)}</button>`).join("");
    $$("#r-more-chips .result-btn").forEach((b) => b.onclick = () => selectResult(b.dataset.code));
  }
  if (prev && (S.statuses.some((x) => x.code === prev.result_code) || (prev.result_code || "").startsWith("S:"))) {
    selectResult(prev.result_code);
    if (prev.followup_date) { $("#r-fdate").value = prev.followup_date; $("#r-ftime").value = prev.followup_time || "10:00"; }
    if (prev.not_subscribed_reason) $("#r-reason-in").value = prev.not_subscribed_reason;
    if (prev.subscription_expiry) $("#r-exp").value = prev.subscription_expiry;
  }
  const reasons = await loadOptions("not_subscribed_reason");
  $("#reason-list").innerHTML = reasons.map((r) => `<option value="${esc(r)}">`).join("");
}

/** Live "what will be written" box, so it is clear before saving what Odoo and the sheet receive. */
function updateWriteSummary() {
  const box = $("#r-summary");
  if (!box || !S.result.ctx) return;
  const ctx = S.result.ctx;
  const dry = !!(S.settings && S.settings.dry_run);
  const code = S.result.code || "";
  const st = S.statuses.find((x) => x.code === code) || (code.startsWith("S:") ? { sheet_value: code.slice(2) } : null);
  const odooOn = $("#r-odoo") && $("#r-odoo").checked && !!ctx.odooId;
  const sheetOn = $("#r-sheet") && $("#r-sheet").checked && !ctx.manual;
  const srcSel = $("#r-source");
  const src = srcSel ? srcSel.value : "";
  const srcInfo = ctx.source || {};
  if (srcSel) srcSel.classList.toggle("needs-choice", sheetOn && !src && !!srcInfo.odoo_value);
  const rows = [];
  rows.push(`<li><span class="sys">Odoo</span>${odooOn
    ? `<span class="ok">✓ Log Note في Chatter</span>${S.result.code === "FOLLOW_UP" ? ' <span class="ok">+ Activity</span>' : ""}`
    : `<span class="no">لن تتم إضافة Log Note${ctx.odooId ? "" : " (العميل غير مربوط بـOdoo)"}</span>`}</li>`);
  if (sheetOn) {
    rows.push(`<li><span class="sys">حالة المتابعة</span>${st ? `<span class="ok">← ${esc(st.sheet_value || "(غير مربوطة – راجع Status Mapping)")}</span>` : '<span class="warn-t">اختر النتيجة أولًا</span>'}</li>`);
    rows.push(`<li><span class="sys">مصدر العميل</span>${src
      ? `<span class="ok">← ${esc(src)}</span>${srcInfo.mapped && src === srcInfo.sheet_value ? ` <span class="badge green">من UTM Source${srcInfo.auto ? " (مطابق تلقائيًا)" : ""}</span>` : ""}`
      : `<span class="warn-t">بدون تغيير${srcInfo.odoo_value ? ` — UTM Source = «${esc(srcInfo.odoo_value)}»، اختر القيمة المقابلة من القائمة لتحديثه` : ""}</span>`}</li>`);
    if (S.result.trial) rows.push(`<li><span class="sys">النسخة التجريبية</span><span class="ok">← ${esc(S.result.trial)}</span></li>`);
    rows.push('<li><span class="sys">الملاحظات</span><span class="ok">← تُضاف ملاحظة جديدة مع الحفاظ على القديمة</span></li>');
  } else {
    rows.push('<li><span class="sys">Google Sheet</span><span class="no">لن يتم التحديث</span></li>');
  }
  box.className = "write-summary" + (dry ? " dry" : "");
  box.innerHTML = `<div class="ws-head">${dry
    ? `⚠️ Dry Run مفعّل: هذا ما <u>كان</u> سيُكتب، ولن يتم تعديل أي نظام <span class="spacer"></span><button type="button" class="btn sm success" id="r-dry-off">إيقاف Dry Run</button>`
    : "عند الحفظ سيتم كتابة:"}</div><ul>${rows.join("")}</ul>`;
  const off = $("#r-dry-off");
  if (off) off.onclick = () => confirmDryRunToggle(true);
}

function selectResult(code) {
  S.result.code = code;
  setTimeout(updateWriteSummary, 0);
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
    trial_registered: ctx.manual ? "" : (S.result.trial || ""),
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
  Dictation.stop();
  if (!S.result.code) { toast("اختر نتيجة التواصل أولًا", "warn"); return; }
  if (S.busy) return;               // double-click protection (plus server idempotency key)
  S.busy = true;
  $("#r-save").disabled = true;
  $("#r-msg").innerHTML = "";
  try {
    await withBusy(btn, async () => {
      const res = await api("POST", previewOnly ? "/api/result/preview" : "/api/result", buildResultBody(previewOnly));
      if (previewOnly) { showPreview(res, "معاينة التغييرات (Would update)"); return; }
      if (res.duplicate && !res.dry_run) {
        toast("نفس النتيجة سُجِّلت لهذا العميل قبل قليل؛ لم يتم تكرار الكتابة في Odoo وGoogle Sheet. اختر نتيجة مختلفة أو انتظر دقيقة.", "warn", 9000);
        return;
      }
      if (res.dry_run) { showPreview(res, "Dry Run — لم يتم تعديل أي نظام", () => afterSave(res), true); return; }
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

function showPreview(res, title, onClose, offerRealSave = false) {
  const p = res.preview || {};
  const sheet = (p.sheet || []).map((c) => `<tr><td><b>Sheet ${esc(c.column)}</b></td><td class="pre">${orDash(c.old)}</td><td class="pre">${orDash(c.new)}</td></tr>`).join("");
  const html = `<p><b>Would update:</b></p>
    ${p.sheet_error ? `<div class="alert error">${esc(p.sheet_error)}</div>` : ""}
    ${sheet ? `<div class="table-wrap"><table class="table"><thead><tr><th>الحقل</th><th>القيمة الحالية</th><th>القيمة الجديدة</th></tr></thead><tbody>${sheet}</tbody></table></div>` : (p.sheet_error ? "" : '<div class="muted">لا تغييرات على Google Sheet.</div>')}
    <h3 style="margin-top:16px">Odoo Note</h3>${p.odoo_note ? `<div class="info note-box">${esc(p.odoo_note)}</div>` : '<div class="muted">لن تتم إضافة ملاحظة.</div>'}
    ${p.activity ? `<h3 style="margin-top:16px">Odoo Activity</h3><div class="info">${esc(p.activity.date_deadline)} — ${esc(p.activity.summary)}<div class="small muted">${esc(p.activity.note || "")}</div></div>` : ""}
    ${(res.warnings || []).map((w) => `<div class="alert warn" style="margin-top:10px">${esc(w)}</div>`).join("")}`;
  const buttons = [{ label: onClose ? "متابعة بدون حفظ" : "إغلاق", cls: offerRealSave ? "" : "primary", onClick: () => { Modal.close(); if (onClose) onClose(); } }];
  if (offerRealSave) {
    buttons.unshift({ label: "إيقاف Dry Run والحفظ فعليًا الآن", cls: "success", onClick: async (btn) => {
      btn.disabled = true;
      try {
        await setDryRun(false);
        Modal.close();
        S.result.key = uuid();  // a new real save (the Dry Run record stays in history)
        await saveResult($("#r-save"), false);
      } catch (e) { btn.disabled = false; toast(e.message, "error"); }
    } });
  }
  Modal.open({ title, html: (offerRealSave ? '<div class="alert warn"><b>لم يتم تسجيل شيء في Odoo أو Google Sheet</b> لأن وضع Dry Run مفعّل.</div>' : "") + html, wide: true, buttons });
}

// ------------------------------------------------------------- next lead
const STEP = { success: ["green", "✓ تم"], failed: ["red", "✗ فشل"], blocked: ["red", "⛔ تم الإيقاف"], skipped: ["", "— لم يُطلب"],
  nochange: ["blue", "بدون تغيير"], dry_run: ["amber", "Dry Run (لم يُكتب)"], pending: ["", "…"] };
function stepBadge(name, status) {
  const [cls, label] = STEP[status] || ["", status || "—"];
  return `<span class="badge ${cls}">${name}: ${label}</span>`;
}
function outcomeLine(res) {
  const errs = (res.errors || []).map((e) => `<div class="small" style="color:var(--danger)">${esc(e)}</div>`).join("");
  return `<div class="row small" style="gap:6px;margin-top:6px">${stepBadge("Odoo Log Note", res.odoo_note_status)}
    ${res.odoo_activity_status && res.odoo_activity_status !== "skipped" ? stepBadge("Activity", res.odoo_activity_status) : ""}
    ${stepBadge("Google Sheet", res.sheet_status)}</div>${errs}`;
}

function afterSave(res) {
  stopCall();
  S.call = { startedAt: null, endedAt: null, timer: null };
  $("#result-card").classList.add("hidden");
  if (S.manual) { S.manual = null; loadCurrent(); return; }
  const card = $("#next-card");
  card.classList.remove("hidden");
  if (res.next_delay === null || res.next_delay === undefined) {
    card.innerHTML = `<div class="row between"><div><b>${esc(res.message)}</b>${outcomeLine(res)}</div><button class="btn primary" id="btn-next">العميل التالي <kbd>N</kbd></button></div>`;
    $("#btn-next").onclick = goNext;
    return;
  }
  let left = res.next_delay;
  const total = Math.max(1, res.next_delay);
  const draw = () => {
    card.innerHTML = `<div class="countdown"><div><b>${esc(res.message)}</b>${outcomeLine(res)}</div><span class="spacer"></span>
      <span class="ring" style="--p:${Math.round((left / total) * 100)}"><span>${left}</span></span>
      <span>الانتقال للعميل التالي خلال <b>${left}</b> ثوانٍ</span>
      <button class="btn" id="btn-cancel-next">إلغاء الانتقال <kbd>Esc</kbd></button><button class="btn primary" id="btn-next">الانتقال الآن <kbd>N</kbd></button></div>`;
    $("#btn-cancel-next").onclick = () => {
      clearInterval(S.nextTimer);
      card.innerHTML = `<div class="row between"><div><span>تم إلغاء الانتقال التلقائي.</span>${outcomeLine(res)}</div><button class="btn primary" id="btn-next">العميل التالي <kbd>N</kbd></button></div>`;
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
  try { render(await api("POST", "/api/lead/next")); loadFilter(); } catch (e) { renderFatal(e, goNext); }
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
    <div class="lead-hero"><div class="lead-title"><div class="avatar">${initials(o.company_name || o.name)}</div><div style="min-width:0">
      <div class="row small"><span class="badge amber">وضع البحث اليدوي</span>${o.stage ? `<span class="badge indigo">${esc(o.stage)}</span>` : ""}</div>
      <h2 class="lead-name">${esc(o.company_name || o.name)}</h2>
      <div class="lead-phone"><span class="ltr">${esc(o.phone || o.mobile || "")}</span>
        <button class="icon-btn" id="btn-copy" title="نسخ الرقم (P)">${ICON.copy}</button></div></div></div></div>
    <div class="lead-body">
    ${warnings.map((w) => `<div class="alert warn">${esc(w)}</div>`).join("")}
    <div class="info-grid">
      <div class="info"><div class="k">UTM Source</div><div class="v">${orDash(o.utm_source)}</div></div>
      <div class="info"><div class="k">UTM Medium</div><div class="v">${orDash(o.utm_medium || o.medium)}</div></div>
      <div class="info"><div class="k">UTM Campaign</div><div class="v">${orDash(o.utm_campaign || o.campaign)}</div></div>
      <div class="info wide"><div class="k">آخر ملاحظة في Odoo Chatter</div><div class="v note-box">${orDash(latestOdooNote(o))}</div></div>
    </div><div id="lead-msg"></div></div>
    <div class="action-bar">
      <button class="btn call" id="btn-call">${PHONE_ICON} اتصال الآن <kbd>C</kbd></button>
      <button class="btn" id="btn-result">${ICON.result} تسجيل النتيجة <kbd>R</kbd></button>
      <span class="spacer"></span>
      <button class="btn ghost" id="btn-exit-manual">العودة لقائمة العمل</button>
    </div>`;
  renderOdoo(o);
  renderChatter(o);
  Live.watch({ kind: "manual", id: o.id });
  $("#btn-copy").onclick = copyPhone;
  $("#btn-call").onclick = (ev) => startCall(ev.currentTarget);
  $("#btn-result").onclick = () => openResultPanel();
  $("#btn-exit-manual").onclick = () => { stopCall(); loadCurrent(); };
}
