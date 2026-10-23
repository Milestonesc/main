/**
 * 프로젝트 현황판 — 공용 구글 계정에서 돌아가는 사내 웹앱.
 *
 * 데이터: 구글 시트 하나(탭마다 표 하나) + 드라이브 폴더(프로젝트별 문서)
 * 연동:   단계 일정 → 공용 구글 캘린더(한 방향), 평일 09시 슬랙 알림(바뀐 게 있을 때만) + 주간 요약
 * 권한:   없음. 누구나 보고 고칠 수 있고, 모든 변경은 '기록' 탭에 남는다.
 */

var TZ = 'Asia/Seoul';
var APP_NAME = '프로젝트 현황판';
var HOLIDAY_CAL = 'ko.south_korea#holiday@group.v.calendar.google.com';
var COST_KINDS = ['견적서', '발주서', '지출결의서', '영수증', '세금계산서', '실비', '기타'];

var SCHEMA = {
  Members: ['name', 'active'],
  Projects: ['id', 'name', 'client', 'color', 'status', 'start', 'end', 'members', 'note', 'folderId', 'eventId',
             'deleted', 'createdAt', 'updatedAt'],
  Phases: ['id', 'projectId', 'name', 'start', 'end', 'order', 'eventId'],
  Tasks: ['id', 'projectId', 'phaseId', 'text', 'assignee', 'due', 'done', 'doneBy', 'doneAt', 'createdBy', 'createdAt'],
  Costs: ['id', 'projectId', 'date', 'kind', 'title', 'amount', 'vendor', 'memo', 'fileId', 'fileName', 'mimeType',
          'by', 'at'],
  Comments: ['id', 'projectId', 'by', 'at', 'text'],
  Log: ['at', 'by', 'projectId', 'project', 'action', 'detail'],
  Settings: ['key', 'value']
};

// ───────────────────────── 웹앱 ─────────────────────────

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle(APP_NAME)
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

/** 처음 한 번 실행: 시트·폴더·캘린더 만들기, 아침 알림 예약. 다시 실행해도 안전하다. */
function setup() {
  var props = PropertiesService.getScriptProperties();
  var ss = props.getProperty('SHEET_ID') ? SpreadsheetApp.openById(props.getProperty('SHEET_ID')) : null;
  if (!ss) {
    ss = SpreadsheetApp.create(APP_NAME + ' 데이터');
    props.setProperty('SHEET_ID', ss.getId());
  }
  Object.keys(SCHEMA).forEach(function (name) {
    var sh = ss.getSheetByName(name) || ss.insertSheet(name);
    sh.getRange(1, 1, 1, SCHEMA[name].length).setValues([SCHEMA[name]]).setFontWeight('bold');
    sh.setFrozenRows(1);
    sh.getRange(1, 1, sh.getMaxRows(), SCHEMA[name].length).setNumberFormat('@'); // 날짜가 자동 변환되지 않게
  });
  var first = ss.getSheetByName('Sheet1') || ss.getSheetByName('시트1');
  if (first && ss.getSheets().length > 1) ss.deleteSheet(first);

  if (!props.getProperty('ROOT_FOLDER_ID')) {
    var root = DriveApp.createFolder(APP_NAME + ' 문서');
    props.setProperty('ROOT_FOLDER_ID', root.getId());
    DriveApp.getFileById(ss.getId()).moveTo(root);
  }
  if (!props.getProperty('CALENDAR_ID')) {
    var cal = CalendarApp.createCalendar(APP_NAME, { timeZone: TZ, color: CalendarApp.Color.BLUE });
    props.setProperty('CALENDAR_ID', cal.getId());
  }
  try { if (!CalendarApp.getCalendarById(HOLIDAY_CAL)) CalendarApp.subscribeToCalendar(HOLIDAY_CAL); } catch (e) {}

  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'morningDigest') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('morningDigest').timeBased().everyDays(1).atHour(9).nearMinute(0).inTimezone(TZ).create();
  return '준비 완료. 시트: ' + ss.getUrl();
}

// ───────────────────────── 저장소 ─────────────────────────

var _ss = null;
function ss_() {
  if (!_ss) _ss = SpreadsheetApp.openById(PropertiesService.getScriptProperties().getProperty('SHEET_ID'));
  return _ss;
}

