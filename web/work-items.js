"use strict";
const itemLabels={note:I18n.t('Мысль'),material:I18n.t('Материал'),question:I18n.t('Вопрос')};
function workItems(taskId) {
  return [...(state.workspace_items || [])].filter(r=>taskId===undefined || r.data.task_id===taskId)
    .sort((a,b)=>b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id));
}
function itemForm(category='note',task=null,item=null) {
  const d=item?.data || {}, fields=[{name:'title',label:category==='question' ? I18n.t('Какой вопрос нужно решить?') : category==='material' ? I18n.t('Название материала') : I18n.t('Что хочешь сохранить?'),type:'textarea',rows:2,max:300,value:d.title || ''},
    {name:'body',label:category==='material' ? I18n.t('Как использовать этот материал?') : I18n.t('Подробности, если нужны'),type:'textarea',max:8000,required:false,value:d.body || ''}];
  const taskOptions=state.tasks.map(t=>({value:t.id,label:t.data.title}));
  fields.push({name:'task_id',label:I18n.t('К какой задаче относится?'),type:'select',required:category!=='note',value:d.task_id || task?.id || '',
    options:[{value:'',label:category==='note' ? I18n.t('Пока без задачи') : I18n.t('Выбери задачу')},...taskOptions]});
  if(category==='material')fields.push({name:'url',label:I18n.t('Ссылка на материал или чат'),value:d.url || '',max:4000});
  if(category==='question')fields.push({name:'condition',label:I18n.t('Что позволит считать вопрос решённым?'),type:'textarea',value:d.condition || ''},
    {name:'depends_on_task_id',label:I18n.t('Зависит от другой задачи? Необязательно'),type:'select',required:false,value:d.depends_on_task_id || '',options:[{value:'',label:I18n.t('Без зависимости')},...taskOptions]});
  if(item)fields.push({name:'reason',label:I18n.t('Почему меняешь запись?'),type:'textarea',rows:2});
  actionForm(item ? I18n.t('Уточнить запись') : {note:I18n.t('Записать мысль'),material:I18n.t('Добавить материал'),question:I18n.t('Сохранить вопрос')}[category],fields,I18n.t('Сохранить'),(values,key)=>save({
    operation:'workspace-item',request_id:crypto.randomUUID(),id:item?.id,expected_revision:item?.revision,
    draft_key:key,after:location.hash || '#today',message:I18n.t('Запись сохранена. Текущий фокус не изменился.'),
    data:{action:item ? 'edit' : 'create',category,...values,task_id:values.task_id || null,depends_on_task_id:values.depends_on_task_id || null}}),
    item ? 'item-edit-'+item.id : 'item-new-'+category+'-'+(task?.id || 'inbox'),
    category==='material' ? I18n.t('HTTP(S) или ссылка Codex. Сохраняется ссылка; содержимое не загружается и не проверяется автоматически.') : I18n.t('Запись останется здесь. Она не создаёт задачу и не меняет результат дня.'),
    item ? {revision:item.revision,fields:fields.filter(f=>f.name!=='reason').map(f=>f.name)} : null);
}
function changeItem(item,action) {
  const captions={resolve:I18n.t('Зафиксировать решение'),archive:I18n.t('Убрать в архив'),reopen:I18n.t('Вернуть к работе')};
  const fields=action==='resolve' ? [{name:'resolution',label:I18n.t('Что решил? Как выполнено условие?'),type:'textarea',max:8000}] : [];
  fields.push({name:'reason',label:I18n.t('Основание изменения'),type:'textarea',rows:2,value:action==='resolve' ? I18n.t('Решение принято мной') : ''});
  actionForm(captions[action],fields,captions[action],(values,key)=>save({operation:'workspace-item',request_id:crypto.randomUUID(),id:item.id,
    expected_revision:item.revision,draft_key:key,after:location.hash || '#inbox',message:action==='resolve' ? I18n.t('Решение сохранено. Состояние задачи не изменилось.') : I18n.t('Состояние записи сохранено.'),
    data:{action,...values}}),'item-'+action+'-'+item.id+'-'+item.revision,
    I18n.t('История записи сохранится. Связанные задачи и рабочая сессия останутся без изменений.'));
}
function itemRow(item) {
  const d=item.data,row=el('article',undefined,'work-item');
  row.append(el('p',itemLabels[d.category]+' · '+time(item.updated_at,{hour:'2-digit',minute:'2-digit'})+' · '+({open:I18n.t('Сохранено'),resolved:I18n.t('Решено'),archived:I18n.t('В архиве')}[d.status]),'candidate-reason'),el('h3',d.title));
  if(d.body)row.append(el('p',d.body,'item-body'));
  if(d.url){const a=link(I18n.t('Открыть материал'),d.url,'text-link');a.target='_blank';a.rel='noopener noreferrer';row.append(a);}
  const task=state.tasks.find(t=>t.id===d.task_id);if(task)row.append(link(I18n.t('Задача: ')+task.data.title,'#task/'+task.id,'text-link plan-link'));
  if(d.condition)row.append(el('p',I18n.t('Условие решения: ')+d.condition,'item-body'));
  if(d.depends_on_task_id){const dependency=state.tasks.find(t=>t.id===d.depends_on_task_id);if(dependency)row.append(link(I18n.t('Зависит от: ')+dependency.data.title+' ('+(dependency.data.deferred ? I18n.t('позже') : taskLabels[dependency.data.status])+')','#task/'+dependency.id,'text-link plan-link'));
    row.append(el('p',I18n.t('Состояние зависимости не закрывает вопрос автоматически.'),'hint'));}
  if(d.resolution)row.append(el('p',I18n.t('Решение: ')+d.resolution,'session-note item-body'));
  const actions=el('div',undefined,'item-actions');
  if(d.status==='open'){
    if(d.category==='question')actions.append(button(I18n.t('Зафиксировать решение'),()=>changeItem(item,'resolve'),'secondary'));
    actions.append(button(d.category==='note' && !task ? I18n.t('Уточнить / связать с задачей') : I18n.t('Уточнить'),()=>itemForm(d.category,task,item),'quiet'));
  } else actions.append(button(I18n.t('Вернуть к работе'),()=>changeItem(item,'reopen'),'quiet'));
  if(d.status!=='archived')actions.append(button(I18n.t('В архив'),()=>changeItem(item,'archive'),'quiet'));
  row.append(actions);
  const history=state.item_history?.[item.id] || [];
  if(history.length>1){const detail=el('details');detail.append(el('summary',I18n.t('История записи')));
    for(const version of [...history].reverse()){const v=version.data,entry=el('section',undefined,'change-entry');entry.append(el('h3',time(version.at,{hour:'2-digit',minute:'2-digit'})+' · '+v.title),el('p',v.body || ''));
      if(v.url)entry.append(el('p',v.url));if(v.condition)entry.append(el('p',v.condition));if(v.resolution)entry.append(el('p',I18n.t('Решение: ')+v.resolution));if(v.change_reason)entry.append(el('p',v.change_reason));detail.append(entry);}
    row.append(detail);}
  return row;
}
function taskItems(task,container,compact=false) {
  const items=workItems(task.id),section=el('section',undefined,'task-materials');
  section.append(el('h2',I18n.t('Материалы и открытые вопросы')));
  const actions=el('div',undefined,'item-actions');
  for(const [category,label] of [['material',I18n.t('Добавить материал')],['question',I18n.t('Сохранить вопрос')],['note',I18n.t('Записать мысль')]])actions.append(button(label,()=>itemForm(category,task),'quiet'));
  section.append(actions);
  const open=items.filter(r=>r.data.status==='open');
  if(!open.length)section.append(el('p',I18n.t('Сохрани нужную ссылку или вопрос, чтобы не искать их в чатах в следующий раз.'),'hint'));
  for(const item of open)section.append(itemRow(item));
  const closed=items.filter(r=>r.data.status!=='open');
  if(closed.length){const details=el('details');details.append(el('summary',I18n.t('Принятые решения и архив')));for(const item of closed)details.append(itemRow(item));section.append(details);}
  if(compact){const details=el('details');details.open=open.length>0;details.append(el('summary',I18n.t('Материалы, мысли и вопросы этой задачи')),section);container.append(details);}
  else container.append(section);
}
function returnToTask(task,container) {
  const last=recent(task.id);if(!last)return;
  const section=el('section',undefined,'return-point');
  section.append(el('h2',I18n.t('Где остановился')),el('p',time(last.data.ended_at,{hour:'2-digit',minute:'2-digit'})+I18n.t(' · Итог сессии'),'hint'),el('p',last.data.note,'item-body'));
  if(last.data.next_action){section.append(el('h3',I18n.t('Точка продолжения')),el('p',last.data.next_action,'return-step'));
    if(last.data.task_revision!==task.revision)section.append(el('p',I18n.t('Задача обновлялась после этой сессии. Проверь сохранённый шаг перед продолжением.'),'hint'));
    if(available(task))section.append(button(I18n.t('Продолжить с этого шага'),()=>pick(taskStream(task),task,null,null,last),'primary'));
    else section.append(el('p',I18n.t('Для новой сессии сначала верни задачу в доступные.'),'hint'));
  } else section.append(el('p',I18n.t('Следующий шаг не был сохранён. Начни новую сессию с текущего шага задачи.'),'hint'));
  const chat=chatLink(I18n.t('Текущий рабочий чат'),task.data.chat_url);if(chat)section.append(chat);
  container.append(section);
}
function inboxPage() {
  page.append(el('h1',I18n.t('Мысли могут подождать.'),'heading'),el('p',I18n.t('Запиши сейчас, разбери позже. Текущая работа остаётся в фокусе.'),'intro'),button(I18n.t('Записать мысль'),()=>itemForm(),'primary'));
  const controls=el('div',undefined,'task-filters'),search=el('input',undefined,'search'),filter=el('select');search.type='search';search.placeholder=I18n.t('Найти мысль');search.setAttribute('aria-label',I18n.t('Поиск мыслей'));filter.setAttribute('aria-label',I18n.t('Состояние входящих'));
  for(const [value,label] of [['open',I18n.t('Открытые')],['unassigned',I18n.t('Без задачи')],['archived',I18n.t('Архив')],['all',I18n.t('Все мысли')]]){const o=el('option',label);o.value=value;filter.append(o);}
  controls.append(search,filter);const rows=el('div');page.append(controls,rows);
  function draw(){rows.replaceChildren();const q=search.value.toLocaleLowerCase(I18n.locale);
    const items=workItems().filter(r=>r.data.category==='note' && (filter.value==='all' || filter.value==='unassigned' && r.data.status==='open' && !r.data.task_id || r.data.status===filter.value) && [r.data.title,r.data.body].join(' ').toLocaleLowerCase(I18n.locale).includes(q));
    for(const item of items)rows.append(itemRow(item));if(!items.length)rows.append(el('p',I18n.t('Здесь пока пусто. Новая мысль может остаться без задачи до разбора.'),'hint'));}
  search.addEventListener('input',draw);filter.addEventListener('change',draw);draw();
}
document.querySelector('#capture-thought').addEventListener('click',()=>{if(state)itemForm();});
