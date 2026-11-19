const test = require('node:test');
const assert = require('node:assert/strict');
const {performance} = require('node:perf_hooks');
const model = require('../web/life-graph-model.js');

const node = (id, type, parents = [], extra = {}) => ({id, kind: 'node', updated_at: '2026-10-24T10:00:00Z', data: {title: id, type, parents, status: 'active', ...extra}});
const task = (id, parents, extra = {}) => ({id, kind: 'task', stale: true, updated_at: '2026-10-24T10:00:00Z', data: {title: 'Задача ' + id, parents, status: 'candidate', priority: 'primary', intent: 'proposed', next_action: 'Уточнить вопрос', ...extra}});
function fixture() {
  return {records: [node('area', 'area'), node('goal', 'goal', ['area']), node('a', 'strategy', ['goal']),
    node('b', 'strategy', ['goal']), task('shared', ['a', 'b']), task('waiting', ['a'], {status: 'waiting', intent: 'reported', waiting_on: 'Reply'}),
    task('done', ['b'], {status: 'done'}), node('old', 'outcome'),
    {id: 'private-diary', kind: 'diary', data: {text: 'Never project diary bodies'}}]};
}

test('shared task is one identity with both real edges and original status/provenance flags', () => {
  const graph = model.build(fixture());
  assert.equal(graph.nodes.filter(n => n.id === 'shared').length, 1);
  assert.equal(graph.links.filter(l => l.target === 'shared').length, 2);
  assert.equal(graph.byId.get('shared').stale, true);
  assert.equal(graph.byId.get('shared').intent, 'proposed');
  assert.equal(graph.byId.has('private-diary'), false);
});

test('adapter and layout never mutate snapshot, even when renderer mutates projection', () => {
  const snapshot = fixture(), before = JSON.stringify(snapshot);
  const graph = model.build(snapshot);
  const projected = model.layout(model.project(graph));
  projected.nodes[0].x = 999;
  projected.nodes[0].parents.push('invented');
  assert.equal(JSON.stringify(snapshot), before);
  assert.equal(graph.nodes[0].parents.includes('invented'), false);
});

test('missing parent is reported, never turned into an invented node', () => {
  const graph = model.build({records: [task('orphan', ['not-in-snapshot'])]});
  assert.deepEqual(graph.nodes[0].missingParents, ['not-in-snapshot']);
  assert.deepEqual(graph.links, []);
  assert.equal(model.project(graph).nodes.length, 1);
});

test('task filters preserve structural ancestors without leaking unrelated tasks', () => {
  const graph = model.build(fixture());
  const projected = model.project(graph, {status: 'waiting'});
  assert.deepEqual(projected.nodes.filter(n => n.type === 'task').map(n => n.id), ['waiting']);
  assert.equal(projected.nodes.some(n => n.id === 'goal'), true);
  assert.equal(projected.nodes.some(n => n.id === 'area'), true);
});

test('search finds Cyrillic and next actions through collapsed branches', () => {
  const graph = model.build(fixture());
  const projected = model.project(graph, {query: 'ЗАДАЧА shared', collapsed: ['area', 'goal', 'a', 'b']});
  assert.equal(projected.nodes.some(n => n.id === 'shared'), true);
  assert.equal(model.project(graph, {query: 'уточнить'}).nodes.some(n => n.id === 'shared'), true);
  assert.equal(model.project(graph, {query: 'no matching text'}).nodes.length, 0);
});

test('collapsed branch hides its descendants but another parent can keep a shared child visible', () => {
  const graph = model.build(fixture());
  assert.equal(model.project(graph, {collapsed: ['a']}).nodes.some(n => n.id === 'shared'), true);
  const collapsed = model.project(graph, {collapsed: ['a', 'b']});
  assert.equal(collapsed.nodes.some(n => n.id === 'shared'), false);
  assert.ok(collapsed.nodes.find(n => n.id === 'a').hiddenChildren >= 1);
});

test('archive and unattached historical outcomes are explicitly available, not current by default', () => {
  const graph = model.build(fixture());
  const normal = model.project(graph);
  assert.equal(normal.nodes.some(n => n.id === 'done'), false);
  assert.equal(normal.nodes.some(n => n.id === 'old'), false);
  assert.equal(model.project(graph, {includeArchived: true}).nodes.some(n => n.id === 'done'), true);
  assert.equal(model.project(graph, {query: 'old'}).nodes.some(n => n.id === 'old'), true);
});

test('focus and branch filtering preserve all existing parents as context', () => {
  const graph = model.build(fixture());
  const focused = model.project(graph, {areaId: 'area', focusId: 'a'});
  assert.equal(focused.nodes.some(n => n.id === 'shared'), true);
  assert.equal(focused.nodes.some(n => n.id === 'b'), true);
  assert.equal(focused.nodes.some(n => n.id === 'old'), false);
  assert.equal(focused.nodes.filter(n => n.type === 'task').length, 2);
});

test('layout is deterministic, finite, and multi-parent nodes have one position', () => {
  const graph = model.project(model.build(fixture()));
  const a = model.layout(graph), b = model.layout(graph);
  assert.deepEqual(a, b);
  assert.equal(a.nodes.filter(n => n.id === 'shared').length, 1);
  assert.ok(a.nodes.every(n => [n.x, n.y, n.z].every(Number.isFinite)));
  assert.ok(a.nodes.find(n => n.id === 'shared').depth > a.nodes.find(n => n.id === 'goal').depth);
});

test('empty snapshot and self-link do not crash projection or layout', () => {
  assert.deepEqual(model.layout(model.project(model.build({records: []}))).nodes, []);
  assert.deepEqual(model.build({records: [node('self', 'goal', ['self'])]}).links, []);
});

test('500 nodes / 1000 links remain searchable without mutating or duplicating entities', () => {
  const records = [node('r', 'area')];
  for (let i = 1; i < 500; i++) records.push(i < 100 ? node('n' + i, 'strategy', ['r']) : task('n' + i, ['n' + (1 + i % 99), 'n' + (1 + (i + 1) % 99), ...(i < 201 ? ['n' + (1 + (i + 2) % 99)] : [])]));
  const before = JSON.stringify(records), begin = performance.now();
  const graph = model.build({records});
  const projected = model.layout(model.project(graph, {query: 'n499'}));
  assert.ok(projected.nodes.some(n => n.id === 'n499'));
  assert.equal(JSON.stringify(records), before);
  assert.equal(new Set(graph.nodes.map(n => n.id)).size, 500);
  assert.equal(graph.links.length, 1000);
  assert.ok(performance.now() - begin < 1500, 'Projection/search budget exceeded');
});
