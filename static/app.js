/* Impact360 SAV Runner — frontend (no framework, no build, no external requests).
   The browser never computes methodology: every number shown comes from the server (preview = same code as the workbook). */
'use strict';

/* The displayed columns come from the server (fixed levels + user-defined segments): these three are updated in place by setCols(). */
const LEVELS = ['sample', 'exposed', 'expnonuser', 'customers', 'noncust'];
const LEVEL_HE = { sample: 'מדגם', exposed: 'נחשפים', expnonuser: 'נחשפים שאינם משתמשים', customers: 'לקוחות', noncust: 'לא לקוחות' };
const LETTER = { sample: 'A', exposed: 'B', expnonuser: 'C', customers: 'D', noncust: 'E' };
function setCols(cols) {
  LEVELS.splice(0, LEVELS.length, ...cols.map(c => c.key));
  Object.keys(LEVEL_HE).forEach(k => delete LEVEL_HE[k]); Object.keys(LETTER).forEach(k => delete LETTER[k]);
  cols.forEach(c => { LEVEL_HE[c.key] = c.name; LETTER[c.key] = c.letter; });
}
const ROLE_HE = { '': '— לא מסר בריף —', main: 'מסר ראשי', sec1: 'משני 1', sec2: 'משני 2', buy: 'קנייה / ניסיון' };
const CONF_HE = { exact: 'exact', alias: 'alias', template: 'תבנית', tag: 'תג', manual: 'ידני', structure: 'מבנה', keyword: 'keyword', 'fuzzy-high': 'fuzzy', 'fuzzy-low': 'fuzzy', none: 'ללא' };

const S = { project: null, review: null, step: 1, netBlock: null, nets: {}, activeNet: null, catalog: null, dictVars: null };
const $ = (s, r = document) => r.querySelector(s);

window.addEventListener('unhandledrejection', ev => { toast('⚠ ' + ((ev.reason && ev.reason.message) || 'שגיאה לא צפויה')); });

/* ------------------------------------------------------------------ helpers */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'open' || k === 'value') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
function toast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 3500); }
function user() { try { return localStorage.getItem('i360user') || ''; } catch (e) { return S._user || ''; } }
function setUser(v) { try { localStorage.setItem('i360user', v); } catch (e) { S._user = v; } $('#nav-user').textContent = '👤 ' + (v || 'ללא שם'); }
async function api(path, opts = {}) {
  const o = { method: 'GET', headers: { 'X-User': encodeURIComponent(user() || 'anonymous') }, ...opts };
  if (opts.json !== undefined) { o.method = opts.method || 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opts.json); }
  let r;
  try { r = await fetch('api' + path, o); } catch (e) { throw new Error('אין חיבור לשרת — ודא/י שהאפליקציה רצה ורענן/י את הדף'); }
  let data = null;
  try { data = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error((data && data.detail) || ('שגיאה ' + r.status));
  const cols = data && (data.columns || (data.levels && data.levels.columns));
  if (Array.isArray(cols)) setCols(cols);
  return data;
}
const pctFmt = (v, kind) => v == null ? '' : (kind === 'mean' ? v.toFixed(2) : v.toFixed(1));
function busy(btn, on) { btn.disabled = on; btn.dataset.txt = btn.dataset.txt || btn.textContent; btn.textContent = on ? 'רגע…' : btn.dataset.txt; }
async function guarded(btn, fn) { busy(btn, true); try { await fn(); } catch (e) { toast('⚠ ' + e.message); } finally { busy(btn, false); } }

function askText(msg, def = '') {   // in-page replacement for prompt() (not available in every embedded browser)
  return new Promise(res => {
    const inp = h('input', { type: 'text', value: def, style: 'width:100%' });
    const done = v => { ov.remove(); res(v); };
    const ov = h('div', { class: 'overlay' }, h('div', { class: 'dlg' }, h('div', { style: 'margin-bottom:8px;font-weight:600' }, msg), inp,
      h('div', { class: 'row', style: 'margin-top:10px' }, h('button', { class: 'btn', onclick: () => done(inp.value.trim()) }, 'אישור'), h('button', { class: 'btn ghost', onclick: () => done(null) }, 'ביטול'))));
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') done(inp.value.trim()); if (e.key === 'Escape') done(null); });
    document.body.append(ov); inp.focus();
  });
}

function askConfirm(msg) {
  return new Promise(res => {
    const done = v => { ov.remove(); res(v); };
    const ov = h('div', { class: 'overlay' }, h('div', { class: 'dlg' }, h('div', { style: 'margin-bottom:10px;font-weight:600' }, msg),
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => done(true) }, 'המשך'), h('button', { class: 'btn ghost', onclick: () => done(false) }, 'ביטול'))));
    document.body.append(ov);
  });
}

function goStep(k) {
  if (k === 1) return viewStep1();
  if (!S.project || !S.review) return toast('קודם יש לפתוח פרויקט (שלב 1)');
  if (k === 2) return viewStep2();
  if (k === 3) return viewStep3();
  if (k === 4) return viewStep4();
}
function backBar(prev, label) {
  return h('div', { class: 'row', style: 'margin-bottom:10px' }, h('button', { class: 'btn ghost small', onclick: prev }, '→ ' + label));
}

function setStep(n) {
  if (S.flushNets) S.flushNets();   // never lose a pending Count Builder change when leaving the screen
  S.step = n;
  document.querySelectorAll('#steps li').forEach(li => {
    const k = +li.dataset.step;
    li.className = k === n ? 'active' : (k < n ? 'done' : '');
  });
}

