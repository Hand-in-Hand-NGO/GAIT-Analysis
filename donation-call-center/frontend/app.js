/* Donations call center – single page app (no build step). */
"use strict";

const S = { token: null, user: null, outcomes: [], byCode: {}, extra: {}, filters: { cities: [], sources: [] }, view: null, agents: [] };
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => (Number(n) || 0).toLocaleString("ar-EG", { maximumFractionDigits: 0 }) + " ج.م";
const int = (n) => (Number(n) || 0).toLocaleString("ar-EG");
const pct = (n) => (Number(n) || 0).toLocaleString("ar-EG", { maximumFractionDigits: 1 }) + "٪";
// server stores naive UTC
const parseUtc = (s) => (s ? new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z") : null);
const fmtDt = (s) => { const d = parseUtc(s); return d ? d.toLocaleString("ar-EG", { dateStyle: "short", timeStyle: "short" }) : "—"; };
const startOfDay = (d) => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
const isoLocalDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3200);
}

async function api(path, { method = "GET", body, form, raw } = {}) {
  const headers = {};
  if (S.token) headers.Authorization = `Bearer ${S.token}`;
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  const res = await fetch(path, { method, headers, body: payload });
  if (res.status === 401 && S.token) { logout(); throw new Error("انتهت الجلسة"); }
  if (raw) return res;
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => e.msg).join("، ") : "حدث خطأ";
    toast(msg); throw new Error(msg);
  }
  return data;
}

const chip = (code, extraClass = "") => {
  const o = S.byCode[code];
  return `<span class="chip ${o ? o.category : code === "new" ? "" : "invalid"} ${extraClass}">${esc(o ? o.label : S.extra[code] || code)}</span>`;
};

/* ---------------- auth ---------------- */
function loginView() {
  $("#root").innerHTML = `
  <div class="login"><form class="panel" id="loginForm">
    <h1>كول سنتر التبرعات</h1>
    <p class="muted">سجّل الدخول بحساب المدير أو الايجنت.</p>
    <label class="field">اسم المستخدم<input id="lu" autocomplete="username" required></label>
    <label class="field">كلمة المرور<input id="lp" type="password" autocomplete="current-password" required></label>
    <button class="btn primary">دخول</button>
  </form></div>`;
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    const r = await api("/api/auth/login", { method: "POST", body: { username: $("#lu").value, password: $("#lp").value } });
    S.token = r.token; S.user = r.user; sessionStorage.setItem("cc_token", r.token);
    boot();
  };
}
function logout() { S.token = null; S.user = null; sessionStorage.removeItem("cc_token"); loginView(); }

/* ---------------- shell ---------------- */
const MANAGER_NAV = [
  ["dashboard", "لوحة التحكم"], ["donors", "المتبرعين"], ["distribution", "التوزيع"],
  ["followups", "المتابعات"], ["calls", "سجل المكالمات"], ["reports", "التقارير"], ["team", "فريق العمل"],
];
const AGENT_NAV = [["queue", "قائمة الاتصال"], ["followups", "متابعاتي"], ["calls", "مكالماتي"], ["mystats", "أدائي"]];

function shell() {
  const nav = S.user.role === "manager" ? MANAGER_NAV : AGENT_NAV;
  $("#root").innerHTML = `
  <div class="shell">
    <aside class="side">
      <div class="brand"><b>كول سنتر التبرعات</b><small>${S.user.role === "manager" ? "لوحة المدير" : "شاشة الايجنت"}</small></div>
      <nav class="nav">${nav.map(([k, l]) => `<button data-view="${k}">${l}</button>`).join("")}</nav>
      <div class="me"><span>${esc(S.user.name)}</span><button class="btn small" id="logout">تسجيل خروج</button></div>
    </aside>
    <main id="main"></main>
  </div>`;
  $$(".nav button").forEach((b) => (b.onclick = () => go(b.dataset.view)));
  $("#logout").onclick = logout;
}

function go(view) {
  S.view = view;
  $$(".nav button").forEach((b) => b.setAttribute("aria-current", b.dataset.view === view ? "page" : "false"));
  if (location.hash !== "#" + view) history.replaceState(null, "", "#" + view);
  VIEWS[view]().catch((e) => console.error(e));
}

async function boot() {
  S.token = S.token || sessionStorage.getItem("cc_token");
  if (!S.token) return loginView();
  try { S.user = await api("/api/auth/me"); } catch { return; }
  const meta = await api("/api/meta/outcomes");
  S.outcomes = meta.outcomes; S.extra = meta.extra_statuses;
  S.byCode = Object.fromEntries(meta.outcomes.map((o) => [o.code, o]));
  S.filters = await api("/api/meta/filters");
  if (S.user.role === "manager") S.agents = await api("/api/users?role=agent");
  shell();
  const nav = S.user.role === "manager" ? MANAGER_NAV : AGENT_NAV;
  const want = location.hash.slice(1);
  go(nav.some(([k]) => k === want) ? want : nav[0][0]);
}

