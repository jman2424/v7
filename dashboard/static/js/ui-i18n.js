(() => {
  'use strict';
  const allowed = new Set(['en', 'es', 'fr', 'ar']);
  const currentScript = document.currentScript;
  const dictionaryUrls = ['ui.json', 'features.json'].map(name => new URL('../i18n/' + name, currentScript.src));
  const cookie = name => {
    const item = document.cookie.split('; ').find(value => value.startsWith(name + '='));
    if (!item) return '';
    try { return decodeURIComponent(item.slice(name.length + 1)); }
    catch { return ''; }
  };
  const preference = () => ['essential', 'all'].includes(cookie('v7_preferences')) ? cookie('v7_preferences') : '';
  const writeCookie = (name, value, age) => {
    document.cookie = name + '=' + encodeURIComponent(value) + '; Path=/; Max-Age=' + age + '; SameSite=Lax' + (location.protocol === 'https:' ? '; Secure' : '');
  };
  const saved = preference() === 'all' ? cookie('v7_language') : '';
  let language = allowed.has(saved) ? saved : navigator.language.split('-')[0].toLowerCase();
  if (!allowed.has(language)) language = 'en';
  let messages = {};
  const translate = source => messages[language]?.[source] || source;
  const apply = () => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
    document.querySelectorAll('[data-language-picker]').forEach(select => { select.value = language; });
    document.querySelectorAll('[data-i18n]').forEach(node => {
      const source = node.dataset.i18nSource || node.textContent.trim();
      node.dataset.i18nSource = source;
      node.textContent = translate(source);
    });
    const banner = document.getElementById('site-cookie-banner');
    if (banner) {
      banner.setAttribute('aria-label', translate('Cookie preferences'));
      banner.querySelector('[data-close-cookie-preferences]')?.setAttribute('aria-label', translate('Close cookie preferences'));
    }
    document.querySelectorAll('[data-language-picker]').forEach(select => select.setAttribute('aria-label', translate('Language')));
    window.dispatchEvent(new CustomEvent('v7-language-changed', {detail:{language}}));
  };
  const setLanguage = value => {
    language = allowed.has(value) ? value : 'en';
    if (preference() === 'all') writeCookie('v7_language', language, 180 * 86400);
    apply();
  };
  const choose = choice => {
    if (choice !== 'all' && choice !== 'essential') return;
    writeCookie('v7_preferences', choice, 180 * 86400);
    if (choice === 'essential') writeCookie('v7_language', '', 0);
    else writeCookie('v7_language', language, 180 * 86400);
    closePreferences();
  };
  const banner = document.getElementById('site-cookie-banner');
  let preferenceOpener = null;
  const reserveBannerSpace = () => {
    document.body.style.paddingBottom = banner && !banner.hidden ? Math.ceil(banner.getBoundingClientRect().height) + 28 + 'px' : '';
  };
  const setBannerOpen = open => {
    if (banner) banner.hidden = !open;
    document.querySelectorAll('[data-open-cookie-preferences]').forEach(button => {
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-controls', 'site-cookie-banner');
    });
    reserveBannerSpace();
  };
  const closePreferences = () => {
    setBannerOpen(false);
    preferenceOpener?.focus();
    preferenceOpener = null;
  };
  window.V7UI = {t: translate, language: () => language, setLanguage};
  document.querySelectorAll('[data-language-picker]').forEach(select => select.addEventListener('change', () => setLanguage(select.value)));
  document.querySelectorAll('[data-open-cookie-preferences]').forEach(button => button.addEventListener('click', () => {
    preferenceOpener = button;
    setBannerOpen(true);
    banner?.querySelector('[data-close-cookie-preferences]')?.focus();
  }));
  document.querySelectorAll('[data-close-cookie-preferences]').forEach(button => button.addEventListener('click', closePreferences));
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && banner && !banner.hidden) closePreferences(); });
  document.querySelectorAll('[data-preferences]').forEach(button => button.addEventListener('click', () => choose(button.dataset.preferences)));
  if (banner && typeof ResizeObserver !== 'undefined') new ResizeObserver(reserveBannerSpace).observe(banner);
  setBannerOpen(!preference());
  apply();
  Promise.all(dictionaryUrls.map(url => fetch(url, {credentials:'omit'}).then(response => response.ok ? response.json() : {}).catch(() => ({})))).then(values => {
    for (const value of values) {
      if (!value || typeof value !== 'object') continue;
      for (const [name, entries] of Object.entries(value)) {
        if (allowed.has(name) && entries && typeof entries === 'object') messages[name] = {...messages[name], ...entries};
      }
    }
    apply();
  }).catch(() => {});
})();
