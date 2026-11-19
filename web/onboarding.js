"use strict";
// Use the existing draft/retry path for setup and creation, including uncertain saves.
function setupPage() {
  const box=el('section',undefined,'onboarding');
  box.append(el('h1',I18n.t('Начни со своего пространства.')),el('p',I18n.t('Здесь будут твои направления, задачи и один выбранный результат на сегодня. Всё сохраняется на этом компьютере.'),'intro'));
  const form=el('form'), key='workspace-setup-draft', draft=stored(key) || {};
  const name=el('input'),zone=el('input');name.required=true;name.maxLength=100;name.id='setup-name';name.autocomplete='given-name';name.value=draft.display_name || '';
  zone.required=true;zone.id='setup-timezone';zone.value=draft.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const nameLabel=el('label',I18n.t('Как тебя называть?')),zoneLabel=el('label',I18n.t('Часовой пояс'));nameLabel.append(name);zoneLabel.append(zone);
  const values=()=>({display_name:name.value.trim(),timezone:zone.value.trim()});
  form.addEventListener('input',()=>persist(key,values()));
  const submit=el('button',I18n.t('Создать пространство'),'primary');submit.type='submit';submit.dataset.save='true';
  form.append(nameLabel,zoneLabel,el('p',I18n.t('Например: Europe/Paris или America/New_York. Часовой пояс определяет, когда начинается новый день.'),'hint'),submit);
  form.addEventListener('submit',event=>{event.preventDefault();if(busy)return;if(pending){save(pending);return;}persist(key,values());save({operation:'setup',request_id:crypto.randomUUID(),data:values(),draft_key:key,after:'#home',message:I18n.t('Пространство готово. Добавь первое направление.')});});
  box.append(form,el('p',I18n.t('Для начала не нужны календарь, подписка на AI или доступ к чатам. Их можно настроить отдельно.'),'hint'));page.append(box);
  document.title=I18n.t('Первый запуск — Моё пространство');
}
function welcomePage() {
  const box=el('section',undefined,'onboarding');
  box.append(el('h1',state.display_name ? state.display_name+I18n.t(', с чего начнём?') : I18n.t('Одно направление для начала.')),el('p',I18n.t('Направление объединяет задачи вокруг того, что для тебя важно: работа, свой проект, обучение или личные дела.'),'intro'),el('ol',undefined,'onboarding-steps'));
  const steps=box.querySelector('ol');for(const text of [I18n.t('Создай направление и опиши желаемый результат.'),I18n.t('Добавь задачу с понятным первым шагом.'),I18n.t('Выбери её на сегодня и начни сессию.')])steps.append(el('li',text));
  box.append(button(I18n.t('Создать направление'),()=>createDirection(),'primary'),el('p',I18n.t('Можно начать с одного направления и добавить остальные позже.'),'hint'));page.append(box);
}
function createDirection() {
  actionForm(I18n.t('Новое направление'),[
    {name:'title',label:I18n.t('Название направления'),max:160},
    {name:'outcome',label:I18n.t('Какой результат хочешь получить?'),type:'textarea',max:2000},
    {name:'color',label:I18n.t('Цвет карточки'),type:'select',value:'lilac',options:[['lilac',I18n.t('Сиреневый')],['mint',I18n.t('Мятный')],['peach',I18n.t('Персиковый')],['blue',I18n.t('Голубой')],['rose',I18n.t('Розовый')],['sand',I18n.t('Песочный')],['teal',I18n.t('Бирюзовый')],['slate',I18n.t('Серый')]].map(([value,label])=>({value,label}))}
  ],I18n.t('Создать направление'),(data,key)=>save({operation:'create-workstream',request_id:crypto.randomUUID(),data,draft_key:key,after:'#project/{id}',message:I18n.t('Направление создано. Теперь добавь задачу.')}),'new-direction',I18n.t('Например: «Изучить испанский» и «Поддерживать разговор в поездке».'));
}
function createTask(stream=null) {
  const choices=streams();if(!choices.length){createDirection();return;}
  actionForm(I18n.t('Новая задача'),[
    {name:'workstream_id',label:I18n.t('Направление'),type:'select',value:stream?.id || choices[0].id,options:choices.map(s=>({value:s.id,label:s.data.title}))},
    {name:'title',label:I18n.t('Что хочешь сделать?'),max:2000},
    {name:'next_action',label:I18n.t('С какого конкретного шага начнёшь?'),type:'textarea',max:4000}
  ],I18n.t('Добавить задачу'),(data,key)=>save({operation:'create-task',request_id:crypto.randomUUID(),data,draft_key:key,after:'#task/{id}',message:I18n.t('Задача добавлена. Можно выбрать её на сегодня.')}),'new-task-'+(stream?.id || 'any'),I18n.t('Задача останется доступной. Добавление не выбирает её на сегодня и не бронирует время.'));
}
function firstTaskPage() {
  const box=el('section',undefined,'onboarding');box.append(el('h1',I18n.t('Теперь — первая задача.')),el('p',I18n.t('Выбери небольшое действие, которое продвинет твоё направление. Укажи первый шаг, чтобы было проще начать.'),'intro'),button(I18n.t('Добавить задачу'),()=>createTask(),'primary'),link(I18n.t('Все направления'),'#home','text-link'));page.append(box);
}