/* ------------------------------------------------------------------ step 1 */
async function viewStep1() {
  setStep(1);
  const main = $('#main'); main.replaceChildren();
  let projects = [];
  try { projects = await api('/projects'); } catch (e) { /* ignore */ }
  const state = { sav: null, qnr: null, created: null };

  const info = h('div');
  const form = h('div', { class: 'card' });
  const savInput = h('input', { type: 'file', accept: '.sav', style: 'display:none' });
  const qnrInput = h('input', { type: 'file', accept: '.docx' });
  const drop = h('div', { class: 'drop' }, 'גרור לכאן את קובץ ה-SAV או לחץ לבחירה');
  const nameIn = h('input', { type: 'text', placeholder: 'למשל: האגיס FreeFeel' });
  drop.onclick = () => savInput.click();
  drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); pickSav(e.dataTransfer.files[0]); };
  savInput.onchange = () => pickSav(savInput.files[0]);
  function pickSav(f) {
    if (!f) return;
    if (!/\.sav$/i.test(f.name)) return toast('יש לבחור קובץ .sav');
    state.sav = f; drop.textContent = '✔ ' + f.name + ' (' + (f.size / 1048576).toFixed(1) + 'MB)';
    if (!nameIn.value) nameIn.value = f.name.replace(/\.sav$/i, '');
  }
  const upBtn = h('button', { class: 'btn' }, 'העלה וקרא את הקובץ');
  upBtn.onclick = () => guarded(upBtn, async () => {
    if (!state.sav) throw new Error('בחר/י קובץ SAV');
    const fd = new FormData();
    fd.append('sav', state.sav); if (qnrInput.files[0]) fd.append('qnr', qnrInput.files[0]); fd.append('name', nameIn.value);
    const r = await fetch('api/projects', { method: 'POST', body: fd, headers: { 'X-User': encodeURIComponent(user() || 'anonymous') } });
    const d = await r.json(); if (!r.ok) throw new Error(d.detail || 'שגיאה');
    state.created = d; renderNext(d);
  });
  form.append(h('h2', null, 'פרויקט חדש'), h('p', { class: 'muted' }, 'קובץ ה-SAV נשאר על השרת הפנימי ונמחק אוטומטית לפי מדיניות הניקוי.'), drop, savInput,
    h('div', { class: 'row', style: 'margin-top:12px' }, h('label', { class: 'f' }, 'שם הפרויקט', nameIn),
      h('label', { class: 'f' }, 'שאלון Word (אופציונלי — לאימות ולסדר המסרים)', qnrInput)),
    h('div', { style: 'margin-top:12px' }, upBtn), info);

  function renderNext(d) {
    info.replaceChildren();
    const brand = h('select', null, ...d.brand_options.map(b => h('option', { value: b }, b)));
    const camp = h('input', { type: 'text', placeholder: 'I360-2026-0XX' });
    const omni = h('input', { type: 'checkbox' });
    let tpl = '';
    const tplBox = h('div');
    if (d.template_suggestions.length) {
      tplBox.append(h('div', { class: 'alert warn' }, 'נמצאה תבנית דומה מאותו מעקב. ההצעה לא מופעלת בשקט — בחר/י אם להחיל:'));
      const opts = [h('label', null, h('input', { type: 'radio', name: 'tpl', checked: true, onchange: () => tpl = '' }), ' לא להחיל תבנית (זיהוי מחדש)')];
      d.template_suggestions.forEach(t => opts.push(h('div', null, h('label', null, h('input', { type: 'radio', name: 'tpl', onchange: () => tpl = t.id }),
        ` החל '${t.name}' v${t.version} · דמיון ${(t.similarity * 100).toFixed(0)}%`))));
      tplBox.append(...opts);
    }
    const warns = d.questionnaire_warnings.map(w => h('div', { class: 'alert warn' }, '⚠ ' + w));
    const go = h('button', { class: 'btn gold' }, 'המשך לסקירה ←');
    go.onclick = () => guarded(go, async () => {
      S.project = d.project;
      S.review = await api(`/projects/${d.project.id}/profile`, { json: { name: nameIn.value.trim(), brand: brand.value, campaign_id: camp.value, omnibus: omni.checked, template_id: tpl || null } });
      viewStep2();
    });
    info.append(h('hr'), h('div', { class: 'alert ok' }, `נקרא: N=${d.project.n}, ${d.n_columns} עמודות.`), ...warns,
      h('div', { class: 'row' }, h('label', { class: 'f' }, 'מותג נבדק', brand), h('label', { class: 'f' }, 'CAMPAIGN_ID (אופציונלי)', camp),
        h('label', { class: 'f', style: 'min-width:120px' }, 'אומניבוס?', h('span', null, omni, ' כן'))),
      tplBox, h('div', { style: 'margin-top:12px' }, go));
  }

  main.append(h('h1', null, 'שלב 1 · פרויקט'), form);
  if (projects.length) {
    const t = h('table', null, h('thead', null, h('tr', null, ...['פרויקט', 'קובץ', 'שלב', 'עודכן', ''].map(x => h('th', null, x)))),
      h('tbody', null, ...projects.slice(0, 15).map(p => h('tr', null, h('td', null, p.name), h('td', null, p.sav_name),
        h('td', null, ({ uploaded: 'הועלה', profiled: 'זוהה', reviewed: 'נסקר', done: 'הופק' })[p.stage] || p.stage), h('td', null, (p.updated_at || p.created_at || '').replace('T', ' ')),
        h('td', null, h('button', { class: 'btn small ghost', onclick: () => resume(p.id) }, 'המשך'))))));
    main.append(h('div', { class: 'card' }, h('h2', null, 'פרויקטים אחרונים'), h('div', { class: 'tablewrap', style: 'margin-top:8px' }, t)));
  }
}
async function resume(pid) {
  try {
    S.project = await api('/projects/' + pid);
    if (!S.project.has_mapping) return toast('לפרויקט זה טרם הורץ פרופיל — העלה/י את הקובץ שוב בשלב 1');
    S.review = await api(`/projects/${pid}/review`);
    S.project.has_output ? viewStep3() : viewStep2();
  } catch (e) { toast('⚠ ' + e.message); }
}

/* ------------------------------------------------------------------ step 2 */
async function refreshReview() { S.review = await api(`/projects/${S.project.id}/review`); }
async function patch(body) { S.review = await api(`/projects/${S.project.id}/mapping`, { method: 'PUT', json: body }); }

function sec(title, pill, pillClass, ...body) {
  return h('details', { class: 'sec', open: true, id: 'sec-' + title.split('.')[0] }, h('summary', null, h('h2', null, title), pill ? h('span', { class: 'pill ' + (pillClass || '') }, pill) : null), h('div', { class: 'body' }, ...body));
}

async function viewStep2() {
  const keepY = S.step === 2 ? window.scrollY : null;   // a decision re-renders the page: stay where the user was
  setStep(2);
  const main = $('#main'); main.replaceChildren();
  const R = S.review, M = R.mapping, pid = S.project.id;
  main.append(backBar(viewStep1, 'חזרה לשלב 1 (פרויקט)'), h('h1', null, `שלב 2 · סקירה — ${M.project.name || ''} `,
    h('button', { class: 'btn small ghost', title: 'שנה את שם הפרויקט', onclick: async () => {
      const n = await askText('שם הפרויקט:', M.project.name || ''); if (!n) return;
      try { await patch({ project: { name: n } }); S.project.name = n; viewStep2(); } catch (e) { toast('⚠ ' + e.message); }
    } }, '✎ שנה שם')));
  const q = M.questionnaire;
  if (M.template_diff) {
    const d = M.template_diff;
    main.append(h('div', { class: 'alert ok' }, `הוחלה תבנית '${d.template.name}' v${d.template.version}: ${d.applied.length} בלוקים נלקחו מהתבנית. `,
      d.new.length ? `בלוקים חדשים: ${d.new.join(', ')}. ` : '', d.missing.length ? `חסרים מול התבנית: ${d.missing.join(', ')}. ` : '',
      d.structure_changed.length ? `שינוי מבנה: ${d.structure_changed.join(', ')}.` : ''));
  }
  if (S.jumpTo) { const j = S.jumpTo; S.jumpTo = null; S.pendingJump = j; }
  main.append(snapshotBar(), secExposure(M, R), secCustomers(M, R), secSegments(M, R), secQuestions(M, R), secMessages(M, R), await secNets(), secWarnings(), secResults(false));
  if (S.pendingJump) { const j = S.pendingJump; S.pendingJump = null; setTimeout(() => { const el = $('#sec-5'); if (el) el.scrollIntoView({ behavior: 'smooth' }); }, 400); }
  const next = h('button', { class: 'btn gold' }, 'המשך להרצה ←');
  next.onclick = () => viewStep3();
  main.append(h('div', { style: 'margin-top:14px' }, next));
  if (keepY != null && !S.pendingJump) { window.scrollTo(0, keepY); requestAnimationFrame(() => window.scrollTo(0, keepY)); }
}

/* named snapshots of this study's current settings (not a template): save now, load later to re-run */
function snapshotBar() {
  const host = h('div', { class: 'card snap' });
  async function draw() {
    let list = [];
    try { list = await api(`/projects/${S.project.id}/snapshots`); } catch (e) { /* offline handled elsewhere */ }
    const sel = h('select', null, h('option', { value: '' }, list.length ? 'בחר/י הגדרות שמורות…' : 'אין הגדרות שמורות'),
      ...list.map(s => h('option', { value: s.id }, `${s.name} · ${s.created_by || '—'} · ${s.created_at.replace('T', ' ')}`)));
    const save = h('button', { class: 'btn small' }, '💾 שמור את ההגדרות הנוכחיות');
    save.onclick = () => guarded(save, async () => {
      const n = await askText('שם להגדרות השמורות (למשל: "לפני שינוי סלוגן"):', S.review.mapping.project.name || '');
      if (!n) return;
      await api(`/projects/${S.project.id}/snapshots`, { json: { name: n } }); toast('ההגדרות נשמרו'); draw();
    });
    const load = h('button', { class: 'btn small ghost' }, '📂 טען');
    load.onclick = () => guarded(load, async () => {
      if (!sel.value) throw new Error('בחר/י הגדרות שמורות');
      if (!await askConfirm('הטעינה תחליף את ההגדרות הנוכחיות (הן יישמרו אוטומטית כגיבוי). להמשיך?')) return;
      S.review = await api(`/projects/${S.project.id}/snapshots/${sel.value}/load`, { json: {} });
      S.catalog = null; toast('ההגדרות נטענו'); S.step === 3 ? viewStep3() : viewStep2();
    });
    const del = h('button', { class: 'btn small ghost', title: 'מחק את ההגדרות השמורות שנבחרו' }, '🗑');
    del.onclick = () => guarded(del, async () => { if (!sel.value) return; await api(`/projects/${S.project.id}/snapshots/${sel.value}`, { method: 'DELETE' }); draw(); });
    host.replaceChildren(h('div', { class: 'row' }, h('b', null, 'הגדרות שמורות של המחקר:'), save, sel, load, del,
      h('span', { class: 'muted' }, 'שמירה/טעינה של כל ההחלטות (התאמות, סיכומים, מסרים, חשיפה, לקוחות) — בלי קשר לתבנית לגלים הבאים.')));
  }
  draw();
  return host;
}

