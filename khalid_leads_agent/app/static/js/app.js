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

function setTheme(theme) {
  if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
  try { theme ? localStorage.setItem("kla-theme", theme) : localStorage.removeItem("kla-theme"); } catch (e) { /* private mode */ }
  const label = $("#theme-label");
  if (label) label.textContent = document.documentElement.dataset.theme === "dark" ? "الوضع الفاتح" : "الوضع الداكن";
}
function toggleTheme() { setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"); }

const PAGES = ["/", "/history", "/skipped", "/errors", "/settings", "/diagnostics"];
const PAGE_TITLES = ["الرئيسية", "سجل المتابعات", "العملاء المتخطون", "الأخطاء", "الإعدادات", "التشخيص"];
Shortcuts.register([
  { code: "Slash", label: "?", shift: true, title: "عرض الاختصارات", group: "عام", run: () => Shortcuts.help() },
  { code: "KeyD", label: "D", alt: true, title: "تبديل الوضع الداكن / الفاتح", group: "عام", allowInInputs: true, run: toggleTheme },
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
  const sh = $("#btn-shortcuts"); if (sh) sh.onclick = () => Shortcuts.help();
  refreshStatus();
  setInterval(refreshStatus, 20000);
  const odooChip = $("#chip-odoo");
  if (odooChip) odooChip.onclick = async () => {
    try { const r = await api("POST", "/api/odoo/check-login"); toast(r.logged_in ? "Odoo: متصل" : "تسجيل الدخول إلى Odoo مطلوب", r.logged_in ? "success" : "warn"); }
    catch (e) { toast(e.message, "error"); }
    refreshStatus();
  };
});
