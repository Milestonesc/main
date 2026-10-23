// 서버 코드(Code.gs) 시험: node dev/test.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert0 = require('assert/strict');
// vm 안에서 만든 배열은 프로토타입이 달라서 JSON으로 풀어 비교한다
const plain = (v) => JSON.parse(JSON.stringify(v));
const assert = Object.assign(Object.create(assert0), { deepEqual: (a, b, m) => assert0.deepEqual(plain(a), plain(b), m) });
const install = require('./mock.js');

const HOLIDAYS = [
  { date: '2026-10-03', name: '개천절' }, { date: '2026-10-05', name: '개천절 대체 휴일' },
  { date: '2026-10-09', name: '한글날' }, { date: '2026-05-08', name: '어버이날', off: false },
  { date: '2026-09-24', name: '추석 전날' }, { date: '2026-09-25', name: '추석' }, { date: '2026-09-26', name: '추석 다음날' }
];
const CODE = fs.readFileSync(path.join(__dirname, '../apps-script/Code.gs'), 'utf8');

function fresh(now = '2026-10-20T10:00:00+09:00', maxRows) {
  const ctx = { console, Intl, Math, JSON, Array, Object, String, Number, Boolean, Error, RegExp, isNaN, Buffer, encodeURIComponent };
  vm.createContext(ctx);
  ctx.Date = Date;
  const store = install(ctx, { now, holidays: HOLIDAYS, maxRows });
  vm.runInContext(CODE, ctx);
  ctx.setup();
  ctx.saveMembers(null, ['김민수', '이지은', '박준호']);
  return { g: ctx, store, a: { name: '김민수', pass: '' }, b: { name: '이지은', pass: '' } };
}

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('setup은 여러 번 해도 안전하다', () => {
  const { g, store } = fresh();
  const sheet = store.props.SHEET_ID;
  g.setup(); g.setup();
  assert.equal(store.props.SHEET_ID, sheet);
  assert.equal(store.triggers.filter((t) => t.getHandlerFunction() === 'morningDigest').length, 1);
  assert.equal(store.triggers[0].hour, 9);
});

test('로그인: 목록에 없는 이름과 틀린 비밀번호는 막는다', () => {
  const { g, a } = fresh();
  assert.throws(() => g.getData({ name: '모르는사람' }), /이름/);
  g.saveSettings(a, { teamPassword: '1234' });
  assert.throws(() => g.getData(a), /비밀번호/);
  assert.equal(g.getData({ name: '김민수', pass: '1234' }).me, '김민수');
  assert.equal(g.getLoginInfo().needPassword, true);
});

test('프로젝트·단계 만들기 → 캘린더 일정 + 기록', () => {
  const { g, store, a } = fresh();
  const id = g.saveProject(a, { name: 'A사 리뉴얼', client: 'A사', start: '2026-10-01', end: '2026-11-30', members: '김민수, 이지은',
    phases: [{ name: '기획', start: '2026-10-01', end: '2026-10-10' }, { name: '디자인', start: '2026-10-13', end: '2026-10-31' }] });
  const d = g.getData(a);
  assert.equal(d.projects.length, 1);
  assert.deepEqual(d.phases.map((x) => x.name), ['기획', '디자인']);
  const cal = store.calendars[store.props.CALENDAR_ID];
  assert.deepEqual(cal.events.map((e) => e.title).sort(), ['[A사 리뉴얼] 기획', '[A사 리뉴얼] 디자인']);
  const design = cal.events.find((e) => e.title.endsWith('디자인'));
  assert.equal(design.s.getDate(), 13);
  assert.equal(design.e.getMonth(), 10); assert.equal(design.e.getDate(), 1); // 끝 다음날(11/1)
  assert.equal(d.log[0].action, '새 프로젝트');
  assert.equal(d.log[0].project, 'A사 리뉴얼');
  assert.ok(!('eventId' in d.phases[0]));
  return id;
});

test('단계 기간 변경·이름 변경·삭제가 기록되고 캘린더도 따라간다', () => {
  const { g, store, a } = fresh();
  const id = g.saveProject(a, { name: 'P', phases: [{ name: '기획', start: '2026-10-01', end: '2026-10-10' }, { name: '개발', start: '2026-10-11', end: '2026-10-20' }] });
  let d = g.getData(a);
  const [p1, p2] = d.phases;
  g.addTask(a, { projectId: id, phaseId: p2.id, text: '서버 세팅' });
  g.saveProject(a, { id, name: 'P', phases: [{ id: p1.id, name: '기획·조사', start: '2026-10-01', end: '2026-10-14' }] });
  d = g.getData(a);
  const log = d.log[0];
  assert.equal(log.action, '프로젝트 수정');
  assert.match(log.detail, /단계 이름 '기획' → '기획·조사'/);
  assert.match(log.detail, /'기획·조사' 기간 10\/1~10\/10 → 10\/1~10\/14/);
  assert.match(log.detail, /단계 삭제 '개발'/);
  assert.equal(d.tasks[0].phaseId, '', '지운 단계의 할 일은 단계 없음으로');
  const cal = store.calendars[store.props.CALENDAR_ID];
  assert.deepEqual(cal.events.map((e) => e.title), ['[P] 기획·조사']);
});

