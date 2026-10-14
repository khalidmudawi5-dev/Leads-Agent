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
  if (res.status === 401 && data.error && data.error.code === "LOGIN_REQUIRED") {
    const idle = (data.error.details || {}).reason === "idle" ? "error=idle&" : "";
    window.location.href = `/login?${idle}next=${encodeURIComponent(location.pathname + location.search)}`;
  }
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
  open_settings: "فتح الإعدادات", open_crm: "فتح CRM", reconnect_google: "إعادة ربط Google",
};

/** Sign in to Google again (expired / revoked token) without leaving the page; reloads when done. */
async function reconnectGoogle(btn) {
  try {
    const st = await api("GET", "/api/status");
    if (st.remote) { toast("إعادة ربط Google تتم من جهاز الكمبيوتر (تفتح صفحة Google هناك).", "warn", 8000); return; }
    await api("POST", "/api/google/connect");
  } catch (e) { toast(e.message, "error", 8000); return; }
  toast("فُتحت صفحة Google في المتصفح: اختر حسابك ووافق، ثم ارجع هنا.", "info", 10000);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> بانتظار تسجيل الدخول في Google…'; }
  for (let i = 0; i < 150; i++) {  // up to 5 minutes, like the sign-in page itself
    await new Promise((r) => setTimeout(r, 2000));
    let r;
    try { r = await api("GET", "/api/google/connect-status"); } catch (e) { continue; }
    if (r.flow && r.flow.done) { toast("تم ربط Google بنجاح", "success"); setTimeout(() => location.reload(), 800); return; }
    if (r.flow && r.flow.error) { toast(r.flow.error, "error", 9000); break; }
    if (r.flow && !r.flow.running) break;
  }
  if (btn) { btn.disabled = false; btn.textContent = ACTION_LABELS.reconnect_google; }
}

