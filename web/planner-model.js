(function (scope) {
  'use strict';
  const dates = start => Array.from({length: 7}, (_, i) => {
    const d = new Date(start + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + i); return d.toISOString().slice(0, 10);
  });
  const time = minute => `${Math.floor(minute / 60).toString().padStart(2, '0')}:${(minute % 60).toString().padStart(2, '0')}`;
  const duration = n => n < 60 ? `${n}m` : `${Math.floor(n / 60)}h${n % 60 ? ` ${n % 60}m` : ''}`;
  const colors = [['#516ac3','#edf0ff'],['#b36527','#fff0e2'],['#18786f','#e5f5ef'],['#8251ad','#f1eafb'],['#376e9c','#e8f2fc'],['#576b35','#eef3e5'],['#a34d70','#faedf3'],['#64748b','#eef2f6']];
  const projects = cards => [...new Set(cards.map(c=>c.project).filter(Boolean))].sort();
  function projectColor(project) {
    let hash=0;for(const c of String(project || ''))hash=(Math.imul(hash,31)+c.codePointAt(0))>>>0;
    return [...colors[hash%colors.length]];
  }
  function conflicts(cards) {
    const pairs = [];
    cards.forEach((a, i) => cards.slice(i + 1).forEach(b => {
      const x = a.placement, y = b.placement;
      if (x && y && x.date === y.date && x.start_minute !== null && y.start_minute !== null &&
          x.start_minute < y.start_minute + b.minutes && y.start_minute < x.start_minute + a.minutes) pairs.push([a, b]);
    }));
    return pairs;
  }
  function dropRange(y, height, start, end, minutes, grabMinutes = 0) {
    const snapped = Math.round((start + y / height * (end - start) - grabMinutes) / 15) * 15;
    const from = Math.max(start, Math.min(end - minutes, snapped));
    return {start: from, end: from + minutes};
  }
  function dropMinute(y, height, start, end, minutes) {
    return dropRange(y, height, start, end, minutes).start;
  }
  function resizeMinutes(original, deltaPixels, pixelsPerMinute, start, visibleEnd = 1440) {
    const snapped = Math.round((original + deltaPixels / pixelsPerMinute) / 15) * 15;
    return Math.max(15, Math.min(720, visibleEnd - start, 1440 - start, snapped));
  }
  const api = {dates, time, duration, conflicts, dropMinute, dropRange, resizeMinutes, projects, projectColor};
  if (typeof module !== 'undefined') module.exports = api;
  scope.PlannerModel = api;
})(typeof window !== 'undefined' ? window : globalThis);
