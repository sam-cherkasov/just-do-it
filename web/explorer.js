"use strict";
const snapshot = JSON.parse(document.getElementById("snapshot").textContent);
const records = snapshot.records;
const byId = new Map(records.map(r => [r.id, r]));
const page = document.getElementById("page");
const dialog = document.getElementById("inspector");
let lifeMapController;
let lifeMapState = {};
document.querySelector(".skip").addEventListener("click", event => {
  event.preventDefault();
  document.getElementById("content").focus();
});
const tz = snapshot.config.timezone;
const niceTime = value => new Date(value).toLocaleString(undefined, {timeZone: tz, dateStyle: "medium", timeStyle: "short"});
const title = r => r.data.title || ({diary:"Original diary note", summary:"Daily summary", reflection:"Period reflection", report:"Reported activity", memory:"Saved understanding", feedback:"Pilot feedback", review:"Cycle review", plan:"Plan", calendar:"Calendar snapshot", source_check:"Source check", source_review:"Source reconciliation"}[r.kind]) || r.kind;
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
function link(text, hash, cls) { const a = el("a", text, cls); a.href = "#" + hash; return a; }
function button(text, handler, cls="plain-button") { const b = el("button", text, cls); b.type = "button"; b.addEventListener("click", handler); return b; }
function badge(text) { return el("span", text, "badge " + text); }
function header(heading, intro) { page.append(el("h1", heading), el("p", intro, "intro")); }
function empty(heading, text, target=page) { const div=el("div", undefined,"empty"); div.append(el("strong",heading),el("p",text));target.append(div); }
function recordButton(r, label) { return button(label || title(r), () => inspect(r.id)); }
function sources(target, refs) {
  const list=el("ul",undefined,"source-list");
  for (const ref of refs || []) { const li=el("li"); const r=byId.get(ref.id); li.append(r ? recordButton(r, title(r)+" · revision "+ref.revision) : el("span","Source unavailable: "+ref.id));list.append(li); }
  target.append(list);
}
function inspect(id) {
  const r=byId.get(id); if (!r) return;
  const target=document.getElementById("inspector-content"); target.replaceChildren();
  const heading=el("h2", title(r));heading.id="inspector-title";target.append(heading);
  if(r.stale) target.append(badge("stale"),el("p","Sources changed or new notes arrived. Revisit this interpretation or regenerate the summary before relying on it."));
  const meta=el("dl",undefined,"meta");
  for (const [k,v] of Object.entries({"Source":r.source.kind,"Reference":r.source.reference,"Saved":niceTime(r.created_at),"Updated":niceTime(r.updated_at),"Revision":r.revision,"File":r._path})) meta.append(el("dt",k),el("dd",String(v)));
  target.append(meta);
  if(r.data.text) target.append(el("p",r.data.text,"body-text"));
  for(const [key,label] of [["next_action","Next action"],["waiting_on","Waiting for"],["rationale","Why it matters"],["completion_evidence","Reported completion"],["summary","Reconciliation"],["locator","Source location"]]) {
    if(r.data[key])target.append(el("h3",label),el("p",r.data[key],"body-text"));
  }
  if(r.data.intent)target.append(badge(r.data.intent));
  if(r.data.attention_date)target.append(el("p",r.data.attention_date+" · "+r.data.date_basis,"small"));
  if(r.data.status) target.append(badge(r.data.status));
  if(r.data.evidence_kind) target.append(el("p",r.data.evidence_kind.replaceAll("_"," ")));
  if(r.data.missing_days) target.append(el("p","Days without notes/reports: "+(r.data.missing_days.join(", ")||"None in this period")+". Selective reporting is not a complete record of life.","small"));
  if(r.data.sources) {target.append(el("h3","Source records"));sources(target,r.data.sources);}
  if(r.data.records?.length){target.append(el("h3","Saved updates"));sources(target,r.data.records);}
  if(r.data.source_id&&byId.has(r.data.source_id)){target.append(el("h3","Project source"),recordButton(byId.get(r.data.source_id)));}
  if(r.data.checked_at)target.append(el("p","Checked: "+niceTime(r.data.checked_at),"small"));
  if(r.data.interpretations?.length) {
    target.append(el("h3","Possible patterns"));
    for(const h of r.data.interpretations) {target.append(el("p",h.text),badge("hypothesis"),el("p",h.limitations,"small"));sources(target,(h.support||[]).map(id=>({id,revision:byId.get(id)?.revision})));target.append(el("p","Counterexamples","small"));sources(target,(h.counterevidence||[]).map(id=>({id,revision:byId.get(id)?.revision})));}
  }
  const detail=el("details");detail.append(el("summary","Inspect all saved fields"),el("pre",JSON.stringify(r.data,null,2)));target.append(detail);
  if(r.history?.length) {const history=el("details");history.append(el("summary","Earlier versions ("+r.history.length+")"));for(const old of r.history){history.append(el("h3","Revision "+old.revision),el("p",niceTime(old.updated_at),"small"),el("pre",old.data.text || JSON.stringify(old.data,null,2)));}target.append(history);}
  if(!dialog.open) dialog.showModal();
  document.getElementById("close-inspector").focus();
}
document.getElementById("close-inspector").addEventListener("click",()=>dialog.close());
function planSection(target) {
  const today=new Intl.DateTimeFormat("en-CA",{timeZone:tz,year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const all=records.filter(r=>r.kind==="plan" && ["agreed","draft"].includes(r.data.status));
  const plans=all.filter(r=>(r.data.agreed||r.data.proposal).end>=today);
  if(!plans.length)empty("No current plan",'The next planning conversation can use your connected projects. Past plans do not automatically become today’s obligations.',target);
  const past=all.filter(r=>(r.data.agreed||r.data.proposal).end<today);
  if(past.length){const history=el("details");history.append(el("summary","Past planning periods · "+past.length));for(const r of past){const p=r.data.agreed||r.data.proposal;history.append(el("p",p.start+" to "+p.end,"small"),recordButton(r,"Inspect historical plan"));}target.append(history);}
  for(const r of plans) {
    const box=el("section",undefined,"sheet");const plan=r.data.agreed||r.data.proposal;
    box.append(el("h2",plan.title),badge(r.data.status),el("p",plan.start+" to "+plan.end,"small"),recordButton(r,"Inspect this plan"));
    if(r.data.agreed && r.data.proposal) box.append(el("p","A proposed change is waiting. The agreed plan below is still in effect."),badge("draft"));
    for(const action of plan.actions) {
      const row=el("div",undefined,"row"),body=el("div");
      const reports=records.filter(x=>x.kind==="report"&&x.data.plan_id===r.id&&x.data.action_id===action.id).sort((a,b)=>(a.data.event_date+a.updated_at).localeCompare(b.data.event_date+b.updated_at));
      const report=reports[reports.length-1];
      body.append(el("h3",action.title),el("p",action.minutes+" min · "+(report?"Reported "+report.data.status:"No report yet")));
      if(report) body.append(recordButton(report,"Read report"));
      row.append(el("span",action.date||"Unallocated","action-date"),body);box.append(row);
    }
    box.append(el("p","Protected rest: "+(plan.protected_days.join(", ")||"Not specified"),"small"));target.append(box);
  }
}
function overview() {
  header("Карта твоих целей", "Выбери цель, проследи связи и найди следующий шаг.");
  lifeMapController = PersonalOsLifeMap.mount(page, snapshot, {inspect, savedState: lifeMapState});
  const currentTasks=records.filter(r=>r.kind==="task"&&!['done','dropped'].includes(r.data.status));
  if(currentTasks.length){const focus=el("section",undefined,"focus-grid");const actionable=el("div"),waiting=el("div");actionable.append(el("h2","Next moves"));for(const r of sortedTasks(currentTasks.filter(r=>r.data.status!=="waiting")).slice(0,3))actionable.append(taskCard(r));waiting.append(el("h2","Waiting"));for(const r of currentTasks.filter(r=>r.data.status==="waiting").slice(0,3))waiting.append(taskCard(r));if(!currentTasks.some(r=>r.data.status==="waiting"))waiting.append(el("p","No reported waiting items.","small"));focus.append(actionable,waiting);page.append(focus);}
  if(snapshot.source_health?.length){const issues=snapshot.source_health.filter(s=>s.state!=="reviewed"||s.expired);page.append(link("Project sources · "+issues.length+" need checking or review","sources","source-status"));}
  const columns=el("div",undefined,"columns"),work=el("section"),learning=el("section");
  work.append(el("h2","Current cycle"));planSection(work);learning.append(el("h2","Recent reflection"));
  const reviews=records.filter(r=>["review","reflection"].includes(r.kind)).sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).slice(0,3);
  for(const r of reviews){const item=el("div",undefined,"note");item.append(recordButton(r),el("p",r.data.start+" to "+r.data.end,"small"));if(r.stale)item.append(badge("stale"));learning.append(item);}
  if(!reviews.length) learning.append(el("p","Reviews will connect what you planned with what you reported. Silence stays unknown.","muted"));
  columns.append(work,learning);page.append(columns);
}
function node(id) {
  const r=byId.get(id);if(!r||r.kind!=="node"){empty("This item is not in the snapshot","Refresh the view from your conversation.");return;}
  const crumbs=el("nav",undefined,"breadcrumbs");crumbs.setAttribute("aria-label","Breadcrumb");crumbs.append(link("Life map","overview"));
  const chain=[];let cursor=r;const visited=new Set([r.id]);
  while(cursor.data.parents?.length){const parent=byId.get(cursor.data.parents[0]);if(!parent||visited.has(parent.id))break;visited.add(parent.id);chain.unshift(parent);cursor=parent;}
  for(const ancestor of chain)crumbs.append(el("span","/"),link(ancestor.data.title,"node/"+encodeURIComponent(ancestor.id)));
  page.append(crumbs);header(r.data.title,r.data.rationale||r.data.description||"Follow the connections below, or inspect the saved context.");page.append(badge(r.data.mode||r.data.type),recordButton(r," Inspect source"));
  const otherParents=(r.data.parents||[]).slice(1);if(otherParents.length){page.append(el("h2","Also connected to"));for(const id of otherParents){const p=byId.get(id);if(p)page.append(link(p.data.title,"node/"+encodeURIComponent(id)));}}
  const children=records.filter(x=>x.kind==="node"&&(x.data.parents||[]).includes(id));
  if(children.length){page.append(el("h2","Next level"));const list=el("div",undefined,"branch-list");for(const child of children){const row=el("div",undefined,"branch"),a=link(child.data.title,"node/"+encodeURIComponent(child.id));a.append(el("span",child.data.type));row.append(a);list.append(row);}page.append(list);}
  const related=records.filter(x=>x.kind==="task"&&(x.data.parents||[]).includes(id)&&x.data.status!=="dropped");
  if(related.length){page.append(el("h2","Connected tasks"));for(const task of sortedTasks(related))page.append(taskCard(task));}
  for(const p of records.filter(x=>x.kind==="plan"&&x.data.status!=="closed")) {
    const plan=p.data.agreed||p.data.proposal;if(!plan)continue;
    const actions=plan.actions.filter(a=>a.outcome_ids.includes(id));
    if(actions.length){page.append(el("h2","Actions in this cycle"),badge(p.data.status));for(const a of actions){const row=el("div",undefined,"row");row.append(el("div",a.title),el("span",(a.date||"Unallocated")+" · "+a.minutes+" min","small"),recordButton(p,"View plan"));page.append(row);}}
  }
  if(!children.length && !related.length && !["outcome","experiment"].includes(r.data.type))empty("No next level chosen yet","You can explore an approach in conversation before deciding to turn it into a commitment.");
}
function sortedTasks(items){const rank={primary:0,supporting:1,unranked:2};return [...items].sort((a,b)=>(rank[a.data.priority]??2)-(rank[b.data.priority]??2)||title(a).localeCompare(title(b)));}
function taskCard(r){
  const card=el("article",undefined,"task-card");card.append(recordButton(r),el("div",r.data.intent==="proposed"?"Proposed · "+r.data.priority:"Reported · "+r.data.status,"small"));
  card.append(el("p",r.data.status==="waiting"?r.data.waiting_on:r.data.next_action||r.data.completion_evidence||"", "task-next"));
  if(r.stale)card.append(badge("stale"));
  if(r.data.attention_date)card.append(el("p",r.data.attention_date+" · "+r.data.date_basis,"small"));
  const connections=el("div",undefined,"task-links");for(const id of r.data.parents||[]){const parent=byId.get(id);if(parent)connections.append(link(parent.data.title,"node/"+encodeURIComponent(id)));}card.append(connections);return card;
}
function tasks(){
  header("Task board","See proposed next moves, reported work, and items waiting on someone else. Status changes are saved through your Personal OS conversation.");
  const items=records.filter(r=>r.kind==="task"&&r.data.status!=="dropped");
  if(!items.length){empty("Your board is ready","Source-backed tasks will appear here as project updates are reconciled.");return;}
  const board=el("div",undefined,"task-board");
  const emptyStates=[];
  for(const [state,label] of [["candidate","Candidates"],["ready","Ready"],["doing","Doing"],["waiting","Waiting"],["done","Done"]]){const selected=sortedTasks(items.filter(r=>r.data.status===state));if(!selected.length){emptyStates.push(label);continue;}const lane=el("section",undefined,"task-lane");lane.append(el("h2",label));for(const r of selected)lane.append(taskCard(r));board.append(lane);}page.append(board);if(emptyStates.length)page.append(el("p","No items in: "+emptyStates.join(", "),"small"));
}
function projectSources(){
  header("Project sources","A successful read and an update to your priorities are separate steps. This shows what was checked and what still needs review.");
  const health=snapshot.source_health||[];
  if(!health.length){empty("No sources registered","Connect existing project files and chats through your conversation. You do not need to duplicate their contents.");return;}
  const labels={not_checked:"Not checked",needs_review:"Needs reconciliation",reviewed:"Reviewed",unavailable:"Unavailable",paused:"Paused"};
  for(const item of health){const r=byId.get(item.id);if(!r)continue;const block=el("section",undefined,"sheet");block.append(el("h2",item.title),badge(labels[item.state]||item.state));if(item.expired)block.append(badge("Check expired"));block.append(el("p",r.data.scope),el("p",r.data.locator,"body-text small"));block.append(el("p",item.checked_at?"Last checked: "+niceTime(item.checked_at):"No successful check recorded yet","small"));if(item.last_success_at)block.append(el("p","Last successful read: "+niceTime(item.last_success_at),"small"));if(item.error)block.append(el("p",item.error,"body-text"));if(item.check_id)block.append(recordButton(byId.get(item.check_id),"Inspect latest check"));if(item.review_id)block.append(el("span"," · "),recordButton(byId.get(item.review_id),"Inspect reconciliation"));page.append(block);}
}
function diary() {
  header("A record in your own words", "Notes stay separate from summaries. Open a day to revisit what you said, then follow the sources behind a reflection.");
  const filters=el("div",undefined,"filters"),from=el("input"),to=el("input");from.type=to.type="date";
  for(const [label,input] of [["From",from],["Through",to]]){const l=el("label",label);l.append(input);filters.append(l);}
  page.append(filters);const timeline=el("div",undefined,"timeline");page.append(timeline);
  function update(){timeline.replaceChildren();const entries=records.filter(r=>["diary","summary","reflection"].includes(r.kind)&&(!from.value||r.data.event_date>=from.value)&&(!to.value||r.data.event_date<=to.value));
    const dates=[...new Set(entries.map(r=>r.data.event_date))].sort().reverse();
    if(!dates.length){empty("No diary entries in this view",'Say “This is a diary note…” in your conversation. Your supplied words will be saved without turning them into a task.',timeline);return;}
    for(const date of dates){const day=el("section",undefined,"day");day.append(el("h2",date));for(const r of entries.filter(r=>r.data.event_date===date).sort((a,b)=>a.created_at.localeCompare(b.created_at))){const note=el("article",undefined,"note");note.append(recordButton(r),el("p",r.kind==="diary"?"Your supplied words":"Agent-generated · follow the sources","small"));if(r.stale)note.append(badge("stale"));note.append(el("div",r.data.text,"excerpt"));day.append(note);}timeline.append(day);}}
  from.addEventListener("change",update);to.addEventListener("change",update);update();
}
function memory() {
  header("What I know, and why", "Your statements, recorded observations, and tentative interpretations stay distinct. You can correct any of them in conversation.");
  const groups=[["user_statement","What you told me"],["observation","Recorded observations"],["hypothesis","Working hypotheses"]];
  let count=0;for(const [kind,label] of groups){const items=records.filter(r=>r.kind==="memory"&&r.data.evidence_kind===kind);if(!items.length)continue;count+=items.length;page.append(el("h2",label));for(const r of items){const item=el("section",undefined,"note");item.append(recordButton(r,r.data.text),el("p",r.data.scope,"small"),badge(r.data.status));if(r.stale)item.append(badge("stale"));page.append(item);}}
  if(!count)empty("No personal beliefs have been saved", "This view fills only with explicitly saved context. Diary entries do not automatically become facts about you.");
}
function feedback() {
  header("Shape the pilot as you use it", "Capture a rough edge when it happens. Later, choose one item or a batch to work on.");
  const label=el("label","Show "),select=el("select");for(const status of ["all","new","selected","resolved","deferred"]){const option=el("option",status);option.value=status;select.append(option);}label.append(select);page.append(label);const list=el("section");page.append(list);
  function update(){list.replaceChildren();const items=records.filter(r=>r.kind==="feedback"&&(select.value==="all"||r.data.status===select.value));if(!items.length){empty("No feedback in this view",'Say “Save some feedback…” whenever something gets in your way.',list);return;}for(const r of items){const row=el("div",undefined,"row");row.append(recordButton(r,r.data.text),badge(r.data.status));list.append(row);}}
  select.addEventListener("change",update);update();
}
function route(){if(lifeMapController){lifeMapState=lifeMapController.getState();lifeMapController.destroy();lifeMapController=null;}page.replaceChildren();const hash=decodeURIComponent(location.hash.slice(1)||"overview");const tab=hash.startsWith("node/")?"overview":hash.startsWith("task/")?"tasks":hash;
  document.body.classList.toggle("map-screen", tab==="overview" && !hash.startsWith("node/"));
  for(const a of document.querySelectorAll("[data-tab]")){if(a.dataset.tab===tab)a.setAttribute("aria-current","page");else a.removeAttribute("aria-current");}
  if(hash.startsWith("node/"))node(hash.slice(5));else if(hash.startsWith("task/")){tasks();inspect(hash.slice(5));}else ({overview,tasks,sources:projectSources,diary,memory,feedback}[tab]||overview)();
  document.title="Personal OS · "+(page.querySelector("h1")?.textContent||"Life map");
}
document.getElementById("freshness").textContent="Snapshot: "+niceTime(snapshot.generated_at)+" ("+tz+")";
document.getElementById("revision").textContent="Snapshot revision "+snapshot.revision;
if(snapshot.config.synthetic)document.getElementById("environment").textContent="Synthetic demonstration · no real commitments";
window.addEventListener("hashchange",route);route();
