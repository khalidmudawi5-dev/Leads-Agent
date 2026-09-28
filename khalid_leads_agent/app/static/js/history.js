"use strict";
const STEP = {
  success: ['green', 'نجح'], failed: ['red', 'فشل'], blocked: ['red', 'مُنع'], dry_run: ['amber', 'Dry Run'],
  skipped: ['', 'تخطي'], nochange: ['', 'بدون تغيير'], pending: ['', '…'],
};
function stepBadge(s) { const [c, l] = STEP[s] || ['', s]; return `<span class="badge ${c}">${l}</span>`; }

async function loadHistory() {
  const params = new URLSearchParams(new FormData($("#filters")));
  const tbody = $("#rows");
  try {
    const r = await api("GET", "/api/history?" + params.toString());
    const sel = $("#f-result");
    if (sel.options.length === 1) Object.entries(r.result_labels).forEach(([k, v]) => sel.add(new Option(v, k)));
    if (!r.items.length) { tbody.innerHTML = '<tr><td colspan="10" class="empty">لا توجد سجلات.</td></tr>'; return; }
    tbody.innerHTML = r.items.map((i) => `<tr>
      <td class="nowrap">${esc(i.time)}${i.dry_run ? ' <span class="badge amber">Dry Run</span>' : ""}${i.manual ? ' <span class="badge">يدوي</span>' : ""}</td>
      <td><b>${esc(i.company)}</b>${i.followup_at ? `<div class="small muted">متابعة: ${esc(i.followup_at)}</div>` : ""}</td>
      <td class="ltr">${esc(i.phone)}</td><td>${esc(i.result)}</td>
      <td class="pre small" style="max-width:320px">${orDash(i.note)}</td>
      <td>${stepBadge(i.odoo)}${i.activity && i.activity !== "skipped" ? `<div class="small">Activity: ${stepBadge(i.activity)}</div>` : ""}</td>
      <td>${stepBadge(i.google)}</td><td class="ltr">${fmtDuration(i.duration)}</td>
      <td class="small" style="max-width:260px">${[...i.errors, ...i.warnings].map((e) => `<div>${esc(e)}</div>`).join("") || "—"}</td>
      <td class="nowrap"><button class="btn sm" data-d="${i.id}">تفاصيل</button>
        ${i.can_retry ? `<button class="btn sm primary" data-r="${i.id}">إعادة المحاولة</button>` : ""}</td></tr>`).join("");
    $$("button[data-r]").forEach((b) => b.onclick = () => withBusy(b, async () => {
      try { const res = await api("POST", `/api/history/${b.dataset.r}/retry`); toast(res.message, res.status === "done" ? "success" : "warn"); loadHistory(); }
      catch (e) { toast(e.message, "error", 7000); }
    }));
    $$("button[data-d]").forEach((b) => b.onclick = () => showDetails(b.dataset.d));
  } catch (e) { tbody.innerHTML = `<tr><td colspan="10"><div class="alert error">${esc(e.message)}</div></td></tr>`; }
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
  loadHistory();
});