function fmtDate_(v) {
  if (v instanceof Date) {  // 누군가 시트에서 직접 날짜를 쳐 넣었을 때
    var t = Utilities.formatDate(v, TZ, "yyyy-MM-dd'T'HH:mm:ss");
    return t.slice(11) === '00:00:00' ? t.slice(0, 10) : t;
  }
  return v === null || v === undefined ? '' : String(v);
}

/** 탭 전체를 객체 목록으로. _row는 시트의 행 번호(2부터). */
function rows_(name) {
  var sh = ss_().getSheetByName(name);
  var values = sh.getDataRange().getValues();
  var cols = SCHEMA[name];
  var out = [];
  for (var i = 1; i < values.length; i++) {
    if (values[i].every(function (c) { return c === '' || c === null; })) continue;
    var o = { _row: i + 1 };
    cols.forEach(function (c, j) { o[c] = fmtDate_(values[i][j]); });
    out.push(o);
  }
  return out;
}

function toRow_(name, o) {
  return SCHEMA[name].map(function (c) {
    var v = o[c];
    return v === undefined || v === null ? '' : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : String(v);
  });
}

/** 새 행도 '글자' 서식으로 써서 날짜·숫자가 자동 변환되지 않게 한다. */
function append_(name, o) {
  var sh = ss_().getSheetByName(name), n = SCHEMA[name].length;
  var r = sh.getLastRow() + 1;
  if (r > sh.getMaxRows()) {
    sh.insertRowsAfter(sh.getMaxRows(), 500);
    sh.getRange(r, 1, sh.getMaxRows() - r + 1, n).setNumberFormat('@');
  }
  sh.getRange(r, 1, 1, n).setNumberFormat('@').setValues([toRow_(name, o)]);
  return o;
}

function write_(name, o) {
  ss_().getSheetByName(name).getRange(o._row, 1, 1, SCHEMA[name].length).setValues([toRow_(name, o)]);
}

function remove_(name, list) {
  // 아래 행부터 지워야 행 번호가 밀리지 않는다
  list.map(function (o) { return o._row; }).sort(function (a, b) { return b - a; })
    .forEach(function (r) { ss_().getSheetByName(name).deleteRow(r); });
}

function find_(name, id) {
  var hit = rows_(name).filter(function (o) { return o.id === id; })[0];
  if (!hit) throw new Error('찾을 수 없어요 (' + name + ' ' + id + ')');
  return hit;
}

function setting_(key) {
  var hit = rows_('Settings').filter(function (o) { return o.key === key; })[0];
  return hit ? hit.value : '';
}

function setSetting_(key, value) {
  var hit = rows_('Settings').filter(function (o) { return o.key === key; })[0];
  if (hit) { hit.value = value; write_('Settings', hit); } else append_('Settings', { key: key, value: value });
}

function uid_() { return Utilities.getUuid().slice(0, 8); }
function now_() { return Utilities.formatDate(new Date(), TZ, "yyyy-MM-dd'T'HH:mm:ss"); }
function isTrue_(v) { return v === true || String(v).toUpperCase() === 'TRUE'; }
function md_(d) { return d ? Number(d.slice(5, 7)) + '/' + Number(d.slice(8, 10)) : '?'; }
function span_(s, e) { return md_(s) + (e && e !== s ? '~' + md_(e) : ''); }
function won_(n) { return n === '' || n === null || isNaN(Number(n)) ? '' : Number(n).toLocaleString('ko-KR') + '원'; }

function log_(by, project, action, detail) {
  append_('Log', { at: now_(), by: by, projectId: project ? project.id : '', project: project ? project.name : '',
                   action: action, detail: detail || '' });
}

/** 여러 사람이 동시에 고쳐도 엉키지 않게 한 번에 한 요청만 쓴다. */
function locked_(fn) {
  var lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try { return fn(); } finally { lock.releaseLock(); }
}

// ───────────────────────── 로그인 ─────────────────────────

function check_(auth) {
  var pass = setting_('teamPassword');
  if (pass && (!auth || auth.pass !== pass)) throw new Error('비밀번호가 맞지 않아요.');
  var names = rows_('Members').filter(function (m) { return isTrue_(m.active); }).map(function (m) { return m.name; });
  if (!auth || !auth.name || (names.length && names.indexOf(auth.name) < 0)) throw new Error('이름을 다시 골라 주세요.');
  return auth.name;
}

