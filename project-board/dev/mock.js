/* 개발·시험용: 구글 앱스 스크립트 서비스를 메모리에서 흉내 낸다. 노드와 브라우저 둘 다에서 쓴다. */
(function (root) {
  function install(g, opts) {
    opts = opts || {};
    var store = { files: {}, folders: {}, sheets: {}, calendars: {}, props: {}, cache: {}, fetches: [], triggers: [], n: 0 };
    var id = function (p) { return p + (++store.n); };
    var RealDate = g.Date;
    var fixed = opts.now ? new RealDate(opts.now).getTime() : null;
    function FakeDate() {
      if (!(this instanceof FakeDate)) return new RealDate(fixed === null ? RealDate.now() : fixed).toString();
      var a = Array.prototype.slice.call(arguments);
      if (!a.length) return new RealDate(fixed === null ? RealDate.now() : fixed);
      return new (Function.prototype.bind.apply(RealDate, [null].concat(a)))();
    }
    FakeDate.prototype = RealDate.prototype;
    FakeDate.now = function () { return fixed === null ? RealDate.now() : fixed; };
    FakeDate.UTC = RealDate.UTC; FakeDate.parse = RealDate.parse;
    g.Date = FakeDate;
    store.setNow = function (iso) { fixed = new RealDate(iso).getTime(); };

    // ── Spreadsheet ──
    function Sheet(name) { this.name = name; this.data = [[]]; this.frozen = 0; this.maxRows = opts.maxRows || 1000; }
    Sheet.prototype = {
      getName: function () { return this.name; },
      width: function () { return Math.max.apply(null, this.data.map(function (r) { return r.length; }).concat([1])); },
      getDataRange: function () { var s = this; return { getValues: function () {
        var w = s.width(); var rows = s.data.length && s.data[0].length ? s.data : [];
        return rows.map(function (r) { var c = r.slice(); while (c.length < w) c.push(''); return c; }); } }; },
      getRange: function (r, c, nr, nc) {
        var s = this; nr = nr || 1; nc = nc || 1;
        var api = {
          setValues: function (v) { if (r + nr - 1 > s.maxRows) throw new Error('범위가 시트 크기를 넘어요'); for (var i = 0; i < nr; i++) { while (s.data.length < r + i) s.data.push([]); var row = s.data[r - 1 + i];
            for (var j = 0; j < nc; j++) row[c - 1 + j] = v[i][j]; } return api; },
          getValues: function () { var out = []; for (var i = 0; i < nr; i++) { var row = s.data[r - 1 + i] || []; var o = [];
            for (var j = 0; j < nc; j++) o.push(row[c - 1 + j] === undefined ? '' : row[c - 1 + j]); out.push(o); } return out; },
          setFontWeight: function () { return api; }, setNumberFormat: function () { return api; }
        };
        return api;
      },
      appendRow: function (row) { if (this.data.length === 1 && !this.data[0].length) this.data[0] = row.slice(); else this.data.push(row.slice()); },
      deleteRow: function (r) { this.data.splice(r - 1, 1); },
      setFrozenRows: function (n) { this.frozen = n; }, getMaxRows: function () { return this.maxRows; },
      insertRowsAfter: function (after, n) { this.maxRows += n; },
      getLastRow: function () { return this.data.length === 1 && !this.data[0].length ? 0 : this.data.length; }
    };
    function Spreadsheet(name) { this.id = id('ss'); this.name = name; this.sheets = [new Sheet('Sheet1')]; store.sheets[this.id] = this;
      store.files[this.id] = { id: this.id, name: name, parent: null }; }
    Spreadsheet.prototype = {
      getId: function () { return this.id; }, getUrl: function () { return 'https://docs.google.com/spreadsheets/d/' + this.id; },
      getSheetByName: function (n) { return this.sheets.filter(function (s) { return s.name === n; })[0] || null; },
      insertSheet: function (n) { var s = new Sheet(n); this.sheets.push(s); return s; },
      deleteSheet: function (s) { this.sheets.splice(this.sheets.indexOf(s), 1); }, getSheets: function () { return this.sheets.slice(); }
    };
    g.SpreadsheetApp = {
      create: function (n) { return new Spreadsheet(n); },
      openById: function (i) { if (!store.sheets[i]) throw new Error('no sheet ' + i); return store.sheets[i]; }
    };

    // ── Drive ──
    function blob(bytes, type, name) {
      return { bytes: bytes, type: type, name: name, getBytes: function () { return this.bytes; }, getContentType: function () { return this.type; },
               getName: function () { return this.name; } };
    }
    function File(b, parent) { this.id = id('file'); this.blob = b; this.name = b.name; this.parent = parent; this.trashed = false; store.files[this.id] = this; }
    File.prototype = {
      getId: function () { return this.id; }, setName: function (n) { this.name = n; return this; }, getName: function () { return this.name; },
      getBlob: function () { return blob(this.blob.bytes, this.blob.type, this.name); }, setTrashed: function (t) { this.trashed = t; return this; },
      moveTo: function (f) { this.parent = f.id; return this; }
    };
    function Folder(name, parent) { this.id = id('folder'); this.name = name; this.parent = parent; store.folders[this.id] = this; }
    Folder.prototype = {
      getId: function () { return this.id; }, getUrl: function () { return 'https://drive.google.com/drive/folders/' + this.id; },
      createFolder: function (n) { return new Folder(n, this.id); }, createFile: function (b) { return new File(b, this.id); },
      getName: function () { return this.name; }
    };
    g.DriveApp = {
      createFolder: function (n) { return new Folder(n, null); },
      getFolderById: function (i) { if (!store.folders[i]) throw new Error('no folder'); return store.folders[i]; },
      getFileById: function (i) {
        var f = store.files[i]; if (!f) throw new Error('no file');
        if (!(f instanceof File)) f.moveTo = function (folder) { f.parent = folder.id; };
        return f;
      }
    };

    // ── Calendar ──
    function Ev(title, s, e, o) { this.id = id('ev') + '@google.com'; this.title = title; this.s = s; this.e = e; this.desc = (o && o.description) || ''; }
    Ev.prototype = {
      getId: function () { return this.id; }, getTitle: function () { return this.title; }, setTitle: function (t) { this.title = t; },
      setAllDayDates: function (s, e) { this.s = s; this.e = e; }, setDescription: function (d) { this.desc = d; },
      getDescription: function () { return this.desc; }, getAllDayStartDate: function () { return this.s; }
    };
    function Cal(cid, name) { this.id = cid; this.name = name; this.events = []; store.calendars[cid] = this; }
    Cal.prototype = {
      getId: function () { return this.id; },
      createAllDayEvent: function (t, s, e, o) { var ev = new Ev(t, s, e, o); this.events.push(ev); return ev; },
      getEventById: function (i) { return this.events.filter(function (e) { return e.id === i; })[0] || null; },
      getEvents: function (s, e) { return this.events.filter(function (ev) { return ev.s < e && ev.e > s; }); }
    };
    Ev.prototype.deleteEvent = function () { var self = this; Object.keys(store.calendars).forEach(function (k) {
      var c = store.calendars[k]; c.events = c.events.filter(function (x) { return x !== self; }); }); };
    var hol = new Cal('ko.south_korea#holiday@group.v.calendar.google.com', '대한민국의 휴일');
    (opts.holidays || []).forEach(function (h) {
      var p = h.date.split('-').map(Number), s = new RealDate(p[0], p[1] - 1, p[2]), e = new RealDate(p[0], p[1] - 1, p[2] + 1);
      hol.createAllDayEvent(h.name, s, e, { description: h.off === false ? '기념일\n기념일을 숨기려면…' : '공휴일' });
    });
    g.CalendarApp = {
      Color: { BLUE: 'blue' },
      createCalendar: function (n) { return new Cal(id('cal') + '@group.calendar.google.com', n); },
      getCalendarById: function (i) { return store.calendars[i] || null; },
      subscribeToCalendar: function () {}
    };

    // ── 그 밖 ──
    g.PropertiesService = { getScriptProperties: function () { return {
      getProperty: function (k) { return store.props[k] || null; }, setProperty: function (k, v) { store.props[k] = v; } }; } };
    g.CacheService = { getScriptCache: function () { return {
      get: function (k) { return store.cache[k] || null; }, put: function (k, v) { store.cache[k] = v; } }; } };
    g.LockService = { getScriptLock: function () { return { waitLock: function () {}, releaseLock: function () {} }; } };
    g.Session = { getScriptTimeZone: function () { return 'Asia/Seoul'; } };
    g.HtmlService = { createHtmlOutputFromFile: function () { var o = { setTitle: function () { return o; }, addMetaTag: function () { return o; } }; return o; } };
    var trig = function (fn) { var t = { getHandlerFunction: function () { return fn; } }; return t; };
    g.ScriptApp = {
      getProjectTriggers: function () { return store.triggers.slice(); },
      deleteTrigger: function (t) { store.triggers.splice(store.triggers.indexOf(t), 1); },
      newTrigger: function (fn) { var b = { timeBased: function () { return b; }, everyDays: function () { return b; }, atHour: function (h) { b.hour = h; return b; },
        nearMinute: function () { return b; }, inTimezone: function () { return b; }, create: function () { var t = trig(fn); t.hour = b.hour; store.triggers.push(t); return t; } }; return b; }
    };
    g.UrlFetchApp = { fetch: function (url, o) { store.fetches.push({ url: url, body: JSON.parse(o.payload) });
      return { getResponseCode: function () { return 200; }, getContentText: function () { return 'ok'; } }; } };

    var b64enc = function (bytes) { if (typeof Buffer !== 'undefined') return Buffer.from(bytes).toString('base64');
      var s = ''; for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i] & 255); return btoa(s); };
    var b64dec = function (str) { if (typeof Buffer !== 'undefined') return Array.from(Buffer.from(str, 'base64'));
      var s = atob(str), a = []; for (var i = 0; i < s.length; i++) a.push(s.charCodeAt(i)); return a; };
    g.Utilities = {
      getUuid: function () { return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function () { return (Math.random() * 16 | 0).toString(16); }); },
      newBlob: blob, base64Decode: b64dec, base64Encode: b64enc,
      formatDate: function (d, tz, fmt) {
        var parts = {}; new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit',
          minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).formatToParts(d).forEach(function (p) { parts[p.type] = p.value; });
        return fmt.replace(/'([^']*)'/g, '\u0001$1\u0002').replace(/yyyy|MM|dd|HH|mm|ss/g, function (k) {
          return { yyyy: parts.year, MM: parts.month, dd: parts.day, HH: parts.hour, mm: parts.minute, ss: parts.second }[k]; })
          .replace(/\u0001([^\u0002]*)\u0002/g, '$1');
      }
    };
    return store;
  }
  if (typeof module !== 'undefined') module.exports = install; else root.installAppsScriptMocks = install;
})(this);
