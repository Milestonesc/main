// 미리보기 만들기: node dev/build-preview.js <라이브러리 폴더>
// Index.html + Code.gs + mock.js 를 한 페이지로 묶어, 구글 없이 브라우저에서 앱을 돌려 본다.
const fs = require('fs');
const path = require('path');
const libs = process.argv[2];
const out = path.join(__dirname, 'out');
fs.mkdirSync(out, { recursive: true });
fs.copyFileSync(path.join(libs, 'fullcalendar-6.1.15/index.global.min.js'), path.join(out, 'fullcalendar.js'));
fs.copyFileSync(path.join(libs, 'xlsx-0.18.5/dist/xlsx.full.min.js'), path.join(out, 'xlsx.js'));
fs.copyFileSync(path.join(__dirname, 'mock.js'), path.join(out, 'mock.js'));
// 서버 코드는 화면 코드와 함수 이름이 겹치므로(addTask 등) 따로 감싼다
const code = fs.readFileSync(path.join(__dirname, '../apps-script/Code.gs'), 'utf8');
const names = [...code.matchAll(/^function (\w+)/gm)].map((m) => m[1]);
fs.writeFileSync(path.join(out, 'code.js'), 'window.SERVER = (function () {\n' + code + '\nreturn {' + names.map((n) => n + ': ' + n).join(', ') + '};\n})();');

const shim = `
<script src="mock.js"></script>
<script>
  var __store = installAppsScriptMocks(window, { now: (new URLSearchParams(location.search).get('now')) || undefined, holidays: [
    { date: '2026-10-03', name: '개천절' }, { date: '2026-10-05', name: '개천절 대체 휴일' }, { date: '2026-10-09', name: '한글날' },
    { date: '2026-09-24', name: '추석 전날' }, { date: '2026-09-25', name: '추석' }, { date: '2026-09-26', name: '추석 다음날' },
    { date: '2026-11-11', name: '빼빼로데이', off: false }, { date: '2026-12-25', name: '기독탄신일' }] });
</script>
<script src="code.js"></script>
<script>
  SERVER.setup(); // 미리보기는 새로고침하면 처음부터 다시 시작한다
  // google.script.run 흉내: 비동기, 값은 JSON으로 오간다(실제와 같이 Date·함수는 못 넘긴다)
  window.google = { script: { run: (function make(ok, fail) {
    return new Proxy({}, { get: function (_, name) {
      if (name === 'withSuccessHandler') return function (f) { return make(f, fail); };
      if (name === 'withFailureHandler') return function (f) { return make(ok, f); };
      return function () { var args = JSON.parse(JSON.stringify(Array.prototype.slice.call(arguments)));
        setTimeout(function () { try { var v = SERVER[name].apply(null, args); v = v === undefined ? null : JSON.parse(JSON.stringify(v)); ok && ok(v); }
          catch (e) { console.warn(e); fail && fail({ message: e.message }); } }, 60); }; } }); })() } };
</script>`;
let html = fs.readFileSync(path.join(__dirname, '../apps-script/Index.html'), 'utf8');
html = html.replace('https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/index.global.min.js', 'fullcalendar.js')
  .replace('https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js', 'xlsx.js')
  .replace('<script src="fullcalendar.js">', shim + '\n<script src="fullcalendar.js">');
fs.writeFileSync(path.join(out, 'index.html'), html);
console.log('미리보기:', path.join(out, 'index.html'));
