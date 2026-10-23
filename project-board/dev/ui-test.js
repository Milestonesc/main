// 화면 시험: 미리보기를 띄운 뒤 node dev/ui-test.js <주소> <스크린샷 폴더>
const { chromium } = require('playwright');
const assert = require('assert/strict');
const url = process.argv[2] || 'http://localhost:8765/index.html';
const shots = process.argv[3] || '.';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ acceptDownloads: true, viewport: { width: 1360, height: 900 }, locale: 'ko-KR' });
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', (d) => d.accept());
  const idle = () => page.waitForFunction(() => document.getElementById('busy').classList.contains('hidden'));
  const shot = (n) => page.screenshot({ path: `${shots}/${n}.png` });

  await page.goto(url + '?now=2026-10-20T10:00:00%2B09:00');
  // 처음 실행: 직원 등록 → 이름 고르기
  await page.fill('#first-names', '김민수\n이지은\n박준호\n최수아');
  await shot('01-first-run');
  await page.click('text=시작하기');
  await page.click('.names button[data-name="김민수"]');
  await idle();
  await page.waitForSelector('#app:not(.hidden)');

  async function newProject(p) {
    await page.click('text=+ 새 프로젝트');
    await page.fill('#p-name', p.name);
    await page.fill('#p-client', p.client);
    await page.fill('#p-start', p.start);
    await page.fill('#p-end', p.end);
    for (const m of p.members) await page.check(`.p-mem[value="${m}"]`);
    if (p.color) await page.click(`#p-colors button:nth-child(${p.color})`);
    for (const [i, ph] of p.phases.entries()) {
      await page.click('text=+ 단계 추가');
      const row = page.locator('.phase-edit').nth(i);
      await row.locator('.ph-name').fill(ph[0]);
      await row.locator('.ph-start').fill(ph[1]);
      await row.locator('.ph-end').fill(ph[2]);
    }
    if (p.shot) await shot(p.shot);
    await page.click('#modal-save');
    await idle();
    await page.waitForSelector('.drawer');
  }
  async function addTask(phaseIdx, text, who, due) {
    const box = page.locator('.phase').nth(phaseIdx);
    await box.locator('input[type=text]').fill(text);
    if (who) await box.locator('select').selectOption(who);
    if (due) await box.locator('input[type=date]').fill(due);
    await box.locator('button', { hasText: '추가' }).click();
    await idle();
  }

  await newProject({ name: 'A사 홈페이지 리뉴얼', client: 'A사', start: '2026-10-01', end: '2026-11-27', members: ['이지은', '박준호'],
    phases: [['기획', '2026-10-01', '2026-10-14'], ['디자인', '2026-10-15', '2026-11-06'], ['개발', '2026-11-09', '2026-11-25'], ['납품', '2026-11-27', '2026-11-27']],
    shot: '02-new-project' });
  await addTask(0, '요구사항 정리', '김민수', '2026-10-08');
  await addTask(0, '사이트맵 확정', '이지은', '2026-10-14');
  await addTask(1, '메인 시안 3종', '이지은', '2026-10-23');
  await addTask(1, '고객사 시안 검토 미팅', '김민수', '2026-10-19');
  await addTask(1, '상세 페이지 디자인', '박준호', '2026-11-04');
  await addTask(2, '개발 서버 세팅', '박준호', '2026-11-10');
  await page.locator('.task', { hasText: '요구사항 정리' }).locator('input[type=checkbox]').check();
  await idle();
  await page.locator('.task', { hasText: '사이트맵 확정' }).locator('input[type=checkbox]').check();
  await idle();
  assert.match(await page.textContent('.drawer-head'), /진행률 33%/);
  await shot('03-project-tasks');

  // 비용·문서: 파일 올리기 + 증빙 없는 실비
  await page.click('.subtabs button:has-text("비용·문서")');
  await page.selectOption('#c-kind', '견적서');
  await page.fill('#c-vendor', '애드몰');
  await page.fill('#c-amount', '1,250,000');
  await page.setInputFiles('#c-file', { name: '현수막_견적서.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') });
  assert.equal(await page.inputValue('#c-title'), '현수막_견적서');
  await page.click('button:has-text("올리기")');
  await idle();
  await page.waitForSelector('table.grid td:has-text("현수막_견적서")');
  assert.equal(await page.inputValue('#c-vendor'), '', '올린 뒤 입력란은 비워진다');
  await page.selectOption('#c-kind', '실비');
  await page.fill('#c-title', '샘플 퀵 배송');
  await page.fill('#c-amount', '18000');
  await page.click('button:has-text("올리기")');
  await idle();
  await page.waitForSelector('table.grid td:has-text("샘플 퀵 배송")');
  assert.match(await page.textContent('.drawer-body'), /합계 1,268,000원/);
  assert.match(await page.textContent('table.grid tr:has-text("샘플 퀵 배송")'), /증빙 없음/);
  await shot('04-project-costs');

  // 댓글
  await page.click('.subtabs button:has-text("댓글")');
  await page.fill('#cm', '고객사 미팅 10/19(월) 2시로 확정. 시안 3종 준비 부탁해요.');
  await page.click('.drawer-body button:has-text("올리기")');
  await idle();
  await page.waitForSelector('.comment');
  await page.click('.subtabs button:has-text("기록")');
  await shot('05-project-log');
  await page.click('.drawer-head button:has-text("✕")');

  await newProject({ name: 'B사 제품 촬영', client: 'B사', start: '2026-10-19', end: '2026-10-30', members: ['최수아'], color: 3,
    phases: [['섭외·준비', '2026-10-19', '2026-10-23'], ['촬영', '2026-10-26', '2026-10-27'], ['보정·전달', '2026-10-28', '2026-10-30']] });
  await addTask(0, '스튜디오 예약', '최수아', '2026-10-21');
  await addTask(0, '소품 구매', '김민수', '2026-10-22');
  await page.click('.drawer-head button:has-text("✕")');
  await newProject({ name: '사내 브로슈어', client: '', start: '2026-11-02', end: '2026-11-20', members: ['박준호'], color: 5, phases: [] });
  await page.click('.drawer-head button:has-text("✕")');

  // 화면마다
  await page.click('nav button:has-text("달력")');
  await page.waitForSelector('.fc-event');
  assert.match(await page.textContent('#calendar'), /한글날/);
  await shot('06-calendar');
  await page.click('nav button:has-text("타임라인")');
  await shot('07-timeline');
  await page.click('nav button:has-text("프로젝트")');
  await shot('08-projects');
  await page.click('nav button:has-text("내 할 일")');
  assert.match(await page.textContent('#view'), /지난 기한 · 1/);
  await shot('09-mine');
  await page.click('nav button:has-text("비용·문서")');
  assert.match(await page.textContent('#view'), /2건/);
  const dl = page.waitForEvent('download');
  await page.click('button:has-text("⬇ 전체 엑셀")');
  // 시험용 헤드리스 브라우저는 한글 파일 이름을 'download'로 바꿔 보고하므로 내용으로 확인한다
  const file = await (await dl).path();
  const XLSX = require(process.env.XLSX_LIB);
  const wb = XLSX.readFile(file);
  assert.deepEqual(wb.SheetNames, ['프로젝트', '단계', '할 일', '비용·문서']);
  const rows = XLSX.utils.sheet_to_json(wb.Sheets['비용·문서']);
  assert.equal(rows.length, 2);
  assert.equal(rows.reduce((a, r) => a + (r['금액'] || 0), 0), 1268000);
  assert.equal(XLSX.utils.sheet_to_json(wb.Sheets['프로젝트']).find((r) => r['프로젝트'] === 'A사 홈페이지 리뉴얼')['진행률'], '33%');
  await shot('10-costs');
  await page.click('nav button:has-text("기록")');
  await shot('11-log');
  await page.click('button[title="설정"]');
  await shot('12-settings');
  await page.click('#modal-wrap button:has-text("취소")');

  // 진행률이 할 일 수정·단계 변경 후에도 맞는지
  await page.click('nav button:has-text("프로젝트")');
  await page.click('.pcard:has-text("A사")');
  await page.click('.subtabs button:has-text("단계·할 일")');
  await page.click('.drawer-head button:has-text("✎ 수정")');
  await page.locator('.phase-edit').nth(1).locator('.ph-end').fill('2026-11-13');
  await page.click('#modal-save');
  await idle();
  await page.click('.subtabs button:has-text("기록")');
  assert.match(await page.textContent('.drawer-body'), /'디자인' 기간 10\/15~11\/6 → 10\/15~11\/13/);

  // 좁은 화면
  await page.setViewportSize({ width: 390, height: 844 });
  await page.click('.drawer-head button:has-text("✕")');
  await page.click('nav button:has-text("프로젝트")');
  await shot('13-narrow');

  console.log(errors.length ? '콘솔 오류:\n' + errors.join('\n') : '콘솔 오류 없음');
  await browser.close();
  if (errors.length) process.exit(1);
  console.log('화면 시험 통과');
})().catch((e) => { console.error(e); process.exit(1); });