function levelBases(R) { const b = R.levels.bases; return LEVELS.map(l => `${LEVEL_HE[l]}: ${b[l]}`).join(' · '); }

function secSegments(M, R) {
  const segs = M.segments || [];
  const colOf = id => (R.levels.columns || []).find(c => c.key === 'seg:' + id);
  const rows = segs.map(s => { const c = colOf(s.id); return h('tr', null, h('td', null, c ? c.letter : ''), h('td', null, s.name), h('td', null, h('code', null, s.desc || s.var)),
    h('td', { class: 'num' }, c ? c.n : ''), h('td', null, h('button', { class: 'btn small ghost', title: 'הסר חיתוך', onclick: async () => {
      if (!await askConfirm(`להסיר את החיתוך "${s.name}"?`)) return;
      try { await patch({ segment_remove: s.id }); viewStep2(); } catch (e) { toast('⚠ ' + e.message); }
    } }, '✕'))); });
  return sec('2ב. חיתוכים נוספים (עמודות לתתי-קהלים / דמוגרפיה)', segs.length ? `${segs.length} חיתוכים` : 'אין', '',
    h('p', { class: 'muted' }, 'כל חיתוך הוא עמודה נוספת בטבלאות ובאקסל (אחרי E), המחושבת מכלל המדגם לפי משתנה וערכים שתבחר/י (למשל "נשים 25-34"). המובהקות היא מול כל מי שמחוץ לחיתוך (▲ גבוה / ▼ נמוך). לניתוח בלבד: לא נכנס ל-DATA_לייבוא ולתאומי _E.'),
    segs.length ? h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['עמודה', 'שם', 'הגדרה', 'N', ''].map(x => h('th', null, x)))), h('tbody', null, ...rows))) : null,
    h('div', { style: 'margin-top:8px' }, h('button', { class: 'btn small', onclick: () => openSegmentDialog() }, '+ הוסף חיתוך')));
}

function openSegmentDialog() {
  const name = h('input', { type: 'text', placeholder: 'למשל: נשים 25-34', style: 'width:100%' });
  const valsHost = h('div', { class: 'tablewrap', style: 'margin-top:8px;max-height:260px' }, h('span', { class: 'muted' }, 'בחר/י משתנה כדי לראות את הערכים שלו.'));
  let chosenVar = '', chosen = new Set();
  const ov = h('div', { class: 'overlay' });
  const close = () => ov.remove();
  async function showValues() {
    valsHost.textContent = 'טוען…';
    try {
      const d = await api(`/projects/${S.project.id}/variables/${encodeURIComponent(chosenVar)}`);
      valsHost.replaceChildren(h('table', null, h('thead', null, h('tr', null, ...['בחר', 'ערך', 'תווית', 'n', '%'].map(x => h('th', null, x)))),
        h('tbody', null, ...d.values.map(v => h('tr', null, h('td', null, h('input', { type: 'checkbox', onchange: e => { e.target.checked ? chosen.add(v.value) : chosen.delete(v.value); } })),
          h('td', { class: 'num' }, String(v.value)), h('td', null, v.label || ''), h('td', { class: 'num' }, v.n), h('td', { class: 'num' }, (100 * v.n / d.n).toFixed(1)))))));
    } catch (e) { valsHost.textContent = '⚠ ' + e.message; }
  }
  const picker = comboDict('', v => { if (!v) return; chosenVar = v; chosen = new Set(); showValues(); }, async () => api(`/projects/${S.project.id}/variables`), '(בחר/י משתנה)', false);
  const add = h('button', { class: 'btn' }, 'הוסף חיתוך');
  add.onclick = () => guarded(add, async () => {
    if (!name.value.trim()) throw new Error('יש לתת שם לחיתוך');
    if (!chosenVar || !chosen.size) throw new Error('יש לבחור משתנה ולסמן ערך אחד לפחות');
    await patch({ segment_add: { name: name.value.trim(), var: chosenVar, values: [...chosen] } }); close(); viewStep2();
  });
  ov.append(h('div', { class: 'dlg', style: 'width:min(640px,94vw)' }, h('div', { style: 'font-weight:700;margin-bottom:8px' }, 'חיתוך נוסף (עמודה חדשה)'),
    h('label', { class: 'f' }, 'שם העמודה', name), h('label', { class: 'f', style: 'margin-top:8px' }, 'משתנה', picker), valsHost,
    h('div', { class: 'row', style: 'margin-top:10px' }, add, h('button', { class: 'btn ghost', onclick: close }, 'ביטול'))));
  document.body.append(ov); name.focus();
}

function secExposure(M, R) {
  const comps = M.exposure.components;
  const rows = comps.map((c, i) => h('tr', null,
    h('td', null, h('input', { type: 'checkbox', checked: c.enabled !== false, onchange: async e => { await patch({ exposure_enabled: { [i]: e.target.checked } }); viewStep2(); } })),
    h('td', { title: c.question || '' }, c.question || (Array.isArray(c.var) ? c.var.join(', ') : c.var)),
    h('td', null, h('code', null, c.dict_var || '—')), h('td', null, c.kind === 'any_of' ? 'אחד מתוך רשימה' : 'שאלה בודדת')));
  const chk = R.levels.checks[0];
  return sec('1. חשיפה (Total Exposed)', `נחשפים: ${R.levels.bases.exposed}`, '',
    h('p', { class: 'muted' }, 'נחשפים = איחוד שאלות המדיה שסומנו. סמן/י או בטל/י רכיבים; המספר מתעדכן. בקרב הנחשפים יש הטיה לטובת משתמשי המותג, ולכן בטבלאות מוצגת עמודה "נחשפים שאינם משתמשים" (חשיפה × לא לקוחות, לפי ההגדרה בסעיף 2) במקום "לא נחשפים".'),
    h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['כלול', 'שאלת מדיה', 'משתנה מילון', 'סוג'].map(x => h('th', null, x)))), h('tbody', null, ...rows))),
    chk ? h('div', { class: 'alert ' + (chk[2] === 'OK' ? 'ok' : 'warn') }, `${chk[0]}: ${chk[1]}`) : null,
    h('div', { class: 'muted' }, levelBases(R)));
}