test('단계 없는 프로젝트는 프로젝트 기간 하나로, 단계가 생기면 바뀐다', () => {
  const { g, store, a } = fresh();
  const id = g.saveProject(a, { name: 'Q', start: '2026-10-05', end: '2026-10-07' });
  const cal = store.calendars[store.props.CALENDAR_ID];
  assert.deepEqual(cal.events.map((e) => e.title), ['[Q]']);
  g.saveProject(a, { id, name: 'Q', phases: [{ name: '촬영', start: '2026-10-06', end: '2026-10-06' }] });
  assert.deepEqual(cal.events.map((e) => e.title), ['[Q] 촬영']);
  g.deleteProject(a, id);
  assert.equal(cal.events.length, 0);
  assert.equal(g.getData(a).projects.length, 0);
});

test('할 일 체크·수정·삭제와 진행 기록', () => {
  const { g, a, b } = fresh();
  const id = g.saveProject(a, { name: 'P', phases: [{ name: '기획' }] });
  const ph = g.getData(a).phases[0];
  const t1 = g.addTask(a, { projectId: id, phaseId: ph.id, text: '요구사항 정리', assignee: '이지은', due: '2026-10-22' });
  g.addTask(a, { projectId: id, phaseId: ph.id, text: '견적 요청' });
  g.updateTask(b, t1, { done: true });
  let d = g.getData(a);
  const t = d.tasks.find((x) => x.id === t1);
  assert.equal(t.done, true); assert.equal(t.doneBy, '이지은');
  assert.equal(d.log[0].action, '완료 체크'); assert.equal(d.log[0].by, '이지은');
  g.updateTask(a, t1, { due: '2026-10-24', assignee: '박준호' });
  d = g.getData(a);
  assert.match(d.log[0].detail, /담당 이지은 → 박준호, 기한 10\/22 → 10\/24/);
  g.deleteTask(a, t1);
  assert.equal(g.getData(a).tasks.length, 1);
  assert.throws(() => g.addTask(a, { projectId: id, text: '  ' }), /할 일/);
});

test('비용·문서: 파일 올리기, 증빙 없는 실비, 내려받기, 삭제', () => {
  const { g, store, a } = fresh();
  const id = g.saveProject(a, { name: 'P' });
  const data = Buffer.from('%PDF-1.4 견적').toString('base64');
  const c1 = g.addCost(a, { projectId: id, kind: '견적서', date: '2026-10-20', title: '현수막', amount: '1,200,000', vendor: '애드몰',
    file: { name: '견적서.pdf', mimeType: 'application/pdf', data } });
  g.addCost(a, { projectId: id, kind: '실비', title: '퀵 배송', amount: '18000' });
  assert.throws(() => g.addCost(a, { projectId: id, kind: '기타' }), /파일을 올리거나/);
  let d = g.getData(a);
  assert.equal(d.costs.length, 2);
  const cost = d.costs.find((c) => c.id === c1);
  assert.equal(cost.amount, '1200000');
  assert.equal(cost.fileName, '견적서.pdf');
  const file = store.files[cost.fileId];
  assert.equal(file.name, '2026-10-20_견적서_견적서.pdf');
  const proj = d.projects[0];
  assert.equal(store.folders[file.parent].name, 'P');
  assert.equal(store.folders[file.parent].parent, store.props.ROOT_FOLDER_ID);
  assert.equal(proj.folderId, file.parent);
  const back = g.getFile(a, c1);
  assert.equal(Buffer.from(back.data, 'base64').toString(), '%PDF-1.4 견적');
  assert.match(d.log[1].detail, /견적서 현수막 1,200,000원 📎/);
  g.deleteCost(a, c1);
  assert.equal(file.trashed, true);
  assert.equal(g.getData(a).costs.length, 1);
});

test('댓글', () => {
  const { g, a } = fresh();
  const id = g.saveProject(a, { name: 'P' });
  g.addComment(a, id, '고객사 미팅 11/3로 변경');
  const d = g.getData(a);
  assert.equal(d.comments[0].text, '고객사 미팅 11/3로 변경');
  assert.equal(d.log[0].action, '댓글');
});

test('공휴일: 공휴일과 기념일을 구분한다', () => {
  const { g, a } = fresh();
  const h = g.getData(a).holidays;
  assert.equal(h.find((x) => x.date === '2026-10-09').off, true);
  assert.equal(h.find((x) => x.date === '2026-05-08').off, false);
});