/** 로그인 화면용: 이름 목록과 비밀번호 필요 여부만. */
function getLoginInfo() {
  return {
    appName: APP_NAME,
    names: rows_('Members').filter(function (m) { return isTrue_(m.active); }).map(function (m) { return m.name; }),
    needPassword: !!setting_('teamPassword')
  };
}

function login(auth) { check_(auth); return true; }

// ───────────────────────── 읽기 ─────────────────────────

function getData(auth) {
  check_(auth);
  var projects = rows_('Projects').filter(function (p) { return !isTrue_(p.deleted); });
  var alive = {};
  projects.forEach(function (p) { alive[p.id] = true; });
  var keep = function (o) { return alive[o.projectId]; };
  var strip = function (o) { var c = {}; for (var k in o) if (k !== '_row' && k !== 'eventId') c[k] = o[k]; return c; };
  var tasks = rows_('Tasks').filter(keep).map(function (t) { t = strip(t); t.done = isTrue_(t.done); return t; });
  var log = rows_('Log');
  return {
    me: auth.name,
    today: Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'),
    members: rows_('Members').filter(function (m) { return isTrue_(m.active); }).map(function (m) { return m.name; }),
    projects: projects.map(strip),
    phases: rows_('Phases').filter(keep).map(strip),
    tasks: tasks,
    costs: rows_('Costs').filter(keep).map(strip),
    comments: rows_('Comments').filter(keep).map(strip),
    log: log.slice(Math.max(0, log.length - 500)).map(strip).reverse(),
    holidays: holidays_(),
    costKinds: COST_KINDS,
    settings: {
      hasSlack: !!setting_('slackWebhook'),
      hasPassword: !!setting_('teamPassword'),
      calendarId: PropertiesService.getScriptProperties().getProperty('CALENDAR_ID') || '',
      sheetUrl: ss_().getUrl(),
      folderUrl: DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty('ROOT_FOLDER_ID')).getUrl()
    }
  };
}

/** 올해·내년 한국 공휴일(구글 '대한민국의 휴일' 캘린더). 하루 한 번만 읽고 저장해 둔다. */
function holidays_() {
  var cache = CacheService.getScriptCache();
  var hit = cache.get('holidays');
  if (hit) return JSON.parse(hit);
  var out = [];
  try {
    var cal = CalendarApp.getCalendarById(HOLIDAY_CAL);
    var y = Number(Utilities.formatDate(new Date(), TZ, 'yyyy'));
    cal.getEvents(new Date(y - 1, 0, 1), new Date(y + 2, 0, 1)).forEach(function (ev) {
      var desc = (ev.getDescription() || '').split('\n')[0];
      out.push({ date: Utilities.formatDate(ev.getAllDayStartDate(), TZ, 'yyyy-MM-dd'), name: ev.getTitle(),
                 off: desc.indexOf('공휴일') === 0 || desc.indexOf('Public holiday') === 0 });
    });
  } catch (e) { /* 휴일 캘린더를 못 읽어도 앱은 돌아간다 */ }
  cache.put('holidays', JSON.stringify(out), 21600);
  return out;
}

// ───────────────────────── 프로젝트·단계 ─────────────────────────

/**
 * 프로젝트 저장(새로 만들기·고치기). p.phases = [{id?, name, start, end}] 순서대로.
 * 목록에 없는 기존 단계는 지우고, 그 단계의 할 일은 '단계 없음'으로 옮긴다.
 */
