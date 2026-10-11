/* Shared helpers: API calls, toasts, modals, error display, topbar status. */
"use strict";

class ApiError extends Error {
  constructor(error, status) {
    super((error && error.message) || "خطأ غير معروف");
    this.code = (error && error.code) || "ERROR";
    this.actions = (error && error.actions) || [];
    this.details = (error && error.details) || {};
    this.status = status;
  }
}

async function api(method, url, body) {
  const opts = { method, headers: { "X-KLA": "1" } };
  if (body instanceof FormData) {
    opts.body = body;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch (e) {
    throw new ApiError({ code: "NETWORK", message: "تعذر الاتصال بالـAgent. تأكد أنه يعمل (02_start_agent.bat).", actions: ["retry"] }, 0);
  }
  let data = {};
  try { data = await res.json(); } catch (e) { data = {}; }
  if (!res.ok) throw new ApiError(data.error, res.status);
  return data;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const ICONS = {
  history: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>',
  skip: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 5l7 7-7 7M13 5l7 7-7 7"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l10 18H2z"/><path d="M12 10v4M12 17v.5"/></svg>',
  done: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg>',
};
/** Friendly empty state for tables/cards (same look on every page). */
function emptyState(text, sub = "", icon = "done") {
  return `<div class="empty" style="padding:28px 10px"><div class="ill">${ICONS[icon] || ICONS.done}</div>
    <div class="big" style="font-size:1.05rem">${esc(text)}</div>${sub ? `<div class="small">${esc(sub)}</div>` : ""}</div>`;
}
function emptyRow(cols, text, sub = "", icon = "done") {
  return `<tr><td colspan="${cols}" class="empty-cell">${emptyState(text, sub, icon)}</td></tr>`;
}
function orDash(v) { return v ? esc(v) : '<span class="muted">—</span>'; }
function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
  return Date.now().toString(16) + Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
}
function fmtDuration(sec) {
  if (sec === null || sec === undefined) return "—";
  sec = Math.max(0, Math.round(sec));
  const m = Math.floor(sec / 60), s = sec % 60;
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}
const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

function toast(message, type = "info", ms = 4000) {
  let box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = message;
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
}

const Modal = {
  /** Optional per-modal key handler (return true when handled). */
  onKey: null,
  isOpen() { return !!$("#modal-backdrop"); },
  open({ title, html, buttons = [], onOpen, wide, onKey }) {
    Modal.close();
    const back = document.createElement("div");
    back.className = "modal-backdrop";
    back.id = "modal-backdrop";
    back.innerHTML = `<div class="modal" role="dialog" aria-modal="true" ${wide ? 'style="width:min(1200px,100%)"' : ""}>
      <header>${esc(title)}</header><div class="body">${html}</div><footer></footer></div>`;
    const footer = $("footer", back);
    buttons.forEach((b) => {
      const btn = document.createElement("button");
      btn.className = "btn " + (b.cls || "");
      btn.textContent = b.label;
      btn.onclick = () => b.onClick ? b.onClick(btn) : Modal.close();
      footer.appendChild(btn);
    });
    if (!buttons.length) footer.remove();
    back.addEventListener("mousedown", (ev) => { if (ev.target === back) Modal.close(); });
    document.body.appendChild(back);
    Modal.onKey = onKey || null;
    if (onOpen) onOpen($(".modal", back));
    const first = $("footer .btn.primary, input, textarea, footer .btn", back);
    if (first && !first.matches("input, textarea")) first.focus({ preventScroll: true });
    return back;
  },
  close() { const m = $("#modal-backdrop"); if (m) m.remove(); Modal.onKey = null; },
};

// ------------------------------------------------------------ keyboard shortcuts
/**
 * Layout-independent shortcuts (uses KeyboardEvent.code, so they work with the Arabic keyboard too).
 * Each entry: { code: "KeyC", label: "C", title: "اتصال الآن", group, run(ev), when?(), alt?, ctrl?, shift?, allowInInputs? }
 */
const Shortcuts = {
  items: [],
  register(list) { Shortcuts.items.push(...list); },
  typing(el) {
    return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
  },
  handle(ev) {
    if (ev.repeat) return;
    if (ev.key === "Escape") {
      if (Modal.isOpen()) { ev.preventDefault(); Modal.close(); return; }
    }
    if (Modal.isOpen()) {
      if (Modal.onKey && !Shortcuts.typing(ev.target) && Modal.onKey(ev)) ev.preventDefault();
      return;
    }
    const typing = Shortcuts.typing(ev.target);
    for (const sc of Shortcuts.items) {
      if (sc.code !== ev.code) continue;
      if (!!sc.alt !== ev.altKey || !!sc.ctrl !== (ev.ctrlKey || ev.metaKey) || (sc.shift !== undefined && !!sc.shift !== ev.shiftKey)) continue;
      if (typing && !sc.allowInInputs) continue;
      if (sc.when && !sc.when()) continue;
      ev.preventDefault();
      sc.run(ev);
      return;
    }
  },
  help() {
    const groups = {};
    Shortcuts.items.filter((s) => s.title).forEach((s) => { (groups[s.group || "عام"] = groups[s.group || "عام"] || []).push(s); });
    const keys = (s) => [s.ctrl ? "Ctrl" : "", s.alt ? "Alt" : "", s.shift && s.label !== "?" ? "Shift" : "", s.label]
      .filter(Boolean).map((k) => `<kbd>${esc(k)}</kbd>`).join("");
    Modal.open({
      title: "اختصارات لوحة المفاتيح", wide: false,
      html: `<p class="muted small">الاختصارات تعمل مع لوحة المفاتيح العربية والإنجليزية، ولا تعمل أثناء الكتابة داخل حقل (ما عدا Ctrl+Enter و Esc).</p>
        <div class="kbd-list">${Object.entries(groups).map(([g, list]) => `<h4>${esc(g)}</h4>` + list.map((s) =>
          `<div class="help-row"><span>${esc(s.title)}</span><span class="keys">${keys(s)}</span></div>`).join("")).join("")}</div>`,
      buttons: [{ label: "إغلاق", cls: "primary" }],
    });
  },
};
document.addEventListener("keydown", (ev) => Shortcuts.handle(ev));

/** Turn Dry Run on/off from anywhere (topbar chip, dashboard). Fires "dry-run-changed". */
async function setDryRun(on) {
  await api("PUT", "/api/settings", { dry_run: !!on });
  await refreshStatus();
  document.dispatchEvent(new CustomEvent("dry-run-changed", { detail: { dry_run: !!on } }));
  toast(on ? "تم تفعيل Dry Run: لن يتم تعديل Odoo أو Google Sheet" : "تم إيقاف Dry Run: الحفظ سيكتب فعليًا في Odoo وGoogle Sheet",
    on ? "warn" : "success", 5000);
}

function confirmDryRunToggle(currentlyOn) {
  Modal.open({
    title: currentlyOn ? "إيقاف Dry Run؟" : "تفعيل Dry Run؟",
    html: currentlyOn
      ? `<p>عند إيقاف Dry Run، زر <b>حفظ النتيجة</b> سيقوم فعليًا بـ:</p>
         <ul><li>إضافة <b>Log Note</b> في Chatter العميل في Odoo (و Activity عند «متابعة لاحقًا»).</li>
         <li>تحديث <b>حالة المتابعة</b> و<b>المصدر</b> و<b>الملاحظات</b> في صف العميل في Google Sheet فقط.</li></ul>
         <p class="muted small">يبقى التحقق من «المسؤول الحالي» قبل أي تعديل، ولا يتم تعديل صفوف الآخرين.</p>`
      : "<p>في وضع Dry Run يتم عرض معاينة فقط ولا يُكتب أي شيء في Odoo أو Google Sheet.</p>",
    buttons: [
      { label: currentlyOn ? "نعم، أوقف Dry Run" : "نعم، فعّل Dry Run", cls: currentlyOn ? "success" : "primary",
        onClick: async () => { Modal.close(); try { await setDryRun(!currentlyOn); } catch (e) { toast(e.message, "error"); } } },
      { label: "إلغاء" },
    ],
  });
}

function setTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
  try { theme ? localStorage.setItem("kla-theme", theme) : localStorage.removeItem("kla-theme"); } catch (e) { /* private mode */ }
  const label = $("#theme-label");
  if (label) label.textContent = document.documentElement.dataset.theme === "dark" ? "الوضع الفاتح" : "الوضع الداكن";
}
const PALETTES = ["indigo", "blue", "stc"];
function setPalette(p) {
  if (!PALETTES.includes(p)) p = "indigo";
  if (p === "indigo") delete document.documentElement.dataset.palette; else document.documentElement.dataset.palette = p;
  try { localStorage.setItem("kla-palette", p); } catch (e) { /* private mode */ }
  $$(".swatch").forEach((b) => b.classList.toggle("on", b.dataset.p === p));
}
function cyclePalette() {
  const cur = document.documentElement.dataset.palette || "indigo";
  setPalette(PALETTES[(PALETTES.indexOf(cur) + 1) % PALETTES.length]);
}
function toggleTheme() { setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); }

