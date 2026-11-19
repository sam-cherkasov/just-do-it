"use strict";
(function(root) {
  const text = (key) => root.I18n ? root.I18n.t(key) : key;
  function streamFor(state, task) { return state.workstreams.find(s=>(s.data.task_ids || []).includes(task.id)); }
  function bucket(task) {
    if (['done','dropped'].includes(task.data.status)) return 'closed';
    if (task.data.deferred) return 'later';
    if (task.data.status === 'waiting') return 'waiting';
    return 'available';
  }
  function choice(state) { return (state.day_choices || []).find(r=>r.data.date===state.today); }
  function weekEnd(start) { const date=new Date(start+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+6);return date.toISOString().slice(0,10); }
  function candidates(state) {
    const result = state.tasks.filter(t=>bucket(t)==='available' && streamFor(state,t)?.data.status!=='paused').map(task=>{
      const stream = streamFor(state,task), reasons=[];
      const cards = (state.relationships?.cards || []).filter(c=>c.task_id===task.id && c.selected && c.placement?.date===state.today);
      if(cards.length) reasons.push(text('Карточка выбрана в плане на сегодня'));
      if(task.data.attention_date === state.today) reasons.push(text('На сегодня отмечена дата внимания: ')+(task.data.date_basis || text('см. задачу')));
      const session = [...state.sessions].filter(s=>s.data.task_id===task.id && s.data.status==='closed' && s.data.next_action).sort((a,b)=>b.updated_at.localeCompare(a.updated_at))[0];
      if(session) reasons.push(text('После сессии сохранён следующий шаг'));
      if((stream?.data.questions || []).some(q=>q.task_id===task.id) && !task.data.user_control?.fields.some(f=>['title','next_action'].includes(f))) reasons.push(text('В направлении есть вопрос для твоего решения'));
      if(task.data.status==='doing') reasons.push(text('В сохранённом контексте задача уже начата'));
      if(!reasons.length) reasons.push(text('Открытая задача')+(stream ? text(' в направлении «')+stream.data.title+text('»') : text(' без направления')));
      return {task,stream,reasons,session,order:cards.length ? 0 : task.data.attention_date===state.today ? 1 : session ? 2 : 3};
    });
    return result.sort((a,b)=>a.order-b.order || (a.stream?.data.order ?? 99)-(b.stream?.data.order ?? 99) || a.task.data.title.localeCompare(b.task.data.title,root.I18n?.locale || 'ru'));
  }
  root.TodayModel = {streamFor,bucket,choice,candidates,weekEnd};
  if(typeof module !== 'undefined')module.exports=root.TodayModel;
})(typeof globalThis !== 'undefined' ? globalThis : this);
