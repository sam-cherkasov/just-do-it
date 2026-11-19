const {test} = require('node:test');
const assert = require('node:assert/strict');
const {signature,canRefresh} = require('../web/workspace-refresh.js');
const base = {workstreams:[{id:'direction',revision:1}],tasks:[{id:'task',revision:1}],sessions:[],source_health:[],generated_at:'old',token:'old'};
test('clock and token refresh do not rebuild or interrupt a page', () => {
  assert.equal(signature(base),signature({...base,generated_at:'new',token:'new'}));
});
test('task, workstream, session and source changes become visible', () => {
  for(const changed of [
    {...base,tasks:[{id:'task',revision:2}]},
    {...base,workstreams:[{id:'direction',revision:2}]},
    {...base,sessions:[{id:'session',revision:1}]},
    {...base,day_choices:[{id:'day',revision:2}]},
    {...base,workspace_items:[{id:'thought',revision:1}]},
    {...base,today:'2026-11-05'},
    {...base,planners:[{id:'planner',revision:2}]},
    {...base,source_health:[{id:'source',state:'unavailable'}]}
  ]) assert.notEqual(signature(base),signature(changed));
});
test('item edits and archival refresh existing views', () => {
  const before={...base,workspace_items:[{id:'item',revision:1}]};
  assert.notEqual(signature(before),signature({...before,workspace_items:[{id:'item',revision:2}]}));
});
test('typing, modal, save, uncertain retry and background tab defer updates', () => {
  const idle={busy:false,pending:false,modalOpen:false,editing:false,hidden:false};
  assert.equal(canRefresh(idle),true);
  for(const key of Object.keys(idle))assert.equal(canRefresh({...idle,[key]:true}),false);
});
test('changing record order alone is not a content update', () => {
  const a={...base,tasks:[{id:'a',revision:1},{id:'b',revision:2}]};
  assert.equal(signature(a),signature({...a,tasks:[...a.tasks].reverse()}));
});
