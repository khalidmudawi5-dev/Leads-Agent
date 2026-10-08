/* Reports: number tiles, results per day (one series, columns), results distribution (bars), per-source table. */
"use strict";
const R = { period: "week", start: "", end: "" };
const fmt = (n) => Number(n || 0).toLocaleString("en-US");
const pct = (n) => `${Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 1 })}%`;

function query() {
  const p = new URLSearchParams({ period: R.period });
  if (R.period === "custom") { p.set("start", R.start); p.set("end", R.end); }
  return p.toString();
}

async function load() {
  $("#btn-export").href = `/api/reports/export?${query()}`;
  let r;
  try { r = await api("GET", `/api/reports?${query()}`); }
  catch (e) { $("#rep-tiles").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; return; }
  $("#rep-range").textContent = r.start === r.end ? r.start : `${r.start} → ${r.end}`;
  renderTiles(r.totals);
  renderDays(r.by_day);
  renderResults(r.by_result, r.totals.calls);
  renderSources(r.by_source);
}

function tile(label, value, sub = "") {
  return `<div class="rtile"><div class="rt-label">${esc(label)}</div><div class="rt-value">${value}</div>${sub ? `<div class="rt-sub">${esc(sub)}</div>` : ""}</div>`;
}
function renderTiles(t) {
  $("#rep-tiles").innerHTML = [
    tile("النتائج المسجلة", fmt(t.calls), `${fmt(t.customers)} عميل`),
    tile("نسبة الرد", pct(t.answer_rate), `${fmt(t.answered)} رد من ${fmt(t.calls)}`),
    tile("نسبة الاهتمام", pct(t.interest_rate), "مهتم + اشترك ÷ من رد"),
    tile("تم الاشتراك", fmt(t.subscribed), `${fmt(t.interested)} مهتم`),
    tile("متابعة لاحقة", fmt(t.follow_up), `${fmt(t.no_answer)} لم يرد`),
    tile("رسائل واتساب", fmt(t.whatsapp)),
  ].join("");
}

/** Clean axis maximum: 1, 2, 5 × 10^n at or above the data maximum. */
function niceMax(v) {
  if (v <= 4) return 4;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v);
}
const DAY = new Intl.DateTimeFormat("ar-SA-u-nu-latn-ca-gregory", { weekday: "short", day: "numeric", month: "numeric" });

function renderDays(days) {
  const box = $("#rep-days");
  if (days.length < 2) { box.innerHTML = emptyState("اختر «هذا الأسبوع» أو «هذا الشهر» لعرض الأيام", "", "history"); return; }
  const max = niceMax(Math.max(...days.map((d) => d.calls)));
  const peak = Math.max(...days.map((d) => d.calls));
  const labelEvery = days.length > 14 ? Math.ceil(days.length / 10) : 1;
  box.innerHTML = `<div class="colchart" role="img" aria-label="عدد النتائج المسجلة لكل يوم">
      <div class="cc-axis"><span>${fmt(max)}</span><span>${fmt(max / 2)}</span><span>0</span></div>
      <div class="cc-plot"><div class="cc-grid"><i></i><i></i><i></i></div>
        ${days.map((d, i) => {
          const h = (d.calls / max) * 100;
          const dt = new Date(d.date + "T12:00:00");
          return `<div class="cc-col" data-i="${i}" tabindex="0">
            ${d.calls === peak && peak > 0 ? `<span class="cc-val" style="bottom:calc(${h}% + 4px)">${fmt(d.calls)}</span>` : ""}
            <span class="cc-bar" style="height:${h}%"></span>
            <span class="cc-x">${i % labelEvery === 0 ? esc(DAY.format(dt)) : ""}</span></div>`;
        }).join("")}</div></div>
    <details class="small" style="margin-top:10px"><summary>عرض كجدول</summary>
      <table class="table"><thead><tr><th>اليوم</th><th>النتائج</th></tr></thead><tbody>
      ${days.map((d) => `<tr><td class="ltr">${d.date}</td><td>${fmt(d.calls)}</td></tr>`).join("")}</tbody></table></details>`;
  const tip = document.createElement("div");
  tip.className = "cc-tip hidden";
  box.appendChild(tip);
  $$(".cc-col", box).forEach((col) => {
    const show = () => {
      const d = days[+col.dataset.i];
      tip.innerHTML = `<b>${esc(DAY.format(new Date(d.date + "T12:00:00")))}</b><br>${fmt(d.calls)} نتيجة`;
      tip.classList.remove("hidden");
      const b = col.getBoundingClientRect(), p = box.getBoundingClientRect();
      tip.style.left = `${Math.min(Math.max(b.left - p.left + b.width / 2 - tip.offsetWidth / 2, 0), p.width - tip.offsetWidth)}px`;
      const bar = $(".cc-bar", col).getBoundingClientRect();
      tip.style.top = `${Math.max(0, bar.top - p.top - tip.offsetHeight - 6)}px`;
    };
    col.onmouseenter = show; col.onfocus = show;
    col.onmouseleave = () => tip.classList.add("hidden"); col.onblur = col.onmouseleave;
  });
}