function secCustomers(M, R) {
  const opts = M.customer_options || [];
  const cu = M.customer || null;
  const cur = cu && cu.var;
  const valsHost = h('div', { class: 'tablewrap', style: 'margin-top:8px' }, 'טוען ערכים…');
  let chosenVar = cur || '';
  let chosen = new Set((cu && cu.customer_values) || []);
  async function applyDef() {
    if (!chosen.size) { toast('יש לסמן לפחות ערך אחד שמגדיר לקוח'); return; }
    try { await patch({ customer_def: { var: chosenVar, values: [...chosen] } }); viewStep2(); } catch (e) { toast('⚠ ' + e.message); }
  }
  async function showValues() {
    if (!chosenVar) { valsHost.textContent = 'בחר/י משתנה.'; return; }
    try {
      const d = await api(`/projects/${S.project.id}/variables/${encodeURIComponent(chosenVar)}`);
      valsHost.replaceChildren(h('table', null, h('thead', null, h('tr', null, ...['לקוח (D)', 'ערך', 'תווית', 'n', '%'].map(x => h('th', null, x)))),
        h('tbody', null, ...d.values.map(v => h('tr', { class: chosen.has(v.value) ? 'sum' : '' },
          h('td', null, h('input', { type: 'checkbox', checked: chosen.has(v.value), onchange: e => { e.target.checked ? chosen.add(v.value) : chosen.delete(v.value); applyDef(); } })),
          h('td', { class: 'num' }, String(v.value)), h('td', null, v.label || ''), h('td', { class: 'num' }, v.n), h('td', { class: 'num' }, (100 * v.n / d.n).toFixed(1)))),
          d.n_missing ? h('tr', null, h('td', null, ''), h('td', { class: 'num' }, '—'), h('td', null, 'ריק (נחשב לא לקוח)'), h('td', { class: 'num' }, d.n_missing), h('td', { class: 'num' }, (100 * d.n_missing / d.n).toFixed(1))) : null)));
    } catch (e) { valsHost.textContent = '⚠ ' + e.message; }
  }
  const picker = comboDict(cur || '', v => {
    if (!v) return;
    chosenVar = v; chosen = new Set(); valsHost.textContent = 'טוען ערכים…'; showValues();
    toast('סמן/י את הערכים שמגדירים לקוח (עמודה D)');
  }, async () => api(`/projects/${S.project.id}/variables`), '(בחר/י משתנה)', false);
  const quick = opts.length ? h('select', { onchange: async e => { if (!e.target.value) return; chosenVar = e.target.value; chosen = new Set([1]); await applyDef(); } },
    h('option', { value: '' }, 'קיצור: שורת מותג בשאלת השימוש ל-3 חודשים…'),
    ...opts.map(o => h('option', { value: o.var, selected: o.var === cur }, o.text.replace(/\[[^\]]*\]/g, '').trim()))) : null;
  showValues();
  return sec('2. לקוחות / לא לקוחות (עמודות D ו-E)', `לקוחות: ${R.levels.bases.customers} · לא לקוחות: ${R.levels.bases.noncust} · נחשפים שאינם משתמשים: ${R.levels.bases.expnonuser}`, '',
    h('p', { class: 'muted' }, 'בחר/י על איזה משתנה מחולקים לקוחות ולא לקוחות, וסמן/י אילו ערכים מגדירים "לקוח". כל השאר (כולל ריקים) = לא לקוח. בדרך כלל: שורת המותג הנבדק בשאלת השימוש ל-3 החודשים (ערך 1). המערכת לא מנחשת את המותג. חיתוך זה אינו מיובא ל-DATA_לייבוא.'),
    !cu ? h('div', { class: 'alert warn' }, 'טרם הוגדר משתנה לקוחות — עמודות D/E ריקות.') : null,
    h('div', { class: 'row' }, h('label', { class: 'f' }, 'משתנה', picker), quick ? h('label', { class: 'f' }, 'קיצור', quick) : null),
    valsHost,
    cu ? h('p', { class: 'muted' }, 'הגדרה נוכחית: ', h('code', null, cu.option_text || cu.var)) : null);
}

async function loadDictVars() {
  if (!S.dictVars) S.dictVars = await api('/library/dictionary/vars');
  return S.dictVars;
}

/* searchable dictionary-variable picker: opens with ALL variables, filters as you type (a native datalist only shows matches of the current text) */
function comboDict(current, onPick, getItems, placeholder, noneLabel) {
  getItems = getItems || loadDictVars;
  const inp = h('input', { type: 'text', class: 'inline-input', value: current || '', placeholder: placeholder || '(ללא — ניתוח בלבד)', autocomplete: 'off' });
  const caret = h('button', { type: 'button', class: 'btn small ghost', title: 'הצג את כל המשתנים', onclick: () => { inp.focus(); open(true); } }, '▾');
  let panel = null;
  function close() { if (panel) { panel.remove(); panel = null; } document.removeEventListener('mousedown', outside, true); }
  function outside(ev) { if (panel && !panel.contains(ev.target) && ev.target !== inp && ev.target !== caret) { inp.value = current || ''; close(); } }
  async function open(all) {
    const vars = await getItems();
    const q = all ? '' : inp.value.trim().toLowerCase();
    const items = vars.filter(v => !q || (v.var + ' ' + v.title + ' ' + v.module).toLowerCase().includes(q)).slice(0, 250);
    if (!panel) { panel = h('div', { class: 'combo' }); document.body.append(panel); document.addEventListener('mousedown', outside, true); }
    const r = inp.getBoundingClientRect();
    Object.assign(panel.style, { top: (r.bottom + 2) + 'px', left: Math.max(4, Math.min(r.left, innerWidth - 360)) + 'px' });
    panel.replaceChildren(noneLabel === false ? null : h('div', { class: 'opt none', onclick: () => { close(); onPick(null); } }, noneLabel || '— ללא משתנה מילון (ניתוח בלבד) —'),
      ...items.map(v => h('div', { class: 'opt' + (v.var === current ? ' cur' : ''), onclick: () => { close(); onPick(v.var); } },
        h('code', null, v.var), ' ', v.title, h('span', { class: 'muted' }, v.module ? ' · ' + v.module : ''))),
      items.length ? null : h('div', { class: 'opt muted' }, 'אין התאמה'));
    if (all && current) {   // start the list at the current variable (its neighbours are the related family, e.g. REC*); the rest is one scroll away
      const cur = panel.querySelector('.opt.cur');
      if (cur) panel.scrollTop = Math.max(0, cur.offsetTop - 2 * cur.offsetHeight);
    }
  }
  inp.addEventListener('focus', () => { inp.select(); open(true); });
  inp.addEventListener('input', () => open(false));
  inp.addEventListener('keydown', ev => { if (ev.key === 'Escape') { inp.value = current || ''; close(); } if (ev.key === 'Enter') { ev.preventDefault(); const v = inp.value.trim(); close(); onPick(v || null); } });
  return h('span', { style: 'white-space:nowrap' }, inp, ' ', caret);
}

function secQuestions(M, R) {
  const pending = R.pending.length;
  let onlyPending = S.onlyPending != null ? S.onlyPending : pending > 0;
  const box = h('div');
  loadDictVars();
  function render() {
    box.replaceChildren();
    const qs = M.questions.filter(e => !onlyPending || (e.include !== false && e.needs_approval) || (e.warnings || []).length);
    const rows = qs.map(e => {
      const combo = comboDict(e.dict_var || '', async v => {
        if ((v || '') === (e.dict_var || '')) return;
        try { await patch({ remap: { [e.key]: v } }); toast(`${e.key}: ${v || 'ללא משתנה מילון'}`); viewStep2(); } catch (err) { toast('⚠ ' + err.message); }
      });
      const inc = h('label', null, h('input', { type: 'checkbox', checked: e.include !== false, onchange: async ev => { await patch({ questions: { [e.key]: { include: ev.target.checked } } }); viewStep2(); } }), ' רלוונטי');
      return h('tr', { class: (e.include === false ? 'off ' : '') + (e.needs_approval ? 'need' : '') },
        h('td', null, h('code', null, e.key)), h('td', { title: e.question || '' }, (e.question || '').slice(0, 90), (e.warnings || []).map(w => h('div', { class: 'muted' }, '⚠ ' + w))),
        h('td', null, e.type || ''), h('td', null, combo, e.dict_title ? h('div', { class: 'muted' }, e.dict_title) : null),
        h('td', null, h('span', { class: 'badge ' + e.confidence }, CONF_HE[e.confidence] || e.confidence), e.needs_approval ? h('div', { class: 'state wait' }, 'ממתין לאישור') : (e.confirmed && e.dict_var && !['exact', 'alias', 'template', 'tag', 'manual'].includes(e.confidence) ? h('div', { class: 'state ok' }, 'אושר') : null), e.qnr_item ? h('div', { class: 'muted' }, 'בשאלון: ' + e.qnr_item.tag) : null), h('td', null, inc));
    });
    box.append(h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['בלוק', 'שאלה', 'סוג', 'משתנה מילון', 'ביטחון', 'רלוונטי לדוח'].map(x => h('th', null, x)))), h('tbody', null, ...rows))));
  }
  const filt = h('label', null, h('input', { type: 'checkbox', checked: onlyPending, onchange: e => { onlyPending = S.onlyPending = e.target.checked; render(); } }), ' הצג רק מה שדורש החלטה');
  const all = h('button', { class: 'btn gold', onclick: () => guarded(all, async () => { await patch({ confirm_all: true }); viewStep2(); }) }, `✔ אישרתי את ההתאמות המוצעות (${pending})`);
  render();
  return sec('3. שאלות ומילון', pending ? `${pending} דורשות החלטה` : 'הכול מאושר', pending ? 'need' : 'okp',
    h('p', { class: 'muted' }, 'עבור על השורות: אם המשתנה המוצע לא מתאים, לחץ/י על השדה (או ▾) ובחר/י משתנה אחר או "ללא משתנה מילון" (הטבלה תופיע בדוח כניתוח בלבד). התאמות שאינן exact/alias/תבנית הן הצעות שממתינות: הן לא נכנסות ל-DATA_לייבוא עד שתלחץ/י על "אישרתי את ההתאמות המוצעות". "רלוונטי לדוח" מבוטל = הבלוק לא יופיע בדוח בכלל (למשל שאלות של לקוח אחר באומניבוס).'),
    h('div', { class: 'row', style: 'margin-bottom:8px' }, filt, pending ? all : null), box);
}

