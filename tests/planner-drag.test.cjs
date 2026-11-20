const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const model=require('../web/planner-model.js');

// Minimal synthetic DOM: exercise the actual drag handlers without browser writes.
function harness(){
  class Node {
    constructor(){this.children=[];this.style={};this.dataset={};this.handlers={};this.className='';this.textContent='';this.parentElement=null;this.classes=new Set();this.classList={add:c=>this.classes.add(c),remove:c=>this.classes.delete(c),toggle:(c,on)=>on?this.classes.add(c):this.classes.delete(c),contains:c=>this.classes.has(c)};}
    append(...nodes){for(const n of nodes){n.remove();n.parentElement=this;this.children.push(n);}}
    remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
    querySelector(selector){return this.children.find(n=>n.className===selector.slice(1));}
    addEventListener(name,fn){this.handlers[name]=fn;}
    contains(node){return this===node||this.children.includes(node);}
    getBoundingClientRect(){return {top:100,height:896};}
  }
  const nodes=new Map(),document={body:new Node(),createElement:()=>new Node(),getElementById:id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);},querySelectorAll:()=>[],addEventListener:()=>{}};
  const context=vm.createContext({I18n:{t:(text,values={})=>({'hour-short':'h','minute-short':'m'}[text]||text).replace(/\{(\w+)\}/g,(m,k)=>values[k]??m),locale:'en-GB'},URLSearchParams,location:{search:''},document,window:{PlannerModel:model,addEventListener:()=>{}},fetch:()=>new Promise(()=>{}),Intl,Date,console});
  vm.runInContext(fs.readFileSync('web/planner.js','utf8'),context);
  const column=new Node();context.column=column;
  vm.runInContext("record={data:{cards:[{id:'fiction',title:'Fictional result',minutes:90}]}};activeDrag={id:'fiction',grabMinutes:0,ghost:document.createElement('div')};dropTarget(column,'2026-11-02',true);",context);
  function hover(y){let prevented=false;column.handlers.dragover({clientY:y,dataTransfer:{},preventDefault(){prevented=true;}});assert.ok(prevented);return column.children[0];}
  return {context,column,nodes,hover};
}
test('drag hover paints only its exact interval and follows the pointer',()=>{
  const h=harness(),first=h.hover(308);
  assert.equal(first.querySelector('.drop-time').textContent,'10:45–12:15');
  assert.equal(first.style.height,'84px');
  assert.equal(h.column.classes.size,0,'the whole day must not be highlighted');
  const second=h.hover(322);
  assert.equal(second,first,'move the same preview, without leaving trails');
  assert.equal(second.querySelector('.drop-time').textContent,'11:00–12:30');
  assert.equal(second.style.top,'224px');
});
test('leaving the target clears the preview and announcement',()=>{
  const h=harness();h.hover(308);h.column.handlers.dragleave({relatedTarget:null});
  assert.equal(h.column.children.length,0);
  assert.equal(h.nodes.get('drop-announcement').textContent,'');
});
test('canceling a drag clears its interval and drag state',()=>{
  const h=harness();h.hover(308);vm.runInContext('finishDrag()',h.context);
  assert.equal(h.column.children.length,0);
  assert.equal(vm.runInContext('activeDrag',h.context),null);
});
