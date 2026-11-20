"use strict";
(function(root) {
  function signature(state) {
    if (!state) return '';
    // Transport timestamps and rotated tokens must not rebuild the page.
    return JSON.stringify({
      records: ['workstreams','tasks','sessions','planners','day_choices','workspace_items'].flatMap(key => (state[key] || []).map(r => [r.id,r.revision])).sort((a,b) => a[0].localeCompare(b[0])),
      today: state.today,
      needs_setup: Boolean(state.needs_setup),
      health: [...(state.source_health || [])].sort((a,b) => a.id.localeCompare(b.id)),
      automation: state.auto_refresh || null
    });
  }
  function canRefresh({busy, pending, modalOpen, editing, hidden}) {
    return !busy && !pending && !modalOpen && !editing && !hidden;
  }
  root.WorkspaceRefresh = {signature,canRefresh};
  if (typeof module !== 'undefined') module.exports = root.WorkspaceRefresh;
})(typeof globalThis !== 'undefined' ? globalThis : this);