function secMessages(M, R) {
  const mo = R.messages.options;
  if (!mo.length) return sec('4. מסרים', 'לא נמצאה שאלת MAIN_MESSAGE_TAKEOUT', '', h('p', { class: 'muted' }, 'אין מה לאשר.'));
  const roles = mo.map(o => o.role);
  const sug = R.messages.suggestion;
  const sels = mo.map((o, i) => h('select', { onchange: e => roles[i] = e.target.value }, ...['', 'main', 'sec1', 'sec2', 'buy'].map(r => h('option', { value: r, selected: r === o.role }, ROLE_HE[r]))));
  const map = { main: 'main', secondary: 'sec1', generic: 'buy' };
  const apply = h('button', { class: 'btn small ghost' }, 'החל את ההצעה מהשאלון');
  if (sug && sug.order && sug.order.length === mo.length) {
    apply.onclick = () => { let sec2 = false; sug.order.forEach((m, i) => { let r = map[m.role] || ''; if (m.role === 'secondary') { r = sec2 ? 'sec2' : 'sec1'; sec2 = true; } roles[i] = r; sels[i].value = r; }); toast('ההצעה הוצבה — יש ללחוץ "אשר סדר מסרים"'); };
  } else apply.disabled = true;
  const save = h('button', { class: 'btn' }, 'אשר סדר מסרים');
  save.onclick = () => guarded(save, async () => { await patch({ roles }); toast('סדר המסרים נשמר'); viewStep2(); });
  const rows = mo.map((o, i) => h('tr', null, h('td', null, i + 1), h('td', null, o.label), h('td', null, sels[i]), h('td', { class: 'muted' }, sug && sug.order && sug.order[i] ? `שאלון: ${sug.order[i].role || '—'}` : '')));
  return sec('4. מסרים (MAIN / TOTAL MESSAGE_TAKEOUT)', '', '',
    h('p', { class: 'muted' }, 'ברירת המחדל = סדר האפשרויות בשאלון (ראשי, משני 1, משני 2, קנייה/ניסיון). ההצעה מהשאלון אינה מופעלת בלי אישור.'),
    h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['#', 'נוסח המסר', 'תפקיד', 'רמז'].map(x => h('th', null, x)))), h('tbody', null, ...rows))),
    h('div', { class: 'row', style: 'margin-top:8px' }, apply, save));
}

