const test=require('node:test');
const assert=require('node:assert/strict');
const model=require('../web/today-model.js');
const task=(id,extra={})=>({id,revision:1,data:{title:id,status:'ready',...extra}});
function fixture(){return {today:'2026-11-04',tasks:[task('plain'),task('planned'),task('waiting',{status:'waiting'}),task('later',{deferred:true}),task('done',{status:'done'})],workstreams:[],sessions:[],relationships:{cards:[{task_id:'planned',selected:true,placement:{date:'2026-11-04'}}]},day_choices:[]};}
test('available candidates exclude waiting, later and closed with honest reasons',()=>{
  const state=fixture(),before=JSON.stringify(state),candidates=model.candidates(state);
  assert.deepEqual(candidates.map(c=>c.task.id),['planned','plain']);
  assert.match(candidates[0].reasons.join(' '),/плане на сегодня/);
  assert.match(candidates[1].reasons.join(' '),/без направления/);
  assert.equal(JSON.stringify(state),before);
});
test('an earlier weekly placement is not todays commitment',()=>{
  const state=fixture();state.relationships.cards[0].placement.date='2026-11-02';
  assert.ok(model.candidates(state).every(c=>!c.reasons.join(' ').includes('плане на сегодня')));
});
test('a previous day choice is never silently carried forward',()=>{
  const state=fixture();state.day_choices=[{id:'old',data:{date:'2026-11-03',status:'selected'}}];
  assert.equal(model.choice(state),undefined);
  state.day_choices.push({id:'today',data:{date:state.today,status:'cleared'}});
  assert.equal(model.choice(state).data.status,'cleared');
});
test('manual correction suppresses stale question as recommendation reason',()=>{
  const state=fixture();state.workstreams=[{id:'stream',data:{title:'Test',task_ids:['plain'],questions:[{task_id:'plain',text:'Old question'}]}}];
  state.tasks[0].data.user_control={fields:['title','next_action']};
  assert.ok(!model.candidates(state).find(c=>c.task.id==='plain').reasons.join(' ').includes('вопрос'));
});
test('defer remains a choice after its review date, not automatic activation',()=>{
  assert.equal(model.bucket(task('later',{deferred:true,deferred_until:'2026-11-01'})),'later');
  assert.equal(model.bucket(task('done',{status:'done',deferred:true})),'closed');
});
test('week range is deterministic across month/year boundaries',()=>{
  assert.equal(model.weekEnd('2026-12-28'),'2027-01-03');
});
test('paused directions do not appear as Today suggestions',()=>{
  const state=fixture();state.workstreams=[{id:'paused',data:{status:'paused',task_ids:['planned']}}];
  assert.deepEqual(model.candidates(state).map(c=>c.task.id),['plain']);
});
