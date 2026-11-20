const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = name => fs.readFileSync(require.resolve('../web/' + name), 'utf8');
function localization(language, extra = {}) {
  const context = vm.createContext({URLSearchParams, URL, location:{search:'?lang='+language}, ...extra});
  vm.runInContext(source('i18n-catalog.js'), context);
  vm.runInContext(source('i18n.js'), context);
  return context;
}

test('language preference validates URL and storage; old installations keep Russian', () => {
  const {I18n} = localization('uk');
  assert.equal(I18n.resolveLanguage('?lang=en','uk'), 'en');
  assert.equal(I18n.resolveLanguage('?lang=bad','uk'), 'uk');
  assert.equal(I18n.resolveLanguage('', 'bad'), 'ru');
  assert.equal(I18n.resolveLanguage('', null), 'ru');
  assert.equal(I18n.locale, 'uk-UA');
  assert.equal(localization('en').I18n.locale, 'en-GB');
});

test('denied browser storage still permits an explicit language URL', () => {
  const {I18n} = localization('uk', {localStorage:{getItem(){throw Error('Denied');},setItem(){throw Error('Denied');}}});
  assert.equal(I18n.t('Сегодня'), 'Сьогодні');
});

test('all interface messages have three translations and identical named placeholders', () => {
  const {PersonalOSMessages:messages} = localization('uk');
  const params = value => [...value.matchAll(/\{(\w+)\}/g)].map(m=>m[1]).sort();
  for (const [key, copy] of Object.entries(messages)) {
    for (const lang of ['uk','ru','en']) {
      assert.equal(typeof copy[lang], 'string', key + ': ' + lang);
      assert.ok(copy[lang].trim(), key + ': ' + lang);
      assert.deepEqual(params(copy[lang]), params(key), key + ': placeholders in ' + lang);
    }
  }
  for (const file of ['workspace.js','today.js','work-items.js','onboarding.js','planner.js']) {
    for (const match of source(file).matchAll(/I18n\.t\('((?:\\.|[^'\\])*)'/g)) {
      const key = match[1].replace(/\\n/g,'\n').replace(/\\'/g,"'");
      assert.ok(Object.hasOwn(messages,key), file + ': missing ' + key);
    }
  }
});

test('interpolation preserves record text and never recursively translates inserted values', () => {
  const {I18n} = localization('uk');
  const title = 'Сегодня <b>literal text</b> {duration}';
  assert.equal(I18n.t('Edit {title}, {duration}', {title,duration:'30 хв'}), 'Редагувати: '+title+', 30 хв');
  assert.equal(I18n.t('My original note'), 'My original note');
});

test('candidate reasons use the interface language but preserve task titles and user date basis', () => {
  const context = localization('en');
  vm.runInContext(source('today-model.js'), context);
  const task = {id:'t', data:{title:'Сегодня',status:'ready',attention_date:'2026-11-05',date_basis:'Моя исходная формулировка'}};
  const state = {today:'2026-11-05',tasks:[task],workstreams:[],sessions:[]};
  const before = JSON.stringify(state);
  assert.equal(context.TodayModel.candidates(state)[0].reasons[0], 'Attention date set for today: Моя исходная формулировка');
  assert.equal(JSON.stringify(state), before);
});

test('switcher persists language and retains route, board ID and hash; a pending save prevents navigation', () => {
  class Element {
    constructor(tag) { this.nodeType=1;this.tagName=tag.toUpperCase();this.childNodes=[];this.attributes={};this.listeners={}; }
    getAttribute(key){return this.attributes[key] || null;}
    setAttribute(key,value){this.attributes[key]=value;}
    append(child){this.childNodes.push(child);}
    addEventListener(name,fn){this.listeners[name]=fn;}
  }
  const html=new Element('html'),host=new Element('span'),stored=new Map();let navigation;
  const context=localization('uk',{
    document:{documentElement:html,createElement:tag=>new Element(tag),querySelectorAll:()=>[host]},
    location:{search:'?board=fiction&lang=uk',href:'http://127.0.0.1:8770/planner?board=fiction&lang=uk#example',assign:url=>{navigation=url;}},
    localStorage:{getItem:key=>stored.get(key),setItem:(key,value)=>stored.set(key,value)}
  });
  const select=host.childNodes[0];
  assert.equal(html.lang,'uk');assert.equal(select.attributes['aria-label'],'Мова інтерфейсу');
  context.I18n.beforeChange=()=>false;select.value='en';select.listeners.change();
  assert.equal(navigation,undefined);assert.equal(select.value,'uk');
  context.I18n.beforeChange=()=>true;select.value='en';select.listeners.change();
  assert.equal(navigation,'http://127.0.0.1:8770/planner?board=fiction&lang=en#example');
  assert.equal(stored.get('personal-os-language-v1'),'en');
});