/* -------- Net Builder (server-side live results) */
async function secNets() {
  const box = h('div');
  try { S.catalog = await api(`/projects/${S.project.id}/catalog`); } catch (e) { S.catalog = []; }
  const rank = b => (b.wanted.length ? 0 : (b.type === 'coded_open' ? 1 : (b.dict_var ? 2 : 3)));
  const blocks = S.catalog.slice().sort((a, b) => rank(a) - rank(b));
  if (!blocks.length) return sec('5. סיכומי קודים (Count Builder)', '', '', h('p', { class: 'muted' }, 'אין שאלות מקודדות/רב-ברירה בפרויקט.'));
  const localNets = {}; blocks.forEach(b => localNets[b.key] = JSON.parse(JSON.stringify(b.nets || {})));
  /* autosave: every change is saved ~0.6s later; a summary with no code ticked yet (empty include) is kept locally only */
  const validNets = n => { const o = {}; for (const k of Object.keys(n)) { if (n[k].include && !n[k].include.length) continue; o[k] = n[k]; } return o; };
  const saved = {}; blocks.forEach(b => saved[b.key] = JSON.stringify(validNets(localNets[b.key])));
  const dirty = new Set(); let saveTimer = null;
  const statusEl = h('span', { class: 'savestate' }, 'שינויים נשמרים אוטומטית');
  async function saveBlock(key) {
    const payload = validNets(localNets[key]);
    if (JSON.stringify(payload) === saved[key]) return;
    statusEl.className = 'savestate'; statusEl.textContent = 'שומר…';
    try { await patch({ questions: { [key]: { nets: payload } } }); saved[key] = JSON.stringify(payload); statusEl.className = 'savestate ok'; statusEl.textContent = '✓ נשמר'; }
    catch (e) { statusEl.className = 'savestate err'; statusEl.textContent = '⚠ השמירה נכשלה: ' + e.message; dirty.add(key); }
  }
  async function flush() { clearTimeout(saveTimer); const keys = [...dirty]; dirty.clear(); for (const k of keys) await saveBlock(k); }
  function scheduleSave(key) { dirty.add(key); statusEl.className = 'savestate'; statusEl.textContent = 'שומר…'; clearTimeout(saveTimer); saveTimer = setTimeout(flush, 600); }
  S.flushNets = flush;
  S.netBlock = S.netBlock && blocks.find(b => b.key === S.netBlock) ? S.netBlock : blocks[0].key;
  S.activeNet = null;
  let timer = null;

  function netDefs(b) {
    // defined summaries first, in their real order (this is the order of the rows in the tables); then dictionary summaries not defined yet
    const wanted = Object.fromEntries(b.wanted.map(w => [w.united, w.label]));
    const defs = Object.keys(localNets[b.key]).map(k => ({ key: k, label: wanted[k] || localNets[b.key][k].label || k, dict: k in wanted }));
    b.wanted.forEach(w => { if (!defs.find(d => d.key === w.united)) defs.push({ key: w.united, label: w.label, dict: true }); });
    return defs;
  }
  function moveNet(b, key, dir) {
    const n = localNets[b.key], keys = Object.keys(n), i = keys.indexOf(key), j = i + dir;
    if (i < 0 || j < 0 || j >= keys.length) return;
    [keys[i], keys[j]] = [keys[j], keys[i]];
    const o = {}; keys.forEach(k => o[k] = n[k]); localNets[b.key] = o;
    change();
  }
  async function render() {
    box.replaceChildren();
    const b = blocks.find(x => x.key === S.netBlock);
    const nets = localNets[b.key];
    const tabs = h('div', { class: 'tabs' }, ...blocks.map(x => h('span', { class: 'tab' + (x.key === b.key ? ' active' : ''), title: x.question || x.key, onclick: () => { flush(); S.netBlock = x.key; S.activeNet = null; render(); } },
      x.key, Object.keys(localNets[x.key]).length ? h('span', { class: 'dot' }) : null)));
    const defs = netDefs(b);
    if (!S.activeNet || !defs.find(d => d.key === S.activeNet)) S.activeNet = defs.length ? defs[0].key : null;
    const cur = S.activeNet ? nets[S.activeNet] : null;
    const setOf = () => new Set(cur ? (cur.include || cur.exclude || []) : []);
    const mode = cur ? (cur.include ? 'include' : 'exclude') : 'include';

    const left = h('div', null, h('div', { class: 'qtext' }, b.question || b.key), h('div', { class: 'muted', style: 'margin-bottom:6px' }, 'סיכומים לשאלה: ' + (b.dict_var || 'ללא משתנה מילון')),
      ...defs.map(d => h('div', { class: 'netitem' + (d.key === S.activeNet ? ' active' : ''), onclick: () => { S.activeNet = d.key; render(); } },
        nets[d.key] ? h('span', { class: 'netmove' },
          h('button', { title: 'הזז למעלה', disabled: Object.keys(nets)[0] === d.key, onclick: ev => { ev.stopPropagation(); moveNet(b, d.key, -1); } }, '▲'),
          h('button', { title: 'הזז למטה', disabled: Object.keys(nets).slice(-1)[0] === d.key, onclick: ev => { ev.stopPropagation(); moveNet(b, d.key, 1); } }, '▼')) : null,
        nets[d.key] ? h('button', { class: 'netx', title: 'מחק סיכום זה', 'aria-label': 'מחק סיכום', onclick: async ev => {
          ev.stopPropagation();
          if (!await askConfirm(`למחוק את הסיכום "${d.label}"?`)) return;
          delete nets[d.key]; if (S.activeNet === d.key) S.activeNet = null;
          try { await patch({ questions: { [b.key]: { nets: validNets(nets) } } }); saved[b.key] = JSON.stringify(validNets(nets)); toast('הסיכום נמחק'); } catch (e) { toast('⚠ ' + e.message); }
          render();
        } }, '✕') : null,
        h('div', { class: 't' }, d.label), h('div', { class: 'muted' }, d.dict ? d.key : 'סיכום בשם חופשי (לא מיובא ל-DATA)'),
        nets[d.key] ? h('div', { class: 'muted' }, (nets[d.key].include ? 'נטו: ' + nets[d.key].include.length + ' קודים' : 'כל תשובה מלבד ' + (nets[d.key].exclude || []).length)) : h('div', { class: 'muted' }, 'לא הוגדר'))),
      h('button', { class: 'btn small ghost', onclick: async () => { const n = await askText('שם הסיכום החופשי:'); if (!n) return; const k = 'USER:' + Math.random().toString(36).slice(2, 8); nets[k] = { include: [], label: n }; S.activeNet = k; render(); } }, '+ סיכום חדש'));

    const right = h('div');
    if (S.activeNet) {
      right.append(h('div', { class: 'row', style: 'margin-bottom:8px' },
        h('label', null, h('input', { type: 'radio', name: 'nm', checked: mode === 'include', onchange: () => { const s = setOf(); nets[S.activeNet] = { ...(cur || {}), include: [...s] }; delete nets[S.activeNet].exclude; change(); } }), ' נטו = לפחות אחד מהמסומנים'),
        h('label', null, h('input', { type: 'radio', name: 'nm', checked: mode === 'exclude', onchange: () => { const s = setOf(); nets[S.activeNet] = { ...(cur || {}), exclude: [...s] }; delete nets[S.activeNet].include; change(); } }), ' "כל תשובה" = הכול מלבד המסומנים (למשל "לא זוכר")'),
        h('button', { class: 'btn small ghost', onclick: () => { delete nets[S.activeNet]; change(); } }, 'נקה הגדרה')));
    } else right.append(h('div', { class: 'alert warn' }, 'בחר/י סיכום מהרשימה משמאל כדי להגדיר אילו קודים נכללים בו.'));
    const tblHost = h('div', { class: 'tablewrap' }, 'טוען תוצאות…'); right.append(tblHost);
    const netHost = h('div', { style: 'margin-top:10px' }); right.append(netHost);
    right.append(h('div', { style: 'margin-top:10px' }, statusEl));
    box.append(tabs, h('div', { class: 'split' }, left, right));

    let pv;
    try { pv = await api(`/projects/${S.project.id}/preview`, { json: { block: b.key, nets: localNets[b.key] } }); } catch (e) { tblHost.textContent = '⚠ ' + e.message; return; }
    const sel = setOf();
    const hdr = h('tr', null, h('th', null, ''), h('th', null, 'קוד'), ...LEVELS.map(l => h('th', null, `${LEVEL_HE[l]} (${LETTER[l]})`, h('div', { class: 'muted', style: 'color:#dbe4f5' }, 'N=' + pv.bases[l]))));
    /* three states per code: empty = not assigned · ✔ (blue) = in the selected summary · ✔ (grey) = in another summary.
       A grey code can still be ticked (e.g. 'all correct messages' reuses codes of the other summaries). Only 'include'
       summaries own codes; an 'all answers except …' summary lists exclusions, not members. */
    const labelOf = k => (defs.find(d => d.key === k) || {}).label || (nets[k] && nets[k].label) || k;
    const otherNets = {};
    Object.keys(nets).forEach(k => { if (k !== S.activeNet && nets[k].include) nets[k].include.forEach(v => (otherNets[v] = otherNets[v] || []).push(labelOf(k))); });
    const rows = pv.codes.map(c => {
      const mine = sel.has(c.var) && mode === 'include', other = !mine && !!otherNets[c.var];
      const box = S.activeNet ? h('input', { type: 'checkbox', class: other ? 'other' : '', checked: sel.has(c.var) || other,
        title: other ? 'משויך לסיכום אחר: ' + otherNets[c.var].join(' · ') + ' (אפשר לסמן גם כאן)' : '',
        onchange: () => { const s = setOf(); s.has(c.var) ? s.delete(c.var) : s.add(c.var); const k = mode === 'include' ? 'include' : 'exclude'; nets[S.activeNet] = { ...(cur || {}), [k]: [...s] }; change(); } }) : '';
      return h('tr', null, h('td', null, box),
        h('td', null, c.label, otherNets[c.var] && !mine ? h('div', { class: 'assigned' }, '↳ ' + otherNets[c.var].join(' · ')) : null), ...LEVELS.map(l => valueCell(c, l, true)));
    });
    tblHost.replaceChildren(h('table', null, h('thead', null, hdr), h('tbody', null, ...rows)));
    if (pv.nets.length) netHost.append(h('h2', { style: 'font-size:15px;margin:6px 0' }, 'תוצאות הסיכומים (חיות, אותה חישוביות כמו באקסל)'),
      h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'סיכום'), h('th', null, 'united'), ...LEVELS.map(l => h('th', null, LEVEL_HE[l] + ' (' + LETTER[l] + ')')))),
        h('tbody', null, ...pv.nets.map(n => h('tr', { class: 'sum' }, h('td', null, n.label, n.members_text ? h('div', { class: 'members', title: n.members_full }, n.members_text) : null), h('td', null, n.united ? h('code', null, n.united) : h('span', { class: 'muted' }, 'חופשי')), ...LEVELS.map(l => valueCell(n, l, true))))))));
    if (pv.base_note === 'all') netHost.append(h('div', { class: 'muted' }, 'בסיס: כלל המדגם (שאלת המשך מותנית בחשיפה).'));
  }
  function valueCell(row, l, withCount) {
    const v = row.values[l], n = row.n[l];
    return h('td', { class: 'num' + (v != null && n < 30 ? ' low' : '') }, v == null ? '' : pctFmt(v, row.kind), row.letters[l] ? h('span', { class: 'sig' }, row.letters[l]) : null,
      withCount && row.counts ? h('div', { class: 'muted' }, 'n=' + row.counts[l]) : null);
  }
  function change() { scheduleSave(S.netBlock); clearTimeout(timer); timer = setTimeout(render, 150); }
  render();
  const pending = blocks.filter(b => b.wanted.length && !Object.keys(b.nets || {}).length).length;
  return sec('5. סיכומי קודים (Count Builder)', pending ? `${pending} שאלות עם סיכומי מילון שטרם הוגדרו` : '', pending ? 'need' : '',
    h('p', { class: 'muted' }, 'השינויים נשמרים אוטומטית. לכל שאלה מקודדת: סמן/י אילו קודים בונים כל סיכום מהמילון (SLOGAN#01, SPONTIMP_CORRECT, SEMIAEX-VD_* ועוד) או סיכום בשם חופשי. המערכת לא מנחשת את הסלוגן/המסר הנכון.'), box);
}

function secWarnings() {
  const host = h('div', 'טוען…');
  api(`/projects/${S.project.id}/warnings`).then(w => {
    host.replaceChildren(w.length ? h('ul', null, ...w.map(x => h('li', null, x.text))) : h('div', { class: 'alert ok' }, 'אין אזהרות פתוחות.'));
    pill.textContent = w.length + ' אזהרות'; pill.className = 'pill ' + (w.length ? 'need' : 'okp');
  }).catch(e => host.textContent = '⚠ ' + e.message);
  const pill = h('span', { class: 'pill' }, '…');
  return h('details', { class: 'sec' }, h('summary', null, h('h2', null, '6. אזהרות'), pill), h('div', { class: 'body' }, host));
}