/** Render an Arabic error with action buttons into `container` (or a toast when none). */
function showError(err, container, handlers = {}) {
  const message = err && err.message ? err.message : "حدث خطأ غير متوقع.";
  if (!container) { toast(message, "error", 6000); return; }
  const actions = (err.actions || []).filter((a) => handlers[a] || ["open_settings", "open_login", "reconnect_google"].includes(a));
  container.innerHTML = `<div class="alert error"><div><b>${esc(message)}</b></div>
    ${actions.length ? `<div class="actions">${actions.map((a) => `<button class="btn sm" data-act="${a}">${ACTION_LABELS[a] || a}</button>`).join("")}</div>` : ""}</div>`;
  $$("button[data-act]", container).forEach((b) => {
    b.onclick = async () => {
      const act = b.dataset.act;
      if (handlers[act]) return handlers[act]();
      if (act === "open_settings") location.href = "/settings";
      if (act === "reconnect_google") return reconnectGoogle(b);
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

// ------------------------------------------------------------ idle sign-out
/**
 * With sign-in on: no mouse/keyboard/touch for N minutes (any open tab of the agent) → sign out.
 * Real activity is reported to the agent at most once a minute; background checks never count.
 */
const IdleWatch = {
  KEY: "kla-last-activity",
  minutes: 0, lastSent: 0, warned: false,
  now() { return Date.now(); },
  last() {
    let v = 0;
    try { v = Number(localStorage.getItem(IdleWatch.KEY)) || 0; } catch (e) { /* private mode */ }
    return Math.max(v, IdleWatch._mem || 0);
  },
  mark() {
    const t = IdleWatch.now();
    IdleWatch._mem = t;
    try { localStorage.setItem(IdleWatch.KEY, String(t)); } catch (e) { /* private mode */ }
    if (IdleWatch.warned) { IdleWatch.warned = false; const w = $("#idle-warn"); if (w) w.remove(); }
    if (t - IdleWatch.lastSent > 60000) {
      IdleWatch.lastSent = t;
      fetch("/api/auth/activity", { method: "POST", headers: { "X-KLA": "1" } }).catch(() => {});
    }
  },
  async signOut() {
    try { await fetch("/logout?reason=idle", { method: "POST" }); } catch (e) { /* already out */ }
    window.location.href = "/login?error=idle&next=" + encodeURIComponent(location.pathname);
  },
  tick() {
    const idleMs = IdleWatch.now() - IdleWatch.last();
    const limit = IdleWatch.minutes * 60000;
    if (idleMs >= limit) { IdleWatch.signOut(); return; }
    if (idleMs >= limit - 60000 && !IdleWatch.warned) {
      IdleWatch.warned = true;
      const el = document.createElement("div");
      el.id = "idle-warn"; el.className = "toast warn"; el.setAttribute("role", "alert");
      el.textContent = "لا يوجد نشاط: سيتم تسجيل الخروج خلال دقيقة. حرّك الماوس أو اضغط أي زر للبقاء.";
      ($("#toasts") || document.body).appendChild(el);
    }
  },
  start() {
    IdleWatch.minutes = Number(document.body.dataset.idle || 0);
    if (!IdleWatch.minutes) return;
    IdleWatch.lastSent = IdleWatch.now();  // opening the page already counted on the agent
    IdleWatch._mem = IdleWatch.now();
    try { localStorage.setItem(IdleWatch.KEY, String(IdleWatch._mem)); } catch (e) { /* private mode */ }
    let throttle = 0;
    const onAct = () => { const t = IdleWatch.now(); if (t - throttle > 5000) { throttle = t; IdleWatch.mark(); } };
    ["mousemove", "mousedown", "keydown", "wheel", "touchstart", "scroll"].forEach((ev) =>
      window.addEventListener(ev, onAct, { passive: true, capture: true }));
    setInterval(IdleWatch.tick, 10000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) IdleWatch.tick(); });
  },
};
document.addEventListener("DOMContentLoaded", () => IdleWatch.start());

// ------------------------------------------------------------ end-of-day summary
async function showDaySummary() {
  let d;
  try { d = await api("GET", "/api/reports/summary"); } catch (e) { toast(e.message, "error"); return; }
  const t = d.totals;
  const n = (v) => Number(v || 0).toLocaleString("en-US");
  const canOpen = typeof render === "function" && !!document.getElementById("stats");
  const who = (x, extra = "") => `<li><span>${canOpen && x.fingerprint ? `<button type="button" class="linklike" data-fp="${esc(x.fingerprint)}">${esc(x.company)}</button>` : `<b>${esc(x.company)}</b>`}</span>
    <span class="muted small">${extra}</span></li>`;
  const section = (title, list, row, empty) => `<div class="sum-sec"><h4>${title} <span class="badge">${list.length}</span></h4>
    ${list.length ? `<ul class="sum-list">${list.map(row).join("")}</ul>` : `<div class="small muted">${empty}</div>`}</div>`;
  const tile = (label, value, sub = "") => `<div class="rtile"><div class="rt-label">${label}</div><div class="rt-value">${value}</div>${sub ? `<div class="rt-sub">${sub}</div>` : ""}</div>`;
  Modal.open({
    title: `ملخص اليوم · ${d.date.split("-").reverse().join("/")}`, wide: true,
    html: `<div class="rep-tiles sum-tiles">
        ${tile("النتائج المسجلة", n(t.calls), d.goal ? `من هدف ${n(d.goal)} (${d.goal_pct}%)` : "")}
        ${tile("تم الرد", n(t.answered), `${t.answer_rate}% · لم يرد ${n(t.no_answer)}`)}
        ${tile("مهتم / اشترك", `${n(t.interested)} / ${n(t.subscribed)}`, `متابعة لاحقة ${n(t.follow_up)}`)}
        ${tile("واتساب", n(t.whatsapp), `بانتظار التواصل ${n(d.pending)}`)}
      </div>
      ${d.first_at ? `<p class="small muted" style="margin:8px 0 0">أول نتيجة ${d.first_at} · آخر نتيجة ${d.last_at}</p>` : ""}
      <div class="sum-grid">
        ${section("⭐ المهتمون اليوم", d.hot, (h) => who(h, esc(h.label) + (h.note ? " — " + esc(h.note) : "")), "لا يوجد اليوم.")}
        ${section("📅 متابعات بكرة", d.followups_tomorrow, (i) => who(i, `<span class="ltr">${esc(i.followup_at.slice(11, 16) || "—")}</span>${i.note ? " · " + esc(i.note) : ""}`), "لا توجد متابعات بكرة.")}
        ${section("⏰ متابعات مفتوحة لم تُنجز", d.followups_open, (i) => who(i, `<span class="ltr">${esc(i.followup_at.slice(0, 10))}</span>`), "ممتاز، لا يوجد.")}
        ${section(`💬 يحتاجون واتساب (لم يردوا ${d.attempts_limit}+ مرات)`, d.need_whatsapp, (w) => who(w, `<span class="ltr">${esc(w.phone)}</span> · ${w.attempts} محاولات`), "لا يوجد.")}
      </div>`,
    buttons: [
      { label: "نسخ الملخص", cls: "primary", onClick: async () => {
        try { await navigator.clipboard.writeText(d.text); toast("تم نسخ الملخص.", "success"); }
        catch (e) { toast("تعذر النسخ تلقائيًا.", "warn"); }
      } },
      { label: "إرسال واتساب", onClick: () => window.open(`https://api.whatsapp.com/send?text=${encodeURIComponent(d.text)}`, "_blank", "noopener") },
      { label: "تنزيل Excel", onClick: () => { location.href = "/api/reports/export?period=today"; } },
      { label: "إغلاق" },
    ],
    onOpen: (m) => $$("[data-fp]", m).forEach((b) => b.onclick = async () => {
      Modal.close();
      try { render(await api("POST", `/api/lead/${b.dataset.fp}/goto`)); } catch (e) { toast(e.message, "error"); }
    }),
  });
}

// ------------------------------------------------------------ follow-up reminders
/** A card (+ soft sound, + desktop notification if allowed) N minutes before a timed follow-up, and at its time. */
const Reminders = {
  KEY: "kla-reminded",
  seen() { try { return JSON.parse(localStorage.getItem(Reminders.KEY) || "{}"); } catch (e) { return {}; } },
  remember(key) {
    const s = Reminders.seen(); s[key] = Date.now();
    for (const k of Object.keys(s)) if (Date.now() - s[k] > 3 * 86400000) delete s[k];
    try { localStorage.setItem(Reminders.KEY, JSON.stringify(s)); } catch (e) { /* private mode */ }
  },
  beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [[660, 0], [880, 0.22]].forEach(([f, at]) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "sine"; o.frequency.value = f;
        g.gain.setValueAtTime(0.0001, ctx.currentTime + at);
        g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + at + 0.03);
        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.2);
        o.connect(g).connect(ctx.destination); o.start(ctx.currentTime + at); o.stop(ctx.currentTime + at + 0.22);
      });
      setTimeout(() => ctx.close(), 800);
    } catch (e) { /* no audio */ }
  },
  show(item, mins, sound) {
    let box = $("#reminders");
    if (!box) { box = document.createElement("div"); box.id = "reminders"; box.setAttribute("aria-live", "assertive"); document.body.appendChild(box); }
    const when = mins > 0 ? `بعد ${mins} دقيقة` : "الآن";
    const el = document.createElement("div");
    el.className = "reminder";
    el.innerHTML = `<div class="rm-head">⏰ موعد متابعة ${when} · <span class="ltr">${esc(item.at.slice(11))}</span></div>
      <div class="rm-name">${esc(item.company)}</div>
      <div class="small muted"><span class="ltr">${esc(item.phone || "")}</span>${item.note ? " · " + esc(item.note) : ""}</div>
      <div class="rm-actions"><button class="btn primary sm" type="button" data-open>فتح العميل</button><button class="btn sm" type="button" data-close>تمام</button></div>`;
    $("[data-close]", el).onclick = () => el.remove();
    $("[data-open]", el).onclick = async () => {
      el.remove();
      if (typeof render === "function" && document.getElementById("stats")) {
        try { render(await api("POST", `/api/lead/${item.fingerprint}/goto`)); } catch (e) { toast(e.message, "error"); }
      } else { window.location.href = `/?lead=${encodeURIComponent(item.fingerprint)}`; }
    };
    box.appendChild(el);
    if (sound) Reminders.beep();
    if ("Notification" in window && Notification.permission === "granted" && document.hidden) {
      try { new Notification(`موعد متابعة ${when}: ${item.company}`, { body: `${item.at.slice(11)} ${item.note || ""}`.trim(), tag: item.fingerprint + item.at }); }
      catch (e) { /* not supported */ }
    }
  },
  async check() {
    let r;
    try { r = await api("GET", "/api/followups/reminders"); } catch (e) { return; }
    if (!r.minutes) return;
    const now = Date.now();
    const seen = Reminders.seen();
    for (const it of r.items || []) {
      const at = new Date(it.at.replace(" ", "T") + ":00").getTime();
      if (Number.isNaN(at)) continue;
      const left = at - now;
      const stage = left > 0 && left <= r.minutes * 60000 ? "before" : left <= 0 && left > -10 * 60000 ? "now" : "";
      const key = `${it.fingerprint}|${it.at}|${stage}`;
      if (!stage || seen[key]) continue;
      Reminders.remember(key);
      Reminders.show(it, stage === "before" ? Math.max(1, Math.round(left / 60000)) : 0, r.sound);
    }
  },
  start() {
    setTimeout(Reminders.check, 4000);
    setInterval(Reminders.check, 60000);
  },
};
document.addEventListener("DOMContentLoaded", () => Reminders.start());

// ------------------------------------------- end-of-day summary shown automatically, notifications
/** Once a day after «day_summary_time» (settings) the summary opens by itself on the first page used. */
const AutoSummary = {
  KEY: "kla-summary-shown",
  async check() {
    const at = document.body.dataset.summaryTime || "";
    if (!at) return;
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const hm = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
    let shown = "";
    try { shown = localStorage.getItem(AutoSummary.KEY) || ""; } catch (e) { return; }
    if (shown === day || hm < at || $("#modal-backdrop")) return;
    try { localStorage.setItem(AutoSummary.KEY, day); } catch (e) { return; }
    showDaySummary();
  },
  start() { setTimeout(AutoSummary.check, 6000); setInterval(AutoSummary.check, 60000); },
};

document.addEventListener("DOMContentLoaded", () => {
  AutoSummary.start();
  $$("[data-day-summary]").forEach((b) => b.onclick = () => showDaySummary());
});
