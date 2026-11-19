/* Shared, offline interface localization. Record contents are never translated. */
(function(root) {
  'use strict';
  const languages = ['uk', 'ru', 'en'];
  const storageKey = 'personal-os-language-v1';
  const messages = root.PersonalOSMessages || {};
  function valid(value) { return languages.includes(value); }
  function resolveLanguage(search, saved) {
    const requested = new URLSearchParams(search || '').get('lang');
    return valid(requested) ? requested : valid(saved) ? saved : 'ru';
  }
  let saved;
  try { saved = root.localStorage?.getItem(storageKey); } catch { /* Private browsing can deny storage. */ }
  const language = resolveLanguage(root.location?.search, saved);
  try { root.localStorage?.setItem(storageKey, language); } catch { /* URL selection still works. */ }
  function t(key, values = {}) {
    const text = messages[key]?.[language] ?? key;
    return String(text).replace(/\{(\w+)\}/g, (match, name) => Object.hasOwn(values, name) ? String(values[name]) : match);
  }
  const api = {language, locale:{uk:'uk-UA',ru:'ru-RU',en:'en-GB'}[language], t, resolveLanguage, beforeChange:()=>true};
  root.I18n = api;
  if (typeof module !== 'undefined') module.exports = api;
  if (!root.document) return;
  document.documentElement.lang = language;
  // Run once, before application rendering: translate only the static HTML shell.
  // Do not observe or translate dynamically inserted personal text or form values.
  function staticCopy(node) {
    if (node.nodeType === 3) {
      const key = node.textContent.trim();
      if (Object.hasOwn(messages, key)) node.textContent = node.textContent.replace(key, t(key));
      return;
    }
    if (node.nodeType !== 1 || ['SCRIPT','STYLE','TEXTAREA'].includes(node.tagName)) return;
    for (const attr of ['aria-label','placeholder','title']) {
      const key = node.getAttribute(attr);
      if (key && Object.hasOwn(messages, key)) node.setAttribute(attr, t(key));
    }
    for (const child of node.childNodes) staticCopy(child);
  }
  staticCopy(document.documentElement);
  for (const host of document.querySelectorAll('[data-language-switcher]')) {
    const select = document.createElement('select');
    select.className = 'language-select';
    select.setAttribute('aria-label', {uk:'Мова інтерфейсу',ru:'Язык интерфейса',en:'Interface language'}[language]);
    select.title = {uk:'Мова інтерфейсу',ru:'Язык интерфейса',en:'Interface language'}[language];
    for (const [value, label] of [['uk','UA'],['ru','RU'],['en','EN']]) {
      const option = document.createElement('option');
      option.value = value; option.textContent = label;
      option.lang = value;
      option.title = {uk:'Українська',ru:'Русский',en:'English'}[value];
      select.append(option);
    }
    select.value = language;
    select.addEventListener('change', () => {
      if (!valid(select.value) || !api.beforeChange()) { select.value = language; return; }
      const next = select.value;
      try { root.localStorage.setItem(storageKey, next); } catch { /* Use the URL fallback. */ }
      const url = new URL(root.location.href);
      url.searchParams.set('lang', next);
      root.location.assign(url.href);
    });
    host.append(select);
  }
})(globalThis);