/* -------- findings tables (verification): every question, 5 columns, letters, n per answer */
function secResults(open) {
  const host = h('div', null, h('button', { class: 'btn small', onclick: e => load(e.target) }, 'טען טבלאות ממצאים'));
  async function load(btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'מחשב…'; }
    try { if (!S.catalog) S.catalog = await api(`/projects/${S.project.id}/catalog`); renderTables(host, await api(`/projects/${S.project.id}/results`), () => { host.replaceChildren(h('p', { class: 'muted' }, 'מחשב…')); load(); }); } catch (e) { host.replaceChildren(h('div', { class: 'alert err' }, e.message)); }
  }
  const d = h('details', { class: 'sec', open: !!open }, h('summary', null, h('h2', null, '7. ממצאים — טבלאות לאימות'), h('span', { class: 'pill' }, 'מדגם · נחשפים · נחשפים שאינם משתמשים · לקוחות · לא לקוחות · חיתוכים נוספים')),
    h('div', { class: 'body' }, h('p', { class: 'muted' }, 'כל השאלות כפי שיופיעו באקסל, עם n (מספר משיבים) לכל תשובה ואותיות מובהקות (אות גדולה 95%, קטנה 90%; D מול E; חיתוך נוסף מול השאר ▲▼). ערך אדום = בסיס קטן מ-30. אם משהו לא נראה נכון, חזור/י לסעיף 3 והחלף/אשר את ההתאמה.'), host));
  d.addEventListener('toggle', () => { if (d.open && !host.dataset.loaded) { host.dataset.loaded = 1; load(host.querySelector('button')); } });
  if (open) setTimeout(() => { if (!host.dataset.loaded) { host.dataset.loaded = 1; load(host.querySelector('button')); } }, 0);
  return d;
}

function editCounts(key) { S.netBlock = key; S.jumpTo = key; S.step === 2 ? viewStep2() : viewStep2(); }

function renderTables(host, R, reload) {
  host.replaceChildren();
  const editable = new Set((S.catalog || []).map(b => b.key));
  let showN = true, q = '', onlyDict = false;
  const list = h('div');
  const bar = h('div', { class: 'row', style: 'margin-bottom:8px' },
    h('input', { type: 'text', placeholder: 'חיפוש שאלה / משתנה…', oninput: e => { q = e.target.value.trim().toLowerCase(); draw(); } }),
    h('label', null, h('input', { type: 'checkbox', checked: true, onchange: e => { showN = e.target.checked; draw(); } }), ' הצג n לכל תשובה'),
    h('label', null, h('input', { type: 'checkbox', onchange: e => { onlyDict = e.target.checked; draw(); } }), ' רק שאלות שמופו למילון'),
    reload ? h('button', { class: 'btn small ghost', onclick: reload }, '↻ רענן אחרי שינויים') : null,
    h('span', { class: 'muted' }, LEVELS.map(l => `${LETTER[l]}=${LEVEL_HE[l]} (N=${R.bases[l]})`).join(' · ')));
  function cell(r, l) {
    const v = r.values[l], n = r.n[l];
    return h('td', { class: 'num' + (v != null && n < R.min_n ? ' low' : '') }, v == null ? '' : pctFmt(v, r.kind), r.letters[l] ? h('span', { class: 'sig' }, r.letters[l]) : null,
      showN && v != null ? h('div', { class: 'muted' }, r.counts[l] != null ? `n=${r.counts[l]} מתוך ${n}` : `בסיס ${n}`) : null);
  }
  function draw() {
    list.replaceChildren();
    R.tables.filter(t => (!onlyDict || t.dict_var) && (!q || (t.key + ' ' + t.title + ' ' + t.question + ' ' + (t.dict_var || '')).toLowerCase().includes(q))).forEach(t => {
      const sums = t.rows.filter(r => r.section === 'summary'), body = t.rows.filter(r => r.section !== 'summary');
      const tr = r => h('tr', { class: r.section === 'summary' ? 'sum' : '' }, h('td', null, r.label, r.members_text ? h('div', { class: 'members', title: r.members_full }, r.members_text) : null, r.in_nets && r.in_nets.length ? h('div', { class: 'assigned' }, '↳ ' + r.in_nets.join(' · ')) : null, r.note ? h('div', { class: 'muted' }, r.note) : null), h('td', null, r.united ? h('code', null, r.united) : ''), ...LEVELS.map(l => cell(r, l)));
      const conf = t.confidence ? h('span', { class: 'badge ' + t.confidence, style: 'margin-inline-start:8px' }, CONF_HE[t.confidence] || t.confidence) : null;
      list.append(h('details', { class: 'sec' }, h('summary', { title: t.question || t.title }, h('b', null, t.title), h('code', null, t.key), conf, t.question ? h('span', { class: 'qhint' }, t.question.slice(0, 70) + (t.question.length > 70 ? '…' : '')) : null, h('span', { class: 'pill' }, t.rows.length + ' שורות')),
        h('div', { class: 'body' }, h('div', { class: 'row', style: 'margin-bottom:6px' }, editable.has(t.key) ? h('button', { class: 'btn small ghost', onclick: () => editCounts(t.key) }, '✎ הגדר/ערוך סיכומי קודים (counts) לשאלה זו') : null, h('button', { class: 'btn small ghost', onclick: () => viewStep2() }, '← לסקירה (התאמת מילון / אישור)')), t.question ? h('p', { class: 'qtext' }, t.question) : null,
          h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, h('th', null, 'תשובה'), h('th', null, 'united'), ...LEVELS.map(l => h('th', null, `${LEVEL_HE[l]} (${LETTER[l]})`)))),
            h('tbody', null, ...sums.map(tr), ...body.map(tr)))), ...t.notes.map(n => h('div', { class: 'muted', style: 'color:var(--red)' }, '⚠ ' + n)))));
    });
    if (!list.children.length) list.append(h('p', { class: 'muted' }, 'אין תוצאות לחיפוש.'));
  }
  draw(); host.append(bar, list);
}

/* ------------------------------------------------------------------ step 3 */
async function viewStep3() {
  setStep(3);
  const main = $('#main'); main.replaceChildren(backBar(viewStep2, 'חזרה לסקירה (עריכת התאמות וסיכומים)'), h('h1', null, 'שלב 3 · הרצה'));
  let loadErr = null;
  try { await refreshReview(); } catch (e) { loadErr = e; }
  if (loadErr && !S.review) { main.append(h('div', { class: 'alert err' }, '⚠ ' + loadErr.message), h('button', { class: 'btn', onclick: () => viewStep3() }, 'נסה שוב')); return; }
  const pend = S.review.pending;
  const card = h('div', { class: 'card' });
  const go = h('button', { class: 'btn gold' }, 'הרץ ממצאים');
  const prog = h('div'); const out = h('div');
  if (pend.length) card.append(h('div', { class: 'alert warn' }, `שים/י לב: ${pend.length} התאמות לא אושרו (${pend.slice(0, 6).join(', ')}) — הן יופקו כ"ניתוח בלבד" ללא united. ניתן לחזור לשלב 2.`));
  card.append(h('p', { class: 'muted' }, levelBases(S.review)), snapshotBar(), go, prog);
  if (loadErr) card.prepend(h('div', { class: 'alert warn' }, '⚠ ' + loadErr.message + ' (מוצגים נתונים אחרונים שנטענו)'));
  go.onclick = () => guarded(go, async () => {
    prog.replaceChildren(); out.replaceChildren();
    try { await runJob(); } catch (e) { prog.replaceChildren(h('div', { class: 'alert err' }, '⚠ ההרצה נכשלה: ' + e.message)); }
  });
  async function runJob() {
    const { job_id } = await api(`/projects/${S.project.id}/run`, { json: {} });
    const bar = h('div', { class: 'progress' }, h('div', { style: 'width:0%' })); const lbl = h('div', { class: 'muted' }, 'ממתין…');
    prog.replaceChildren(bar, lbl);
    for (;;) {
      const j = await api('/jobs/' + job_id);
      bar.firstChild.style.width = j.pct + '%'; lbl.textContent = j.stage;
      if (j.status === 'error') throw new Error(j.error);
      if (j.status === 'done') { renderResult(out, j.result); break; }
      await new Promise(r => setTimeout(r, 700));
    }
  }
  main.append(card, out, secResults(true));
}

