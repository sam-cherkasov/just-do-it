const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

// Minimal DOM adapter: execute the real form, storage, save/409 and reload handlers.
// Browser layout and native constraint validation are verified separately.
class Element {
  constructor(tag) { this.tagName=tag; this.children=[]; this.listeners={}; this.value=''; this.open=false; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
  setAttribute(name, value) { this[name]=value; }
  dispatch(type) { for(const fn of this.listeners[type] || []) fn({preventDefault(){}}); }
  close() { this.open=false; }
  showModal() { this.open=true; }
  focus() {}
  querySelectorAll() { return []; }
}
const flatten = element => [element,...element.children.flatMap(flatten)];
const task = () => ({id:'task_example',revision:1,data:{title:'Old title',next_action:'Old action',chat_url:'codex://threads/old'}});
function harness(language='ru') {
  const localized=vm.createContext({URLSearchParams,location:{search:'?lang='+language}});
  for(const file of ['i18n-catalog.js','i18n.js'])vm.runInContext(fs.readFileSync(require.resolve('../web/'+file),'utf8'),localized);
  const nodes=new Map(), storage=new Map(), requests=[];
  const node=key=>{ if(!nodes.has(key))nodes.set(key,new Element('div'));return nodes.get(key); };
  let snapshot={token:'test',tasks:[task()],workstreams:[],sessions:[],planners:[]}, conflict=false;
  const context=vm.createContext({
    document:{querySelector:node,querySelectorAll:()=>[],createElement:tag=>new Element(tag),addEventListener(){}},
    window:{addEventListener(){}},setInterval(){},location:{hash:''},
    sessionStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    I18n:localized.I18n,
    crypto:{randomUUID:()=>String(requests.length)},TodayModel:require('../web/today-model.js'),
    fetch:async (url,options)=>{
      if(options){ requests.push(JSON.parse(options.body)); if(conflict){conflict=false;return {ok:false,status:409,json:async()=>({error:'Revision conflict'})};} }
      return {ok:true,json:async()=>JSON.parse(JSON.stringify(snapshot))};
    }
  });
  for(const file of ['workspace.js','today.js','work-items.js','onboarding.js'])vm.runInContext(fs.readFileSync(require.resolve('../web/'+file),'utf8'),context);
  vm.runInContext('render=()=>{};syncStatus=()=>{};',context);
  const setState=value=>{snapshot=value;context.incoming=value;vm.runInContext('state=incoming;',context);};
  setState(snapshot);
  const open=()=>vm.runInContext("controlTask(state.tasks[0],'edit')",context);
  const elements=()=>flatten(node('#action-dialog'));
  const field=name=>elements().find(e=>e.name===name);
  const form=()=>node('#action-dialog').children[0];
  const input=(name,value)=>{field(name).value=value;form().dispatch('input');};
  const submit=async()=>{form().dispatch('submit');await new Promise(setImmediate);};
  return {context,node,storage,requests,open,field,form,input,submit,elements,
    update(data){setState({...snapshot,tasks:[{...snapshot.tasks[0],revision:snapshot.tasks[0].revision+1,data:{...snapshot.tasks[0].data,...data}}]});},
    conflict(data){snapshot={...snapshot,tasks:[{...snapshot.tasks[0],revision:2,data:{...snapshot.tasks[0].data,...data}}]};conflict=true;},
    setState};
}

test('409 reload and recovered draft submit only user edits, preserving concurrent title and chat',async()=>{
  const h=harness();h.open();h.input('next_action','My new action');h.input('reason','Clarify next action');
  h.conflict({title:'Concurrent title',chat_url:'codex://threads/new'});
  await h.submit();
  assert.equal(h.requests[0].expected_revision,1);
  assert.equal(h.node('#action-dialog').open,false);
  h.open();
  assert.equal(h.field('title').value,'Concurrent title');
  assert.equal(h.field('chat_url').value,'codex://threads/new');
  assert.equal(h.field('next_action').value,'My new action');
  await h.submit();
  assert.equal(h.requests[1].expected_revision,2);
  assert.deepEqual(h.requests[1].data.values,{next_action:'My new action'});
  assert.equal(h.storage.has('task-draft-task_example-edit'),false);
});

test('dismissed draft preserves untouched updates after background refresh',async()=>{
  const h=harness();h.open();h.input('next_action','My action');h.input('reason','Clarify');
  h.node('#action-dialog').close();h.update({title:'Fresh title'});h.open();await h.submit();
  assert.deepEqual(h.requests[0].data.values,{next_action:'My action'});
});

for(const resolution of ['current','draft'])test('same-field conflict requires explicit '+resolution+' resolution',async()=>{
  const h=harness();h.open();h.input('title','My title');h.input('next_action','My action');h.input('reason','Clarify');
  h.update({title:'Concurrent title'});h.open();
  await h.submit();assert.equal(h.requests.length,0);
  const select=h.elements().find(e=>e.tagName==='select');
  assert.ok(select.required);select.value=resolution;select.dispatch('change');
  await h.submit();
  assert.deepEqual(h.requests[0].data.values,resolution==='current' ? {next_action:'My action'} : {title:'My title',next_action:'My action'});
});

test('legacy draft without a base cannot silently restore stale fields',async()=>{
  const h=harness();h.storage.set('task-draft-task_example-edit',JSON.stringify({title:'Legacy title',next_action:'Old action',chat_url:'codex://threads/old',reason:'Legacy reason'}));
  h.open();await h.submit();assert.equal(h.requests.length,0);
  const select=h.elements().find(e=>e.tagName==='select');select.value='current';select.dispatch('change');await h.submit();
  assert.equal(h.requests.length,0); // Choosing the current version makes this a no-op.
});

test('explicit chat clearing is retained through an unrelated title update',async()=>{
  const h=harness();h.open();h.input('chat_url','');h.input('reason','Clear chat');h.update({title:'New title'});h.open();await h.submit();
  assert.deepEqual(h.requests[0].data.values,{chat_url:''});
});

test('stale card can be unlinked even when no tasks are available',async()=>{
  const h=harness();h.setState({token:'test',tasks:[],workstreams:[],sessions:[],planners:[]});
  vm.runInContext("linkPlanCard({id:'board',revision:2},{id:'card',task_id:'old',workstream_id:'empty'})",h.context);
  h.input('task_id','__unlink__');await h.submit();
  assert.deepEqual(h.requests[0].data.links,[{card_id:'card',task_id:null,task_revision:null,workstream_id:null,reason:'Подтверждаю изменение связи карточки'}]);
});

test('card relinking uses current membership instead of its obsolete direction',async()=>{
  const h=harness();h.setState({token:'test',tasks:[task()],sessions:[],planners:[],workstreams:[{id:'new',data:{title:'New direction',task_ids:['task_example']}}]});
  vm.runInContext("linkPlanCard({id:'board',revision:2},{id:'card',task_id:'task_example',workstream_id:'old'})",h.context);
  await h.submit();assert.equal(h.requests[0].data.links[0].workstream_id,'new');
});

test('quick thought capture stays on focus and preserves unfinished outcome draft',async()=>{
  const h=harness();
  h.storage.set('focus-draft-active',JSON.stringify({note:'Unfinished report',next_action:'Later'}));
  vm.runInContext("location.hash='#focus';itemForm()",h.context);
  h.input('title','A distracting thought');h.input('body','Keep for later');await h.submit();
  assert.equal(h.requests[0].operation,'workspace-item');
  assert.equal(h.requests[0].after,'#focus');
  assert.equal(h.requests[0].data.task_id,null);
  assert.equal(JSON.parse(h.storage.get('focus-draft-active')).note,'Unfinished report');
  assert.equal(vm.runInContext('location.hash',h.context),'#focus');
});

test('editing an inbox note merges untouched concurrent task links',async()=>{
  const h=harness();
  h.context.original={id:'note',revision:1,data:{category:'note',title:'Thought',body:'Original',task_id:null,status:'open'}};
  vm.runInContext("itemForm('note',null,original)",h.context);h.input('body','My detail');h.input('reason','Clarify');
  h.context.fresh={id:'note',revision:2,data:{category:'note',title:'Fresh title',body:'Original',task_id:'task_example',status:'open'}};
  vm.runInContext("itemForm('note',null,fresh)",h.context);await h.submit();
  assert.equal(h.requests[0].expected_revision,2);
  assert.equal(h.requests[0].data.title,'Fresh title');
  assert.equal(h.requests[0].data.task_id,'task_example');
  assert.equal(h.requests[0].data.body,'My detail');
});

test('explicit continuation carries session identity and saved step into start form',async()=>{
  const h=harness();
  h.context.prior={id:'previous',revision:2,data:{task_id:'task_example',status:'closed',target:'Original desired result',next_action:'Exact continuation'}};
  // The browser supplies select.options; this adapter only needs the budget presets.
  h.node('#minutes').options=[{value:'60'}];h.node('#minutes').querySelector=()=>null;
  vm.runInContext('pick(null,state.tasks[0],null,null,prior)',h.context);
  assert.equal(h.node('#session-first-action').textContent,'Первый шаг: Exact continuation');
  h.node('#session-form').dispatch('submit');await new Promise(setImmediate);
  assert.equal(h.requests[0].data.continuation_id,'previous');
  assert.equal(h.requests[0].data.continuation_revision,2);
  assert.equal(h.requests[0].data.target,'Original desired result');
  assert.equal(h.requests[0].data.day_choice_id,undefined);
});


test('new task preserves creation draft and opens the confirmed task identity',async()=>{
  const h=harness();h.setState({token:'test',tasks:[],sessions:[],planners:[],created_id:'task_new',workstreams:[{id:'stream',data:{title:'Learning',status:'active',task_ids:[]}}]});
  vm.runInContext('createTask(state.workstreams[0])',h.context);
  h.input('title','Draft example');h.input('next_action','Open page');
  h.node('#action-dialog').close();vm.runInContext('createTask(state.workstreams[0])',h.context);
  assert.equal(h.field('title').value,'Draft example');
  await h.submit();
  assert.equal(h.requests[0].operation,'create-task');
  assert.deepEqual(h.requests[0].data,{workstream_id:'stream',title:'Draft example',next_action:'Open page'});
  assert.equal(h.context.location.hash,'#task/task_new');
  assert.equal(h.storage.has('new-task-stream'),false);
});

test('creating a direction does not choose a day or start a session',async()=>{
  const h=harness();h.setState({token:'test',tasks:[],sessions:[],planners:[],workstreams:[],created_id:'stream_new'});
  vm.runInContext('createDirection()',h.context);h.input('title','Learning');h.input('outcome','Explain an idea');await h.submit();
  assert.equal(h.requests.length,1);assert.equal(h.requests[0].operation,'create-workstream');
  assert.equal(h.context.location.hash,'#project/stream_new');
  assert.equal(h.requests[0].data.color,'lilac');
});

for(const language of ['uk','en'])test('translated task form preserves personal text and saves only edits: '+language,async()=>{
  const h=harness(language);h.open();
  assert.equal(h.field('title').value,'Old title');
  h.input('next_action','Мой текст остаётся в оригинале');h.input('reason','Explicit correction');
  await h.submit();
  assert.deepEqual(h.requests[0].data.values,{next_action:'Мой текст остаётся в оригинале'});
});

test('English task counts use singular only for one, including 21 and 101',()=>{
  const h=harness('en');
  for(const n of [0,1,2,5,11,21,101])assert.equal(vm.runInContext(`plural(${n},['task','tasks','tasks'])`,h.context),n+' '+(n===1?'task':'tasks'));
});