test('아침 알림: 바뀐 게 있을 때만, 쉬는 날은 건너뛴다', () => {
  const { g, store, a } = fresh('2026-10-21T09:00:00+09:00'); // 수요일
  g.saveSettings(a, { slackWebhook: 'https://hooks.slack.com/services/T/B/x' });
  g.morningDigest();
  assert.equal(store.fetches.length, 1, '설정 변경도 바뀐 내용');
  assert.match(store.fetches[0].body.text, /바뀐 내용 2건/); // 직원 목록 + 슬랙 연결
  store.setNow('2026-10-22T09:00:00+09:00');
  g.morningDigest();
  assert.equal(store.fetches.length, 1, '바뀐 게 없으면 안 보낸다');
  const id = g.saveProject(a, { name: 'A사', phases: [{ name: '기획', start: '2026-10-01', end: '2026-10-10' }] });
  g.addTask(a, { projectId: id, text: '킥오프' });
  store.setNow('2026-10-24T09:00:00+09:00'); // 토요일
  g.morningDigest();
  assert.equal(store.fetches.length, 1, '주말은 건너뛴다');
  store.setNow('2026-10-09T09:00:00+09:00'); // 한글날
  g.morningDigest();
  assert.equal(store.fetches.length, 1, '공휴일은 건너뛴다');
});

test('주간 요약: 그 주 첫 출근일에 함께 보낸다 (월요일이 대체휴일이면 화요일)', () => {
  const { g, store, a } = fresh('2026-10-02T09:00:00+09:00');
  g.saveSettings(a, { slackWebhook: 'https://hooks.slack.com/services/T/B/x' });
  const id = g.saveProject(a, { name: 'A사', end: '2026-10-30', phases: [{ name: '디자인', start: '2026-10-01', end: '2026-10-08' }] });
  g.addTask(a, { projectId: id, text: '시안', due: '2026-10-07' });
  g.addCost(a, { projectId: id, kind: '실비', title: '택배', amount: '5000' });
  store.setNow('2026-10-05T09:00:00+09:00'); // 월요일 = 개천절 대체 휴일
  g.morningDigest();
  assert.equal(store.fetches.length, 0);
  store.setNow('2026-10-06T09:00:00+09:00'); // 화요일 = 그 주 첫 출근일
  g.morningDigest();
  assert.equal(store.fetches.length, 1);
  const text = store.fetches[0].body.text;
  assert.match(text, /바뀐 내용 5건/);
  assert.match(text, /\*A사\*/);
  assert.match(text, /주간 요약 \(10\/5~10\/11\)/);
  assert.match(text, /'디자인' 10\/8 마감/);
  assert.match(text, /기한 이번 주까지 남은 할 일 1개/);
  store.setNow('2026-10-07T09:00:00+09:00');
  g.addComment(a, id, '수요일 소식');
  g.morningDigest();
  assert.doesNotMatch(store.fetches[1].body.text, /주간 요약/);
});

test('주간 요약은 바뀐 게 없어도 보낸다', () => {
  const { g, store, a } = fresh('2026-10-16T09:00:00+09:00');
  g.saveSettings(a, { slackWebhook: 'https://hooks.slack.com/services/T/B/x' });
  g.saveProject(a, { name: 'A사' });
  g.morningDigest();
  store.setNow('2026-10-19T09:00:00+09:00'); // 월요일
  g.morningDigest();
  assert.equal(store.fetches.length, 2);
  assert.match(store.fetches[1].body.text, /주간 요약/);
  assert.doesNotMatch(store.fetches[1].body.text, /바뀐 내용/);
});

test('잘못된 슬랙 주소는 거절', () => {
  const { g, a } = fresh();
  assert.throws(() => g.saveSettings(a, { slackWebhook: 'https://example.com/x' }), /hooks.slack.com/);
});

test('직원 목록: 처음엔 로그인 없이, 그다음엔 로그인해서', () => {
  const { g, a } = fresh();
  assert.throws(() => g.saveMembers({ name: '외부인' }, ['x']), /이름/);
  g.saveMembers(a, ['김민수', '최수아']);
  assert.deepEqual(g.getLoginInfo().names, ['김민수', '최수아']);
  assert.match(g.getData(a).log[0].detail, /추가 최수아 \/ 빼기 이지은, 박준호/);
});

test('시트가 꽉 차면 행을 늘려서 계속 쓴다', () => {
  const { g, a } = fresh('2026-10-20T10:00:00+09:00', 6);
  const id = g.saveProject(a, { name: 'P' });
  for (let i = 0; i < 12; i++) g.addTask(a, { projectId: id, text: '할 일 ' + i });
  const d = g.getData(a);
  assert.equal(d.tasks.length, 12);
  assert.ok(d.log.length >= 13);
});

let failed = 0;
for (const [name, fn] of tests) {
  try { fn(); console.log('✓', name); } catch (e) { failed++; console.log('✗', name, '\n ', e.message); }
}
console.log(failed ? `\n${failed}개 실패` : `\n${tests.length}개 모두 통과`);
process.exit(failed ? 1 : 0);