function renderResult(host, r) {
  host.replaceChildren();
  const b = r.bases;
  host.append(h('div', { class: 'card' }, h('h2', null, 'התוצאה'),
    h('div', { class: 'kv', style: 'margin:8px 0' }, h('b', null, 'מדגם'), 'N=' + b.sample, h('b', null, 'נחשפים'), 'N=' + b.exposed, h('b', null, 'לקוחות / לא לקוחות'), `${b.customers} / ${b.noncust}`,
      h('b', null, 'הגדרת חשיפה'), (r.exposure.label || '') + ': ' + r.exposure.components.join(' | ')),
    h('div', { class: 'alert ' + (r.summary.errors.length ? 'err' : 'ok') }, `${r.summary.tables} טבלאות · ${r.summary.slots} משתני מילון · ${r.summary.checks} בקרות · ${r.summary.flagged.length} חריגות · ${r.summary.errors.length} שגיאות`),
    h('a', { class: 'btn', href: `api/projects/${S.project.id}/download` }, '⬇ הורד אקסל'), ' ', h('span', { class: 'muted' }, `${r.filename} · ${(r.size / 1024).toFixed(0)}KB · גרסה ${r.build.app_version} · ${r.build.dictionary_version}`)));
  host.append(h('div', { class: 'card' }, h('h2', null, 'בקרות'), h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['בדיקה', 'תוצאה', 'סטטוס'].map(x => h('th', null, x)))),
    h('tbody', null, ...r.checks.map(c => h('tr', { class: c[2] === 'OK' ? '' : 'need' }, h('td', null, c[0]), h('td', null, c[1]), h('td', null, c[2]))))))));
  if (r.open_assumptions.length) host.append(h('div', { class: 'card' }, h('h2', null, 'הנחות פתוחות (מופיעות גם בגליון הגדרות)'), h('ul', null, ...r.open_assumptions.slice(0, 60).map(x => h('li', null, x)))));
  host.append(h('div', null, h('button', { class: 'btn gold', onclick: () => viewStep4() }, 'שמור כתבנית לגל הבא ←')));
}

/* ------------------------------------------------------------------ step 4 */
async function viewStep4() {
  setStep(4);
  const main = $('#main'); main.replaceChildren(backBar(viewStep3, 'חזרה להרצה ולתוצאות'), h('h1', null, 'שלב 4 · שמירה כתבנית'));
  const tpls = await api('/library/templates');
  const name = h('input', { type: 'text', value: S.review.mapping.project.name || '' });
  const client = h('input', { type: 'text' }); const tracker = h('input', { type: 'text' });
  const existing = h('select', null, h('option', { value: '' }, 'תבנית חדשה'), ...tpls.map(t => h('option', { value: t.id }, `גרסה חדשה של: ${t.name} (v${t.version})`)));
  const save = h('button', { class: 'btn' }, 'שמור תבנית');
  const res = h('div');
  save.onclick = () => guarded(save, async () => {
    const r = await api('/library/templates', { json: { project_id: S.project.id, name: name.value, client: client.value, tracker: tracker.value, template_id: existing.value || null } });
    res.replaceChildren(h('div', { class: 'alert ok' }, `נשמר: ${r.id} v${r.version}`), h('ul', null, ...r.changes.map(c => h('li', null, c))));
  });
  main.append(h('div', { class: 'card' }, h('p', { class: 'muted' }, 'נשמרות החלטות בלבד (מיפוי מאושר, סיכומי קודים, סדר מסרים, הגדרת חשיפה ולקוחות). לא נשמרים נתוני משיבים. אי אפשר לשמור כל עוד יש התאמות שלא אושרו/הוחרגו.'),
    h('div', { class: 'row' }, h('label', { class: 'f' }, 'שם התבנית', name), h('label', { class: 'f' }, 'לקוח', client), h('label', { class: 'f' }, 'מעקב', tracker), h('label', { class: 'f' }, 'גרסה קיימת?', existing)),
    h('div', { style: 'margin-top:12px' }, save), res));
}

/* ------------------------------------------------------------------ library */
async function viewLibrary() {
  setStep(0);
  const main = $('#main'); main.replaceChildren(h('h1', null, 'ספרייה'));
  const [tpls, dicts] = await Promise.all([api('/library/templates'), api('/library/dictionaries')]);
  const hist = h('div');
  const trows = tpls.map(t => h('tr', null, h('td', null, t.name), h('td', null, t.client), h('td', null, t.tracker), h('td', null, 'v' + t.version), h('td', null, t.created_by), h('td', null, t.created_at.replace('T', ' ')),
    h('td', null, h('button', { class: 'btn small ghost', onclick: async () => { const hs = await api(`/library/templates/${t.id}/history`); hist.replaceChildren(h('h2', null, 'היסטוריה: ' + t.name), ...hs.map(x => h('div', { class: 'card' }, h('b', null, `v${x.version} · ${x.created_by || '—'} · ${x.created_at.replace('T', ' ')}`), h('ul', null, ...x.changes.map(c => h('li', null, c)))))); } }, 'היסטוריה'))));
  main.append(h('div', { class: 'card' }, h('h2', null, 'תבניות'), tpls.length ? h('div', { class: 'tablewrap' }, h('table', null, h('thead', null, h('tr', null, ...['שם', 'לקוח', 'מעקב', 'גרסה', 'עודכן ע"י', 'תאריך', ''].map(x => h('th', null, x)))), h('tbody', null, ...trows))) : h('p', { class: 'muted' }, 'אין תבניות עדיין.'), hist));
  const up = h('input', { type: 'file', accept: '.xlsx' });
  const upBtn = h('button', { class: 'btn small' }, 'העלה גרסת מילון חדשה');
  upBtn.onclick = () => guarded(upBtn, async () => { if (!up.files[0]) throw new Error('בחר/י קובץ'); const fd = new FormData(); fd.append('file', up.files[0]); const r = await fetch('api/library/dictionaries', { method: 'POST', body: fd }); const d = await r.json(); if (!r.ok) throw new Error(d.detail); toast('הועלה: ' + d.variables + ' משתנים'); viewLibrary(); });
  main.append(h('div', { class: 'card' }, h('h2', null, 'גרסאות מילון'), h('p', { class: 'muted' }, 'פרויקט חדש משתמש במילון הפעיל. פרויקט קיים נשאר על הגרסה שנבחרה בו (דטרמיניזם).'),
    h('ul', null, ...dicts.map(d => h('li', null, d.file, d.active ? h('span', { class: 'badge exact', style: 'margin-inline-start:8px' }, 'פעיל') : h('button', { class: 'btn small ghost', style: 'margin-inline-start:8px', onclick: async () => { await api('/library/dictionary/active', { method: 'PUT', json: { file: d.file } }); viewLibrary(); } }, 'הפוך לפעיל'), ' ', h('span', { class: 'muted' }, d.uploaded_at.replace('T', ' '))))),
    h('div', { class: 'row' }, up, upBtn)));
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  setUser(user());
  $('#nav-home').onclick = viewStep1; $('#nav-lib').onclick = () => viewLibrary().catch(e => toast('⚠ ' + e.message));
  $('#nav-user').onclick = async () => { const n = await askText('שם משתמש (יירשם ביומן ההחלטות):', user()); if (n != null) setUser(n); };
  try { const v = await api('/version'); $('#foot').textContent = `Impact360 SAV Runner · גרסה ${v.app_version} · build ${v.build_time} · מילון: ${v.dictionary || '—'} · אין קריאות רשת החוצה`; } catch (e) { $('#foot').textContent = 'אין חיבור לשרת'; }
  document.querySelectorAll('#steps li').forEach(li => li.onclick = () => goStep(+li.dataset.step));
  viewStep1();
  if (!user()) { const n = await askText('מה שמך? (יירשם ביומן ההחלטות לצד כל אישור)'); if (n) setUser(n); }
}
boot();
