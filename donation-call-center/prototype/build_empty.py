"""Build the empty test copy of the prototype.

Same app as call-center-prototype.html, but it starts with no data at all, with
the real team's users, uses the real clock, and keeps its data in the browser
(IndexedDB, which holds hundreds of thousands of names; localStorage stops at ~5 MB)
so a refresh does not lose the test.

    python3 build_empty.py
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
src = (HERE / "call-center-prototype.html").read_text(encoding="utf-8")

LEADERS = ["هدير", "خلود", "ياسمين"]
AGENTS = ["ألاء فؤاد", "امل محمد", "بسملة طارق", "مجلس الامناء", "ايمان السيد", "اسراء عبد الحميد",
          "إسراء ياسر", "فريدة احمد", "جنا العباسي", "حنين سعيد", "ندى صالح", "رحمه السيد",
          "رحاب احمد", "ساره جمال", "شروق محمد", "تقي محمد"]

def js_list(xs):
    return "[" + ", ".join(f'"{x}"' for x in xs) + "]"

EMPTY_SEED = f'''function seed() {{
  S = {{ settings: JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), now: Date.now(), r: rng(11), seq: 1, role: "manager", view: "home", param: null,
    agents: [], batches: [], donors: [], calls: [], moves: [], shifts: {{}}, allocLog: [], ui: {{}} }};
  const leaders = {js_list(LEADERS)}, agents = {js_list(AGENTS)};
  S.agents = [...leaders, ...agents].map((name, i) => ({{ id: 100 + i, name, target: i < leaders.length ? 30 : 40, active: true }}));
  S.settings.sched = Object.fromEntries(S.agents.map((a) => [a.id, {{ start: 10, end: 18 }}]));
  // agents split in order across the team leaders; change it from Settings
  const leadIds = S.agents.slice(0, leaders.length).map((a) => a.id), agentIds = S.agents.slice(leaders.length).map((a) => a.id);
  const per = Math.ceil(agentIds.length / leadIds.length);
  S.settings.teams = {{ leaders: leadIds, of: Object.fromEntries(agentIds.map((id, i) => [id, leadIds[Math.floor(i / per)]])) }};
  S.seq = 1000;
}}'''

out = re.sub(r"function seed\(\) \{\n.*?\n\}\n", EMPTY_SEED + "\n", src, count=1, flags=re.S)
assert out != src, "seed() not found"

def rep(old, new):
    global out
    assert out.count(old) == 1, old[:60]
    out = out.replace(old, new)

rep("<title>محاكي كول سنتر التبرعات</title>", "<title>كول سنتر التبرعات — تجربة</title>")
rep('<b>وضع التجربة</b>', '<b>نسخة تجربة فاضية</b>')
rep('>إعادة البيانات التجريبية</button>', '>مسح كل البيانات</button>')
rep('title: "إعادة البيانات التجريبية؟", body: "أي داتا رفعتها أو مكالمات سجلتها في التجربة دي هتتمسح.", action: "إعادة البيانات",',
    'title: "مسح كل البيانات؟", body: "كل الشيتات والمكالمات والحضور اللي سجلتهم هيتمسحوا، والإعدادات ترجع للأول. الحسابات (المدير والتيم ليدرز والايجنتس) هتفضل.", action: "مسح كل البيانات",')
rep('toast("رجعت البيانات التجريبية")', 'toast("اتمسحت كل البيانات")')
rep('<button class="dbtn" id="simDay" type="button">محاكاة يوم شغل للفريق</button>', '')
rep('$("#simDay").onclick', 'if ($("#simDay")) $("#simDay").onclick')

# keep the test data in this browser so a refresh does not lose it
rep("\nseed(); render();", """
const DB = "callcenter-test", OLD_KEY = "callcenter-test-v1";
function idb(mode, fn) {
  return new Promise((ok, bad) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore("s");
    open.onerror = () => bad(open.error);
    open.onsuccess = () => { const tx = open.result.transaction("s", mode), req = fn(tx.objectStore("s")); tx.oncomplete = () => ok(req.result); tx.onerror = () => bad(tx.error); };
  });
}
let saveTimer = null, lastSaveMs = 0;
async function saveNow() {
  clearTimeout(saveTimer); saveTimer = null;
  const t0 = performance.now();
  try { await idb("readwrite", (st) => st.put({ ...S, r: null, ui: {} }, "state")); lastSaveMs = performance.now() - t0; }
  catch (e) { toast("معرفناش نحفظ البيانات في المتصفح. التغييرات هتفضل لحد ما تقفل الصفحة بس."); }
}
/* saving 300k names takes a moment, so changes are batched into one save */
function persist() { if (!saveTimer) saveTimer = setTimeout(saveNow, Math.min(8000, 1500 + lastSaveMs * 3)); }
window.addEventListener("pagehide", () => { if (saveTimer) saveNow(); });
function upgrade(saved) {
  // state saved by an older version of this file
  saved.settings = { ...JSON.parse(JSON.stringify(DEFAULT_SETTINGS)), ...saved.settings };
  saved.settings.alloc = { ...DEFAULT_SETTINGS.alloc, ...(saved.settings.alloc || {}) };
  saved.settings.cycle = { ...DEFAULT_SETTINGS.cycle, ...(saved.settings.cycle || {}) };
  saved.allocLog = saved.allocLog || [];
  return { ...saved, r: rng(11), ui: {}, role: "manager", view: "home", param: null, now: Math.max(saved.now, Date.now()) };
}
const renderInner = render;
render = function () { renderInner(); persist(); };
(async () => {
  let saved = null;
  try { saved = await idb("readonly", (st) => st.get("state")); } catch { /* storage blocked */ }
  if (!saved) { try { saved = JSON.parse(localStorage.getItem(OLD_KEY) || "null"); } catch { saved = null; } }
  if (saved && saved.agents) S = upgrade(saved); else seed();
  render();
})();""")
rep("function render() {", "let render = function () {")
open_close = out.index("let render = function () {")
# close the converted function expression with a semicolon at its end brace
end = out.index("\n}\n", open_close)
out = out[:end] + "\n};\n" + out[end + 3:]
rep('onOk: () => { seed(); render();', 'onOk: () => { seed(); render(); saveNow();')
rep("  S.now += 1000;", "  S.now += 1000;\n  if (Math.floor(S.now / 1000) % 60 === 0) persist();")

(HERE / "call-center-test-empty.html").write_text(out, encoding="utf-8")

def standalone(body: str) -> str:
    head, rest = body.split("</style>", 1)
    return ('<!doctype html>\n<html lang="ar" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"{head}</style>\n</head>\n<body>{rest}\n</body>\n</html>\n")

(HERE / "call-center-test-empty-standalone.html").write_text(standalone(out), encoding="utf-8")
print("built", len(out))