/* ---------------- shared helpers ---------------- */
function rangeControls(id, preset = "today") {
  return `<div class="row" id="${id}">
    <label class="field">الفترة<select data-r="preset">
      <option value="today">اليوم</option><option value="yesterday">أمس</option><option value="7">آخر ٧ أيام</option>
      <option value="30">آخر ٣٠ يوم</option><option value="custom">مخصص</option></select></label>
    <label class="field">من<input type="date" data-r="from"></label>
    <label class="field">إلى<input type="date" data-r="to"></label>
  </div>`;
}
function readRange(id) {
  const box = $("#" + id);
  const preset = $('[data-r="preset"]', box).value;
  const today = startOfDay(new Date());
  let from = today, to = new Date(today.getTime() + 864e5);
  if (preset === "yesterday") { from = new Date(today.getTime() - 864e5); to = today; }
  else if (preset === "7" || preset === "30") from = new Date(today.getTime() - (Number(preset) - 1) * 864e5);
  else if (preset === "custom") {
    const f = $('[data-r="from"]', box).value, t = $('[data-r="to"]', box).value;
    if (f) from = startOfDay(new Date(f + "T00:00")); if (t) to = new Date(startOfDay(new Date(t + "T00:00")).getTime() + 864e5);
  }
  $('[data-r="from"]', box).value = isoLocalDate(from);
  $('[data-r="to"]', box).value = isoLocalDate(new Date(to.getTime() - 1));
  return `date_from=${encodeURIComponent(from.toISOString())}&date_to=${encodeURIComponent(to.toISOString())}`;
}
function bindRange(id, cb) {
  const box = $("#" + id);
  $$("select,input", box).forEach((el) => (el.onchange = () => {
    if (el.dataset.r !== "preset") $('[data-r="preset"]', box).value = "custom";
    cb();
  }));
}
const agentOptions = (sel, withAll = true) =>
  (withAll ? `<option value="">كل الايجنتس</option>` : "") +
  S.agents.filter((a) => a.active).map((a) => `<option value="${a.id}" ${String(sel) === String(a.id) ? "selected" : ""}>${esc(a.name)}</option>`).join("");
const opts = (list, sel, all) => `<option value="">${all}</option>` + list.map((v) => `<option ${v === sel ? "selected" : ""}>${esc(v)}</option>`).join("");

function donorTable(items, { select = false, showAgent = true, actions = true } = {}) {
  if (!items.length) return `<div class="empty">لا يوجد متبرعين هنا.</div>`;
  const now = Date.now();
  return `<div class="tablewrap"><table><thead><tr>
    ${select ? `<th><input type="checkbox" id="selAll" aria-label="تحديد الكل"></th>` : ""}
    <th>المتبرع</th><th>الموبايل</th><th>المدينة</th><th>المصدر</th>${showAgent ? "<th>الايجنت</th>" : ""}
    <th>الحالة</th><th class="num">محاولات</th><th>المتابعة القادمة</th><th class="num">إجمالي التبرع</th>${actions ? "<th></th>" : ""}
  </tr></thead><tbody>${items.map((d) => {
    const due = parseUtc(d.next_action_at); const overdue = due && due.getTime() < now;
    return `<tr>
      ${select ? `<td><input type="checkbox" class="sel" value="${d.id}" aria-label="تحديد"></td>` : ""}
      <td>${esc(d.name)}${d.do_not_call ? ' <span class="chip negative">لا تتصل</span>' : ""}</td>
      <td class="num" dir="ltr">${esc(d.phone)}</td><td>${esc(d.city || "—")}</td><td>${esc(d.source || "—")}</td>
      ${showAgent ? `<td>${esc(d.agent_name || "غير موزع")}</td>` : ""}
      <td>${chip(d.status)}</td><td class="num">${int(d.attempts)}</td>
      <td>${due ? `<span class="chip ${overdue ? "overdue" : ""}">${fmtDt(d.next_action_at)}</span>` : "—"}</td>
      <td class="num">${d.total_donated ? money(d.total_donated) : "—"}</td>
      ${actions ? `<td><button class="btn small" data-open="${d.id}">${S.user.role === "agent" ? "اتصال" : "فتح"}</button></td>` : ""}
    </tr>`;
  }).join("")}</tbody></table></div>`;
}
function bindDonorTable(root, onChange) {
  $$("[data-open]", root).forEach((b) => (b.onclick = () => openCall(Number(b.dataset.open), onChange)));
  const all = $("#selAll", root);
  if (all) all.onchange = () => $$(".sel", root).forEach((c) => (c.checked = all.checked));
}

