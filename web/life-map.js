const PersonalOsLifeMap = (() => {
  'use strict';
  const e = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const typeNames = {area: 'Область', goal: 'Цель', strategy: 'Направление', outcome: 'Результат', experiment: 'Эксперимент', task: 'Задача'};
  const statusNames = {candidate: 'Предложено', ready: 'Готово к работе', doing: 'В работе', waiting: 'Ожидание', done: 'Завершено', dropped: 'Отменено', active: 'Активно', paused: 'На паузе', superseded: 'Архив'};

  function mount(parent, snapshot, {inspect, savedState = {}}) {
    const model = PersonalOsGraph.build(snapshot);
    const records = new Map(snapshot.records.map(r => [r.id, r]));
    const state = Object.assign({mode: '3d', query: '', priority: '', status: '', areaId: '', focusId: '',
      includeArchived: false, collapsed: model.nodes.filter(n => n.type === 'outcome').map(n => n.id), selectedId: null}, savedState);
    state.collapsed = [...state.collapsed];
    let renderer = null, disposed = false, projection, positioned, fallbackMessage = '', searchTimer;
    const abort = new AbortController();
    const listen = (target, event, handler) => target.addEventListener(event, handler, {signal: abort.signal});
    const root = e('section', undefined, 'life-map-workspace');
    root.setAttribute('aria-label', 'Карта целей и задач');
    const toolbar = e('div', undefined, 'map-toolbar');
    function button(text, action, cls = 'map-button') {
      const b = e('button', text, cls); b.type = 'button'; b.addEventListener('click', action); return b;
    }
    function select(label, values, key) {
      const wrap = e('label', label), input = e('select'); input.setAttribute('aria-label', label);
      for (const [value, text] of values) { const option = e('option', text); option.value = value; input.append(option); }
      input.value = state[key];
      listen(input, 'change', () => { state[key] = input.value; state.focusId = ''; refresh(true); });
      wrap.append(input); toolbar.append(wrap); return input;
    }
    const searchLabel = e('label', 'Поиск'), search = e('input');
    search.type = 'search'; search.placeholder = 'Цель или задача'; search.value = state.query;
    search.setAttribute('aria-label', 'Поиск по карте'); searchLabel.append(search); toolbar.append(searchLabel);
    listen(search, 'input', () => { state.query = search.value; state.focusId = ''; clearTimeout(searchTimer); searchTimer = setTimeout(() => refresh(true), 110); });
    const branchInput = select('Ветка', [['', 'Все ветки'], ...model.nodes.filter(n => n.type === 'area' || (!n.parents.length && model.children.get(n.id).length)).map(n => [n.id, n.title])], 'areaId');
    const priorityInput = select('Приоритет', [['', 'Все'], ['primary', 'Основной'], ['supporting', 'Поддерживающий'], ['unranked', 'Не определён']], 'priority');
    const statusInput = select('Статус задачи', [['', 'Все'], ['candidate', 'Предложено'], ['ready', 'Готово к работе'], ['doing', 'В работе'], ['waiting', 'Ожидание']], 'status');
    const modes = e('div', undefined, 'map-mode'); modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', 'Режим карты');
    const modeButtons = {};
    for (const [mode, label] of [['3d', '3D'], ['2d', '2D']]) {
      modeButtons[mode] = button(label, () => { state.mode = mode; fallbackMessage = ''; refresh(true); }); modes.append(modeButtons[mode]);
    }
    toolbar.append(modes);
    const grid = e('div', undefined, 'map-grid'), stage = e('div', undefined, 'map-stage');
    const notice = e('p', '', 'map-notice'); notice.setAttribute('role', 'status');
    const viewport = e('div', undefined, 'map-viewport');
    const canvasTools = e('div', undefined, 'map-canvas-tools');
    const reset = button('Вся карта', () => {
      state.focusId = ''; state.areaId = ''; state.query = ''; state.priority = ''; state.status = '';
      search.value = ''; branchInput.value = ''; priorityInput.value = ''; statusInput.value = ''; refresh(true);
    });
    canvasTools.append(reset);
    const count = e('span', '', 'map-count'); count.setAttribute('role', 'status'); canvasTools.append(count);
    const hint = e('p', 'Потяни, чтобы повернуть · прокрути, чтобы приблизить', 'map-hint');
    const card = e('aside', undefined, 'map-detail'); card.setAttribute('aria-label', 'Выбранный узел');
    stage.append(notice, canvasTools, viewport, hint); grid.append(stage, card);
    const options = e('div', undefined, 'map-options'), archiveLabel = e('label'), archive = e('input');
    archive.type = 'checkbox'; archive.checked = state.includeArchived;
    archiveLabel.append(archive, document.createTextNode('Показать завершённое и архив')); options.append(archiveLabel);
    listen(archive, 'change', () => { state.includeArchived = archive.checked; refresh(true); });
    options.append(e('span', 'Линии показывают сохранённые связи. Приоритеты — из плана и обсуждений.', 'small'));
    const listDetails = e('details', undefined, 'map-list');
    const listSummary = e('summary', 'Узлы карты'), list = e('div', undefined, 'map-list-items');
    listDetails.append(listSummary, list);
    root.append(toolbar, grid, options, listDetails); parent.append(root);

    function sourceSummary(r) {
      const checks = [];
      const seen = new Set();
      const collect = record => {
        if (!record || seen.has(record.id)) return;
        seen.add(record.id);
        if (record.kind === 'source_check') checks.push(record);
        for (const ref of record.data.sources || []) collect(records.get(ref.id));
      };
      collect(r);
      if (!checks.length) return e('p', 'Сохранено ' + new Date(r.updated_at).toLocaleDateString(undefined, {timeZone: snapshot.config.timezone}) + '. Данные можно уточнить в диалоге.', 'small');
      const latest = checks.sort((a, b) => b.data.checked_at.localeCompare(a.data.checked_at))[0];
      const health = (snapshot.source_health || []).filter(h => checks.some(c => c.data.source_id === h.id));
      const issue = health.some(h => h.expired || h.state !== 'reviewed');
      return e('p', 'Источник проверен ' + new Date(latest.data.checked_at).toLocaleString(undefined, {timeZone: snapshot.config.timezone, dateStyle: 'short', timeStyle: 'short'}) + (issue ? '. Есть обновления или требуется проверка.' : '. Последняя проверка учтена.'), 'small');
    }

    function selectNode(id, fit = false) {
      if (!projection.nodes.some(n => n.id === id)) return;
      state.selectedId = id;
      renderer?.select(id); renderCard();
      for (const item of list.querySelectorAll('button')) item.setAttribute('aria-pressed', String(item.dataset.nodeId === id));
      if (state.mode === '2d') render2D();
      if (fit) renderer?.fit(new Set([id, ...model.byId.get(id).parents, ...model.children.get(id)]));
    }
    function renderCard() {
      card.replaceChildren();
      const n = model.byId.get(state.selectedId), r = records.get(state.selectedId);
      if (!n || !r) { card.append(e('h2', 'Выбери цель или задачу'), e('p', 'Здесь появятся следующий шаг, связи и актуальность информации.')); return; }
      card.append(e('h2', n.title));
      const info = [typeNames[n.type], statusNames[n.status] || n.status];
      if (n.intent === 'proposed') info.push('Предложение');
      card.append(e('p', info.filter(Boolean).join(' · '), 'map-detail-status'));
      if (n.priority !== 'unranked') card.append(e('p', n.priority === 'primary' ? 'Основной приоритет' : 'Поддерживающий приоритет', 'map-priority'));
      if (n.stale) card.append(e('p', 'Источник изменился — статус нужно перепроверить.', 'map-stale'));
      if (n.missingParents.length) card.append(e('p', 'Часть связей отсутствует в снимке.', 'small'));
      const d = r.data;
      if (n.type === 'task') {
        card.append(e('h3', n.status === 'waiting' ? 'Чего ждём' : n.status === 'done' ? 'Что завершено' : 'Следующий шаг'),
          e('p', (n.status === 'waiting' ? d.waiting_on : n.status === 'done' ? d.completion_evidence : d.next_action) || 'Следующий шаг пока не выбран.', 'map-action'));
      }
      if (d.rationale || d.description) card.append(e('h3', 'Зачем'), e('p', d.rationale || d.description));
      card.append(sourceSummary(r));
      const controls = e('div', undefined, 'map-card-actions');
      const children = model.children.get(n.id);
      if (children.length) {
        controls.append(button('Фокус на ветке', () => { state.focusId = n.id; state.query = ''; search.value = ''; refresh(true); }));
        const collapsed = state.collapsed.includes(n.id);
        controls.append(button(collapsed ? 'Раскрыть ветку' : 'Свернуть ветку', () => {
          state.focusId = ''; state.query = ''; search.value = ''; state.priority = ''; priorityInput.value = ''; state.status = ''; statusInput.value = '';
          state.collapsed = collapsed ? state.collapsed.filter(id => id !== n.id) : [...state.collapsed, n.id]; refresh(true);
        }));
      }
      controls.append(button('Источники и подробности', () => inspect(n.id), 'plain-button'));
      const open = e('a', n.type === 'task' ? 'Открыть на доске' : 'Открыть связи');
      open.href = '#' + (n.type === 'task' ? 'task/' : 'node/') + encodeURIComponent(n.id); controls.append(open);
      card.append(controls);
      const related = children.filter(id => records.has(id));
      if (related.length) {
        card.append(e('h3', 'Связанные элементы'));
        const connections = e('div', undefined, 'map-connections');
        for (const id of related.slice(0, 8)) connections.append(button(records.get(id).data.title, () => {
          if (!projection.nodes.some(n => n.id === id)) { state.collapsed = state.collapsed.filter(p => p !== n.id); state.focusId = n.id; state.query = ''; search.value = ''; state.priority = ''; priorityInput.value = ''; state.status = ''; statusInput.value = ''; refresh(false); }
          selectNode(id, true);
        }, 'plain-button'));
        card.append(connections);
      }
    }
    function render2D() {
      viewport.replaceChildren();
      const tree = e('div', undefined, 'map-flat');
      for (const n of [...positioned.nodes].sort((a, b) => a.depth - b.depth || a.x - b.x)) {
        const row = button(n.title + (n.hiddenChildren ? ` (+${n.hiddenChildren})` : ''), () => selectNode(n.id), 'map-flat-node');
        row.style.marginLeft = Math.min(n.depth, 5) * 18 + 'px';
        row.setAttribute('aria-pressed', String(state.selectedId === n.id));
        row.append(e('span', typeNames[n.type] + ' · ' + (statusNames[n.status] || n.status), 'small'));
        tree.append(row);
      }
      viewport.append(tree);
    }
    function fallback(message) {
      renderer?.destroy(); renderer = null;
      state.mode = '2d'; fallbackMessage = message; refresh(false);
    }
    function refresh(fit) {
      if (disposed) return;
      projection = PersonalOsGraph.project(model, state);
      positioned = PersonalOsGraph.layout(projection);
      if (!projection.nodes.some(n => n.id === state.selectedId)) state.selectedId =
        projection.nodes.find(n => n.type === 'goal')?.id || projection.nodes[0]?.id || null;
      notice.textContent = fallbackMessage || (state.focusId ? 'Фокус: ' + model.byId.get(state.focusId)?.title : '');
      notice.hidden = !notice.textContent;
      count.textContent = `${projection.nodes.length} из ${model.nodes.length} узлов` + (projection.hidden ? ` · скрыто ${projection.hidden}` : '');
      for (const [mode, b] of Object.entries(modeButtons)) b.setAttribute('aria-pressed', String(state.mode === mode));
      listSummary.textContent = 'Найти узел в списке (' + projection.nodes.length + ')';
      list.replaceChildren();
      for (const n of projection.nodes) {
        const b = button(n.title, () => selectNode(n.id, true), 'map-list-item');
        b.dataset.nodeId = n.id; b.setAttribute('aria-pressed', String(state.selectedId === n.id));
        b.append(e('span', typeNames[n.type], 'small')); list.append(b);
      }
      if (!projection.nodes.length) {
        renderer?.destroy(); renderer = null; viewport.replaceChildren();
        viewport.append(e('p', 'По этим фильтрам ничего не найдено. Измени поиск или нажми «Вся карта».', 'map-no-results'));
        renderCard(); return;
      }
      if (state.mode === '3d') {
        hint.textContent = 'Потяни, чтобы повернуть · прокрути, чтобы приблизить';
        try {
          if (!renderer) {
            viewport.replaceChildren();
            const css = getComputedStyle(root);
            renderer = PersonalOs3D.create(viewport, {onSelect: id => selectNode(id), onError: fallback,
              colors: Object.fromEntries(['teal', 'blue', 'line', 'muted', 'amber'].map(key => [key, css.getPropertyValue('--' + key).trim()]))});
          }
          renderer.update(positioned); renderer.select(state.selectedId); if (fit) renderer.fit();
        } catch (error) { fallback('3D недоступен в этом браузере. Карта и задачи доступны в режиме 2D.'); return; }
      } else {
        renderer?.destroy(); renderer = null;
        hint.textContent = 'Выбери узел на карте или в списке'; render2D();
      }
      renderCard();
    }
    refresh(true);
    return {
      getState: () => ({...state, collapsed: [...state.collapsed]}),
      destroy() { disposed = true; clearTimeout(searchTimer); abort.abort(); renderer?.destroy(); root.remove(); },
      stats: () => renderer?.stats() || {mode: '2d'}
    };
  }
  return {mount};
})();
