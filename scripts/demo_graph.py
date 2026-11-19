#!/usr/bin/env python3
"""Generate an offline synthetic 3D workload and fallback check for a real browser."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_os.view import render
from tests.scenario import Scenario


def main():
    root = Path(tempfile.mkdtemp(prefix='personal-os-graph-check-')).resolve()
    scenario = Scenario(root)
    scenario.populate()
    path = render(scenario.engine)
    # This diagnostics-only page creates fictional projection data in memory.
    # It never reads or writes personal records, calendar, or project sources.
    script = r'''
const bench = document.createElement('section');
bench.style.cssText = 'background:white;padding:20px;border:1px solid #c7d4df;margin-bottom:25px';
const heading = document.createElement('h2'); heading.textContent = 'Synthetic graph diagnostics';
const result = document.createElement('p'); result.id = 'benchmark-result';
result.textContent = 'Choose a synthetic workload. No personal data is used.';
const mount = document.createElement('div'); bench.append(heading, result, mount);
let workload, benchRenderer;
function makeRecords(count) {
  const records = [];
  const add = (id, type, parents, extra = {}) => records.push({id, kind:type==='task'?'task':'node', revision:1,
    source:{kind:'synthetic',reference:'Diagnostics-only fictional records'}, updated_at:new Date().toISOString(),
    data:{title:(type==='task'?'Проверить следующий шаг ':'Тестовая ветка ')+id,type,parents,status:'active',...extra}});
  add('r', 'area', [], {mode:'growth'});
  if (count === 500) {
    for(let i=1;i<500;i++) {
      if(i<100)add('n'+i,'strategy',['r']);
      else add('n'+i,'task',['n'+(1+i%99),'n'+(1+(i+1)%99),...(i<201?['n'+(1+(i+2)%99)]:[])],
        {status:'ready',intent:'proposed',priority:'primary',next_action:'Сформулировать один вопрос',rationale:'Synthetic example'});
    }
  } else {
    for(let i=1;i<20;i++)add('n'+i,'strategy',['r']);
    for(let i=20;i<count;i++)add('n'+i,'task',['n'+(1+i%19),'n'+(1+(i+1)%19),'n'+(1+(i+2)%19),...(i<61?['n'+(1+(i+3)%19)]:[])],
      {status:'ready',intent:'proposed',priority:'primary',next_action:'Сформулировать один вопрос',rationale:'Synthetic example'});
  }
  return records;
}
for(const size of [100,500]) {
  const b = document.createElement('button'); b.textContent = 'Load '+size+' nodes'; b.type='button';
  b.addEventListener('click',()=> {
    workload?.destroy(); mount.replaceChildren(); benchRenderer=null;
    const data={...snapshot,records:makeRecords(size),source_health:[]};
    workload=PersonalOsLifeMap.mount(mount,data,{inspect:()=>{},savedState:{collapsed:[]}});
    result.textContent=size+' synthetic nodes loaded. Use the scene or run the render benchmark.';
  }); bench.insertBefore(b,mount);
}
const run=document.createElement('button');run.textContent='Run render benchmark';run.type='button';bench.insertBefore(run,mount);
run.addEventListener('click',()=>{
  if(!workload)return;
  const start=performance.now(), before=workload.stats().renders;
  let frames=0;
  // Dispatch genuine resize observations: same rendering path as normal viewport interaction.
  const viewport=mount.querySelector('.map-viewport');
  function tick() {
    viewport.style.width=(frames%2?100:99.8)+'%';frames++;
    if(frames<90){requestAnimationFrame(tick);return;}
    requestAnimationFrame(()=>{
      const elapsed=performance.now()-start, stats=workload.stats();
      const renders=stats.renders-before;
      const fps=renders/(elapsed/1000);
      result.textContent=stats.nodes+' nodes; '+frames+' interaction frames; '+renders+' renders in '+elapsed.toFixed(0)+' ms; '+fps.toFixed(1)+' renders/sec.';
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        const idle=workload.stats().renders;
        setTimeout(()=>{result.textContent+=' Idle renders after 600 ms: '+(workload.stats().renders-idle)+'.';},600);
      }));
    });
  }
  requestAnimationFrame(tick);
});
const loss=document.createElement('button'); loss.textContent='Simulate WebGL loss';loss.type='button';bench.insertBefore(loss,mount);
loss.addEventListener('click',()=>{
  const canvas=mount.querySelector('canvas');
  canvas?.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext();
});
document.getElementById('page').prepend(bench);
'''
    html = path.read_text().replace('</body>', '<script>' + script + '</script></body>')
    path.write_text(html)
    print(json.dumps({'synthetic': True, 'root': str(root), 'view': str(path)}, indent=2))


if __name__ == '__main__':
    main()