/* ---------------- call modal ---------------- */
async function openCall(donorId, onDone) {
  const d = await api(`/api/donors/${donorId}`);
  const dlg = $("#callDialog"), box = $("#callModal");
  let chosen = null; const started = Date.now();
  const canCall = S.user.role === "agent" || S.user.role === "manager";
  box.innerHTML = `
    <div class="head"><div><h2>${esc(d.name)}</h2>
      <div class="muted"><span dir="ltr">${esc(d.phone)}</span>${d.alt_phone ? ` · <span dir="ltr">${esc(d.alt_phone)}</span>` : ""}
      · ${esc(d.city || "")} · ${esc(d.source || "")}</div></div>
      <div class="row">${chip(d.status)}<span class="chip num" id="timer">00:00</span><button class="btn small" data-close>إغلاق</button></div></div>
    <div class="grid2">
      <div class="kpi"><span>آخر تبرع</span><b class="num">${d.last_donation_amount ? money(d.last_donation_amount) : "—"}</b></div>
      <div class="kpi"><span>المحاولات</span><b class="num">${int(d.attempts)}</b></div>
      <div class="kpi"><span>وعد قائم</span><b class="num">${d.status === "pledged" ? money(d.pledge_amount) : "—"}</b><small>${d.pledge_due ? fmtDt(d.pledge_due) : ""}</small></div>
      <div class="kpi"><span>الايجنت</span><b style="font-size:15px">${esc(d.agent_name || "غير موزع")}</b></div>
    </div>
    ${d.notes ? `<div class="panel"><b>ملاحظات</b><span>${esc(d.notes)}</span></div>` : ""}
    ${d.do_not_call ? `<div class="chip negative">هذا المتبرع طلب عدم الاتصال</div>` : ""}
    ${canCall ? `<h3>نتيجة المكالمة</h3>
    <div class="outcomes">${S.outcomes.map((o) => `<button type="button" data-oc="${o.code}" aria-pressed="false"><span class="chip ${o.category}">${esc(o.label)}</span></button>`).join("")}</div>
    <form id="callForm" class="grid2">
      <label class="field" data-need="amount" hidden>المبلغ (ج.م)<input id="cAmount" type="number" min="0" step="1"></label>
      <label class="field" data-need="pay" hidden>طريقة الدفع<select id="cPay">
        <option>تحويل بنكي</option><option>فودافون كاش</option><option>إنستاباي</option><option>مندوب تحصيل</option><option>فوري</option><option>بطاقة</option><option>كاش بالمقر</option></select></label>
      <label class="field" data-need="follow" hidden><span id="followLbl">موعد المتابعة</span><input id="cFollow" type="datetime-local"></label>
      <label class="field" style="grid-column:1/-1">ملاحظات<textarea id="cNotes" rows="2"></textarea></label>
      <div class="row" style="grid-column:1/-1"><button class="btn primary" id="saveCall" disabled>حفظ النتيجة</button></div>
    </form>` : ""}
    <h3>سجل المكالمات (${int(d.calls.length)})</h3>
    <div class="history">${d.calls.length ? d.calls.map((c) => `<div>${chip(c.outcome)}<span class="muted">${fmtDt(c.created_at)}</span>
      <span>${esc(c.agent_name)}</span>${c.amount ? `<b class="num">${money(c.amount)}</b>` : ""}${c.payment_method ? `<span class="muted">${esc(c.payment_method)}</span>` : ""}
      ${c.follow_up_at ? `<span class="muted">متابعة: ${fmtDt(c.follow_up_at)}</span>` : ""}${c.notes ? `<span>— ${esc(c.notes)}</span>` : ""}</div>`).join("") : '<span class="muted">لا توجد مكالمات بعد.</span>'}</div>
    ${S.user.role === "manager" && ["exhausted", ...S.outcomes.filter((o) => o.final).map((o) => o.code)].includes(d.status)
      ? `<div class="row"><button class="btn" id="reopen">إعادة فتح المتبرع للاتصال</button></div>` : ""}`;
  const timer = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    const t = $("#timer", box); if (t) t.textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }, 1000);
  const close = () => { clearInterval(timer); dlg.close(); };
  dlg.onclose = () => clearInterval(timer);
  $("[data-close]", box).onclick = close;
  $$("[data-oc]", box).forEach((b) => (b.onclick = () => {
    chosen = S.byCode[b.dataset.oc];
    $$("[data-oc]", box).forEach((x) => x.setAttribute("aria-pressed", x === b ? "true" : "false"));
    $('[data-need="amount"]', box).hidden = !chosen.needs_amount;
    $('[data-need="pay"]', box).hidden = chosen.code !== "donated";
    $('[data-need="follow"]', box).hidden = !(chosen.needs_follow_up || ["interested", "send_info", "complaint"].includes(chosen.code));
    $("#followLbl", box).textContent = chosen.code === "pledged" ? "موعد تحصيل الوعد" : chosen.needs_follow_up ? "موعد المتابعة (مطلوب)" : "موعد المتابعة (اختياري)";
    $("#saveCall", box).disabled = false;
  }));
  const form = $("#callForm", box);
  if (form) form.onsubmit = async (e) => {
    e.preventDefault(); if (!chosen) return;
    const follow = $("#cFollow", box).value;
    const body = {
      outcome: chosen.code, notes: $("#cNotes", box).value || null,
      amount: chosen.needs_amount && $("#cAmount", box).value ? Number($("#cAmount", box).value) : null,
      payment_method: chosen.code === "donated" ? $("#cPay", box).value : null,
      follow_up_at: follow && !$('[data-need="follow"]', box).hidden ? new Date(follow).toISOString() : null,
      duration_sec: Math.round((Date.now() - started) / 1000),
    };
    await api(`/api/donors/${donorId}/calls`, { method: "POST", body });
    toast(`تم حفظ: ${chosen.label}`); close(); onDone && onDone();
  };
  const reopen = $("#reopen", box);
  if (reopen) reopen.onclick = async () => { await api(`/api/donors/${donorId}`, { method: "PATCH", body: { status: "new" } }); toast("تمت إعادة الفتح"); close(); onDone && onDone(); };
  dlg.showModal();
}