function saveProject(auth, p) {
  var me = check_(auth);
  return locked_(function () {
    if (!p.name || !String(p.name).trim()) throw new Error('프로젝트 이름을 적어 주세요.');
    var t = now_();
    var cur, changes = [];
    var fields = { name: '이름', client: '고객사', status: '상태', start: '시작', end: '마감', members: '구성원', note: '설명',
                   color: '색' };
    if (p.id) {
      cur = find_('Projects', p.id);
      Object.keys(fields).forEach(function (k) {
        var nv = p[k] === undefined ? cur[k] : String(p[k]);
        if (nv !== cur[k]) {
          if (k === 'note' || k === 'color') changes.push(fields[k] + ' 수정');
          else changes.push(fields[k] + ' ' + (cur[k] || '없음') + ' → ' + (nv || '없음'));
          cur[k] = nv;
        }
      });
      cur.updatedAt = t;
      write_('Projects', cur);
    } else {
      cur = { id: uid_(), name: String(p.name).trim(), client: p.client || '', color: p.color || '', status: p.status || '진행',
              start: p.start || '', end: p.end || '', members: p.members || '', note: p.note || '', folderId: '',
              eventId: '', deleted: 'FALSE', createdAt: t, updatedAt: t };
      append_('Projects', cur);
      log_(me, cur, '새 프로젝트', span_(cur.start, cur.end));
    }
    if (p.phases) changes = changes.concat(savePhases_(cur, p.phases));
    if (changes.length && p.id) log_(me, cur, '프로젝트 수정', changes.join(', '));
    syncCalendar_(cur.id);
    return cur.id;
  });
}

function savePhases_(project, list) {
  var existing = rows_('Phases').filter(function (ph) { return ph.projectId === project.id; });
  var byId = {};
  existing.forEach(function (ph) { byId[ph.id] = ph; });
  var keep = {}, changes = [];
  list.forEach(function (ph, i) {
    if (!ph.name || !String(ph.name).trim()) return;
    var name = String(ph.name).trim();
    if (ph.id && byId[ph.id]) {
      var cur = byId[ph.id];
      keep[cur.id] = true;
      if (cur.name !== name) changes.push("단계 이름 '" + cur.name + "' → '" + name + "'");
      if (cur.start !== (ph.start || '') || cur.end !== (ph.end || ''))
        changes.push("'" + name + "' 기간 " + span_(cur.start, cur.end) + ' → ' + span_(ph.start, ph.end));
      cur.name = name; cur.start = ph.start || ''; cur.end = ph.end || ''; cur.order = String(i);
      write_('Phases', cur);
    } else {
      var n = append_('Phases', { id: uid_(), projectId: project.id, name: name, start: ph.start || '', end: ph.end || '',
                                  order: String(i), eventId: '' });
      keep[n.id] = true;
      changes.push("단계 추가 '" + name + "' " + span_(n.start, n.end));
    }
  });
  var gone = existing.filter(function (ph) { return !keep[ph.id]; });
  if (gone.length) {
    var calId = PropertiesService.getScriptProperties().getProperty('CALENDAR_ID');
    gone.forEach(function (ph) {
      changes.push("단계 삭제 '" + ph.name + "'");
      deleteEvent_(calId, ph.eventId);
    });
    var goneIds = gone.map(function (ph) { return ph.id; });
    rows_('Tasks').forEach(function (tk) {
      if (goneIds.indexOf(tk.phaseId) >= 0) { tk.phaseId = ''; write_('Tasks', tk); }
    });
    remove_('Phases', rows_('Phases').filter(function (ph) { return goneIds.indexOf(ph.id) >= 0; }));
  }
  return changes;
}

/** 지워도 시트에는 남긴다(deleted=TRUE). 캘린더 일정만 지운다. */
function deleteProject(auth, id) {
  var me = check_(auth);
  return locked_(function () {
    var p = find_('Projects', id);
    p.deleted = 'TRUE'; p.updatedAt = now_();
    write_('Projects', p);
    var calId = PropertiesService.getScriptProperties().getProperty('CALENDAR_ID');
    deleteEvent_(calId, p.eventId);
    rows_('Phases').filter(function (ph) { return ph.projectId === id; }).forEach(function (ph) { deleteEvent_(calId, ph.eventId); });
    log_(me, p, '프로젝트 삭제', '');
    return true;
  });
}

// ───────────────────────── 캘린더 (앱 → 구글 캘린더) ─────────────────────────

function deleteEvent_(calId, eventId) {
  if (!calId || !eventId) return;
  try { var ev = CalendarApp.getCalendarById(calId).getEventById(eventId); if (ev) ev.deleteEvent(); } catch (e) {}
}

function day_(s) { return new Date(Number(s.slice(0, 4)), Number(s.slice(5, 7)) - 1, Number(s.slice(8, 10))); }
function nextDay_(s) { var d = day_(s); d.setDate(d.getDate() + 1); return d; }

