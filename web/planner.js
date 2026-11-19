'use strict';
const $ = id => document.getElementById(id);
const M = {...window.PlannerModel, duration(n) { return n < 60 ? n + ' ' + I18n.t('minute-short') : Math.floor(n / 60) + ' ' + I18n.t('hour-short') + (n % 60 ? ' ' + n % 60 + ' ' + I18n.t('minute-short') : ''); }};
let record, token, mode = 'week', activeDate, editingId, pending = null, busy = false;
const boardId = new URLSearchParams(location.search).get('board');
const boardEndpoint = '/api/board' + (boardId ? '?board=' + encodeURIComponent(boardId) : '');
let workspaceUrl = 'http://127.0.0.1:8770/';
let hourStart = 420, hourEnd = 1380;
let activeDrag = null, dropPreview = null, activeResize = null;
const el = (tag, cls, text) => { const e = document.createElement(tag); if(cls)e.className=cls; if(text!==undefined)e.textContent=text; return e; };
const dateLabel = (date, opts={weekday:'short',day:'numeric',month:'short'}) => new Intl.DateTimeFormat(I18n.locale,{...opts,timeZone:'UTC'}).format(new Date(date+'T12:00:00Z'));
const todayDate = () => new Intl.DateTimeFormat('en-CA',{timeZone:record?.data.timezone || 'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const cardById = id => record.data.cards.find(c => c.id===id);
function toast(text){$('toast').textContent=text;$('toast').style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('toast').style.display='none',2800);}
function updateSaveState(text){$('save-state').textContent=text;}
function setBusy(value){busy=value;document.body.classList.toggle('saving',value);document.querySelectorAll('#card-form button,#add-task').forEach(e=>e.disabled=value);}
async function load(){
  const response=await fetch(boardEndpoint); if(!response.ok)throw new Error(I18n.t('Could not load saved choices.'));
  const result=await response.json();record=result.record;token=result.token;
  workspaceUrl=result.workspace_url||workspaceUrl;
  const dates=M.dates(record.data.week_start);activeDate=dates.includes(todayDate())?todayDate():dates[0];
  const projects=M.projects(record.data.cards);
  $('project-filter').replaceChildren(new Option(I18n.t('All projects'),''),...projects.map(p=>new Option(p === 'Other' ? I18n.t('Other') : p,p)));
  $('edit-project').replaceChildren(...(projects.length ? projects : ['Other']).map(p=>new Option(p === 'Other' ? I18n.t('Other') : p,p)));
  $('day-picker').replaceChildren(...dates.map(d=>new Option(dateLabel(d),d)));
  $('edit-day').replaceChildren(new Option(I18n.t('Not placed'),''),...dates.map(d=>new Option(dateLabel(d),d)));
  $('week-title').textContent=`${Number(dates[0].slice(-2))}–${dateLabel(dates[6],{day:'numeric',month:'long',year:'numeric'})}`;
  updateSaveState(I18n.t('All choices saved'));render();
  $('calendar-scroll').scrollTop=128;
}
async function persist(){
  if(!pending)return;
  setBusy(true);updateSaveState(I18n.t('Saving your choices…'));$('retry').hidden=true;$('reload').hidden=true;$('error').hidden=true;
  try{
    const response=await fetch(boardEndpoint,{method:'POST',headers:{'Content-Type':'application/json','X-Planner-Token':token},body:JSON.stringify(pending)});
    const result=await response.json();
    if(!response.ok){const err=new Error(I18n.t(result.error||'Save failed.'));err.conflict=response.status===409;throw err;}
    record=result.record;pending=null;setBusy(false);render();updateSaveState(I18n.t('All choices saved'));
  }catch(error){
    setBusy(false);updateSaveState(I18n.t('Changes not confirmed'));$('error').textContent=error.conflict?I18n.t('Another window changed this week. Export your choices if needed, then reload the saved version.'):error.message+' '+I18n.t('Your proposed changes remain visible. Retry to confirm the save.');
    $('error').hidden=false;$('retry').hidden=Boolean(error.conflict);$('reload').hidden=!error.conflict;
  }
}
function mutate(fn){
  if(busy||pending){render();toast(I18n.t('Finish or retry the current save first.'));return false;}
  fn();pending={request_id:crypto.randomUUID(),expected_revision:record.revision,data:structuredClone(record.data)};render();persist();return true;
}
function place(id,date,start){
  const card=cardById(id);if(!card)return;
  mutate(()=>{card.selected=true;card.placement={date,start_minute:start};});
}
function clearDropPreview(){
  dropPreview?.remove();dropPreview=null;
  document.querySelectorAll('.drop-day-active').forEach(node=>node.classList.remove('drop-day-active'));
  $('drop-announcement').textContent='';
}
function finishDrag(){
  clearDropPreview();
  document.querySelectorAll('.dragging').forEach(node=>node.classList.remove('dragging'));
  activeDrag?.ghost.remove();activeDrag=null;
}
function previewDrop(element,date,timed,clientY){
  if(!activeDrag)return null;
  const card=cardById(activeDrag.id);if(!card)return null;
  activeDrag.target={element,date,timed,clientY};
  if(!timed){
    clearDropPreview();element.classList.add('drop-day-active');
    $('drop-announcement').textContent=I18n.t('{date}: time open',{date:dateLabel(date)});
    return null;
  }
  document.querySelectorAll('.drop-day-active').forEach(node=>node.classList.remove('drop-day-active'));
  const rect=element.getBoundingClientRect();
  const range=M.dropRange(clientY-rect.top,rect.height,hourStart,hourEnd,card.minutes,activeDrag.grabMinutes);
  if(!dropPreview){dropPreview=el('div','drop-preview');dropPreview.append(el('strong','drop-time'),el('span','drop-title'));}
  if(dropPreview.parentElement!==element)element.append(dropPreview);
  dropPreview.style.top=`${(range.start-hourStart)/(hourEnd-hourStart)*rect.height}px`;
  dropPreview.style.height=`${card.minutes/(hourEnd-hourStart)*rect.height}px`;
  dropPreview.classList.toggle('compact',card.minutes<=30);
  const label=`${M.time(range.start)}–${M.time(range.end)}`;
  dropPreview.querySelector('.drop-time').textContent=label;
  dropPreview.querySelector('.drop-title').textContent=card.title;
  dropPreview.dataset.startMinute=range.start;dropPreview.dataset.endMinute=range.end;
  $('drop-announcement').textContent=`${dateLabel(date)} ${label}`;
  return range.start;
}
function draggable(element, card){
  element.draggable=true;
  element.addEventListener('dragstart',event=>{
    if(busy||pending||activeResize){event.preventDefault();return;}
    finishDrag();
    const rect=element.getBoundingClientRect();
    const ghost=el('div','drag-ghost');document.body.append(ghost);
    activeDrag={id:card.id,ghost,grabMinutes:element.classList.contains('scheduled-card')?Math.max(0,Math.min(card.minutes,(event.clientY-rect.top)/rect.height*card.minutes)):0};
    event.dataTransfer.setData('text/plain',card.id);event.dataTransfer.effectAllowed='move';
    event.dataTransfer.setDragImage(ghost,0,0);element.classList.add('dragging');
  });
  element.addEventListener('dragend',finishDrag);
}
function dropTarget(element,date,timed=false){
  element.addEventListener('dragover',event=>{
    if(!activeDrag)return;
    event.preventDefault();event.dataTransfer.dropEffect='move';previewDrop(element,date,timed,event.clientY);
  });
  element.addEventListener('dragleave',event=>{
    if(!element.contains(event.relatedTarget)){
      clearDropPreview();if(activeDrag)activeDrag.target=null;
    }
  });
  element.addEventListener('drop',event=>{
    event.preventDefault();event.stopPropagation();
    if(!activeDrag)return;
    const id=activeDrag.id,start=previewDrop(element,date,timed,event.clientY);
    finishDrag();place(id,date,start);
  });
}
$('calendar-scroll').addEventListener('scroll',()=>{
  if(activeResize)previewResize(activeResize.lastY);
  const target=activeDrag?.target;
  if(target)previewDrop(target.element,target.date,target.timed,target.clientY);
});
document.addEventListener('drop',finishDrag);
document.addEventListener('dragend',finishDrag);
document.addEventListener('keydown',event=>{if(event.key==='Escape'){finishDrag();finishResize(false);}});
window.addEventListener('blur',()=>finishResize(false));
function previewResize(clientY){
  const state=activeResize;if(!state)return;
  state.lastY=clientY;state.moved=state.moved||Math.abs(clientY-state.startY)>=3;
  const delta=clientY-state.startY+$('calendar-scroll').scrollTop-state.scrollTop;
  state.minutes=M.resizeMinutes(state.originalMinutes,delta,state.pixelsPerMinute,state.start,hourEnd);
  state.element.style.height=`${state.minutes*state.pixelsPerMinute-2}px`;
  state.element.classList.toggle('short',state.minutes<=30);
  const range=`${M.time(state.start)}–${M.time(state.start+state.minutes)}`;
  state.element.querySelector('.card-meta').firstChild.textContent=`${range} · ${state.project}`;
  state.label.textContent=`${range} · ${M.duration(state.minutes)}`;
  state.label.style.top=`${Math.max(0,(state.start-hourStart+state.minutes)*state.pixelsPerMinute-30)}px`;
  $('drop-announcement').textContent=`${state.title}: ${range}, ${M.duration(state.minutes)}`;
}
function resizeAutoscroll(){
  const state=activeResize;if(!state)return;
  const scroll=$('calendar-scroll'),rect=scroll.getBoundingClientRect();
  const edge=36;
  if(state.moved&&state.lastY>rect.bottom-edge)scroll.scrollTop+=12;
  else if(state.moved&&state.lastY<rect.top+edge)scroll.scrollTop-=12;
  state.frame=requestAnimationFrame(resizeAutoscroll);
}
function finishResize(save){
  const state=activeResize;if(!state)return;
  activeResize=null;cancelAnimationFrame(state.frame);
  if(state.handle.hasPointerCapture(state.pointerId))state.handle.releasePointerCapture(state.pointerId);
  state.element.draggable=true;state.label.remove();document.body.classList.remove('resizing');
  $('drop-announcement').textContent='';
  if(save&&state.minutes!==state.originalMinutes){
    mutate(()=>{const card=cardById(state.id);card.minutes=state.minutes;card.estimate_basis=I18n.t('Your duration adjustment in the calendar; revise after trying the task.');});
  }else render();
}
function resizable(element,card){
  const handle=el('button','resize-handle');handle.type='button';handle.draggable=false;
  handle.setAttribute('aria-label',I18n.t('Resize {title}; press Enter to edit duration',{title:card.title}));
  handle.title=I18n.t('Drag to resize · 15-minute steps');element.append(handle);
  handle.addEventListener('pointerdown',event=>{
    if(event.button!==0||busy||pending||activeResize)return;
    event.preventDefault();event.stopPropagation();finishDrag();
    const column=element.parentElement,label=el('div','resize-range');column.append(label);
    activeResize={id:card.id,title:card.title,project:card.project,start:card.placement.start_minute,
      originalMinutes:card.minutes,minutes:card.minutes,startY:event.clientY,lastY:event.clientY,
      scrollTop:$('calendar-scroll').scrollTop,pixelsPerMinute:column.getBoundingClientRect().height/(hourEnd-hourStart),
      element,handle,label,pointerId:event.pointerId};
    element.draggable=false;document.body.classList.add('resizing');
    handle.setPointerCapture(event.pointerId);previewResize(event.clientY);resizeAutoscroll();
  });
  handle.addEventListener('pointermove',event=>{if(activeResize?.pointerId===event.pointerId)previewResize(event.clientY);});
  handle.addEventListener('pointerup',event=>{if(activeResize?.pointerId===event.pointerId){event.preventDefault();event.stopPropagation();previewResize(event.clientY);finishResize(true);}});
  handle.addEventListener('pointercancel',event=>{if(activeResize?.pointerId===event.pointerId)finishResize(false);});
  handle.addEventListener('lostpointercapture',event=>{if(activeResize?.pointerId===event.pointerId)finishResize(false);});
  handle.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();if(event.detail===0)openEditor(card.id);});
}
function cardElement(card,kind='tray',overlap=false){
  const colors=M.projectColor(card.project);
  const e=el('article',`task-card ${card.selected?'selected':''} ${kind==='scheduled'?'scheduled-card':''} ${kind==='parked'?'parked-card':''} ${overlap?'overlap':''}`);
  e.dataset.cardId=card.id;e.style.setProperty('--accent',colors[0]);e.style.setProperty('--tint',colors[1]);
  const meta=el('div','card-meta');meta.append(el('span','',kind==='scheduled'?`${M.time(card.placement.start_minute)}–${M.time(card.placement.start_minute+card.minutes)} · ${card.project}`:card.project));if(kind!=='scheduled')meta.append(el('span','duration',M.duration(card.minutes)));e.append(meta);
  const button=el('button','card-open',card.title);button.type='button';button.addEventListener('click',()=>openEditor(card.id));button.setAttribute('aria-label',I18n.t('Edit {title}, {duration}',{title:card.title,duration:M.duration(card.minutes)}));e.append(button);
  if(kind==='tray'){
    e.append(el('p','card-result',card.outcome));
    const foot=el('div','card-footer'),label=el('label'),check=el('input');check.type='checkbox';check.checked=card.selected;check.setAttribute('aria-label',I18n.t('Select {title}',{title:card.title}));
    check.addEventListener('change',()=>mutate(()=>{card.selected=check.checked;if(!card.selected)card.placement=null;}));label.append(check,document.createTextNode(I18n.t('Select')));foot.append(label,el('span','',card.selected?I18n.t('Ready to place'):I18n.t('Optional this week')));e.append(foot);
  }
  draggable(e,card);if(kind==='scheduled')resizable(e,card);return e;
}
function render(){
  const calendarScroll=$('calendar-scroll').scrollTop, trayScroll=$('tray-cards').scrollTop;
  const data=record.data,dates=M.dates(data.week_start),visible=mode==='week'?dates:[activeDate];
  const hourHeight=mode==='day'?56:64;
  document.querySelector('.schedule').classList.toggle('day-view',mode==='day');
  $('week-mode').setAttribute('aria-pressed',mode==='week');$('day-mode').setAttribute('aria-pressed',mode==='day');$('day-picker').hidden=mode==='week';$('day-picker').value=activeDate;
  $('calendar-title').textContent=mode==='week'?I18n.t('Arrange your week'):dateLabel(activeDate,{weekday:'long',day:'numeric',month:'long'});
  const selected=data.cards.filter(c=>c.selected),placed=data.cards.filter(c=>c.placement);
  const availabilityNotes=[...new Set(Object.values(data.availability).filter(a=>a.level!=='unknown').map(a=>a.note))];
  const gymCount=data.cards.filter(c=>/^Gym session [0-9]+$/.test(c.title)).length;
  $('context-strip').replaceChildren(...[data.timezone,...availabilityNotes.slice(0,1),...(gymCount?[I18n.t('Gym sessions: {count} · choose the days',{count:gymCount})]:[])].map(text=>el('span','',text)));
  $('totals').textContent=I18n.t('Selected: {selected} · estimated: {duration} · placed: {placed}',{selected:selected.length,duration:M.duration(selected.reduce((n,c)=>n+c.minutes,0)),placed:placed.length});
  const project=$('project-filter').value,selectedOnly=$('selected-filter').checked;
  const tray=data.cards.filter(c=>!c.placement&&(!project||c.project===project)&&(!selectedOnly||c.selected));
  $('tray-cards').replaceChildren(...tray.map(c=>cardElement(c)));
  if(!tray.length)$('tray-cards').append(el('p','empty-tray',I18n.t('No unplaced cards in this view. Change the filter or open a calendar card to return it to the tray.')));
  const pairs=M.conflicts(data.cards).filter(([a])=>visible.includes(a.placement.date)),overlaps=new Set(pairs.flatMap(pair=>pair.map(c=>c.id)));
  const warnings=[];
  if(pairs.length)warnings.push(I18n.t('Overlaps: {count}. {cards}.',{count:pairs.length,cards:pairs.slice(0,2).map(([a,b])=>a.title+' / '+b.title).join('; ')}));
  const limited=placed.filter(c=>visible.includes(c.placement.date)&&data.availability[c.placement.date]?.level!=='unknown'&&data.availability[c.placement.date]);
  if(limited.length)warnings.push(I18n.t('Cards on limited-availability days: {count}. Check against your travel plans.',{count:limited.length}));
  $('warnings').textContent=warnings.join(' ');
  const timed=placed.filter(c=>c.placement.start_minute!==null);
  hourStart=Math.min(420,...timed.map(c=>Math.floor(c.placement.start_minute/60)*60));
  hourEnd=Math.max(1380,...timed.map(c=>Math.ceil((c.placement.start_minute+c.minutes)/60)*60));
  const grid=el('div','calendar-grid');grid.style.setProperty('--days',visible.length);grid.style.setProperty('--hour',hourHeight+'px');
  if(mode==='week'){
  grid.append(el('div','axis-head',I18n.t('Day')));
  visible.forEach(date=>{
    const availability=data.availability[date],isLimited=availability&&availability.level!=='unknown';
    const h=el('div',`day-head ${date===todayDate()?'today':''} ${isLimited?'limited':''}`);h.dataset.date=date;
    const button=el('button');button.append(el('span','weekday-name',dateLabel(date,{weekday:'short'})),el('span','date-number',date.slice(-2).replace(/^0/,'')));button.setAttribute('aria-label',I18n.t('View {date} in day mode',{date:dateLabel(date)}));button.onclick=()=>{activeDate=date;mode='day';render();};h.append(button);
    const dayCards=placed.filter(c=>c.placement.date===date);h.append(el('small','',I18n.t('{duration} placed',{duration:M.duration(dayCards.reduce((n,c)=>n+c.minutes,0))})));
    if(isLimited){h.append(el('small','availability',availability.level==='off'?I18n.t('Day off'):I18n.t('Limited')));h.title=availability.note;}
    dropTarget(h,date);grid.append(h);
  });
  }
  grid.append(el('div','park-axis',I18n.t('Untimed')));
  visible.forEach(date=>{const parking=el('div','day-parking');parking.dataset.date=date;const cards=placed.filter(c=>c.placement.date===date&&c.placement.start_minute===null);parking.append(...cards.map(c=>cardElement(c,'parked')));if(!cards.length)parking.append(el('span','park-hint',I18n.t('Time open')));dropTarget(parking,date);grid.append(parking);});
  const axis=el('div','time-axis');for(let m=hourStart;m<hourEnd;m+=60)axis.append(el('div','hour-label',M.time(m)));grid.append(axis);
  visible.forEach(date=>{
    const col=el('div',`day-column ${data.availability[date]?.level!=='unknown'&&data.availability[date]?'limited':''}`);col.dataset.date=date;col.style.height=`${(hourEnd-hourStart)/60*hourHeight}px`;dropTarget(col,date,true);
    const cards=timed.filter(c=>c.placement.date===date).sort((a,b)=>a.placement.start_minute-b.placement.start_minute);
    // Connected overlap clusters share horizontal lanes; no card is hidden behind another.
    const clusters=[];let cluster=[],end=-1;
    cards.forEach(c=>{if(c.placement.start_minute>=end&&cluster.length){clusters.push(cluster);cluster=[];end=-1;}cluster.push(c);end=Math.max(end,c.placement.start_minute+c.minutes);});if(cluster.length)clusters.push(cluster);
    clusters.forEach(group=>group.forEach((card,i)=>{const block=cardElement(card,'scheduled',overlaps.has(card.id));block.style.top=`${(card.placement.start_minute-hourStart)/60*hourHeight}px`;block.style.height=`${card.minutes/60*hourHeight-2}px`;if(card.minutes<=30)block.classList.add('short');if(group.length>1){block.style.left=`calc(${i/group.length*100}% + 3px)`;block.style.width=`calc(${100/group.length}% - 6px)`;block.style.right='auto';}col.append(block);}));grid.append(col);
  });
  $('calendar').replaceChildren(grid);$('calendar-scroll').scrollTop=calendarScroll;$('tray-cards').scrollTop=trayScroll;
  const changes=data.changes||[];$('history-count').textContent=changes.length?`(${changes.length})`:'';$('history').replaceChildren();
  if(!changes.length)$('history').append(el('li','',I18n.t('Your first selection or placement will appear here.')));
  changes.slice(-12).reverse().forEach(change=>{const li=el('li'),stamp=new Intl.DateTimeFormat(I18n.locale,{timeZone:data.timezone,hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'}).format(new Date(change.at));li.append(el('time','',stamp));let text=change.title+': ';
    if(change.fields.includes('placement')){const p=change.after?.placement;text+=p?`${dateLabel(p.date)}${p.start_minute===null?I18n.t(' · time open'):I18n.t(' at ')+M.time(p.start_minute)}`:I18n.t('returned to tray');}
    else if(change.fields.includes('selected'))text+=change.after?.selected?I18n.t('selected'):I18n.t('unselected');else text+=change.fields.join(', ')+I18n.t(' changed');
    if(change.reason)text+=' — '+change.reason;li.append(document.createTextNode(text));$('history').append(li);
  });
}
function openEditor(id){
  if(busy||pending){toast(I18n.t('Finish or retry the current save first.'));return;}
  editingId=id;const c=id?cardById(id):{title:'',project:'Other',outcome:'',first_action:'',minutes:60,selected:true,placement:null,note:'',estimate_basis:I18n.t('Your approximate estimate; adjust after trying the task.')};
  $('editor-title').textContent=id?I18n.t('Shape this task'):I18n.t('Add a task');$('edit-title').value=c.title;$('edit-project').value=c.project;$('edit-outcome').value=c.outcome;$('edit-first').value=c.first_action;$('edit-minutes').value=c.minutes;$('edit-selected').checked=c.selected;$('edit-day').value=c.placement?.date||'';$('edit-time').value=c.placement?.start_minute!=null?M.time(c.placement.start_minute):'';$('edit-note').value=c.note||'';$('estimate-basis').textContent=c.estimate_basis;$('form-error').textContent='';$('unschedule').hidden=!c.placement;
  $('chat-link').hidden=!c.chat_url;if(c.chat_url)$('chat-link').href=c.chat_url;
  let linked = $('linked-task');
  if(!linked){linked=el('a');linked.id='linked-task';$('chat-link').after(linked);}
  linked.hidden=!(c.task_id && c.workstream_id);
  if(!linked.hidden){linked.textContent=I18n.t('Open linked task');linked.href=workspaceUrl+'#planned/'+record.id+'/'+c.id;}
  $('editor').showModal();
}
$('card-form').addEventListener('submit',event=>{
  event.preventDefault();const minutes=Number($('edit-minutes').value),day=$('edit-day').value,t=$('edit-time').value;const minute=t?Number(t.slice(0,2))*60+Number(t.slice(3)):null;
  if((t&&!day)||(minute!==null&&(minute%15!==0||minute+minutes>1440))){$('form-error').textContent=I18n.t('Choose a day and a 15-minute start time that fits before midnight.');return;}
  const old=editingId?cardById(editingId):null;
  const c={...(old||{}),id:editingId||'task-'+crypto.randomUUID(),title:$('edit-title').value.trim(),project:$('edit-project').value,outcome:$('edit-outcome').value.trim(),first_action:$('edit-first').value.trim(),minutes,selected:$('edit-selected').checked||Boolean(day),placement:day?{date:day,start_minute:minute}:null,note:$('edit-note').value.trim(),estimate_basis:old?.minutes===minutes?old.estimate_basis:I18n.t('Your approximate estimate; adjust after trying the task.'),chat_url:old?.chat_url||''};
  if(!c.title||!c.outcome||!c.first_action){$('form-error').textContent=I18n.t('Add a task, expected result and first action.');return;}
  if(mutate(()=>{if(old)record.data.cards[record.data.cards.indexOf(old)]=c;else record.data.cards.push(c);})){ $('editor').close(); }
});
$('unschedule').onclick=()=>{if(mutate(()=>{cardById(editingId).placement=null;}))$('editor').close();};
$('edit-selected').onchange=()=>{if(!$('edit-selected').checked){$('edit-day').value='';$('edit-time').value='';}};
$('close-editor').onclick=()=>$('editor').close();$('add-task').onclick=()=>openEditor(null);
$('project-filter').onchange=render;$('selected-filter').onchange=render;
$('week-mode').onclick=()=>{mode='week';render();};$('day-mode').onclick=()=>{mode='day';render();};$('day-picker').onchange=()=>{activeDate=$('day-picker').value;render();};
$('today').onclick=()=>{const today=todayDate();activeDate=M.dates(record.data.week_start).includes(today)?today:record.data.week_start;mode='day';render();};
$('retry').onclick=persist;$('reload').onclick=()=>location.reload();
$('export').onclick=()=>{if(!record)return;const blob=new Blob([JSON.stringify(record,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=el('a');a.href=url;a.download=`planning-${record.data.week_start}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('beforeunload',event=>{if(pending){event.preventDefault();event.returnValue='';}});
load().catch(error=>{$('error').textContent=error.message+I18n.t(' Refresh the page to try again.');$('error').hidden=false;updateSaveState(I18n.t('Unable to load'));});

I18n.beforeChange = () => { if (busy || pending || activeDrag || activeResize) { toast(I18n.t('Finish or retry the current save first.')); return false; } return true; };
