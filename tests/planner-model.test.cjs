const test=require('node:test');
const assert=require('node:assert/strict');
const M=require('../web/planner-model.js');
test('project choices come from saved cards and colors are stable for arbitrary names',()=>{
  const cards=[{project:'Example B'},{project:'Example A'},{project:'Example B'}],before=JSON.stringify(cards);
  assert.deepEqual(M.projects(cards),['Example A','Example B']);
  assert.deepEqual(M.projects([]),[]);
  assert.deepEqual(M.projectColor('Example A'),M.projectColor('Example A'));
  assert.ok(M.projectColor('A new project').every(c=>/^#[a-f0-9]{6}$/.test(c)));
  assert.equal(JSON.stringify(cards),before);
});
test('week dates cross month and year boundaries without local timezone drift',()=>{
  assert.deepEqual(M.dates('2026-12-28'),['2026-12-28','2026-12-29','2026-12-30','2026-12-31','2027-01-01','2027-01-02','2027-01-03']);
});
test('back-to-back blocks do not conflict; day-only cards are excluded',()=>{
  const a={minutes:60,placement:{date:'2026-11-02',start_minute:600}};
  const b={minutes:60,placement:{date:'2026-11-02',start_minute:660}};
  assert.equal(M.conflicts([a,b,{minutes:60,placement:{date:'2026-11-02',start_minute:null}}]).length,0);
  b.placement.start_minute=645;assert.equal(M.conflicts([a,b]).length,1);
});
test('drop snaps and clamps to avoid negative or next-day placement',()=>{
  assert.equal(M.dropMinute(32,1024,420,1380,60),450);
  assert.equal(M.dropMinute(9999,1024,420,1380,120),1260);
  assert.equal(M.dropMinute(-9999,1024,420,1380,120),420);
});

test('preview spans the entire duration and uses 15-minute snapping',()=>{
  assert.deepEqual(M.dropRange(208,896,420,1380,90),{start:645,end:735});
  assert.deepEqual(M.dropRange(222,896,420,1380,90),{start:660,end:750});
});
test('moving a scheduled card preserves where it was grabbed',()=>{
  assert.deepEqual(M.dropRange(240,960,420,1380,90,30),{start:630,end:720});
});
test('long drop preview remains fully inside the visible grid at both edges',()=>{
  assert.deepEqual(M.dropRange(950,960,420,1380,180),{start:1200,end:1380});
  assert.deepEqual(M.dropRange(-20,960,420,1380,180,30),{start:420,end:600});
});

test('resizing snaps duration while preserving its start and limits',()=>{
  assert.equal(M.resizeMinutes(60,28,56/60,600),90);
  assert.equal(M.resizeMinutes(60,-999,1,600),15);
  assert.equal(M.resizeMinutes(60,9999,1,600),720);
  assert.equal(M.resizeMinutes(30,999,1,1410),30);
  assert.equal(M.resizeMinutes(30,999,1,1350,1380),30);
});