/** 단계마다 종일 일정 하나. 단계가 없으면 프로젝트 기간 하나. 날짜가 없으면 일정도 없다. */
function syncCalendar_(projectId) {
  var calId = PropertiesService.getScriptProperties().getProperty('CALENDAR_ID');
  if (!calId) return;
  var cal = CalendarApp.getCalendarById(calId);
  if (!cal) return;
  var p = find_('Projects', projectId);
  var phases = rows_('Phases').filter(function (ph) { return ph.projectId === projectId; });
  var upsert = function (obj, title, sheet) {
    var start = obj.start || obj.end, end = obj.end || obj.start;
    var ev = null;
    if (obj.eventId) { try { ev = cal.getEventById(obj.eventId); } catch (e) { ev = null; } }
    if (!start) { if (ev) ev.deleteEvent(); if (obj.eventId) { obj.eventId = ''; write_(sheet, obj); } return; }
    if (end < start) end = start;
    var desc = '프로젝트 현황판에서 자동으로 만든 일정이에요. 고칠 때는 앱에서 고쳐 주세요.' + (p.client ? '\n고객사: ' + p.client : '');
    if (ev) {
      ev.setTitle(title); ev.setAllDayDates(day_(start), nextDay_(end)); ev.setDescription(desc);
    } else {
      ev = cal.createAllDayEvent(title, day_(start), nextDay_(end), { description: desc });
      obj.eventId = ev.getId(); write_(sheet, obj);
    }
  };
  if (phases.length) {
    if (p.eventId) { deleteEvent_(calId, p.eventId); p.eventId = ''; write_('Projects', p); }
    phases.forEach(function (ph) { upsert(ph, '[' + p.name + '] ' + ph.name, 'Phases'); });
  } else {
    upsert(p, '[' + p.name + ']', 'Projects');
  }
}

// ───────────────────────── 할 일(체크리스트) ─────────────────────────

function phaseName_(phaseId) {
  if (!phaseId) return '';
  var ph = rows_('Phases').filter(function (x) { return x.id === phaseId; })[0];
  return ph ? ph.name : '';
}

function addTask(auth, t) {
  var me = check_(auth);
  return locked_(function () {
    var p = find_('Projects', t.projectId);
    var text = String(t.text || '').trim();
    if (!text) throw new Error('할 일을 적어 주세요.');
    var o = append_('Tasks', { id: uid_(), projectId: p.id, phaseId: t.phaseId || '', text: text, assignee: t.assignee || '',
                               due: t.due || '', done: 'FALSE', doneBy: '', doneAt: '', createdBy: me, createdAt: now_() });
    var where = phaseName_(o.phaseId);
    log_(me, p, '할 일 추가', (where ? "'" + where + "' " : '') + text + (o.assignee ? ' (' + o.assignee + ')' : '') +
         (o.due ? ' ~' + md_(o.due) : ''));
    return o.id;
  });
}

/** patch: {done?, text?, assignee?, due?, phaseId?} */
function updateTask(auth, id, patch) {
  var me = check_(auth);
  return locked_(function () {
    var t = find_('Tasks', id), p = find_('Projects', t.projectId);
    var notes = [];
    if (patch.done !== undefined && isTrue_(patch.done) !== isTrue_(t.done)) {
      t.done = patch.done ? 'TRUE' : 'FALSE';
      t.doneBy = patch.done ? me : ''; t.doneAt = patch.done ? now_() : '';
      log_(me, p, patch.done ? '완료 체크' : '체크 해제', t.text);
    }
    if (patch.text !== undefined && String(patch.text).trim() && String(patch.text).trim() !== t.text) {
      notes.push("'" + t.text + "' → '" + String(patch.text).trim() + "'");
      t.text = String(patch.text).trim();
    }
    if (patch.assignee !== undefined && patch.assignee !== t.assignee) {
      notes.push('담당 ' + (t.assignee || '없음') + ' → ' + (patch.assignee || '없음')); t.assignee = patch.assignee;
    }
    if (patch.due !== undefined && patch.due !== t.due) {
      notes.push('기한 ' + (t.due ? md_(t.due) : '없음') + ' → ' + (patch.due ? md_(patch.due) : '없음')); t.due = patch.due;
    }
    if (patch.phaseId !== undefined && patch.phaseId !== t.phaseId) {
      notes.push("단계 '" + (phaseName_(t.phaseId) || '없음') + "' → '" + (phaseName_(patch.phaseId) || '없음') + "'");
      t.phaseId = patch.phaseId;
    }
    if (notes.length) log_(me, p, '할 일 수정', t.text + ': ' + notes.join(', '));
    write_('Tasks', t);
    return true;
  });
}

