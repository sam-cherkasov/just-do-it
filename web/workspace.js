"use strict";
const page = document.querySelector('#page');
const notice = document.querySelector('#notice');
const modal = document.querySelector('#session-dialog');
const sessionForm = document.querySelector('#session-form');
let state, chosen, busy = false;
let loading = false, stateGeneration = 0;
const pendingKey = 'personal-os-focus-pending-v1';
function stored(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch { return null; } }
function persist(key, value) { try { value === null ? sessionStorage.removeItem(key) : sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* In-memory state still allows an exact retry. */ } }
let pending = stored(pendingKey);
function el(tag, text, cls) { const item = document.createElement(tag); if (text !== undefined) item.textContent = text; if (cls) item.className = cls; return item; }
function button(text, action, cls = 'secondary') { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', action); return b; }
function link(text, url, cls) { const a = el('a', text, cls); a.href = url; return a; }
function chatLink(text, url, cls = 'text-link') { return /^codex:\/\/threads\/[a-zA-Z0-9_-]+$/.test(url || '') ? link(text, url, cls) : null; }
function time(value, options = {}) { if (!value || Number.isNaN(Date.parse(value))) return I18n.t('дата неизвестна'); return new Date(value).toLocaleString(I18n.locale, {timeZone:state?.timezone || 'Europe/Madrid', day:'numeric', month:'short', ...options}); }
function streams() { return [...state.workstreams].filter(s => s.data.status !== 'paused').sort((a,b) => (a.data.order ?? 99) - (b.data.order ?? 99)); }
function tasks(stream) { return (stream.data.task_ids || []).map(id => state.tasks.find(t => t.id === id)).filter(t => t && !['done','dropped'].includes(t.data.status)); }
function active() { return state.sessions.find(s => s.data.status === 'active'); }
function recent(taskId) { return [...state.sessions].filter(s => s.data.task_id === taskId && s.data.status === 'closed').sort((a,b) => b.updated_at.localeCompare(a.updated_at))[0]; }
function plural(count, forms) { if (I18n.language === 'en') return count + ' ' + forms[count === 1 ? 0 : 2]; const n = count % 100; return count + ' ' + forms[n > 10 && n < 20 ? 2 : count % 10 === 1 ? 0 : count % 10 >= 2 && count % 10 <= 4 ? 1 : 2]; }
function shortTask(stream, task) { const brief = {...(stream?.data.task_summaries?.[task.id] || {title:task.data.title, step:task.data.next_action, result:task.data.title})}; const controlled=task.data.user_control?.fields || []; if(controlled.includes('title')){brief.title=task.data.title;brief.result=task.data.title;} if(controlled.includes('next_action'))brief.step=task.data.next_action; return brief; }
function flash(text, error = false, retry = false) { notice.replaceChildren(); const box = el('div', text, 'notice' + (error ? ' error' : '')); if (retry) box.append(button(I18n.t('Повторить сохранение'), () => save(pending), 'secondary')); notice.append(box); }
function failure(error) { flash(error.message || I18n.t('Не удалось загрузить данные. Проверь локальный сервер и нажми «Обновить».'), true); }
async function load() {
  const generation = ++stateGeneration;
  const response = await fetch('/api/workspace'); if (!response.ok) throw new Error(I18n.t('Не удалось прочитать пространство. Проверь локальный сервер.'));
  const incoming = await response.json(); if (generation !== stateGeneration) return;
  state = incoming; render(); syncStatus();
  if (pending) flash(I18n.t('Предыдущая запись ещё не подтверждена. Повтори её, прежде чем начинать новую.'), true, true);
}
async function save(payload) {
  if (busy || !payload) return;
  busy = true; pending = payload; persist(pendingKey, pending);
  stateGeneration += 1;
  document.querySelectorAll('button[type=submit], #start-session, [data-save]').forEach(b => b.disabled = true);
  document.querySelectorAll('.onboarding input, dialog input, dialog textarea, dialog select, .finish-box textarea, .finish-box select').forEach(input => input.disabled = true);
  try {
    const response = await fetch({'setup':'/api/setup','create-workstream':'/api/create-workstream','create-task':'/api/create-task','focus':'/api/focus','day-choice':'/api/day-choice','task-control':'/api/task-control','link-card':'/api/link-card','workspace-item':'/api/workspace-item'}[payload.operation || 'focus'], {method:'POST', headers:{'Content-Type':'application/json','X-Workspace-Token':state.token}, body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 409 || response.status === 400) { pending = null; persist(pendingKey, null); if (response.status === 409) await load(); }
      throw new Error(response.status === 409 ? I18n.t('Данные изменились. Текст сохранён в этой вкладке. Открой действие заново, проверь новые данные и повтори.') : I18n.t(result.error || 'Не удалось сохранить запись.'));
    }
    state = result; stateGeneration += 1; pending = null; persist(pendingKey, null);
    if (payload.id && !payload.operation) persist('focus-draft-' + payload.id, null);
    if(payload.draft_key)persist(payload.draft_key,null);
    document.querySelector('#action-dialog').close();
    if (modal.open) modal.close();
    location.hash = payload.after ? payload.after.replace('{id}', result.created_id || '') : (payload.id ? '#history' : '#focus'); render();
    flash(payload.message || (payload.id ? I18n.t('Итог сессии сохранён. Можно переключаться.') : I18n.t('Сессия сохранена. Сейчас только этот вопрос.')));
  } catch (error) { if (modal.open) modal.close(); document.querySelector('#action-dialog').close(); flash(error.message || I18n.t('Связь прервалась. Статус записи неизвестен.'), true, Boolean(pending)); }
  finally { busy = false; document.querySelectorAll('button[type=submit], #start-session, [data-save], .onboarding input, dialog input, dialog textarea, dialog select, .finish-box textarea, .finish-box select').forEach(b => b.disabled = false); }
}
function pick(stream, task, planning = null, dayChoice = null, continuation = null) {
  if (busy) return;
  if(TodayModel.bucket(task)!=='available'){location.hash='#task/'+task.id;flash(I18n.t('Сначала верни задачу в доступные.'));return;}
  if (pending) { flash(I18n.t('Сначала подтверди предыдущую запись.'), true, true); return; }
  if (active()) { location.hash = '#focus'; flash(I18n.t('Сначала сохрани итог текущей сессии. Затем можно выбрать другой вопрос.')); return; }
  chosen = {stream,task,planning,dayChoice,continuation};
  chosen.draftKey = 'session-start-'+task.id+'-'+(continuation ? continuation.id+'-'+continuation.revision : dayChoice ? dayChoice.id+'-'+dayChoice.revision : planning ? planning.board.id+'-'+planning.card.id : 'direct');
  const draft = stored(chosen.draftKey);
  document.querySelector('#session-task').textContent = shortTask(stream, task).title;
  document.querySelector('#target').value = draft?.target || continuation?.data.target || dayChoice?.data.target || planning?.card.outcome || recent(task.id)?.data.next_action || shortTask(stream, task).result;
  document.querySelector('#session-first-action').textContent=I18n.t('Первый шаг: ')+(continuation?.data.next_action || dayChoice?.data.first_action || planning?.card.first_action || task.data.next_action || I18n.t('Укажи в задаче'));
  const minutes = document.querySelector('#minutes');
  minutes.querySelector('[data-custom]')?.remove();
  const budget = draft?.minutes || (planning && planning.card.minutes <= 180 ? planning.card.minutes : 60);
  if (![...minutes.options].some(o => Number(o.value) === budget)) { const option = new Option(budget + I18n.t(' минут'), String(budget)); option.dataset.custom = 'true'; minutes.add(option); }
  minutes.value = String(budget);
  modal.showModal(); document.querySelector('#target').focus();
}
sessionForm.addEventListener('submit', event => {
  event.preventDefault(); if (!chosen || busy) return;
  if (pending) { save(pending); return; }
  const planning = chosen.planning ? {planner_id:chosen.planning.board.id, planner_revision:chosen.planning.board.revision, planner_card_id:chosen.planning.card.id} : {};
  save({request_id:crypto.randomUUID(), draft_key:chosen.draftKey, data:{workstream_id:chosen.stream?.id || null, task_id:chosen.task.id, task_revision:chosen.task.revision, target:document.querySelector('#target').value.trim(), minutes:Number(document.querySelector('#minutes').value), ...planning, ...(chosen.dayChoice ? {day_choice_id:chosen.dayChoice.id, day_choice_revision:chosen.dayChoice.revision} : {}), ...(chosen.continuation ? {continuation_id:chosen.continuation.id,continuation_revision:chosen.continuation.revision} : {})}});
});
sessionForm.addEventListener('input',()=>{if(chosen)persist(chosen.draftKey,{target:document.querySelector('#target').value,minutes:Number(document.querySelector('#minutes').value)});});
document.querySelector('#dismiss').addEventListener('click', () => { if (!busy) modal.close(); });
modal.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
function focusBand() {
  const session = active(), band = el('section', undefined, 'focus-band'), content = el('div', undefined, 'band-content');
  band.append(el('span','◉','orbit'));
  content.append(el('h2', session ? I18n.t('Сейчас в фокусе') : I18n.t('Для следующего часа — один вопрос')), el('p', session ? session.data.target : I18n.t('Открой направление, выбери задачу и реши, что будет достаточным результатом этой сессии.')));
  band.append(content);
  if (session) band.append(link(I18n.t('Вернуться к работе'), '#focus', 'primary'));
  else band.append(button(I18n.t('Выбрать направление'), () => { document.querySelector('#directions')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant':'smooth'}); document.querySelector('.project-card')?.focus(); }, 'primary'));
  return band;
}
function home() {
  const head = el('div', undefined, 'heading heading-row'), text = el('div');
  text.append(el('h1',I18n.t('Всё на своих местах.')), el('p',I18n.t('Все направления перед глазами. Выбери, чему сейчас нужно твоё внимание.'), 'intro'));
  const search = el('input', undefined, 'search'); search.type = 'search'; search.placeholder = I18n.t('Поиск по задачам'); search.setAttribute('aria-label',I18n.t('Найти направление или задачу'));
  head.append(text,search); page.append(head,focusBand());
  page.append(button(I18n.t('Создать направление'),()=>createDirection(),'secondary'));
  const heading = el('div', undefined, 'section-heading'); heading.id = 'directions'; heading.append(el('h2',I18n.t('Мои направления')), el('span',I18n.t('Порядок карточек — не список приоритетов')));
  const grid = el('div', undefined, 'project-grid'); page.append(heading,grid);
  function draw() {
    grid.replaceChildren(); const query = search.value.trim().toLocaleLowerCase(I18n.locale);
    const found = streams().filter(s => [s.data.title,s.data.summary,...tasks(s).map(t => t.data.title)].join(' ').toLocaleLowerCase(I18n.locale).includes(query));
    for (const stream of found) {
      const d = stream.data, card = link('', '#project/' + stream.id, 'project-card ' + d.color), top = el('div',undefined,'card-top'), body = el('div',undefined,'card-body');
      top.append(el('span',d.symbol || '◈','project-symbol'), el('span','↗','card-open'), el('h3',d.title));
      body.append(el('p',d.summary));
      const meta = el('div',undefined,'card-meta'), questions = (d.questions || []).filter(q => tasks(stream).some(t=>t.id===q.task_id && TodayModel.bucket(t)==='available' && !(t.data.user_control?.fields || []).some(f=>['title','next_action'].includes(f))));
      if (questions.length) meta.append(el('span',plural(questions.length,[I18n.t('открытый вопрос'),I18n.t('открытых вопроса'),I18n.t('открытых вопросов')]),'pill attention'));
      meta.append(el('span',plural(tasks(stream).length,[I18n.t('задача'),I18n.t('задачи'),I18n.t('задач')]),'pill'));
      body.append(meta); card.append(top,body); grid.append(card);
    }
    if (!found.length) grid.append(el('p',I18n.t('Ничего не нашлось. Попробуй другое слово.'),'intro'));
  }
  search.addEventListener('input',draw); draw();
}
function taskCard(stream, task) {
  const brief = shortTask(stream,task), box = el('article',undefined,'task');
  box.append(el('h3',brief.title), el('p',brief.step || task.data.next_action));
  if (task.data.status === 'waiting') box.append(el('p',I18n.t('Ожидается: ') + task.data.waiting_on,'session-note'));
  const last = recent(task.id);
  if (last) box.append(el('p',I18n.t('Последняя сессия: ') + last.data.note + (last.data.next_action ? I18n.t('\nДальше: ') + last.data.next_action : ''),'session-note'));
  const controls = el('div',undefined,'task-controls'); controls.append(link(I18n.t('Открыть задачу'), '#task/'+task.id, 'secondary')); if(TodayModel.bucket(task)==='available')controls.append(button(I18n.t('На сегодня'),()=>chooseResult(task), 'quiet'));
  const chat = chatLink(I18n.t('Открыть рабочий чат'),task.data.chat_url); if (chat) controls.append(chat);
  box.append(controls);
  for (const card of state.relationships?.cards || []) if (card.task_id === task.id && card.workstream_id === stream.id) {
    box.append(link(I18n.t('В плане: ') + card.title + (card.selected ? I18n.t(' · выбрано') : I18n.t(' · вариант')), '#planned/' + card.planner_id + '/' + card.card_id, 'text-link plan-link'));
  }
  const detail = el('details'); detail.append(el('summary',I18n.t('Сохранённые детали и основание')),el('p',task.data.next_action || ''),el('p',task.data.rationale || ''),el('p',I18n.t('Обновлено ') + time(task.updated_at) + '. ' + (task.data.intent === 'proposed' ? I18n.t('Предложенный следующий шаг.') : I18n.t('Сохранено из сообщения пользователя.'))));
  if (task.data.attention_date) detail.append(el('p',task.data.attention_date + ': ' + task.data.date_basis));
  box.append(detail); return box;
}
function project(id) {
  const stream = state.workstreams.find(s => s.id === id); if (!stream) return empty(I18n.t('Направление не найдено'),I18n.t('Вернись к обзору или обнови данные.'));
  const d = stream.data; page.className = d.color;
  page.append(link(I18n.t('Все направления'), '#home','breadcrumb'));
  const head = el('div',undefined,'project-header'); head.append(el('span',d.symbol || '◈','project-symbol'),el('h1',d.title),el('p',d.outcome,'intro'),el('span',I18n.t('Контекст собран ') + time(stream.updated_at), 'updated'));page.append(head);
  const layout = el('div',undefined,'detail-grid'), main = el('div'), side = el('aside');
  const openTasks = tasks(stream), questions = (d.questions || []).filter(q => openTasks.some(t=>t.id===q.task_id && TodayModel.bucket(t)==='available' && !(t.data.user_control?.fields || []).some(f=>['title','next_action'].includes(f))));
  if (questions.length) {
    main.append(el('h2',I18n.t('Где нужно твоё решение')));
    const list = el('ul',undefined,'decision-list');
    for (const q of questions) { const li = el('li',undefined,'decision'); li.append(el('p',q.text),button(I18n.t('Разобрать'),()=>pick(stream,openTasks.find(t=>t.id===q.task_id)),''));list.append(li); }
    main.append(list);
  }
  main.append(el('h2',I18n.t('Возможные следующие шаги')));
  main.append(button(I18n.t('Добавить задачу'),()=>createTask(stream),'secondary'));
  if (!openTasks.length) main.append(el('p',I18n.t('Открытых задач в сохранённом контексте нет.')));
  for (const task of openTasks) main.append(taskCard(stream,task));
  const unlinkedCards = (state.relationships?.cards || []).filter(c=>c.workstream_id===stream.id && !c.task_id);
  if (unlinkedCards.length) {
    const box=el('section',undefined,'context-box');box.append(el('h2',I18n.t('Другие карточки недельного плана')));
    for(const card of unlinkedCards)box.append(link(card.title,'#planned/'+card.planner_id+'/'+card.card_id,'text-link plan-link'));
    box.append(el('p',I18n.t('Привязаны к направлению; соответствие отдельным задачам пока не установлено.'),'hint'));main.append(box);
  }
  const context = el('section',undefined,'context-box'); context.append(el('h2',I18n.t('Что происходит')),el('p',d.context || d.summary));
  if (d.limitations) context.append(el('p',d.limitations,'hint')); side.append(context);
  const chats = el('section',undefined,'context-box'); chats.append(el('h2',I18n.t('Последние связанные чаты')));
  const list = el('ul',undefined,'chat-list');
  for (const chat of [...(d.chats || [])].sort((a,b)=>b.activity_at.localeCompare(a.activity_at)).slice(0,5)) {
    const a = chatLink(chat.title,chat.url,''); if (!a) continue;
    a.append(el('small',I18n.t('Активность ') + time(chat.activity_at))); const li=el('li');li.append(a);list.append(li);
  }
  chats.append(list,el('p',list.children.length ? I18n.t('До пяти чатов из сохранённой подборки. Ссылки открываются в Codex.') : I18n.t('В этом направлении чаты ещё не привязаны.'),'hint'));side.append(chats);
  const health = state.source_health.filter(h=>(d.source_ids || []).includes(h.id)), issues = health.filter(h=>h.expired || h.state !== 'reviewed');
  if (health.length) {const box=el('section',undefined,'context-box'); box.append(el('h2',I18n.t('Свежесть контекста')),el('p',issues.length ? I18n.t('Есть источники, которые нужно перечитать или сверить. До следующей успешной проверки здесь остаются последние известные данные.') : I18n.t('Привязанные источники прочитаны и сверены.')),el('p',I18n.t('Фоновый Codex проверяет изменившиеся чаты по расписанию. Новые записи появятся здесь автоматически.'),'hint'));side.append(box);}
  layout.append(main,side);page.append(layout);
}
function weeks() {
  page.append(el('h1',I18n.t('Планы недели'),'heading'),el('p',I18n.t('Твои сохранённые варианты, выбранные результаты и время.'),'intro'));
  for (const board of [...(state.planners || [])].sort((a,b)=>b.data.week_start.localeCompare(a.data.week_start))) {
    const box = el('article',undefined,'task');
    box.append(el('h2',board.data.title),el('p',I18n.t('Неделя с ') + board.data.week_start),link(I18n.t('Открыть план'),'/planner?board='+encodeURIComponent(board.id),'secondary'));
    for (const card of board.data.cards.filter(c=>c.selected)) box.append(link(card.title,'#planned/'+board.id+'/'+card.id,'text-link plan-link'));
    page.append(box);
  }
  if (!state.planners?.length) page.append(el('p',I18n.t('Сохранённых недель пока нет.')));
}
function planned(boardId, cardId) {
  const board = state.planners?.find(b=>b.id===boardId), card = board?.data.cards.find(c=>c.id===cardId);
  if (!card) return empty(I18n.t('Карточка больше не найдена'),I18n.t('История уже начатых сессий сохранена отдельно.'));
  const task = state.tasks.find(t=>t.id===card.task_id), stream = state.workstreams.find(s=>s.id===card.workstream_id);
  const membershipChanged=Boolean(task && card.workstream_id && !stream?.data.task_ids.includes(task.id));
  page.append(link(I18n.t('К плану недели'),'/planner?board='+encodeURIComponent(board.id),'breadcrumb'),el('h1',card.title,'heading'));
  const box=el('section',undefined,'target-box');box.append(el('h2',card.selected ? I18n.t('Выбранный результат') : I18n.t('Результат карточки')),el('p',card.outcome));page.append(box);
  page.append(el('p',I18n.t('Первый шаг: ') + card.first_action),el('p',card.minutes + I18n.t(' мин · ') + (card.selected ? I18n.t('Выбрано в плане') : I18n.t('Пока вариант')) + (card.placement ? ' · '+card.placement.date : I18n.t(' · Без даты'))));
  if (card.placement?.start_minute != null) page.append(el('p',I18n.t('Начало по плану: ')+String(Math.floor(card.placement.start_minute/60)).padStart(2,'0')+':'+String(card.placement.start_minute%60).padStart(2,'0')));
  if (task && card.task_revision !== task.revision) page.append(el('p',I18n.t('Задача обновилась после привязки. Результат и первый шаг этой карточки сохранены; проверь их перед началом.'),'session-note'));
  if (stream) page.append(link(I18n.t('Направление: ')+stream.data.title,'#project/'+stream.id,'text-link'));
  if (task) page.append(el('p',I18n.t('Связанная задача: ')+task.data.title));
  if (membershipChanged) page.append(el('p',I18n.t('Задача больше не относится к направлению карточки. План можно редактировать; перед началом работы измени или сними связь ниже.'),'session-note'));
  const chat=chatLink(I18n.t('Открыть рабочий чат'),card.chat_url);if(chat)page.append(chat);
  if (task && !membershipChanged && card.selected && TodayModel.bucket(task)==='available') {page.append(button(I18n.t('Выбрать на сегодня'),()=>chooseResult(task,{board,card}),'primary')); page.append(button(I18n.t('Начать с этой карточки'),()=>pick(stream,task,{board,card}),'secondary'));}
  else if(!membershipChanged) page.append(el('p',!task ? I18n.t('Свяжи карточку с существующей задачей, чтобы перейти к работе.') : !card.selected ? I18n.t('Выбери карточку в плане, чтобы начать из неё сессию.') : I18n.t('Верни задачу в доступные, чтобы начать работу.'),'hint'));
  page.append(button(task ? I18n.t('Изменить связь с задачей') : I18n.t('Связать с задачей'),()=>linkPlanCard(board,card),'quiet'));
}
async function connection() {
  page.append(el('h1',I18n.t('Подключение чатов'),'heading'));
  const integrations=el('section',undefined,'context-box');
  integrations.append(el('h2',I18n.t('Можно работать без подключений')),el('p',I18n.t('Направления, задачи, выбор дня и фокус сохраняются локально. Аккаунт AI и календарь для этого не нужны.')),el('p',I18n.t('Чаты: ссылку на чат Codex можно добавить через «Исправить задачу». Автоматическое чтение требует отдельно настроенного ассистента с доступом к источникам.')),el('p',state.calendar_configured ? I18n.t('Календарный аккаунт указан. Это не подтверждает доступ: перед планированием ассистенту нужно проверить подключение.') : I18n.t('Календарь не подключён. Выбор на сегодня не создаёт событий. Подключение можно настроить позже с ассистентом.')));
  page.append(integrations);
  const box=el('section',undefined,'context-box');box.append(el('p',I18n.t('Проверяем сохранённую диагностику…')));page.append(box);
  try {
    const response=await fetch('/api/agent-status'); if(!response.ok)throw new Error();
    const status=await response.json();if(location.hash!=='#connection')return;
    box.replaceChildren(el('h2',status.state==='snapshot' ? I18n.t('Доступен датированный снимок') : I18n.t('Живые статусы пока недоступны')),el('p',I18n.t(status.message)));
    if(status.observed_at)box.append(el('p',I18n.t('Проверено ')+time(status.observed_at,{hour:'2-digit',minute:'2-digit'}),'hint'));
    box.append(el('p',I18n.t('Ссылки на чаты и обновление их содержания работают отдельно. Отсутствие статуса не означает, что агент остановился.'),'hint'));
  } catch {box.replaceChildren(el('p',I18n.t('Не удалось прочитать диагностику. Проверь локальный сервер; статус агентов неизвестен.')));}
}
function empty(title, text) {const box=el('div',undefined,'empty');box.append(el('h1',title),el('p',text),link(I18n.t('Открыть направления'),'#home','primary'));page.append(box);}
function focusPage() {
  const session = active(); if (!session) return empty(I18n.t('Что возьмёшь в фокус?'),I18n.t('Выбери одну задачу в направлении. Здесь останутся только её контекст, нужный чат и результат, к которому ты идёшь.'));
  const d=session.data, stream=state.workstreams.find(s=>s.id===d.workstream_id), box=el('div',undefined,'focus-page');
  box.append(link(stream?.data.title || I18n.t('Задача без направления'),d.workstream_id ? '#project/'+d.workstream_id : '#task/'+d.task_id,'focus-kicker'),el('h1',d.title));
  const target=el('section',undefined,'target-box');target.append(el('h2',I18n.t('Результат этой сессии')),el('p',d.target));box.append(target);
  const clock=el('div',undefined,'time-line');clock.append(el('strong',d.minutes + I18n.t(' мин')),el('span',I18n.t('Твой ориентир. Начало ') + time(d.started_at,{hour:'2-digit',minute:'2-digit'}) + I18n.t('. Можно остановиться раньше.')));box.append(clock);
  const actions=el('div',undefined,'session-actions'), chat=chatLink(I18n.t('Открыть рабочий чат'),d.chat_url,'primary');if(chat)actions.append(chat);actions.append(link(d.workstream_id ? I18n.t('Контекст направления') : I18n.t('Контекст задачи'),d.workstream_id ? '#project/'+d.workstream_id : '#task/'+d.task_id,'secondary'));box.append(actions);
  if(d.day_choice_id)box.append(link(I18n.t('Результат дня'),'#today','text-link plan-link'));
  if(d.planner_id)box.append(link(I18n.t('Исходная карточка плана'),'#planned/'+d.planner_id+'/'+d.planner_card_id,'text-link'));
  const details=el('details');details.append(el('summary',I18n.t('С чего начать')),el('p',d.first_action));box.append(details);
  const task=state.tasks.find(t=>t.id===d.task_id);if(task)taskItems(task,box,true);
  if(d.continuation_id)box.append(link(I18n.t('Итог предыдущего подхода'),'#task/'+d.task_id,'text-link plan-link'));
  const finish=el('section',undefined,'finish-box');finish.append(el('h2',I18n.t('Остановиться и сохранить итог')));
  const form=el('form'), outcome=el('select'), note=el('textarea'), next=el('textarea');outcome.name='outcome';
  for(const [value,text] of [['result',I18n.t('Есть результат')],['progress',I18n.t('Продвинулся, нужен ещё подход')],['blocked',I18n.t('Упёрся в вопрос')],['cancelled',I18n.t('Не приступил / изменил решение')]]){const option=el('option',text);option.value=value;outcome.append(option);}
  note.rows=4;note.required=true;note.maxLength=12000;note.placeholder=I18n.t('Что получилось, что решил или что помешало?');next.rows=2;next.maxLength=4000;next.placeholder=I18n.t('Где продолжить в следующий раз');
  const draft=stored('focus-draft-'+session.id);if(draft){outcome.value=draft.outcome;note.value=draft.note;next.value=draft.next_action;}
  for(const [text,input] of [[I18n.t('Как прошла сессия?'),outcome],[I18n.t('Итог своими словами'),note],[I18n.t('Следующий шаг, если он нужен'),next]]){const label=el('label',text);label.append(input);form.append(label);}
  form.addEventListener('input',()=>persist('focus-draft-'+session.id,{outcome:outcome.value,note:note.value,next_action:next.value}));
  const submit=el('button',I18n.t('Сохранить итог'),'primary');submit.type='submit';form.append(submit,el('p',I18n.t('Итог сохраняется в personal-os. Статус всей задачи автоматически не меняется.'),'hint'));
  form.addEventListener('submit',event=>{event.preventDefault();if(pending)return flash(I18n.t('Сначала подтверди предыдущую запись.'),true,true);save({request_id:crypto.randomUUID(),id:session.id,expected_revision:session.revision,data:{status:'closed',outcome:outcome.value,note:note.value.trim(),next_action:next.value.trim()}});});finish.append(form);box.append(finish);page.append(box);
}
function history() {
  page.append(el('h1',I18n.t('Место, где остаётся результат.'),'heading'),el('p',I18n.t('Решения, продвижение и точки, с которых можно продолжить.'),'intro'));
  const sessions=[...state.sessions].filter(s=>s.data.status==='closed').sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  if(!sessions.length)return empty(I18n.t('Пока нет завершённых сессий'),I18n.t('После первой сессии здесь появятся твой итог и следующий шаг.'));
  const labels={result:I18n.t('Есть результат'),progress:I18n.t('Есть продвижение'),blocked:I18n.t('Открытый вопрос'),cancelled:I18n.t('Остановлено')};
  for(const session of sessions){const d=session.data, item=el('article',undefined,'history-item');item.append(el('div',time(d.ended_at,{hour:'2-digit',minute:'2-digit'}) + ' · ' + labels[d.outcome],'history-meta'),el('h3',d.title),el('p',d.note));if(d.next_action)item.append(el('p',I18n.t('Дальше: ')+d.next_action));item.append(link(I18n.t('Открыть задачу'),'#task/'+d.task_id,'text-link'));if(d.planner_id)item.append(link(I18n.t('Исходная карточка плана'),'#planned/'+d.planner_id+'/'+d.planner_card_id,'text-link'));page.append(item);}
}
function render() {
  if(!state)return;
  document.querySelector('#capture-thought').disabled=Boolean(state.needs_setup);
  if(state.needs_setup){page.replaceChildren();page.className='';document.querySelector('#projects-nav').replaceChildren();setupPage();return;}
  const hash=location.hash.slice(1)||'today'; page.replaceChildren();page.className='';
  const nav=document.querySelector('#projects-nav');nav.replaceChildren();for(const s of streams()){const a=link(s.data.title,'#project/'+s.id,s.data.color);a.prepend(el('span','','nav-dot'));if(hash==='project/'+s.id)a.setAttribute('aria-current','page');nav.append(a);}
  for(const a of document.querySelectorAll('[data-nav]')){if(a.dataset.nav===hash)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  document.querySelector('#active-dot').textContent=active()?'active':'';
  document.querySelector('#current-date').textContent=new Date().toLocaleDateString(I18n.locale,{timeZone:state.timezone,weekday:'long',day:'numeric',month:'long'});
  document.querySelector('#freshness').textContent=I18n.t('Прочитано ')+time(state.generated_at,{hour:'2-digit',minute:'2-digit'});
  if(!state.workstreams.length && !state.tasks.length && ['today','home','tasks'].includes(hash))welcomePage();else if(hash==='today')todayPage();else if(hash==='inbox')inboxPage();else if(hash==='tasks')taskList();else if(hash.startsWith('task/'))taskDetail(hash.slice(5));else if(hash.startsWith('project/'))project(hash.slice(8));else if(hash.startsWith('planned/'))planned(...hash.split('/').slice(1));else if(hash==='focus')focusPage();else if(hash==='history')history();else if(hash==='weeks')weeks();else if(hash==='connection')connection();else home();
  if(state.synthetic)page.prepend(el('p',I18n.t('Тестовый пример — вымышленные данные'),'hint'));
  document.title=(page.querySelector('h1')?.textContent || I18n.t('Обзор'))+I18n.t(' — Моё пространство');
  syncStatus();
}
function syncStatus(error = false) {
  const target = document.querySelector('#sync-status'); if (!state) return;
  if(state.needs_setup){target.textContent='';return;}
  if (error) { target.textContent = I18n.t('Не удалось проверить обновления страницы. Сохранённые данные остаются видны; попробуем снова автоматически.'); return; }
  const config = state.auto_refresh;
  const health = state.source_health || [];
  const checks = health.map(h => h.checked_at).filter(Boolean).sort();
  const issues = health.filter(h => h.state !== 'reviewed' || h.expired);
  target.textContent = (config?.status === 'ACTIVE' ? I18n.t('Проверка чатов: ') + config.schedule_label + '.' : I18n.t('Страница обновляется автоматически. Фоновый сбор не настроен.')) +
    (checks.length ? I18n.t(' Последнее чтение источника: ') + time(checks[checks.length - 1], {hour:'2-digit',minute:'2-digit'}) + '.' : '') +
    (issues.length ? I18n.t(' Требуют сверки: ') + issues.length + '.' : '');
}
function safeToRefresh() {
  return WorkspaceRefresh.canRefresh({busy, pending:Boolean(pending), modalOpen:modal.open || document.querySelector('#action-dialog').open,
    editing:Boolean(document.activeElement?.matches('input, textarea, select, [contenteditable="true"]')), hidden:document.hidden});
}
async function refreshInBackground() {
  if (!state || loading || !safeToRefresh()) return;
  loading = true;
  const generation = stateGeneration;
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch('/api/workspace', {signal:controller.signal});
    if (!response.ok) throw new Error('Refresh failed');
    const incoming = await response.json();
    if (generation !== stateGeneration || !safeToRefresh()) return;
    if (WorkspaceRefresh.signature(incoming) !== WorkspaceRefresh.signature(state)) {
      const scroll = window.scrollY, search = document.querySelector('.search')?.value, taskFilter = document.querySelector('.task-filters select')?.value;
      const expanded = [...page.querySelectorAll('details')].map(d => d.open);
      state = incoming; stateGeneration += 1; render();
      const input = document.querySelector('.search');
      if (input && search) { input.value = search; input.dispatchEvent(new Event('input')); }
      const select = document.querySelector('.task-filters select');if(select && taskFilter){select.value=taskFilter;select.dispatchEvent(new Event('change'));}
      [...page.querySelectorAll('details')].forEach((d,i) => { d.open = Boolean(expanded[i]); });
      window.scrollTo(0,scroll);
    } else { state.token = incoming.token; if(location.hash==='#connection')render(); }
    syncStatus();
  } catch { if (generation === stateGeneration) syncStatus(true); }
  finally { clearTimeout(timeout); loading = false; }
}
document.querySelector('#refresh').addEventListener('click',()=>{if(busy)return;load().then(()=>{if(!pending)flash(I18n.t('Сохранённый контекст обновлён.'));}).catch(failure);});
document.querySelector('.skip-link').addEventListener('click',event=>{event.preventDefault();document.querySelector('#main').focus();});
window.addEventListener('hashchange',()=>{render();window.scrollTo(0,0);document.querySelector('#main').focus({preventScroll:true});});
document.addEventListener('visibilitychange',()=>{if (!document.hidden) refreshInBackground();});
window.addEventListener('focus',refreshInBackground);
setInterval(refreshInBackground,30000);
window.addEventListener('DOMContentLoaded',()=>load().catch(failure));

I18n.beforeChange = () => { if (busy || pending) { flash(I18n.t('Сначала подтверди предыдущую запись.'), true, Boolean(pending)); return false; } return true; };