const PAGES = ["/", "/history", "/skipped", "/errors", "/settings", "/diagnostics", "/reports"];
const PAGE_TITLES = ["الرئيسية", "سجل المتابعات", "العملاء المتخطون", "الأخطاء", "الإعدادات", "التشخيص", "التقارير"];
Shortcuts.register([
  { code: "Slash", label: "?", shift: true, title: "عرض الاختصارات", group: "عام", run: () => Shortcuts.help() },
  { code: "KeyD", label: "D", alt: true, title: "تبديل الوضع الداكن / الفاتح", group: "عام", allowInInputs: true, run: toggleTheme },
  { code: "KeyT", label: "T", alt: true, title: "تبديل نمط الألوان (الأصلي / أزرق وأبيض / stc)", group: "عام", allowInInputs: true, run: cyclePalette },
  ...PAGES.map((url, i) => ({ code: `Digit${i + 1}`, label: String(i + 1), alt: true, title: `الانتقال إلى ${PAGE_TITLES[i]}`,
    group: "التنقل", allowInInputs: true, run: () => { if (location.pathname !== url) location.href = url; } })),
]);

const ACTION_LABELS = {
  retry: "إعادة المحاولة", open_odoo: "فتح Odoo", skip: "تخطي", open_login: "فتح Odoo لتسجيل الدخول",
  open_settings: "فتح الإعدادات", open_crm: "فتح CRM",
};

