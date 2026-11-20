"use strict";
const actionDialog = document.querySelector('#action-dialog');
const taskLabels = {candidate:I18n.t('Вариант'),ready:I18n.t('Можно начать'),doing:I18n.t('Начата'),waiting:I18n.t('Жду'),done:I18n.t('Готово'),dropped:I18n.t('Отказался')};
function taskStream(task) { return TodayModel.streamFor(state,task); }
function currentChoice() { return TodayModel.choice(state); }
function available(task) { return TodayModel.bucket(task)==='available'; }
function actionForm(title, fields, submitText, submit, key, help, editRevision=null) {
  if(busy)return;
  if(pending){flash(I18n.t('Сначала подтверди предыдущую запись.'),true,true);return;}
  const form=el('form'),head=el('div',undefined,'dialog-top'),heading=el('h2',title);heading.id='action-title';
  head.append(heading,button(I18n.t('Закрыть'),()=>{if(!busy)actionDialog.close();},'quiet'));form.append(head);
  const draft=stored(key),inputs={},conflicts=[];
  const editFields=typeof editRevision==='object' && editRevision ? editRevision.fields : ['title','next_action','chat_url'];
  const draftRevision=typeof editRevision==='object' && editRevision ? editRevision.revision : editRevision;
  const base={}, restored=draft?.version===2 ? draft.values : draft;
  for(const field of fields){
    const label=el('label',field.label), input=el(field.type==='select' ? 'select' : field.type==='textarea' ? 'textarea' : 'input');
    if(field.type==='select')for(const option of field.options){const o=el('option',option.label);o.value=option.value;input.append(o);}
    else if(field.type==='textarea'){input.rows=field.rows || 3;input.maxLength=field.max || 4000;}
    else{input.type=field.type || 'text';input.maxLength=field.max || 2000;}
    input.name=field.name;input.id='action-field-'+field.name;input.required=field.required!==false;
    const current=field.value ?? '', saved=restored?.[field.name];
    let value=saved ?? current;
    if(editRevision!==null && editFields.includes(field.name)){
      const original=draft?.version===2 ? draft.base?.[field.name] : undefined;
      const touched=saved!==undefined && saved!==original;
      value=touched ? saved : current;
      base[field.name]=touched ? original : current;
      if(touched && current!==original && current!==saved){
        const conflict=el('section',undefined,'session-note');
        conflict.append(el('p',field.label+I18n.t(' изменилось, пока черновик был открыт.')),
          el('p',I18n.t('Сейчас сохранено: ')+(current || I18n.t('не указано'))),el('p',I18n.t('В черновике: ')+(saved || I18n.t('не указано'))));
        const resolution=el('select');resolution.required=true;resolution.setAttribute('aria-label',I18n.t('Разрешить конфликт: ')+field.label);
        for(const [value,text] of [['',I18n.t('Выбери, какой вариант оставить')],['current',I18n.t('Оставить сохранённый вариант')],['draft',I18n.t('Использовать мой черновик')]]){const o=el('option',text);o.value=value;resolution.append(o);}
        resolution.value='';resolution.addEventListener('change',()=>{input.value=resolution.value==='current' ? current : saved;remember();});
        conflict.append(resolution);form.append(conflict);conflicts.push(resolution);
      }
    }
    input.value=value;inputs[field.name]=input;label.append(input);form.append(label);
  }
  const values=()=>Object.fromEntries(Object.entries(inputs).map(([key,input])=>[key,input.value.trim()]));
  const remember=()=>persist(key,editRevision===null ? values() : {version:2,revision:draftRevision,base,values:values()});
  form.addEventListener('input',remember);
  if(help)form.append(el('p',help,'hint'));
  const saveButton=el('button',submitText,'primary');saveButton.type='submit';form.append(saveButton);
  form.addEventListener('submit',event=>{event.preventDefault();if(busy)return;if(conflicts.some(input=>!input.value)){flash(I18n.t('Выбери вариант для каждого изменившегося поля.'),true);return;}remember();submit(values(),key);});
  actionDialog.replaceChildren(form);actionDialog.showModal();Object.values(inputs)[0]?.focus();
}
actionDialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});