/* ---------------- manager views ---------------- */
async function dashboardView() {
  const m = $("#main");
  m.innerHTML = `<div class="head"><h1>لوحة التحكم</h1>${rangeControls("dr")}</div><div id="dash"></div>`;
  const load = async () => {
    const r = await api(`/api/reports/overview?${readRange("dr")}`);
    const out = await api(`/api/reports/outcomes?${readRange("dr")}`);
    const max = Math.max(1, ...out.items.map((i) => i.count));
    $("#dash").innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>إجمالي المتبرعين</span><b>${int(r.total_donors)}</b><small>${int(r.unassigned)} غير موزع</small></div>
      <div class="kpi"><span>المكالمات</span><b>${int(r.calls)}</b><small>تم الوصول ${int(r.reached)} (${pct(r.contact_rate)})</small></div>
      <div class="kpi"><span>تبرعات</span><b>${int(r.donated)}</b><small>${money(r.donated_amount)}</small></div>
      <div class="kpi"><span>وعود جديدة</span><b>${int(r.pledged)}</b><small>${money(r.pledged_amount)}</small></div>
      <div class="kpi"><span>وعود قائمة (لم تُحصّل)</span><b>${money(r.open_pledge_amount)}</b></div>
      <div class="kpi"><span>متابعات متأخرة</span><b style="color:var(--bad)">${int(r.overdue_followups)}</b></div>
    </div>
    <div class="cols">
      <div class="panel"><h2>أداء الايجنتس</h2>${agentsTable(r.agents, true)}</div>
      <div class="panel"><h2>توزيع نتائج المكالمات</h2><div class="bars">${out.items.map((i) => `
        <div class="bar"><span>${esc(i.label)}</span><div class="track"><div class="fill ${i.category}" style="width:${(100 * i.count) / max}%"></div></div><span class="num">${int(i.count)}</span></div>`).join("")}</div></div>
    </div>`;
  };
  bindRange("dr", load); await load();
}

function agentsTable(rows, compact = false) {
  if (!rows.length) return `<div class="empty">لا يوجد ايجنتس. أضف ايجنت من صفحة فريق العمل.</div>`;
  return `<div class="tablewrap"><table><thead><tr><th>الايجنت</th><th class="num">مكالمات</th><th>الهدف اليومي</th>
    <th class="num">وصول</th><th class="num">اتبرع</th><th class="num">المبلغ</th><th class="num">وعود</th>
    ${compact ? "" : `<th class="num">عنده نية</th><th class="num">معاودة</th><th class="num">لا يرد/مشغول</th><th class="num">مغلق</th><th class="num">رفض</th><th class="num">رقم خطأ</th><th class="num">وعود حُصّلت</th><th class="num">متوسط المكالمة</th>`}
    <th class="num">تحويل</th><th class="num">مفتوح</th><th class="num">متأخر</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td>${esc(r.agent_name)}${r.active ? "" : ' <span class="chip">موقوف</span>'}</td>
      <td class="num">${int(r.calls)}</td>
      <td><div class="progress" title="${int(r.calls)} / ${int(r.daily_target)}"><i style="width:${Math.min(100, (100 * r.calls) / (r.daily_target || 1))}%"></i></div></td>
      <td class="num">${pct(r.contact_rate)}</td><td class="num">${int(r.donated)}</td><td class="num">${money(r.donated_amount)}</td>
      <td class="num">${int(r.pledged)}</td>
      ${compact ? "" : `<td class="num">${int(r.interested)}</td><td class="num">${int(r.callbacks)}</td><td class="num">${int(r.unreachable - r.phone_off)}</td>
      <td class="num">${int(r.phone_off)}</td><td class="num">${int(r.not_interested)}</td><td class="num">${int(r.invalid)}</td>
      <td class="num">${int(r.pledges_fulfilled)}</td><td class="num">${int(Math.round(r.avg_duration_sec / 60 * 10) / 10)} د</td>`}
      <td class="num">${pct(r.conversion_rate)}</td><td class="num">${int(r.open)}</td>
      <td class="num" style="${r.overdue_followups ? "color:var(--bad);font-weight:600" : ""}">${int(r.overdue_followups)}</td></tr>`).join("")}
    </tbody></table></div>`;
}

async function donorsView() {
  const m = $("#main");
  const statusOpts = [["", "كل الحالات"], ["new", S.extra.new], ...S.outcomes.map((o) => [o.code, o.label]), ["exhausted", S.extra.exhausted]];
  m.innerHTML = `
  <div class="head"><h1>المتبرعين</h1><div class="row">
    <button class="btn" id="addDonor">إضافة متبرع</button>
    <label class="btn primary" for="csvFile" style="cursor:pointer">استيراد ملف CSV</label><input type="file" id="csvFile" accept=".csv,text/csv" hidden>
  </div></div>
  <div class="panel"><div class="row">
    <label class="field">بحث<input id="fq" placeholder="اسم أو موبايل"></label>
    <label class="field">الايجنت<select id="fa"><option value="">الكل</option><option value="none">غير موزع</option>${agentOptions("", false)}</select></label>
    <label class="field">الحالة<select id="fs">${statusOpts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("")}</select></label>
    <label class="field">المدينة<select id="fc">${opts(S.filters.cities, "", "الكل")}</select></label>
    <label class="field">المصدر<select id="fsrc">${opts(S.filters.sources, "", "الكل")}</select></label>
  </div>
  <div class="row"><span class="muted" id="count"></span><span style="flex:1"></span>
    <label class="field">توزيع المحدد على<select id="bulkAgent">${agentOptions("", false)}</select></label>
    <button class="btn" id="bulkAssign">توزيع المحدد</button><button class="btn danger" id="bulkUn">سحب المحدد</button></div></div>
  <div id="list"></div><div class="row" id="pager"></div>`;
  let page = 1;
  const load = async () => {
    const a = $("#fa").value;
    const p = new URLSearchParams({ page, page_size: 50 });
    if ($("#fq").value) p.set("q", $("#fq").value);
    if (a === "none") p.set("unassigned", "true"); else if (a) p.set("agent_id", a);
    if ($("#fs").value) p.set("status", $("#fs").value);
    if ($("#fc").value) p.set("city", $("#fc").value);
    if ($("#fsrc").value) p.set("source", $("#fsrc").value);
    const r = await api(`/api/donors?${p}`);
    $("#count").textContent = `${int(r.total)} متبرع`;
    $("#list").innerHTML = donorTable(r.items, { select: true });
    bindDonorTable($("#list"), load);
    const pages = Math.max(1, Math.ceil(r.total / 50));
    $("#pager").innerHTML = pages > 1 ? `<button class="btn small" id="prev" ${page <= 1 ? "disabled" : ""}>السابق</button><span class="muted">صفحة ${int(page)} من ${int(pages)}</span><button class="btn small" id="next" ${page >= pages ? "disabled" : ""}>التالي</button>` : "";
    if ($("#prev")) $("#prev").onclick = () => { page--; load(); };
    if ($("#next")) $("#next").onclick = () => { page++; load(); };
  };
  ["fa", "fs", "fc", "fsrc"].forEach((id) => ($("#" + id).onchange = () => { page = 1; load(); }));
  let t; $("#fq").oninput = () => { clearTimeout(t); t = setTimeout(() => { page = 1; load(); }, 300); };
  const selected = () => $$(".sel:checked").map((c) => Number(c.value));
  $("#bulkAssign").onclick = async () => {
    const ids = selected(); if (!ids.length) return toast("حدد متبرعين أولاً");
    const r = await api("/api/distribution/assign", { method: "POST", body: { donor_ids: ids, agent_id: Number($("#bulkAgent").value) } });
    toast(`تم توزيع ${int(r.assigned)} متبرع`); load();
  };
  $("#bulkUn").onclick = async () => {
    const ids = selected(); if (!ids.length) return toast("حدد متبرعين أولاً");
    const r = await api("/api/distribution/unassign", { method: "POST", body: { donor_ids: ids } });
    toast(`تم سحب ${int(r.unassigned)} متبرع`); load();
  };
  $("#csvFile").onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await api("/api/donors/import", { method: "POST", form: fd });
    toast(`تمت إضافة ${int(r.created)} · مكرر ${int(r.duplicates)} · غير صالح ${int(r.invalid_rows.length)}`);
    e.target.value = ""; S.filters = await api("/api/meta/filters"); donorsView();
  };
  $("#addDonor").onclick = () => formDialog("إضافة متبرع", [
    ["name", "الاسم", "text", true], ["phone", "الموبايل", "tel", true], ["alt_phone", "موبايل آخر", "tel"],
    ["city", "المدينة", "text"], ["source", "المصدر / الحملة", "text"], ["last_donation_amount", "آخر تبرع", "number"], ["notes", "ملاحظات", "text"],
  ], async (v) => { await api("/api/donors", { method: "POST", body: v }); toast("تمت الإضافة"); load(); });
  await load();
}