/** Render an Arabic error with action buttons into `container` (or a toast when none). */
function showError(err, container, handlers = {}) {
  const message = err && err.message ? err.message : "حدث خطأ غير متوقع.";
  if (!container) { toast(message, "error", 6000); return; }
  const actions = (err.actions || []).filter((a) => handlers[a] || a === "open_settings" || a === "open_login");
  container.innerHTML = `<div class="alert error"><div><b>${esc(message)}</b></div>
    ${actions.length ? `<div class="actions">${actions.map((a) => `<button class="btn sm" data-act="${a}">${ACTION_LABELS[a] || a}</button>`).join("")}</div>` : ""}</div>`;
  $$("button[data-act]", container).forEach((b) => {
    b.onclick = async () => {
      const act = b.dataset.act;
      if (handlers[act]) return handlers[act]();
      if (act === "open_settings") location.href = "/settings";
      if (act === "open_login") { try { await api("POST", "/api/odoo/open-login"); toast("تم فتح Odoo. سجّل الدخول ثم اضغط تحقق.", "info"); } catch (e) { toast(e.message, "error"); } }
    };
  });
}

async function withBusy(btn, fn) {
  const old = btn ? btn.innerHTML : "";
  if (btn) { btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> ${old}`; }
  try { return await fn(); } finally { if (btn) { btn.disabled = false; btn.innerHTML = old; } }
}

async function refreshStatus() {
  try {
    const st = await api("GET", "/api/status");
    const g = $("#chip-google"), o = $("#chip-odoo"), d = $("#chip-dry");
    if (g) {
      g.className = "chip " + (st.google.connected ? "ok" : "bad");
      $(".txt", g).textContent = "Google: " + (st.google.connected ? "متصل" : (st.google.configured ? "خطأ" : "غير متصل"));
      g.title = st.google.error || "";
    }
    if (o) {
      o.className = "chip " + (st.odoo.logged_in ? "ok" : (st.odoo.checked ? "bad" : ""));
      $(".txt", o).textContent = "Odoo: " + (st.odoo.logged_in ? "متصل" : (st.odoo.checked ? "تسجيل الدخول مطلوب" : "لم يُفحص"));
    }
    if (d) {
      d.className = "chip " + (st.dry_run ? "warn" : "ok");
      $(".txt", d).textContent = st.dry_run ? "Dry Run: ON" : "Dry Run: OFF";
    }
    window.AGENT_STATUS = st;
    document.dispatchEvent(new CustomEvent("agent-status", { detail: st }));
    return st;
  } catch (e) { return null; }
}

document.addEventListener("DOMContentLoaded", () => {
  setTheme(document.documentElement.dataset.theme || "");
  const th = $("#btn-theme"); if (th) th.onclick = toggleTheme;
  setPalette(document.documentElement.dataset.palette || "indigo");
  $$(".swatch").forEach((b) => b.onclick = () => setPalette(b.dataset.p));
  const sh = $("#btn-shortcuts"); if (sh) sh.onclick = () => Shortcuts.help();
  refreshStatus();
  setInterval(refreshStatus, 20000);
  const dryChip = $("#chip-dry");
  if (dryChip) {
    dryChip.style.cursor = "pointer";
    dryChip.title = "اضغط لتفعيل/إيقاف Dry Run";
    dryChip.onclick = () => confirmDryRunToggle(!!(window.AGENT_STATUS && window.AGENT_STATUS.dry_run));
  }
  const odooChip = $("#chip-odoo");
  if (odooChip) odooChip.onclick = async () => {
    try { const r = await api("POST", "/api/odoo/check-login"); toast(r.logged_in ? "Odoo: متصل" : "تسجيل الدخول إلى Odoo مطلوب", r.logged_in ? "success" : "warn"); }
    catch (e) { toast(e.message, "error"); }
    refreshStatus();
  };
});

// --------------------------------------------------------- follow-up reminders (every page)
/** Polls /api/reminders every minute: a desktop notification + an in-page card when a follow-up is due.
 *  A shown reminder comes back every 30 minutes until «تم» or the customer is opened / gets a new result. */
const Reminders = {
  KEY: "kla-fu-seen", REPEAT_MS: 30 * 60 * 1000, timer: null,
  seen() { try { return JSON.parse(localStorage.getItem(this.KEY) || "{}"); } catch (e) { return {}; } },
  mark(key, untilMs) {
    try {
      const s = this.seen(); const now = Date.now();
      Object.keys(s).forEach((k) => { if (s[k] < now - 3 * 864e5) delete s[k]; });  // keep it small
      s[key] = untilMs; localStorage.setItem(this.KEY, JSON.stringify(s));
    } catch (e) { /* private window: show again next time */ }
  },
  start() { setTimeout(() => this.poll(), 4000); this.timer = setInterval(() => this.poll(), 60000); },
  async poll() {
    let r;
    try { r = await api("GET", "/api/reminders"); } catch (e) { return; }
    DaySummary.maybeAuto(r);
    if (!r.enabled) return;
    const seen = this.seen(); const now = Date.now();
    r.items.filter((i) => !(seen[i.key] > now)).slice(0, 3).forEach((i) => this.show(i));
  },
  async askPermission() {
    if (!("Notification" in window)) { toast("المتصفح لا يدعم الإشعارات. ستظهر التنبيهات داخل الصفحة.", "warn"); return; }
    if (!window.isSecureContext) { toast("إشعارات الويندوز تعمل على جهازك (127.0.0.1) فقط؛ على الجوال تظهر داخل الصفحة.", "info", 7000); return; }
    const p = await Notification.requestPermission();
    toast(p === "granted" ? "تم تفعيل إشعارات الويندوز ✓" : "لم يُسمح بالإشعارات؛ ستظهر داخل الصفحة فقط.", p === "granted" ? "success" : "warn");
  },
  open(item) {
    this.mark(item.key, 9e15);
    if (typeof window.KLA_openLead === "function") window.KLA_openLead(item.fingerprint);
    else location.href = `/?goto=${encodeURIComponent(item.fingerprint)}`;
  },
  beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.18].forEach((t) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(ctx.destination);
        o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.12);
      });
    } catch (e) { /* no sound before the first click: fine */ }
    if (navigator.vibrate) navigator.vibrate([150, 80, 150]);
  },
  show(item) {
    this.mark(item.key, Date.now() + this.REPEAT_MS);
    const when = item.state === "overdue" ? `متأخرة (${item.date} ${item.at})` : item.late ? `الآن (${item.at})` : `الساعة ${item.at}`;
    if ("Notification" in window && Notification.permission === "granted") {
      try {
        const n = new Notification(`موعد متابعة: ${item.company}`, { body: `${when}${item.note ? " — " + item.note : ""}`, tag: item.key, requireInteraction: true });
        n.onclick = () => { window.focus(); n.close(); this.open(item); };
      } catch (e) { /* some browsers need a service worker */ }
    }
    let stack = $("#reminder-stack");
    if (!stack) { stack = document.createElement("div"); stack.id = "reminder-stack"; document.body.appendChild(stack); }
    if ($(`[data-key="${CSS.escape(item.key)}"]`, stack)) return;
    const card = document.createElement("div");
    card.className = "reminder-card";
    card.dataset.key = item.key;
    card.innerHTML = `<div class="rc-head"><span class="rc-ic">⏰</span><b>موعد متابعة ${item.state === "overdue" ? "متأخرة" : ""}</b><span class="spacer"></span>
        <button type="button" class="icon-btn rc-x" title="إغلاق">✕</button></div>
      <div class="rc-co">${esc(item.company)}</div>
      <div class="small muted"><span class="ltr">${esc(item.phone || "")}</span> · ${esc(when)}</div>
      ${item.note ? `<div class="small rc-note">${esc(item.note)}</div>` : ""}
      <div class="rc-actions"><button type="button" class="btn sm primary" data-a="open">فتح العميل</button>
        <button type="button" class="btn sm" data-a="snooze">بعد 10 دقائق</button>
        <button type="button" class="btn sm ghost" data-a="done">تم</button></div>`;
    const close = () => card.remove();
    $(".rc-x", card).onclick = close;
    $('[data-a="open"]', card).onclick = () => { close(); this.open(item); };
    $('[data-a="snooze"]', card).onclick = () => { this.mark(item.key, Date.now() + 10 * 60000); close(); };
    $('[data-a="done"]', card).onclick = () => { this.mark(item.key, 9e15); close(); };
    stack.appendChild(card);
    this.beep();
  },
};

// --------------------------------------------------------------------- day summary
const DaySummary = {
  KEY: "kla-summary-shown",
  maybeAuto(r) {
    if (!r || !r.day_summary_time) return;
    const [day, hm] = (r.now || "").split(" ");
    let shown = "";
    try { shown = localStorage.getItem(this.KEY) || ""; } catch (e) { return; }
    if (shown === day || !hm || hm < r.day_summary_time) return;
    try { localStorage.setItem(this.KEY, day); } catch (e) { /* ignore */ }
    if (!$("#modal-backdrop")) this.open(true);
  },
  async open(auto = false) {
    let d;
    try { d = await api("GET", "/api/reports/day-summary"); } catch (e) { if (!auto) toast(e.message, "error"); return; }
    const t = d.totals;
    const tile = (l, v, sub = "") => `<div class="rtile"><div class="rt-label">${esc(l)}</div><div class="rt-value">${v}</div>${sub ? `<div class="rt-sub">${esc(sub)}</div>` : ""}</div>`;
    const list = (rows, fmt) => rows.length ? `<ul class="ds-list">${rows.map(fmt).join("")}</ul>` : '<div class="muted small">لا يوجد.</div>';
    Modal.open({
      title: `ملخص اليوم — ${d.date}`, wide: true,
      html: `${auto ? '<div class="alert info small">ملخص نهاية اليوم التلقائي (يمكن تغيير الوقت من الإعدادات ← واتساب والمتابعة).</div>' : ""}
        <div class="rep-tiles ds-tiles">${tile("النتائج المسجلة", t.calls, `${t.customers} عميل`)}${tile("تم الرد", t.answered, `${t.answer_rate}%`)}
          ${tile("مهتم", t.interested)}${tile("تم الاشتراك", t.subscribed)}${tile("متابعة لاحقة", t.follow_up)}${tile("رسائل واتساب", t.whatsapp)}</div>
        <div class="grid-2 ds-grid"><div><h3>المهتمون اليوم (${d.interested.length})</h3>
          ${list(d.interested, (h) => `<li><b>${esc(h.company)}</b> <span class="ltr small muted">${esc(h.phone)}</span>${h.note ? `<div class="small muted">${esc(h.note)}</div>` : ""}</li>`)}</div>
          <div><h3>متابعات الغد (${d.tomorrow.length})${d.overdue ? ` · <span class="badge red">متأخرة: ${d.overdue}</span>` : ""}</h3>
          ${list(d.tomorrow, (f) => `<li><span class="ltr">${esc(f.followup_at.slice(11, 16) || "—")}</span> <b>${esc(f.company)}</b>${f.note ? `<div class="small muted">${esc(f.note)}</div>` : ""}</li>`)}</div></div>
        <label class="field" style="margin-top:12px"><span>نص الملخص (للنسخ أو الإرسال)</span><textarea id="ds-text" rows="7" readonly>${esc(d.text)}</textarea></label>`,
      buttons: [
        { label: "نسخ النص", cls: "primary", onClick: async () => {
          try { await navigator.clipboard.writeText(d.text); toast("تم نسخ الملخص", "success"); }
          catch (e) { $("#ds-text").select(); document.execCommand("copy"); toast("تم نسخ الملخص", "success"); }
        } },
        { label: "إرسال واتساب", cls: "wa", onClick: () => window.open(`https://wa.me/?text=${encodeURIComponent(d.text)}`, "_blank", "noopener") },
        { label: "تنزيل Excel", onClick: () => { location.href = "/api/reports/export?period=today"; } },
        { label: "إغلاق" },
      ],
    });
  },
};

document.addEventListener("DOMContentLoaded", () => {
  Reminders.start();
  const perm = $("#btn-notify-perm"); if (perm) perm.onclick = () => Reminders.askPermission();
  $$("[data-day-summary]").forEach((b) => b.onclick = () => DaySummary.open());
});