function renderResults(rows, total) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  $("#rep-results").innerHTML = total ? `<div class="hbars">${rows.map((r) => `<div class="hb-row" title="${esc(r.label)}: ${fmt(r.count)}">
      <span class="hb-label">${esc(r.label)}</span>
      <span class="hb-track">${r.count ? `<span class="hb-bar" style="width:${(r.count / max) * 100}%"></span>` : ""}<span class="hb-val">${fmt(r.count)}</span></span>
    </div>`).join("")}</div>` : emptyState("لا توجد نتائج مسجلة في هذه الفترة", "", "history");
}

function renderSources(rows) {
  $("#rep-sources").innerHTML = rows.length ? `<table class="table"><thead><tr><th>المصدر</th><th>النتائج</th><th>تم الرد</th><th>نسبة الرد</th>
      <th>مهتم</th><th>اشترك</th><th>متابعة</th><th>غير مهتم</th><th>نسبة الاهتمام</th></tr></thead><tbody>
      ${rows.map((s) => `<tr><td><b>${esc(s.source)}</b></td><td>${fmt(s.calls)}</td><td>${fmt(s.answered)}</td><td>${pct(s.answer_rate)}</td>
        <td>${fmt(s.interested)}</td><td>${fmt(s.subscribed)}</td><td>${fmt(s.follow_up)}</td><td>${fmt(s.not_interested)}</td>
        <td><b>${pct(s.interest_rate)}</b></td></tr>`).join("")}</tbody></table>` : emptyState("لا توجد نتائج مسجلة في هذه الفترة", "", "history");
}

// ------------------------------------------------- customers by follow-up status (Odoo enriched)
const CR = { options: [], report: null, busy: false };
const CR_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.2"><path d="M20 6L9 17l-5-5"/></svg>';

