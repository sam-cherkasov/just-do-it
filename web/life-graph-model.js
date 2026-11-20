/* Shared pure projection: no mutation of canonical records or rendering objects. */
const PersonalOsGraph = (() => {
  'use strict';

  function build(snapshot) {
    const seen = new Set();
    const nodes = snapshot.records.filter(r => ['node', 'task'].includes(r.kind) && !seen.has(r.id) && seen.add(r.id)).map(r => ({
      id: r.id, title: r.data.title || r.id, kind: r.kind,
      type: r.kind === 'task' ? 'task' : r.data.type,
      status: r.data.status, priority: r.data.priority || 'unranked',
      intent: r.data.intent || null, stale: Boolean(r.stale),
      parents: [...new Set(r.data.parents || [])],
      nextAction: r.data.next_action || r.data.waiting_on || '',
      updatedAt: r.updated_at
    }));
    const byId = new Map(nodes.map(n => [n.id, n]));
    const links = [];
    for (const n of nodes) {
      n.missingParents = n.parents.filter(id => !byId.has(id));
      n.parents = n.parents.filter(id => byId.has(id) && id !== n.id);
      for (const id of n.parents) links.push({source: id, target: n.id});
    }
    const children = new Map(nodes.map(n => [n.id, []]));
    for (const link of links) children.get(link.source).push(link.target);
    return {nodes, links, byId, children};
  }

  function walk(model, start, direction = 'children') {
    const result = new Set(), queue = [...start];
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      if (result.has(id) || !model.byId.has(id)) continue;
      result.add(id);
      queue.push(...(direction === 'parents' ? model.byId.get(id).parents : model.children.get(id)));
    }
    return result;
  }

  function project(model, state = {}) {
    const archived = n => ['superseded', 'dropped'].includes(n.status) || (n.type === 'task' && n.status === 'done');
    const available = model.nodes.filter(n => state.includeArchived || !archived(n));
    const allowed = new Set(available.map(n => n.id));
    let scope = new Set(allowed);
    if (state.areaId) scope = walk(model, [state.areaId]);
    if (state.focusId) {
      const branch = walk(model, [state.focusId]);
      scope = new Set([...scope].filter(id => branch.has(id)));
    }
    const query = (state.query || '').trim().toLocaleLowerCase();
    const filtered = Boolean(query || state.priority || state.status);
    let seeds = available.filter(n => scope.has(n.id));
    if (state.priority || state.status) seeds = seeds.filter(n => n.type === 'task' &&
      (!state.priority || n.priority === state.priority) && (!state.status || n.status === state.status));
    if (query) seeds = seeds.filter(n => (n.title + ' ' + n.nextAction).toLocaleLowerCase().includes(query));
    // Unlinked historical outcomes remain searchable rather than crowding the starting view.
    if (!filtered && !state.areaId && !state.focusId && !state.includeArchived) {
      const withWork = walk(model, available.filter(n => n.type === 'task').map(n => n.id), 'parents');
      seeds = seeds.filter(n => n.parents.length || n.type === 'area' || n.type === 'goal' || withWork.has(n.id));
    }
    const visible = walk(model, seeds.map(n => n.id), 'parents');
    for (const id of visible) if (!allowed.has(id)) visible.delete(id);
    // Collapse is path-aware: another uncollapsed parent can still reveal a shared child.
    if (!filtered && !state.focusId) {
      const collapsed = new Set(state.collapsed || []);
      const roots = [...visible].filter(id => !model.byId.get(id).parents.some(p => visible.has(p)));
      const reached = new Set(), queue = [...roots];
      for (let i = 0; i < queue.length; i++) {
        const id = queue[i];
        if (reached.has(id)) continue;
        reached.add(id);
        if (!collapsed.has(id)) queue.push(...model.children.get(id).filter(child => visible.has(child)));
      }
      for (const id of visible) if (!reached.has(id)) visible.delete(id);
    }
    const nodes = model.nodes.filter(n => visible.has(n.id)).map(n => ({...n, parents: [...n.parents],
      hiddenChildren: [...walk(model, model.children.get(n.id))].filter(id => allowed.has(id) && !visible.has(id)).length
    }));
    return {nodes, links: model.links.filter(l => visible.has(l.source) && visible.has(l.target)).map(l => ({...l})),
      matched: seeds.length, total: model.nodes.length, hidden: model.nodes.length - nodes.length};
  }

  function layout(graph) {
    const byId = new Map(graph.nodes.map(n => [n.id, n]));
    const depth = new Map(), queue = graph.nodes.filter(n => !n.parents.some(p => byId.has(p))).map(n => n.id);
    for (const id of queue) depth.set(id, 0);
    for (let i = 0; i < queue.length; i++) {
      const id = queue[i];
      for (const link of graph.links.filter(l => l.source === id)) {
        if (!depth.has(link.target)) { depth.set(link.target, depth.get(id) + 1); queue.push(link.target); }
      }
    }
    const layers = new Map();
    for (const n of graph.nodes) {
      const level = depth.get(n.id) || 0;
      if (!layers.has(level)) layers.set(level, []);
      layers.get(level).push(n);
    }
    const result = [];
    for (const [level, items] of layers) {
      items.sort((a, b) => a.parents.join().localeCompare(b.parents.join()) || a.id.localeCompare(b.id));
      const columns = items.length <= 7 ? items.length : Math.ceil(Math.sqrt(items.length));
      const rows = Math.ceil(items.length / columns);
      items.forEach((n, i) => result.push({...n,
        x: ((i % columns) - (columns - 1) / 2) * 170,
        y: -level * 105,
        z: rows > 1 ? (Math.floor(i / columns) - (rows - 1) / 2) * 150 : ((i % 3) - 1) * 48 + (level % 2) * 30,
        depth: level
      }));
    }
    return {nodes: result, links: graph.links.map(l => ({...l}))};
  }
  return {build, project, layout, walk};
})();
if (typeof module !== 'undefined') module.exports = PersonalOsGraph;