function deleteTask(auth, id) {
  var me = check_(auth);
  return locked_(function () {
    var t = find_('Tasks', id);
    remove_('Tasks', [t]);
    log_(me, find_('Projects', t.projectId), '할 일 삭제', t.text);
    return true;
  });
}

// ───────────────────────── 비용·문서 ─────────────────────────

function projectFolder_(p) {
  if (p.folderId) { try { return DriveApp.getFolderById(p.folderId); } catch (e) {} }
  var root = DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty('ROOT_FOLDER_ID'));
  var f = root.createFolder(p.name);
  p.folderId = f.getId();
  write_('Projects', p);
  return f;
}

/** c.file = {name, mimeType, data(base64)} 는 선택. 파일 없이 금액만 적는 실비도 된다. */
function addCost(auth, c) {
  var me = check_(auth);
  if (!c.file && !(c.title && String(c.title).trim())) throw new Error('파일을 올리거나 내용을 적어 주세요.');
  // 파일 저장은 잠금 밖에서 (오래 걸릴 수 있다)
  var p0 = find_('Projects', c.projectId);
  var file = null;
  if (c.file && c.file.data) {
    var blob = Utilities.newBlob(Utilities.base64Decode(c.file.data), c.file.mimeType || 'application/octet-stream', c.file.name);
    var dated = (c.date || Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd')) + '_' + (c.kind || '문서') + '_' + c.file.name;
    file = projectFolder_(p0).createFile(blob).setName(dated);
  }
  return locked_(function () {
    var p = find_('Projects', c.projectId);
    var amount = String(c.amount === undefined || c.amount === null ? '' : c.amount).replace(/[^0-9.-]/g, '');
    var o = append_('Costs', { id: uid_(), projectId: p.id, date: c.date || Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'),
                               kind: c.kind || '기타', title: String(c.title || (c.file ? c.file.name : '')).trim(),
                               amount: amount, vendor: c.vendor || '', memo: c.memo || '',
                               fileId: file ? file.getId() : '', fileName: file ? c.file.name : '',
                               mimeType: file ? (c.file.mimeType || '') : '', by: me, at: now_() });
    log_(me, p, '비용·문서 추가', o.kind + ' ' + o.title + (amount ? ' ' + won_(amount) : '') + (file ? ' 📎' : ''));
    return o.id;
  });
}

function updateCost(auth, id, patch) {
  var me = check_(auth);
  return locked_(function () {
    var c = find_('Costs', id), p = find_('Projects', c.projectId);
    ['date', 'kind', 'title', 'amount', 'vendor', 'memo'].forEach(function (k) {
      if (patch[k] !== undefined) c[k] = k === 'amount' ? String(patch[k]).replace(/[^0-9.-]/g, '') : String(patch[k]);
    });
    write_('Costs', c);
    log_(me, p, '비용·문서 수정', c.kind + ' ' + c.title + (c.amount ? ' ' + won_(c.amount) : ''));
    return true;
  });
}

/** 기록에서 빠지지 않게 파일은 휴지통으로만 보낸다(30일 안에 드라이브에서 되살릴 수 있다). */
function deleteCost(auth, id) {
  var me = check_(auth);
  return locked_(function () {
    var c = find_('Costs', id);
    if (c.fileId) { try { DriveApp.getFileById(c.fileId).setTrashed(true); } catch (e) {} }
    remove_('Costs', [c]);
    log_(me, find_('Projects', c.projectId), '비용·문서 삭제', c.kind + ' ' + c.title + (c.amount ? ' ' + won_(c.amount) : ''));
    return true;
  });
}

/** 직원은 공용 계정으로 로그인하지 않으므로 파일은 앱을 거쳐 내려받는다. */
function getFile(auth, costId) {
  check_(auth);
  var c = find_('Costs', costId);
  if (!c.fileId) throw new Error('파일이 없는 항목이에요.');
  var blob = DriveApp.getFileById(c.fileId).getBlob();
  return { name: c.fileName || blob.getName(), mimeType: blob.getContentType(), data: Utilities.base64Encode(blob.getBytes()) };
}

// ───────────────────────── 댓글 ─────────────────────────

function addComment(auth, projectId, text) {
  var me = check_(auth);
  return locked_(function () {
    var p = find_('Projects', projectId);
    text = String(text || '').trim();
    if (!text) throw new Error('내용을 적어 주세요.');
    append_('Comments', { id: uid_(), projectId: p.id, by: me, at: now_(), text: text });
    log_(me, p, '댓글', text.length > 60 ? text.slice(0, 60) + '…' : text);
    return true;
  });
}

function deleteComment(auth, id) {
  var me = check_(auth);
  return locked_(function () {
    var c = find_('Comments', id);
    remove_('Comments', [c]);
    log_(me, find_('Projects', c.projectId), '댓글 삭제', c.text.slice(0, 60));
    return true;
  });
}

// ───────────────────────── 설정 ─────────────────────────

/** 처음 쓸 때(직원 목록이 비었을 때)도 부를 수 있다. */
function saveMembers(auth, names) {
  var current = rows_('Members').filter(function (m) { return isTrue_(m.active); }).map(function (m) { return m.name; });
  var me = current.length ? check_(auth) : (auth && auth.name) || '처음 설정';
  return locked_(function () {
    var clean = [];
    (names || []).forEach(function (n) { n = String(n).trim(); if (n && clean.indexOf(n) < 0) clean.push(n); });
    if (!clean.length) throw new Error('직원 이름을 한 명 이상 적어 주세요.');
    var all = rows_('Members');
    all.forEach(function (m) { m.active = clean.indexOf(m.name) >= 0 ? 'TRUE' : 'FALSE'; write_('Members', m); });
    clean.forEach(function (n) {
      if (!all.some(function (m) { return m.name === n; })) append_('Members', { name: n, active: 'TRUE' });
    });
    var added = clean.filter(function (n) { return current.indexOf(n) < 0; });
    var removed = current.filter(function (n) { return clean.indexOf(n) < 0; });
    if (added.length || removed.length)
      log_(me, null, '직원 목록', (added.length ? '추가 ' + added.join(', ') : '') +
           (added.length && removed.length ? ' / ' : '') + (removed.length ? '빼기 ' + removed.join(', ') : ''));
    return clean;
  });
}

/** s = {teamPassword?, slackWebhook?}. 빈 문자열이면 끈다. */
function saveSettings(auth, s) {
  var me = check_(auth);
  return locked_(function () {
    if (s.slackWebhook !== undefined) {
      var url = String(s.slackWebhook).trim();
      if (url && url.indexOf('https://hooks.slack.com/') !== 0) throw new Error('슬랙 웹훅 주소는 https://hooks.slack.com/ 으로 시작해요.');
      setSetting_('slackWebhook', url);
      log_(me, null, '설정', url ? '슬랙 연결' : '슬랙 연결 끊기');
    }
    if (s.teamPassword !== undefined) {
      setSetting_('teamPassword', String(s.teamPassword));
      log_(me, null, '설정', s.teamPassword ? '팀 비밀번호 변경' : '팀 비밀번호 끄기');
    }
    return true;
  });
}

function testSlack(auth) {
  var me = check_(auth);
  postSlack_('✅ ' + APP_NAME + ' 슬랙 연결 확인 (' + me + ')');
  return true;
}

// ───────────────────────── 슬랙 아침 알림 ─────────────────────────

function postSlack_(text) {
  var url = setting_('slackWebhook');
  if (!url) return false;
  var res = UrlFetchApp.fetch(url, { method: 'post', contentType: 'application/json',
                                     payload: JSON.stringify({ text: text }), muteHttpExceptions: true });
  if (res.getResponseCode() >= 300) throw new Error('슬랙 전송 실패: ' + res.getResponseCode() + ' ' + res.getContentText());
  return true;
}

function ymd_(d) { return Utilities.formatDate(d, TZ, 'yyyy-MM-dd'); }
function addDays_(s, n) { var d = day_(s); d.setDate(d.getDate() + n); return ymd_(d); }
function weekday_(s) { return day_(s).getDay(); } // 0=일

function isOff_(s, holidays) {
  var w = weekday_(s);
  return w === 0 || w === 6 || holidays.some(function (h) { return h.off && h.date === s; });
}

/** 매일 09시쯤 실행. 쉬는 날은 건너뛰고, 바뀐 게 있을 때만 보낸다. 그 주 첫 출근일엔 주간 요약도. */
function morningDigest() {
  if (!setting_('slackWebhook')) return;
  var today = ymd_(new Date());
  var holidays = holidays_();
  if (isOff_(today, holidays)) return;
  var text = digestText_(today, setting_('lastDigestAt'), holidays);
  if (text) postSlack_(text);
  setSetting_('lastDigestAt', now_());
}

function digestText_(today, since, holidays) {
  var parts = [];
  var changes = rows_('Log').filter(function (l) { return !since || l.at > since; });
  if (changes.length) {
    var groups = {}, order = [];
    changes.forEach(function (l) {
      var k = l.project || '공통';
      if (!groups[k]) { groups[k] = []; order.push(k); }
      groups[k].push('• ' + l.by + ' — ' + l.action + (l.detail ? ': ' + l.detail : ''));
    });
    parts.push('*📋 어제 이후 바뀐 내용 ' + changes.length + '건*\n' +
               order.map(function (k) { return '*' + k + '*\n' + groups[k].slice(0, 15).join('\n') +
                 (groups[k].length > 15 ? '\n• 외 ' + (groups[k].length - 15) + '건' : ''); }).join('\n\n'));
  }
  if (isFirstWorkdayOfWeek_(today, holidays)) parts.push(weeklyText_(today));
  return parts.join('\n\n');
}

function isFirstWorkdayOfWeek_(today, holidays) {
  var w = weekday_(today);
  var monday = addDays_(today, -((w + 6) % 7));
  for (var d = monday; d < today; d = addDays_(d, 1)) if (!isOff_(d, holidays)) return false;
  return true;
}

function progress_(tasks) {
  if (!tasks.length) return null;
  return Math.round(100 * tasks.filter(function (t) { return isTrue_(t.done); }).length / tasks.length);
}

function weeklyText_(today) {
  var w = weekday_(today);
  var monday = addDays_(today, -((w + 6) % 7)), sunday = addDays_(monday, 6), lastMonday = addDays_(monday, -7);
  var projects = rows_('Projects').filter(function (p) { return !isTrue_(p.deleted) && p.status === '진행'; });
  var phases = rows_('Phases'), tasks = rows_('Tasks'), costs = rows_('Costs');
  var lines = ['*🗓 주간 요약 (' + md_(monday) + '~' + md_(sunday) + ')*'];
  if (!projects.length) lines.push('진행 중인 프로젝트가 없어요.');
  projects.forEach(function (p) {
    var pt = tasks.filter(function (t) { return t.projectId === p.id; });
    var pr = progress_(pt);
    var line = '• *' + p.name + '* ' + (pr === null ? '' : pr + '% ') + (p.end ? '(마감 ' + md_(p.end) + ')' : '');
    var due = phases.filter(function (ph) { return ph.projectId === p.id && ph.end >= monday && ph.end <= sunday; })
      .map(function (ph) { return "'" + ph.name + "' " + md_(ph.end) + ' 마감'; });
    var open = pt.filter(function (t) { return !isTrue_(t.done) && t.due && t.due <= sunday; });
    var late = open.filter(function (t) { return t.due < today; }).length;
    if (due.length) line += '\n    이번 주: ' + due.join(', ');
    if (open.length) line += '\n    기한 이번 주까지 남은 할 일 ' + open.length + '개' + (late ? ' (지난 것 ' + late + '개)' : '');
    lines.push(line);
  });
  var lastWeek = costs.filter(function (c) { return c.at >= lastMonday && c.at < monday; });
  if (lastWeek.length) {
    var sum = lastWeek.reduce(function (a, c) { return a + (Number(c.amount) || 0); }, 0);
    lines.push('• 지난주 올라온 비용·문서 ' + lastWeek.length + '건' + (sum ? ', 합계 ' + won_(sum) : ''));
  }
  return lines.join('\n');
}
