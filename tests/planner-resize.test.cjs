const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const model=require('../web/planner-model.js');
function harness(){
  class Node {
    constructor(){this.children=[];this.style={};this.handlers={};this.className='';this.textContent='';this.scrollTop=0;this.classes=new Set();this.classList={add:c=>this.classes.add(c),remove:c=>this.classes.delete(c),toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c),contains:c=>this.classes.has(c)};}
    append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
    querySelector(selector){return this.children.find(n=>n.className===selector.slice(1));}
    get firstChild(){return this.children[0];}
    addEventListener(name,fn){this.handlers[name]=fn;}
    setAttribute(){}
    setPointerCapture(id){this.capture=id;}
    hasPointerCapture(id){return this.capture===id;}
    releasePointerCapture(){this.capture=null;}
    getBoundingClientRect(){return {top:100,bottom:1060,height:960};}
  }
  const nodes=new Map(),document={body:new Node(),createElement:()=>new Node(),getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},querySelectorAll:()=>[],addEventListener:()=>{}};
  const context=vm.createContext({I18n:{t:(text,values={})=>({'hour-short':'h','minute-short':'m'}[text]||text).replace(/\{(\w+)\}/g,(m,k)=>values[k]??m),locale:'en-GB'},URLSearchParams,location:{search:''},document,window:{PlannerModel:model,addEventListener:()=>{}},fetch:()=>new Promise(()=>{}),requestAnimationFrame:()=>42,cancelAnimationFrame:()=>{},Intl,Date,console});
  vm.runInContext(fs.readFileSync('web/planner.js','utf8'),context);
  const card={id:'synthetic',title:'Fictional draft',project:'Other',minutes:90,placement:{date:'2026-11-02',start_minute:600}};
  const column=new Node(),element=new Node(),meta=new Node();meta.className='card-meta';meta.append(new Node());element.append(meta);column.append(element);Object.assign(context,{card,element});
  vm.runInContext("record={data:{cards:[card]}};var saves=0,renders=0;mutate=fn=>{fn();saves++;};render=()=>{renders++;};resizable(element,card);",context);
  const handle=element.querySelector('.resize-handle');
  const event=(y,id=1)=>({button:0,pointerId:id,clientY:y,preventDefault(){},stopPropagation(){}});
  return {context,card,column,element,handle,event};
}
test('resize previews without changing records, then saves once on release',()=>{
  const h=harness();h.handle.handlers.pointerdown(h.event(300));h.handle.handlers.pointermove(h.event(345));
  assert.equal(h.card.minutes,90);
  assert.equal(h.element.style.height,'133px');
  assert.equal(h.column.querySelector('.resize-range').textContent,'10:00–12:15 · 2 h 15 m');
  assert.equal(vm.runInContext('saves',h.context),0);
  h.handle.handlers.pointerup(h.event(345));
  assert.equal(h.card.minutes,135);assert.equal(h.card.placement.start_minute,600);
  assert.equal(vm.runInContext('saves',h.context),1);
  assert.equal(h.column.querySelector('.resize-range'),undefined);
  h.handle.handlers.lostpointercapture(h.event(345));
  assert.equal(vm.runInContext('saves',h.context),1);
});
test('cancel and lost capture restore without saving',()=>{
  for(const end of ['pointercancel','lostpointercapture']){
    const h=harness();h.handle.handlers.pointerdown(h.event(300));h.handle.handlers.pointermove(h.event(360));h.handle.handlers[end](h.event(360));
    assert.equal(h.card.minutes,90);assert.equal(vm.runInContext('saves',h.context),0);assert.equal(vm.runInContext('renders',h.context),1);
    assert.equal(h.element.draggable,true);
  }
});
test('unchanged release does not create a save; other pointer is ignored',()=>{
  const h=harness();h.handle.handlers.pointerdown(h.event(300));h.handle.handlers.pointermove(h.event(360,2));h.handle.handlers.pointercancel(h.event(360,2));
  assert.equal(vm.runInContext('activeResize.minutes',h.context),90);
  h.handle.handlers.pointerup(h.event(300));assert.equal(vm.runInContext('saves',h.context),0);
});
