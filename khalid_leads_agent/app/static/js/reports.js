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

document.addEventListener("DOMContentLoaded", () => {
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
