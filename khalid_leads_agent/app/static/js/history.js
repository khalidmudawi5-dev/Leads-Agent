"use strict";
const STEP = {
  success: ['green', 'نجح'], failed: ['red', 'فشل'], blocked: ['red', 'مُنع'], dry_run: ['amber', 'Dry Run'],
  skipped: ['', 'تخطي'], nochange: ['', 'بدون تغيير'], pending: ['', '…'],
};
function stepBadge(s) { const [c, l] = STEP[s] || ['', s]; return `<span class="badge ${c}">${l}</span>`; }
let LABELS = null;

/** Filters come from the form, and on first load from the URL (dashboard cards link here). */
function applyUrlFilters() {
  const q = new URLSearchParams(location.search);
  const form = $("#filters");
  for (const [k, v] of q.entries()) {
    const el = form.elements[k];
    if (!el) continue;
    if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === v)) el.add(new Option(v, v));
    el.value = v;
  }
}

function syncUrl(params) {
  const clean = new URLSearchParams([...params.entries()].filter(([, v]) => v !== ""));
  history.replaceState(null, "", "/history" + (clean.toString() ? "?" + clean : ""));
}

function setResultFilter(code) {
  const sel = $("#f-result");
  if (code && ![...sel.options].some((o) => o.value === code)) sel.add(new Option(code.startsWith("S:") ? code.slice(2) : code, code));
  sel.value = code;
}
function resultName(code) { return code.startsWith("S:") ? code.slice(2) : ((LABELS || {})[code] || code); }

function renderSummary(items) {
  const counts = {};
  items.forEach((i) => { counts[i.result_code] = (counts[i.result_code] || 0) + 1; });
  const current = $("#f-result").value;
  $("#summary").innerHTML = `<span class="pill ${current ? "" : "active"}" data-r="">الكل: ${items.length}</span>` +
    Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([code, n]) =>
      `<span class="pill r-${esc(code)} ${current === code ? "active" : ""}" data-r="${esc(code)}">${esc(code.startsWith("S:") ? code.slice(2) : ((LABELS || {})[code] || code))}: ${n}</span>`).join("");
  $$("#summary .pill").forEach((p) => p.onclick = () => { setResultFilter(p.dataset.r); loadHistory(); });
}

async function loadHistory() {
  const params = new URLSearchParams(new FormData($("#filters")));
  syncUrl(params);
  const tbody = $("#rows");
  try {
    const r = await api("GET", "/api/history?" + params.toString());
    LABELS = r.result_labels;
    const sel = $("#f-result");
    if (sel.options.length <= 2) {  // fill once (a URL value may already be there)
      const keep = sel.value;
      [...sel.options].slice(1).forEach((o) => o.remove());
      Object.entries(r.result_labels).forEach(([k, v]) => sel.add(new Option(v, k)));
      sel.value = keep;
    }
    if (!params.get("result")) renderSummary(r.items); else $("#summary").innerHTML =
      `<span class="pill r-${esc(params.get("result"))} active">${esc(resultName(params.get("result")))}: ${r.items.length}</span>
       <span class="pill" data-r="">عرض الكل</span>`;
    $$("#summary .pill[data-r]").forEach((p) => p.onclick = () => { setResultFilter(p.dataset.r); loadHistory(); });
    if (!r.items.length) { tbody.innerHTML = emptyRow(9, "لا توجد سجلات لهذه الفلاتر", "غيّر الفترة أو النتيجة، أو اضغط «مسح».", "history"); return; }
    tbody.innerHTML = r.items.map((i) => `<tr>
      <td class="who"><b>${esc(i.company)}</b><div class="meta"><span>${esc(i.time)}</span>
        ${i.dry_run ? '<span class="badge amber">Dry Run</span>' : ""}${i.manual ? '<span class="badge">يدوي</span>' : ""}
        ${i.followup_at ? `<span>· متابعة: ${esc(i.followup_at)}</span>` : ""}</div></td>
      <td><span class="phone">${orDash(i.phone)}</span></td>
      <td><span class="pill r-${esc(i.result_code)}">${esc(i.result)}</span></td>
      <td><div class="note">${orDash(i.note)}</div></td>
      <td>${stepBadge(i.odoo)}${i.activity && i.activity !== "skipped" ? `<div class="small" style="margin-top:4px">Activity: ${stepBadge(i.activity)}</div>` : ""}</td>
      <td>${stepBadge(i.google)}</td>
      <td class="ltr nowrap">${fmtDuration(i.duration)}</td>
      <td><div class="warn-list">${[...i.errors, ...i.warnings].map((e) => `<div>${esc(e)}</div>`).join("") || '<span class="muted">—</span>'}</div></td>
      <td class="nowrap">${(i.fingerprint || i.odoo_lead_id) ? `<a class="btn sm success" href="/?update=${i.id}" title="العميل رجع تواصل؟ افتحه وسجّل نتيجة جديدة تُحدِّث Google Sheet وOdoo">تحديث العميل</a>` : ""}
        <button class="btn sm" data-d="${i.id}">تفاصيل</button>
        ${i.can_retry ? `<button class="btn sm primary" data-rt="${i.id}">إعادة المحاولة</button>` : ""}</td></tr>`).join("");
    $$("button[data-rt]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      try { const res = await api("POST", `/api/history/${b.dataset.rt}/retry`); toast(res.message, res.status === "done" ? "success" : "warn"); loadHistory(); }
      catch (e) { toast(e.message, "error", 7000); }
    }));
    $$("button[data-d]").forEach((b) => b.onclick = () => showDetails(b.dataset.d));
  } catch (e) { tbody.innerHTML = `<tr><td colspan="9"><div class="alert error">${esc(e.message)}</div></td></tr>`; }
}

async function showDetails(id) {
  try {
    const d = await api("GET", `/api/history/${id}`);
    const p = d.preview || {};
    Modal.open({
      title: "تفاصيل التحديث", wide: true,
      html: `<h3>Odoo Note</h3>${p.odoo_note ? `<div class="info note-box">${esc(p.odoo_note)}</div>` : '<div class="muted">—</div>'}
        <h3 style="margin-top:14px">سجل تغييرات Google Sheet (نسخة احتياطية للقيم القديمة)</h3>
        ${d.sync_logs.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>الوقت</th><th>الصف</th><th>العمود</th><th>الخلية</th><th>القيمة القديمة</th><th>القيمة الجديدة</th><th>الحالة</th></tr></thead><tbody>
        ${d.sync_logs.map((s) => `<tr><td>${esc(s.time)}</td><td>${s.row}</td><td>${esc(s.column)}</td><td class="ltr">${esc(s.cell)}</td><td class="pre">${orDash(s.old)}</td><td class="pre">${orDash(s.new)}</td><td>${stepBadge(s.status)}</td></tr>`).join("")}
        </tbody></table></div>` : '<div class="muted">لا توجد تغييرات مسجلة.</div>'}`,
      buttons: [{ label: "إغلاق" }],
    });
  } catch (e) { toast(e.message, "error"); }
}

document.addEventListener("DOMContentLoaded", () => {
  $("#filters").onsubmit = (ev) => { ev.preventDefault(); loadHistory(); };
  $("#btn-clear").onclick = () => { $("#filters").reset(); $("#f-result").value = ""; loadHistory(); };
  applyUrlFilters();
  loadHistory();
});