function chooseResult(task, planning=null, previous=null) {
  if(!available(task)){location.hash='#task/'+task.id;return;}
  const stream=taskStream(task), brief=shortTask(stream,task), chosenToday=currentChoice();
  // Matching a particular card uses its explicit workstream, even if the task belongs to several.
  const selectedStream=planning ? state.workstreams.find(s=>s.id===planning.card.workstream_id) : stream;
  actionForm(I18n.t('Результат на сегодня'),[
    {name:'target',label:I18n.t('Что будет достаточным результатом?'),type:'textarea',value:previous?.target || planning?.card.outcome || brief.result,max:2000},
    {name:'first_action',label:I18n.t('С чего начнёшь?'),type:'textarea',value:previous?.first_action || planning?.card.first_action || recent(task.id)?.data.next_action || task.data.next_action},
    {name:'reason',label:I18n.t('Почему выбираешь это сейчас?'),type:'textarea',value:previous?.reason || I18n.t('Мой выбор на сегодня'),rows:2}
  ],chosenToday?.data.status==='selected' ? I18n.t('Сменить результат дня') : I18n.t('Выбрать на сегодня'),(values,key)=>{
    save({operation:'day-choice',request_id:crypto.randomUUID(),id:chosenToday?.id,expected_revision:chosenToday?.revision || 0,
      draft_key:key,after:'#today',message:I18n.t('Результат дня сохранён. Можно перейти к работе.'),data:{action:'choose',date:state.today,
        task_id:task.id,task_revision:task.revision,workstream_id:selectedStream?.id || null,...values,
        ...(planning ? {planner_id:planning.board.id,planner_revision:planning.board.revision,planner_card_id:planning.card.id} : {})}});
  },'day-draft-'+state.today+'-'+task.id,I18n.t('Это локальный выбор без временного слота. Другие задачи останутся на своих местах.'));
}
function clearChoice(choice) {
  actionForm(I18n.t('Убрать результат дня'),[{name:'reason',label:I18n.t('Что изменилось?'),type:'textarea',value:I18n.t('Сейчас не выбираю результат дня')}],
    I18n.t('Убрать выбор'),(values,key)=>save({operation:'day-choice',request_id:crypto.randomUUID(),id:choice.id,expected_revision:choice.revision,
      draft_key:key,after:'#today',message:I18n.t('Выбор дня снят. Задача сохранена.'),data:{action:'clear',date:state.today,...values}}),
    'clear-day-'+choice.id,I18n.t('Это не удаляет задачу и не завершает рабочую сессию.'));
}
function refineChoice(choice, task) {
  const board=state.planners.find(b=>b.id===choice.data.planner_id);
  const card=board?.data.cards.find(c=>c.id===choice.data.planner_card_id && c.task_id===task.id && c.selected);
  chooseResult(task,card ? {board,card} : null,choice.data);
}
function controlTask(task, action) {
  const captions={edit:I18n.t('Исправить задачу'),later:I18n.t('Оставить на потом'),wait:I18n.t('Отметить ожидание'),done:I18n.t('Завершить задачу'),drop:I18n.t('Отказаться от задачи'),restore:I18n.t('Вернуть в доступные')};
  const fields=action==='edit' ? [
    {name:'title',label:I18n.t('Название задачи'),value:task.data.title},
    {name:'next_action',label:I18n.t('Первый шаг'),type:'textarea',value:task.data.next_action || ''},
    {name:'chat_url',label:I18n.t('Ссылка на рабочий чат Codex'),value:task.data.chat_url || '',required:false}
  ] : [];
  if(action==='later')fields.push({name:'until',label:I18n.t('Когда вернуться к выбору? Необязательно'),type:'date',value:task.data.deferred_until || '',required:false});
  fields.push({name:'reason',label:action==='done' ? I18n.t('Что готово? Зафиксируй результат') : action==='wait' ? I18n.t('Кого или чего ждёшь? Когда вернёшься к вопросу?') : I18n.t('Что изменилось?'),type:'textarea'});
  actionForm(captions[action],fields,action==='edit' ? I18n.t('Сохранить исправление') : captions[action],(values,key)=>{
    const data={action,reason:values.reason};
    if(action==='edit'){
      data.values=Object.fromEntries(['title','next_action','chat_url'].filter(field=>values[field] !== (task.data[field] || '')).map(field=>[field,values[field]]));
      if(!Object.keys(data.values).length){persist(key,null);actionDialog.close();flash(I18n.t('Текст задачи не изменился.'));return;}
    }
    if(action==='later')data.until=values.until || null;
    save({operation:'task-control',request_id:crypto.randomUUID(),id:task.id,expected_revision:task.revision,data,
      draft_key:key,after:'#task/'+task.id,message:I18n.t('Изменение задачи сохранено.')});
  },'task-draft-'+task.id+'-'+action,I18n.t('Твоё решение сохранится при фоновых обновлениях. Историю можно посмотреть в задаче.'),action==='edit' ? task.revision : null);
}
function linkPlanCard(board,card) {
  const eligible=state.tasks.filter(t=>available(t));
  actionForm(I18n.t('Связать карточку с задачей'),[
    {name:'task_id',label:I18n.t('Какой задаче соответствует этот результат?'),type:'select',value:eligible.some(t=>t.id===card.task_id) ? card.task_id : '',options:[{value:'',label:I18n.t('Выбери задачу')}, {value:'__unlink__',label:I18n.t('Снять связь с задачей и направлением')},...eligible.map(t=>({value:t.id,label:(taskStream(t)?.data.title || I18n.t('Без направления'))+' · '+t.data.title}))]},
    {name:'reason',label:I18n.t('Почему меняешь связь?'),type:'textarea',value:I18n.t('Подтверждаю изменение связи карточки')}
  ],I18n.t('Сохранить связь'),(values,key)=>{
    const unlink=values.task_id==='__unlink__',task=eligible.find(t=>t.id===values.task_id);if(!unlink && !task)return;
    const previousStream=state.workstreams.find(s=>s.id===card.workstream_id && s.data.task_ids.includes(task?.id));
    const stream=unlink ? null : previousStream?.id || taskStream(task)?.id || null;
    save({operation:'link-card',request_id:crypto.randomUUID(),id:board.id,expected_revision:board.revision,
      draft_key:key,after:'#planned/'+board.id+'/'+card.id,message:unlink ? I18n.t('Связь снята. Карточка, выбор и время сохранены.') : I18n.t('Карточка связана с задачей. Выбор и время сохранены.'),
      data:{links:[{card_id:card.id,task_id:task?.id || null,task_revision:task?.revision || null,workstream_id:stream,reason:values.reason}]}});
  },'link-draft-'+board.id+'-'+card.id,I18n.t('Направление связи будет взято из выбранной задачи. Текст карточки, выбор и время сохранятся.'));
}
function candidateRow(candidate) {
  const {task,stream,reasons}=candidate, brief=shortTask(stream,task), row=el('article',undefined,'candidate-row '+(stream?.data.color || 'slate'));
  const body=el('div');body.append(el('span',stream?.data.title || I18n.t('Без направления'),'candidate-project'),link(brief.title,'#task/'+task.id,'candidate-title'),el('p',reasons.map(reason=>reason.replace(/[.。]+$/,'')).join('. '),'candidate-reason'));
  row.append(body,button(I18n.t('На сегодня'),()=>chooseResult(task),'secondary'));return row;
}
function todayPage() {
  if(!state.tasks.length){firstTaskPage();return;}
  const choice=currentChoice(), chosen=choice?.data.status==='selected' ? choice : null, session=active();
  page.append(el('h1',I18n.t('Сегодня — один результат.'),'heading'),el('p',I18n.t('Выбери, что хочешь продвинуть. Остальное останется доступным.'),'intro'));
  if(session){const band=el('section',undefined,'focus-band');const text=el('div');text.append(el('h2',I18n.t('Сессия уже идёт')),el('p',session.data.target));band.append(text,link(I18n.t('Вернуться к работе'),'#focus','primary'));page.append(band);}
  const layout=el('div',undefined,'today-layout'),main=el('div'),aside=el('aside',undefined,'today-aside');
  const hero=el('section',undefined,'day-result');
  if(chosen){
    const d=chosen.data,task=state.tasks.find(t=>t.id===d.task_id),stream=state.workstreams.find(s=>s.id===d.workstream_id);
    hero.classList.add(stream?.data.color || 'lilac');hero.append(el('span',stream?.data.title || I18n.t('Мой выбор'),'candidate-project'),el('h2',d.target),el('p',I18n.t('Первый шаг: ')+d.first_action));
    hero.append(el('p',d.reason,'day-reason'));
    const controls=el('div',undefined,'day-actions');
    if(task && available(task) && !session)controls.append(button(I18n.t('Начать сессию'),()=>pick(stream,task,null,chosen),'primary'));
    if(task)controls.append(link(I18n.t('Открыть задачу'),'#task/'+task.id,'secondary'));
    if(task && available(task))controls.append(button(I18n.t('Уточнить результат'),()=>refineChoice(chosen,task),'quiet'));
    controls.append(button(I18n.t('Убрать выбор'),()=>clearChoice(chosen),'quiet'));hero.append(controls);
    if(task && task.revision!==d.task_revision)hero.append(el('p',I18n.t('Задача обновилась после выбора. Результат дня сохранён; проверь первый шаг перед началом.'),'hint'));
    if(task && !available(task))hero.append(el('p',I18n.t('Задача сейчас ')+(task.data.deferred ? I18n.t('отложена') : {done:I18n.t('завершена'),dropped:I18n.t('снята'),waiting:I18n.t('ожидает ответа')}[task.data.status])+I18n.t('. Выбор дня сохранён; можно выбрать другой результат.'),'hint'));
    const outcomes=state.sessions.filter(s=>s.data.day_choice_id===chosen.id && s.data.day_choice_revision===chosen.revision && s.data.status==='closed').sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
    if(outcomes.length){const last=outcomes[0];hero.append(el('p',I18n.t('Последний итог: ')+last.data.note,'session-note'));if(last.data.next_action)hero.append(el('p',I18n.t('Продолжить: ')+last.data.next_action,'hint'));}
  }else{
    hero.classList.add('is-empty');
    hero.append(el('h2',I18n.t('Какой результат хочешь получить сегодня?')),el('p',I18n.t('Выбери задачу ниже и уточни, что хочешь получить. Можно начать с небольшого результата.')),link(I18n.t('Все задачи'),'#tasks','secondary'));
  }
  main.append(hero);
  const changes=state.day_history?.[choice?.id] || [];
  if(changes.length>1){const log=el('details',undefined,'day-choice-history');log.append(el('summary',I18n.t('Как менялся выбор дня')));for(const v of [...changes].reverse()){const item=el('div',undefined,'change-entry');item.append(el('p',time(v.at,{hour:'2-digit',minute:'2-digit'})+' · '+(v.status==='cleared' ? I18n.t('Выбор снят') : v.target)),el('p',v.reason,'hint'));log.append(item);}main.append(log);}
  const candidates=TodayModel.candidates(state).filter(c=>c.task.id!==chosen?.data.task_id);
  const options=chosen ? el('details',undefined,'today-alternatives') : el('section');
  if(chosen)options.append(el('summary',I18n.t('Другие варианты — сменить результат')));
  else options.append(el('h2',I18n.t('От чего можно оттолкнуться'),'section-title'));
  options.append(el('p',I18n.t('Основания из сохранённого контекста. Порядок не задаёт твой приоритет и не оценивает свободное время.'),'hint'));
  for(const candidate of candidates.slice(0,5))options.append(candidateRow(candidate));
  if(!candidates.length)options.append(el('p',I18n.t('Других доступных задач пока нет. Посмотри ожидания и отложенные задачи.'),'hint'));
  options.append(link(I18n.t('Посмотреть все задачи'),'#tasks','text-link plan-link'));main.append(options);
  const week=el('section',undefined,'today-side-section');week.append(el('h2',I18n.t('Из недельного плана')));
  const cards=(state.relationships?.cards || []).filter(c=>c.selected && state.planners.some(b=>b.id===c.planner_id && b.data.week_start<=state.today && state.today<=TodayModel.weekEnd(b.data.week_start)));
  for(const card of cards.slice(0,5))week.append(link(card.title,'#planned/'+card.planner_id+'/'+card.card_id,'text-link plan-link'),el('p',card.placement ? I18n.t('В плане: ')+card.placement.date : I18n.t('Выбрано без даты'),'hint'));
  if(!cards.length)week.append(el('p',I18n.t('На этой неделе пока нет выбранных карточек.'),'hint'));
  week.append(link(I18n.t('Открыть неделю'),'#weeks','secondary'));aside.append(week);
  const previous=(state.day_choices || []).find(r=>r.data.date<state.today && r.data.status==='selected');
  if(previous){const box=el('section',undefined,'today-side-section');box.append(el('h2',I18n.t('Предыдущий выбор')),el('p',previous.data.target),el('p',previous.data.date+I18n.t('. На сегодня автоматически не перенесён.'),'hint'));const t=state.tasks.find(t=>t.id===previous.data.task_id);if(t && available(t))box.append(button(I18n.t('Выбрать снова'),()=>chooseResult(t,null,previous.data),'secondary'));aside.append(box);}
  const parked=el('section',undefined,'today-side-section');parked.append(el('h2',I18n.t('Остальное подождёт')),el('p',I18n.t('Ожидания и отложенные задачи можно вернуть, когда решишь к ним обратиться.'),'hint'),link(I18n.t('Открыть задачи'),'#tasks','text-link'));aside.append(parked);
  layout.append(main,aside);page.append(layout);
}
function taskList() {
  page.append(el('h1',I18n.t('Задачи, которыми управляешь ты.'),'heading'));
  page.append(button(I18n.t('Добавить задачу'),()=>createTask(),'primary'));
  const controls=el('div',undefined,'task-filters'),search=el('input',undefined,'search');search.type='search';search.placeholder=I18n.t('Найти задачу');search.setAttribute('aria-label',I18n.t('Поиск задач'));
  const filter=el('select');filter.setAttribute('aria-label',I18n.t('Состояние задач'));for(const [value,label] of [['available',I18n.t('Можно начать')],['later',I18n.t('Позже')],['waiting',I18n.t('Жду')],['closed',I18n.t('Завершённые и отменённые')],['unassigned',I18n.t('Без направления')],['all',I18n.t('Все задачи')]]){const o=el('option',label);o.value=value;filter.append(o);}
  controls.append(search,filter);const rows=el('div');page.append(controls,rows);
  function draw(){rows.replaceChildren();const query=search.value.toLocaleLowerCase(I18n.locale);const found=state.tasks.filter(t=>(filter.value==='all' || filter.value==='unassigned' && !taskStream(t) || TodayModel.bucket(t)===filter.value) && [t.data.title,t.data.next_action,taskStream(t)?.data.title].join(' ').toLocaleLowerCase(I18n.locale).includes(query));
    for(const task of found){const stream=taskStream(task),row=el('article',undefined,'candidate-row '+(stream?.data.color || 'slate')),body=el('div');body.append(el('span',stream?.data.title || I18n.t('Без направления'),'candidate-project'),link(shortTask(stream,task).title,'#task/'+task.id,'candidate-title'),el('p',task.data.deferred ? I18n.t('Позже')+(task.data.deferred_until ? I18n.t(' · пересмотреть ')+task.data.deferred_until : '') : taskLabels[task.data.status],'candidate-reason'));row.append(body,link(I18n.t('Открыть'),'#task/'+task.id,'secondary'));rows.append(row);}
    if(!found.length)rows.append(el('p',I18n.t('Здесь пока нет задач. Попробуй другой фильтр.'),'intro'));
  }
  search.addEventListener('input',draw);filter.addEventListener('change',draw);draw();
}
function taskDetail(id) {
  const task=state.tasks.find(t=>t.id===id);if(!task)return empty(I18n.t('Задача не найдена'),I18n.t('Обнови контекст и открой список задач.'));
  const d=task.data,stream=taskStream(task);page.append(link(I18n.t('Все задачи'),'#tasks','breadcrumb'),el('h1',d.title),el('p',stream?.data.title || I18n.t('Без направления'),'intro'));
  const box=el('section',undefined,'task-detail');box.append(el('span',d.deferred ? I18n.t('Позже') : taskLabels[d.status],'pill'),el('h2',I18n.t('Следующий шаг')),el('p',d.next_action || I18n.t('Первый шаг не указан')));
  if(d.status==='waiting')box.append(el('p',I18n.t('Жду: ')+d.waiting_on,'session-note'));
  if(d.status==='done')box.append(el('p',I18n.t('Результат: ')+d.completion_evidence,'session-note'));
  if(d.deferred)box.append(el('p',d.deferred_until ? I18n.t('Вернуться к выбору ')+d.deferred_until+I18n.t('. Автоматического переноса в день нет.') : I18n.t('Без даты возвращения.'),'hint'));
  const controls=el('div',undefined,'day-actions');
  if(available(task)){controls.append(button(I18n.t('Выбрать на сегодня'),()=>chooseResult(task),'primary'),button(I18n.t('Начать сессию'),()=>pick(stream,task),'secondary'));}
  else controls.append(button(I18n.t('Вернуть в доступные'),()=>controlTask(task,'restore'),'secondary'));
  controls.append(button(I18n.t('Исправить'),()=>controlTask(task,'edit'),'secondary'));
  const chat=chatLink(I18n.t('Открыть рабочий чат'),d.chat_url);if(chat)controls.append(chat);box.append(controls);
  const actions=el('div',undefined,'task-secondary-actions');
  if(!['done','dropped'].includes(d.status))for(const [action,label] of [['later',I18n.t('Позже')],['wait',I18n.t('Жду')],['done',I18n.t('Завершить')],['drop',I18n.t('Отказаться')]])actions.append(button(label,()=>controlTask(task,action),'quiet'));
  box.append(actions);if(d.user_control)box.append(el('p',I18n.t('Твоё решение: ')+d.user_control.reason+I18n.t('\nСохранено ')+time(d.user_control.at),'hint'));page.append(box);
  returnToTask(task,page);
  taskItems(task,page);
  for(const card of state.relationships?.cards || [])if(card.task_id===id)page.append(link(I18n.t('Карточка плана: ')+card.title,'#planned/'+card.planner_id+'/'+card.card_id,'text-link plan-link'));
  const details=el('details',undefined,'task-audit');details.append(el('summary',I18n.t('История изменений и основание')),el('p',d.rationale || ''));
  const fieldNames={title:I18n.t('Название'),next_action:I18n.t('Первый шаг'),status:I18n.t('Состояние'),intent:I18n.t('Основание состояния'),waiting_on:I18n.t('Ожидание'),completion_evidence:I18n.t('Результат'),deferred:I18n.t('Отложено'),deferred_until:I18n.t('Дата возвращения'),chat_url:I18n.t('Рабочий чат'),rationale:I18n.t('Основание'),attention_date:I18n.t('Дата внимания'),date_basis:I18n.t('Основание даты'),priority:I18n.t('Сохранённый приоритет')};
  for(const change of [...(state.task_history?.[id] || [])].reverse()){
    const item=el('section',undefined,'change-entry');item.append(el('h3',time(change.at,{hour:'2-digit',minute:'2-digit'})+' · '+(change.source_kind==='agent_generated' ? I18n.t('Сверка контекста') : I18n.t('Сохранённое решение'))));
    if(change.reason)item.append(el('p',change.reason));
    for(const [key,value] of Object.entries(change.changes)){const show=v=>v==null || v==='' ? I18n.t('не указано') : key==='status' ? taskLabels[v] || v : typeof v==='boolean' ? (v ? I18n.t('да') : I18n.t('нет')) : key==='intent' ? (v==='reported' ? I18n.t('зафиксировано по сообщению') : I18n.t('предложение')) : v;item.append(el('p',(fieldNames[key] || key)+': '+show(value.before)+' → '+show(value.after)));}
    details.append(item);
  }
  page.append(details);
}
