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
  const legacyId = (row, index) => {
    let hash = 2166136261;
    for (const char of row.from + '\0' + row.text) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    return 'legacy:' + String(index).padStart(3,'0') + ':' + (hash >>> 0).toString(16);
  };
  const rows = values => (Array.isArray(values) ? values : []).slice(-40).flatMap((row,index) =>
    row && ['me','bot','activity'].includes(row.from) && typeof row.text === 'string' && row.text.length <= 4000
      ? [{id:typeof row.id === 'string' && /^[A-Za-z0-9:.-]{1,100}$/.test(row.id) ? row.id : legacyId(row,index),
        at:Number.isFinite(row.at) && row.at >= 0 ? row.at : 0,
        from:row.from,text:row.text,actions:actions(row.actions)}] : []);
  window.V7MergeChatRows = (current, incoming) => {
    const merged = new Map();
    for (const row of [...rows(current),...rows(incoming)]) {
      const previous = merged.get(row.id);
      if (!previous) merged.set(row.id,row);
      else {
        // Message identity/text are immutable; preserve click acknowledgement
        // even when an older peer has not received it yet.
        const combined = [...previous.actions,...row.actions];
        previous.actions = combined.filter((item,index) => combined.findIndex(other =>
          typeof item === 'string' ? item === other : other?.url === item.url) === index).slice(0,3);
        for (const item of previous.actions) if (typeof item !== 'string') item.clicked = combined.some(other => other?.url === item.url && other.clicked);
      }
    }
    return [...merged.values()].sort((a,b)=>a.at-b.at || a.id.localeCompare(b.id)).slice(-40);
  };
  window.V7ChatSession = (storage, tenant, now = () => Date.now()) => {
    const key = 'transcript:' + tenant;
    let expires = 0, identity = '', retired = '';
    const clear = () => { if (identity) retired = identity; expires = 0; identity = ''; try { storage?.removeItem(key); } catch {} };
    return {
      clear,
      read(token, shared) {
        try {
          const raw = shared === undefined ? storage?.getItem(key) : shared;
          if (!raw) return null;
          if (raw.length > LIMIT || byteLength(raw) > LIMIT) { clear(); return null; }
          const saved = JSON.parse(raw);
          if (saved?.token === token && Number.isFinite(saved.expires) && saved.expires <= now()) retired = token;
          if (!token || saved?.version !== 1 || saved.token !== token || !Number.isFinite(saved.expires)
              || saved.expires <= now() || saved.expires > now() + DAY || !Array.isArray(saved.messages)) {
            clear(); return null;
          }
          expires = saved.expires; identity = token;
          return {expires:saved.expires,messages:rows(saved.messages), draft:typeof saved.draft === 'string' ? saved.draft.slice(0,4000) : '',
            pending:typeof saved.pending === 'string' ? saved.pending.slice(0,4000) : ''};
        } catch { clear(); return null; }
      },
      write(token, state) {
        if (!token || typeof token !== 'string' || token.length > 2048) return;
        if (token === retired) return;
        if (identity === token && expires <= now()) { clear(); return; }
        if (identity !== token) { identity = token; expires = now() + DAY; }
        const saved = {version:1,token,expires,messages:rows(state.messages),
          draft:String(state.draft || '').slice(0,4000),pending:String(state.pending || '').slice(0,4000)};
        let encoded;
        try {
          encoded = JSON.stringify(saved);
          while (byteLength(encoded) > LIMIT && saved.messages.length) { saved.messages.shift(); encoded = JSON.stringify(saved); }
          storage?.setItem(key, encoded);
        } catch { /* Blocked/full browser storage must never break chat. */ }
        return encoded;
      }
    };
  };
  // Share requested chat continuity only with open tabs in this browser's
  // same-origin storage partition. No localStorage or longer retention.
  window.V7ChatTabs = (scope, snapshot, receive, Channel = window.BroadcastChannel) => {
    let channel, last = '';
    const publish = force => {
      try {
        const value = snapshot();
        if (value && (force || value !== last)) {
          last = value;
          channel?.postMessage({type:'state',value});
        }
      } catch { /* Unsupported or blocked cross-tab messaging is optional. */ }
    };
    try {
      if (typeof Channel === 'function') {
        channel = new Channel('v7-chat:' + scope);
        channel.onmessage = event => {
          if (event.data?.type === 'request') { publish(true); return; }
          const raw = event.data?.value;
          if (event.data?.type !== 'state' || typeof raw !== 'string' || byteLength(raw) > LIMIT) return;
          try {
            const token = JSON.parse(raw).token;
            if (typeof token !== 'string' || !token || token.length > 2048) return;
            const saved = window.V7ChatSession({getItem:()=>raw,removeItem(){}},scope).read(token);
            if (saved?.messages.length) receive(token, raw);
          } catch { /* Malformed messages cannot disrupt ordinary chat. */ }
        };
        channel.postMessage({type:'request'});
      }
    } catch { channel = null; }
    return {publish:()=>publish(false),close:()=>{try { channel?.close(); } catch {}}};
  };
})();
