(() => {
  'use strict';
  const LIMIT = 96000, DAY = 86400000;
  const byteLength = value => typeof TextEncoder === 'function' ? new TextEncoder().encode(value).length : value.length * 3;
  const actions = values => (Array.isArray(values) ? values : []).slice(0, 3).flatMap(item => {
    if (typeof item === 'string') return ['consultation', 'quote', 'callback'].includes(item) ? [item] : [];
    if (!item || item.type !== 'navigate' || typeof item.url !== 'string' || typeof item.label !== 'string') return [];
    try {
      const url = new URL(item.url);
      if (url.protocol !== 'https:' || url.username || url.password || item.url.length > 2048) return [];
      return [{type:'navigate', url:url.href, label:item.label.slice(0,80),
        ...(typeof item.click_token === 'string' && item.click_token.length <= 4096 ? {click_token:item.click_token} : {}),
        clicked:item.clicked === true}];
    } catch { return []; }
  });
  const rows = values => (Array.isArray(values) ? values : []).slice(-40).flatMap(row =>
    row && ['me','bot','activity'].includes(row.from) && typeof row.text === 'string' && row.text.length <= 4000
      ? [{from:row.from,text:row.text,actions:actions(row.actions)}] : []);
  window.V7ChatSession = (storage, tenant, now = () => Date.now()) => {
    const key = 'transcript:' + tenant;
    let expires = 0, identity = '';
    const clear = () => { expires = 0; identity = ''; try { storage?.removeItem(key); } catch {} };
    return {
      clear,
      read(token) {
        try {
          const raw = storage?.getItem(key);
          if (!raw) return null;
          if (raw.length > LIMIT || byteLength(raw) > LIMIT) { clear(); return null; }
          const saved = JSON.parse(raw);
          if (!token || saved?.version !== 1 || saved.token !== token || !Number.isFinite(saved.expires)
              || saved.expires <= now() || saved.expires > now() + DAY || !Array.isArray(saved.messages)) {
            clear(); return null;
          }
          expires = saved.expires; identity = token;
          return {messages:rows(saved.messages), draft:typeof saved.draft === 'string' ? saved.draft.slice(0,4000) : '',
            pending:typeof saved.pending === 'string' ? saved.pending.slice(0,4000) : ''};
        } catch { clear(); return null; }
      },
      write(token, state) {
        if (!token || typeof token !== 'string' || token.length > 2048) return;
        if (identity !== token || expires <= now()) { identity = token; expires = now() + DAY; }
        const saved = {version:1,token,expires,messages:rows(state.messages),
          draft:String(state.draft || '').slice(0,4000),pending:String(state.pending || '').slice(0,4000)};
        try {
          let encoded = JSON.stringify(saved);
          while (byteLength(encoded) > LIMIT && saved.messages.length) { saved.messages.shift(); encoded = JSON.stringify(saved); }
          storage?.setItem(key, encoded);
        } catch { /* Blocked/full browser storage must never break chat. */ }
      }
    };
  };
})();