function formDialog(title, fields, onSubmit) {
  const dlg = $("#formDialog"), box = $("#formModal");
  box.innerHTML = `<div class="head"><h2>${esc(title)}</h2><button class="btn small" data-close>إغلاق</button></div>
    <form id="fd" class="grid2">${fields.map(([k, l, type, req, extra]) => type === "select"
      ? `<label class="field">${l}<select id="f_${k}">${extra}</select></label>`
      : `<label class="field">${l}<input id="f_${k}" type="${type}" ${req ? "required" : ""}></label>`).join("")}
    <div class="row" style="grid-column:1/-1"><button class="btn primary">حفظ</button></div></form>`;
  $("[data-close]", box).onclick = () => dlg.close();
  $("#fd", box).onsubmit = async (e) => {
    e.preventDefault();
    const v = {};
    fields.forEach(([k, , type]) => { const x = $("#f_" + k, box).value; if (x !== "") v[k] = type === "number" ? Number(x) : x; });
    await onSubmit(v); dlg.close();
  };
  dlg.showModal();
}

async function distributionView() {
  const m = $("#main");
  const s = await api("/api/distribution/summary");
  S.agents = await api("/api/users?role=agent");
  const active = s.agents.filter((a) => a.active);
  const maxOpen = Math.max(1, ...s.agents.map((a) => a.open));
  m.innerHTML = `
  <div class="head"><h1>توزيع الداتا على الايجنتس</h1></div>
  <div class="kpis"><div class="kpi"><span>غير موزع (جديد)</span><b>${int(s.unassigned_new)}</b><small>إجمالي غير موزع ${int(s.unassigned_total)}</small></div>
    ${s.agents.map((a) => `<div class="kpi"><span>${esc(a.name)}${a.active ? "" : " (موقوف)"}</span><b>${int(a.open)}</b><small>مفتوح · ${int(a.new)} جديد · ${int(a.assigned)} إجمالي</small>
      <div class="progress"><i style="width:${(100 * a.open) / maxOpen}%"></i></div></div>`).join("")}</div>
  <div class="cols">
    <form class="panel" id="autoForm"><h2>توزيع تلقائي</h2>
      <p class="muted">يوزع المتبرعين غير الموزعين على الايجنتس المختارين.</p>
      <div class="row">${active.map((a) => `<label><input type="checkbox" name="ag" value="${a.id}" checked> ${esc(a.name)}</label>`).join("") || '<span class="muted">لا يوجد ايجنتس نشطين</span>'}</div>
      <div class="grid2">
        <label class="field">طريقة التوزيع<select id="mode">
          <option value="balanced">متوازن (الأقل حملاً يأخذ أولاً)</option><option value="equal">بالتساوي (بالدور)</option><option value="fixed">عدد ثابت لكل ايجنت</option></select></label>
        <label class="field">عدد لكل ايجنت<input id="perAgent" type="number" min="1" value="50"></label>
        <label class="field">الحد الأقصى الإجمالي<input id="limit" type="number" min="1" placeholder="الكل"></label>
        <label class="field">المدينة<select id="dCity">${opts(S.filters.cities, "", "الكل")}</select></label>
        <label class="field">المصدر<select id="dSrc">${opts(S.filters.sources, "", "الكل")}</select></label>
        <label class="field">الحالات<select id="dStat"><option value="new">جديد فقط</option><option value="new,exhausted">جديد + استنفد المحاولات</option></select></label>
      </div>
      <div class="row"><button class="btn primary">وزّع الآن</button></div></form>
    <form class="panel" id="trForm"><h2>نقل داتا ايجنت (غياب / استقالة)</h2>
      <p class="muted">ينقل متبرعي ايجنت لواحد أو أكثر بالتساوي. المتبرعين اللي قفلوا (اتبرع/رفض) بيفضلوا باسم الايجنت الأصلي إلا لو اخترت الكل.</p>
      <label class="field">من<select id="trFrom">${s.agents.map((a) => `<option value="${a.id}">${esc(a.name)} (${int(a.open)} مفتوح)</option>`).join("")}</select></label>
      <div class="row">${active.map((a) => `<label><input type="checkbox" name="trTo" value="${a.id}"> ${esc(a.name)}</label>`).join("")}</div>
      <label><input type="checkbox" id="trAll"> نقل الكل بما فيهم المقفول</label>
      <div class="row"><button class="btn primary">انقل</button></div></form>
  </div>
  <div class="panel"><h2>آخر عمليات التوزيع</h2><div id="hist"></div></div>`;
  $("#autoForm").onsubmit = async (e) => {
    e.preventDefault();
    const ids = $$('input[name="ag"]:checked').map((c) => Number(c.value));
    if (!ids.length) return toast("اختر ايجنت واحد على الأقل");
    const mode = $("#mode").value;
    const body = { agent_ids: ids, mode, filter: { city: $("#dCity").value || null, source: $("#dSrc").value || null, statuses: $("#dStat").value.split(",") } };
    if (mode === "fixed") body.per_agent = Number($("#perAgent").value);
    if ($("#limit").value) body.limit = Number($("#limit").value);
    const r = await api("/api/distribution/auto", { method: "POST", body });
    toast(`تم توزيع ${int(r.assigned)} متبرع`); distributionView();
  };
  $("#trForm").onsubmit = async (e) => {
    e.preventDefault();
    const to = $$('input[name="trTo"]:checked').map((c) => Number(c.value));
    if (!to.length) return toast("اختر الايجنت المستلم");
    const r = await api("/api/distribution/transfer", { method: "POST", body: { from_agent_id: Number($("#trFrom").value), to_agent_ids: to, only_open: !$("#trAll").checked } });
    toast(`تم نقل ${int(r.moved)} متبرع`); distributionView();
  };
  const h = await api("/api/distribution/history?limit=30");
  const reason = { auto: "تلقائي", manual: "يدوي", transfer: "نقل", unassign: "سحب" };
  $("#hist").innerHTML = h.length ? `<div class="tablewrap"><table><thead><tr><th>الوقت</th><th>متبرع #</th><th>من</th><th>إلى</th><th>النوع</th><th>بواسطة</th></tr></thead><tbody>
    ${h.map((x) => `<tr><td>${fmtDt(x.at)}</td><td class="num">${x.donor_id}</td><td>${esc(x.from || "—")}</td><td>${esc(x.to || "—")}</td><td>${reason[x.reason] || x.reason}</td><td>${esc(x.by)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">لا توجد عمليات بعد.</div>`;
}

async function followupsView() {
  const m = $("#main");
  const isMgr = S.user.role === "manager";
  m.innerHTML = `<div class="head"><h1>${isMgr ? "المتابعات" : "متابعاتي"}</h1><div class="row">
    <label class="field">المدى<select id="days"><option value="0">المتأخر + المستحق الآن</option><option value="1" selected>حتى بكرة</option><option value="7">خلال أسبوع</option></select></label>
    ${isMgr ? `<label class="field">الايجنت<select id="fa">${agentOptions("")}</select></label>` : ""}</div></div>
    <div id="list"></div><div class="panel"><h2>الوعود القائمة</h2><div id="pledges"></div></div>`;
  const load = async () => {
    const p = new URLSearchParams({ days: $("#days").value });
    if (isMgr && $("#fa").value) p.set("agent_id", $("#fa").value);
    $("#list").innerHTML = donorTable(await api(`/api/agent/followups?${p}`), { showAgent: isMgr });
    bindDonorTable($("#list"), load);
    const pl = await api(`/api/reports/pledges${isMgr && $("#fa").value ? `?agent_id=${$("#fa").value}` : ""}`);
    $("#pledges").innerHTML = `<b>إجمالي الوعود القائمة: ${money(pl.total_amount)}</b>` + (pl.items.length ? `<div class="tablewrap"><table><thead><tr><th>المتبرع</th><th>الايجنت</th><th class="num">المبلغ</th><th>موعد التحصيل</th><th></th></tr></thead><tbody>
      ${pl.items.map((d) => `<tr><td>${esc(d.name)}</td><td>${esc(d.agent_name || "—")}</td><td class="num">${money(d.pledge_amount)}</td>
        <td><span class="chip ${d.overdue ? "overdue" : ""}">${fmtDt(d.pledge_due)}</span></td><td><button class="btn small" data-open="${d.id}">${isMgr ? "فتح" : "اتصال"}</button></td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">لا توجد وعود قائمة.</div>`);
    bindDonorTable($("#pledges"), load);
  };
  $("#days").onchange = load; if (isMgr) $("#fa").onchange = load;
  await load();
}

async function callsView() {
  const m = $("#main");
  const isMgr = S.user.role === "manager";
  m.innerHTML = `<div class="head"><h1>${isMgr ? "سجل المكالمات" : "مكالماتي"}</h1>${isMgr ? `<button class="btn" id="exp">تصدير CSV</button>` : ""}</div>
    <div class="panel"><div class="row">${rangeControls("cr")}
      ${isMgr ? `<label class="field">الايجنت<select id="fa">${agentOptions("")}</select></label>` : ""}
      <label class="field">النتيجة<select id="fo"><option value="">الكل</option>${S.outcomes.map((o) => `<option value="${o.code}">${esc(o.label)}</option>`).join("")}</select></label></div></div>
    <div id="list"></div>`;
  const load = async () => {
    let q = readRange("cr");
    if (isMgr && $("#fa").value) q += `&agent_id=${$("#fa").value}`;
    if ($("#fo").value) q += `&outcome=${$("#fo").value}`;
    const rows = await api(`/api/calls?${q}&limit=1000`);
    $("#list").innerHTML = rows.length ? `<div class="tablewrap"><table><thead><tr><th>الوقت</th>${isMgr ? "<th>الايجنت</th>" : ""}<th>المتبرع</th><th>النتيجة</th><th class="num">المبلغ</th><th>متابعة</th><th class="num">المدة</th><th>ملاحظات</th></tr></thead><tbody>
      ${rows.map((c) => `<tr class="click" data-open="${c.donor_id}"><td>${fmtDt(c.created_at)}</td>${isMgr ? `<td>${esc(c.agent_name)}</td>` : ""}<td>${esc(c.donor_name)}</td><td>${chip(c.outcome)}</td>
        <td class="num">${c.amount ? money(c.amount) : "—"}</td><td>${c.follow_up_at ? fmtDt(c.follow_up_at) : "—"}</td><td class="num">${c.duration_sec ? int(Math.round(c.duration_sec / 60)) + " د" : "—"}</td><td>${esc(c.notes || "")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">لا توجد مكالمات في هذه الفترة.</div>`;
    bindDonorTable($("#list"), load);
  };
  bindRange("cr", load);
  if (isMgr) { $("#fa").onchange = load; $("#exp").onclick = () => download(`/api/reports/export/calls.csv?${readRange("cr")}${$("#fa").value ? `&agent_id=${$("#fa").value}` : ""}`, "calls-log.csv"); }
  $("#fo").onchange = load;
  await load();
}

async function download(path, name) {
  const res = await api(path, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a"); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function reportsView() {
  const m = $("#main");
  m.innerHTML = `<div class="head"><h1>التقارير</h1><div class="row">
    <button class="btn" id="expA">تصدير تقرير الايجنتس CSV</button><button class="btn" id="expC">تصدير المكالمات CSV</button></div></div>
    <div class="panel"><div class="row">${rangeControls("rr", "7")}<label class="field">الايجنت<select id="fa">${agentOptions("")}</select></label></div></div>
    <div id="rep"></div>`;
  $('#rr [data-r="preset"]').value = "7";
  const load = async () => {
    const q = readRange("rr") + ($("#fa").value ? `&agent_id=${$("#fa").value}` : "");
    const [ag, out, daily] = await Promise.all([api(`/api/reports/agents?${q}`), api(`/api/reports/outcomes?${q}`), api(`/api/reports/daily?${q}`)]);
    const maxO = Math.max(1, ...out.items.map((i) => i.count));
    const maxD = Math.max(1, ...daily.days.map((d) => d.calls));
    const maxAmt = Math.max(1, ...daily.days.map((d) => d.amount));
    $("#rep").innerHTML = `
    <div class="panel"><h2>تقرير أداء الايجنتس</h2>${agentsTable(ag.agents)}</div>
    <div class="cols">
      <div class="panel"><h2>نتائج المكالمات</h2><span class="muted">${int(out.total)} مكالمة</span><div class="bars">${out.items.map((i) => `
        <div class="bar"><span>${esc(i.label)}</span><div class="track"><div class="fill ${i.category}" style="width:${(100 * i.count) / maxO}%"></div></div><span class="num">${pct(i.pct)}</span></div>`).join("")}</div></div>
      <div class="panel"><h2>المكالمات يومياً</h2><div class="spark">${daily.days.map((d) => `<div style="height:${(100 * d.calls) / maxD}%" title="${d.date}: ${d.calls} مكالمة"><span>${d.date.slice(8)}</span></div>`).join("")}</div>
        <h2 style="margin-top:18px">مبالغ التبرعات يومياً</h2><div class="spark">${daily.days.map((d) => `<div style="height:${(100 * d.amount) / maxAmt}%;background:var(--ok)" title="${d.date}: ${money(d.amount)}"><span>${d.date.slice(8)}</span></div>`).join("")}</div></div>
      <div class="panel"><h2>أفضل أوقات الاتصال</h2><p class="muted">نسبة الرد حسب الساعة — اعرف امتى المتبرعين بيردوا أكتر.</p>
        <div class="bars">${daily.hours.map((h) => `<div class="bar"><span>${new Date(Date.UTC(2000, 0, 1, h.hour)).toLocaleTimeString("ar-EG", { hour: "numeric" })} (${int(h.calls)})</span><div class="track"><div class="fill" style="width:${h.reach_rate}%"></div></div><span class="num">${pct(h.reach_rate)}</span></div>`).join("") || '<span class="muted">لا توجد بيانات.</span>'}</div></div>
    </div>`;
  };
  bindRange("rr", load); $("#fa").onchange = load;
  $("#expA").onclick = () => download(`/api/reports/export/agents.csv?${readRange("rr")}`, "agents-report.csv");
  $("#expC").onclick = () => download(`/api/reports/export/calls.csv?${readRange("rr")}${$("#fa").value ? `&agent_id=${$("#fa").value}` : ""}`, "calls-log.csv");
  await load();
}

async function teamView() {
  const m = $("#main");
  const users = await api("/api/users");
  S.agents = users.filter((u) => u.role === "agent");
  m.innerHTML = `<div class="head"><h1>فريق العمل</h1><button class="btn primary" id="addU">إضافة مستخدم</button></div>
  <div class="tablewrap"><table><thead><tr><th>الاسم</th><th>اسم المستخدم</th><th>الدور</th><th class="num">الهدف اليومي</th><th>الحالة</th><th></th></tr></thead><tbody>
  ${users.map((u) => `<tr><td>${esc(u.name)}</td><td dir="ltr">${esc(u.username)}</td><td>${u.role === "manager" ? "مدير" : "ايجنت"}</td>
    <td class="num">${int(u.daily_target)}</td><td>${u.active ? '<span class="chip success">نشط</span>' : '<span class="chip">موقوف</span>'}</td>
    <td class="row"><button class="btn small" data-tg="${u.id}" data-act="${u.active}">${u.active ? "إيقاف" : "تفعيل"}</button>
    <button class="btn small" data-pw="${u.id}">كلمة مرور</button><button class="btn small" data-tgt="${u.id}">الهدف</button></td></tr>`).join("")}</tbody></table></div>`;
  $("#addU").onclick = () => formDialog("إضافة مستخدم", [
    ["name", "الاسم", "text", true], ["username", "اسم المستخدم", "text", true], ["password", "كلمة المرور (٦ أحرف على الأقل)", "password", true],
    ["role", "الدور", "select", true, `<option value="agent">ايجنت</option><option value="manager">مدير</option>`], ["daily_target", "الهدف اليومي (مكالمات)", "number"],
  ], async (v) => { await api("/api/users", { method: "POST", body: v }); toast("تمت الإضافة"); teamView(); });
  $$("[data-tg]").forEach((b) => (b.onclick = async () => { await api(`/api/users/${b.dataset.tg}`, { method: "PATCH", body: { active: b.dataset.act !== "true" } }); teamView(); }));
  $$("[data-pw]").forEach((b) => (b.onclick = () => formDialog("تغيير كلمة المرور", [["password", "كلمة المرور الجديدة", "password", true]],
    async (v) => { await api(`/api/users/${b.dataset.pw}`, { method: "PATCH", body: v }); toast("تم التغيير"); })));
  $$("[data-tgt]").forEach((b) => (b.onclick = () => formDialog("الهدف اليومي", [["daily_target", "عدد المكالمات", "number", true]],
    async (v) => { await api(`/api/users/${b.dataset.tgt}`, { method: "PATCH", body: v }); teamView(); })));
}

/* ---------------- agent views ---------------- */
async function queueView() {
  const m = $("#main");
  const today = startOfDay(new Date());
  const q = `date_from=${encodeURIComponent(today.toISOString())}&date_to=${encodeURIComponent(new Date(today.getTime() + 864e5).toISOString())}`;
  const [items, stats] = await Promise.all([api("/api/agent/queue"), api(`/api/reports/agents?${q}`)]);
  const s = stats.agents[0] || {};
  const now = Date.now();
  const due = items.filter((d) => d.next_action_at && parseUtc(d.next_action_at).getTime() <= now).length;
  m.innerHTML = `<div class="head"><h1>قائمة الاتصال</h1><button class="btn primary" id="next" ${items.length ? "" : "disabled"}>اتصل بالتالي</button></div>
  <div class="kpis">
    <div class="kpi"><span>مكالمات اليوم</span><b>${int(s.calls)} / ${int(S.user.daily_target)}</b><div class="progress"><i style="width:${Math.min(100, (100 * (s.calls || 0)) / (S.user.daily_target || 1))}%"></i></div></div>
    <div class="kpi"><span>تبرعات اليوم</span><b>${int(s.donated)}</b><small>${money(s.donated_amount)}</small></div>
    <div class="kpi"><span>وعود اليوم</span><b>${int(s.pledged)}</b><small>${money(s.pledged_amount)}</small></div>
    <div class="kpi"><span>مستحق الآن</span><b style="color:var(--bad)">${int(due)}</b><small>من ${int(items.length)} في القائمة</small></div>
  </div>
  <p class="muted">الترتيب: المتابعات المستحقة أولاً، ثم الجديد، ثم المهتمين، ثم المواعيد القادمة.</p>
  <div id="list">${donorTable(items, { showAgent: false })}</div>`;
  bindDonorTable($("#list"), queueView);
  if (items.length) $("#next").onclick = () => openCall(items[0].id, queueView);
}

async function myStatsView() {
  const m = $("#main");
  m.innerHTML = `<div class="head"><h1>أدائي</h1>${rangeControls("mr")}</div><div id="rep"></div>`;
  const load = async () => {
    const q = readRange("mr");
    const [ag, out] = await Promise.all([api(`/api/reports/agents?${q}`), api(`/api/reports/outcomes?${q}`)]);
    const r = ag.agents[0] || {};
    const maxO = Math.max(1, ...out.items.map((i) => i.count));
    $("#rep").innerHTML = `<div class="kpis">
      <div class="kpi"><span>مكالمات</span><b>${int(r.calls)}</b><small>نسبة الوصول ${pct(r.contact_rate)}</small></div>
      <div class="kpi"><span>تبرعات</span><b>${int(r.donated)}</b><small>${money(r.donated_amount)}</small></div>
      <div class="kpi"><span>وعود</span><b>${int(r.pledged)}</b><small>حُصّل ${int(r.pledges_fulfilled)}</small></div>
      <div class="kpi"><span>نسبة التحويل</span><b>${pct(r.conversion_rate)}</b></div>
      <div class="kpi"><span>متابعات متأخرة</span><b>${int(r.overdue_followups)}</b></div></div>
      <div class="panel"><h2>نتائج مكالماتي</h2><div class="bars">${out.items.map((i) => `<div class="bar"><span>${esc(i.label)}</span><div class="track"><div class="fill ${i.category}" style="width:${(100 * i.count) / maxO}%"></div></div><span class="num">${int(i.count)}</span></div>`).join("")}</div></div>`;
  };
  bindRange("mr", load); await load();
}

const VIEWS = {
  dashboard: dashboardView, donors: donorsView, distribution: distributionView, followups: followupsView,
  calls: callsView, reports: reportsView, team: teamView, queue: queueView, mystats: myStatsView,
};

boot();