function crSelected() { return CR.options.filter((o) => o.on).map((o) => (o.empty ? "(فارغ)" : o.value)); }
function crQuery(fmtName) {
  const p = new URLSearchParams({ fmt: fmtName, odoo: $("#cr-odoo").checked, search_unlinked: $("#cr-search").checked });
  crSelected().forEach((s) => p.append("statuses", s));
  return `/api/reports/customers/export?${p}`;
}
function crRenderChips() {
  $("#cr-chips").innerHTML = CR.options.map((o, i) => `<button type="button" class="fchip ${o.on ? "on" : ""}" data-i="${i}">
      <span class="box">${CR_CHECK}</span><span class="t">${o.empty ? "فارغة (بدون حالة)" : esc(o.value)}</span><span class="n">${o.count}</span></button>`).join("")
    || '<span class="small muted">لا توجد حالات. تأكد من إعداد Google Sheet.</span>';
  $$("#cr-chips .fchip").forEach((b) => b.onclick = () => { CR.options[+b.dataset.i].on = !CR.options[+b.dataset.i].on; crRenderChips(); });
  const n = CR.options.filter((o) => o.on).reduce((s, o) => s + o.count, 0);
  $("#cr-sum").textContent = crSelected().length ? `${crSelected().length} حالة مختارة · ${n} عميل` : "اختر حالة واحدة على الأقل";
}
async function crLoadOptions() {
  try {
    const r = await api("GET", "/api/reports/customers/options");
    const want = new URLSearchParams(location.search).getAll("status");
    CR.options = (r.options || []).filter((o) => o.count > 0 || !o.empty)
      .sort((a, b) => (b.count - a.count))
      .map((o) => ({ ...o, on: want.includes(o.empty ? "(فارغ)" : o.value) }));
    crRenderChips();
    if (want.length) crShow($("#cr-show"));
  } catch (e) { $("#cr-chips").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; }
}
function crSetExport(on) { ["#cr-xlsx", "#cr-pdf", "#cr-print"].forEach((s) => { $(s).disabled = !on; }); }
async function crShow(btn) {
  if (!crSelected().length) { toast("اختر حالة متابعة واحدة على الأقل.", "warn"); return; }
  crSetExport(false);
  $("#cr-table").innerHTML = '<div class="empty"><span class="spinner"></span> جاري قراءة العملاء من Google Sheet وOdoo…</div>';
  await withBusy(btn, async () => {
    try {
      CR.report = await api("POST", "/api/reports/customers",
        { statuses: crSelected(), odoo: $("#cr-odoo").checked, search_unlinked: $("#cr-search").checked });
    } catch (e) { $("#cr-table").innerHTML = `<div class="alert error">${esc(e.message)}</div>`; return; }
    crRender(CR.report);
  });
}
function crRender(r) {
  $("#cr-msg").innerHTML = (r.warnings || []).map((w) => `<div class="alert warn">${esc(w)}</div>`).join("");
  $("#cr-sum").textContent = `${fmt(r.total)} عميل` + (r.odoo_read ? ` · في Odoo: ${fmt(r.in_odoo)} · لديه إيميل: ${fmt(r.with_email)}` : "");
  crSetExport(r.total > 0);
  if (!r.rows.length) { $("#cr-table").innerHTML = emptyState("لا يوجد عملاء بهذه الحالات", "اختر حالة أخرى.", "history"); return; }
  $("#cr-table").innerHTML = `<table class="table hist"><thead><tr><th>#</th><th>المنشأة</th><th>جهة الاتصال</th><th>الجوال</th><th>الإيميل</th>
      <th>الحالة</th><th>المصدر (UTM)</th><th>المرحلة</th><th>آخر ملاحظة</th></tr></thead><tbody>
    ${r.rows.map((x, i) => `<tr><td class="muted">${i + 1}</td>
      <td><b>${esc(x.company)}</b>${x.odoo_url ? ` <a class="small" href="${esc(x.odoo_url)}" target="_blank" rel="noopener">Odoo ↗</a>` : (r.odoo_read ? ' <span class="badge">غير موجود في Odoo</span>' : "")}</td>
      <td>${orDash(x.contact)}</td><td class="ltr nowrap">${orDash(x.phone)}</td><td class="ltr">${x.email ? `<a href="mailto:${esc(x.email)}">${esc(x.email)}</a>` : "—"}</td>
      <td><span class="pill">${esc(x.status)}</span></td><td>${orDash(x.utm_source)}</td><td>${orDash(x.stage)}</td>
      <td><div class="note">${orDash(x.last_note)}</div></td></tr>`).join("")}</tbody></table>`;
}
async function crDownload(btn, fmtName) {
  await withBusy(btn, async () => {
    try {
      const res = await fetch(crQuery(fmtName));
      if (!res.ok) {
        let msg = "تعذر التصدير.";
        try { msg = (await res.json()).error.message || msg; } catch (_) { /* not JSON */ }
        throw new Error(msg);
      }
      const name = decodeURIComponent((res.headers.get("Content-Disposition") || "").split("''")[1] || `customers.${fmtName}`);
      const url = URL.createObjectURL(await res.blob());
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      toast(`تم تنزيل ${name}`, "success");
    } catch (e) {
      toast(e.message, "error", 8000);
      if (fmtName === "pdf") toast("بديل: اضغط «طباعة» واختر «حفظ كـPDF».", "info", 8000);
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  $("#cr-show").onclick = (ev) => crShow(ev.currentTarget);
  $("#cr-xlsx").onclick = (ev) => crDownload(ev.currentTarget, "xlsx");
  $("#cr-pdf").onclick = (ev) => crDownload(ev.currentTarget, "pdf");
  $("#cr-print").onclick = () => window.open(crQuery("print"), "_blank");
  ["#cr-odoo", "#cr-search"].forEach((s) => { $(s).onchange = () => { crSetExport(false); if (s === "#cr-odoo") $("#cr-search").disabled = !$("#cr-odoo").checked; }; });
  crLoadOptions();
  const custom = $("#rep-custom");
  $$("#rep-period button").forEach((b) => b.onclick = () => {
    $$("#rep-period button").forEach((x) => x.classList.toggle("on", x === b));
    R.period = b.dataset.p;
    custom.classList.toggle("hidden", R.period !== "custom");
    if (R.period !== "custom") load();
  });
  $("#rep-filters").onsubmit = (ev) => {
    ev.preventDefault();
    const f = new FormData(ev.target);
    R.start = f.get("start"); R.end = f.get("end") || R.start;
    if (!R.start) { toast("حدد تاريخ البداية.", "warn"); return; }
    load();
  };
  load();
});
