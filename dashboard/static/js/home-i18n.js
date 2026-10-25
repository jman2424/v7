(() => {
  'use strict';
  const script = document.currentScript;
  const sources = new WeakMap(), attributes = new WeakMap();
  const normalize = value => value.replace(/\s+/g, ' ').trim();
  let messages = {};
  const translate = source => {
    const language = window.V7UI?.language() || 'en';
    if (language === 'en') return source;
    const entries = messages[language] || {};
    if (typeof entries[source] === 'string') return entries[source];
    const numbers = [];
    const key = source.replace(/(?<![\p{L}\p{N}])\d+(?:[.,]\d+)*(?![\p{L}\p{N}])/gu, value => '{' + (numbers.push(value)-1) + '}');
    if (typeof entries[key] === 'string') return entries[key].replace(/\{(\d+)\}/g, (_, index) => numbers[index] ?? '');
    return window.V7UI?.t(source) || source;
  };
  const apply = () => {
    const walker = document.createTreeWalker(document.body, 4);
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent || parent.closest('script,style,option,code,pre,[aria-hidden="true"],[data-no-i18n]')) continue;
      const marked = parent.closest('[data-i18n]');
      let original = marked?.dataset.i18nSource || sources.get(node);
      if (original === undefined) { original = node.nodeValue; sources.set(node, original); }
      const source = normalize(original);
      if (source) node.nodeValue = original.match(/^\s*/)[0] + translate(source) + original.match(/\s*$/)[0];
    }
    for (const element of document.querySelectorAll('title,meta[name="description"],meta[property="og:title"],meta[property="og:description"],meta[name="twitter:title"],meta[name="twitter:description"],[aria-label],[title],[placeholder],img[alt]')) {
      if (element.matches('[data-language-picker],#site-cookie-banner,[data-close-cookie-preferences]')) continue;
      let saved = attributes.get(element);
      if (!saved) {
        saved = {};
        for (const name of ['aria-label','title','placeholder','alt','content']) if (element.hasAttribute(name)) saved[name] = element.getAttribute(name);
        if (element.tagName === 'TITLE') saved.text = element.textContent;
        attributes.set(element, saved);
      }
      for (const [name, source] of Object.entries(saved)) {
        if (name === 'text') element.textContent = translate(source);
        else element.setAttribute(name, translate(source));
      }
    }
  };
  window.addEventListener('v7-language-changed', apply);
  fetch(new URL('../i18n/home.json?v=20261025', script.src), {credentials:'omit'})
    .then(response => response.ok ? response.json() : {})
    .then(value => { messages = value && typeof value === 'object' ? value : {}; apply(); })
    .catch(() => {});
})();
