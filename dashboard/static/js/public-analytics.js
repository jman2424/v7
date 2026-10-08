(() => {
  'use strict';
  const publicPaths = new Set([
    '/', '/solutions/website-chatbot', '/solutions/ai-chatbot-software',
    '/solutions/sales-chatbot', '/solutions/customer-support-chatbot',
    '/solutions/ai-lead-generation-software', '/solutions/conversational-ai-platform',
    '/solutions/branded-website-chat-widget', '/solutions/ai-product-recommendation-chatbot'
  ]);
  const configElement = document.getElementById('v7-public-analytics-config');
  if (!configElement || !publicPaths.has(location.pathname)) return;
  let configuration;
  try { configuration = JSON.parse(configElement.textContent); }
  catch { return; }
  if (!configuration || typeof configuration !== 'object') return;
  const measurementId = configuration.measurement_id;
  if (typeof measurementId !== 'string' || !/^G-[A-Z0-9]{6,20}$/.test(measurementId)) return;
  const disableKey = 'ga-disable-' + measurementId;
  const consentGranted = () => {
    const item = document.cookie.split('; ').find(value => value.startsWith('v7_analytics_consent='));
    if (!item) return false;
    try { return decodeURIComponent(item.slice('v7_analytics_consent='.length)) === 'v1:granted'; }
    catch { return false; }
  };
  const page = {
    page_location: location.origin + location.pathname,
    page_referrer: '',
    page_title: document.title
  };
  const denied = {ad_storage:'denied', ad_user_data:'denied', ad_personalization:'denied', analytics_storage:'denied'};
  let script;
  let loaded = false;
  let configured = false;
  let active = false;
  let pageViewSent = false;
  let queue;
  window[disableKey] = true;
  const stop = () => {
    window[disableKey] = true;
    active = false;
    window.V7UI?.clearAnalyticsCookies();
    // Do not issue a consent update ping after withdrawal in basic mode.
  };
  const recordPage = () => {
    if (!loaded || !consentGranted() || !publicPaths.has(location.pathname)) { stop(); return; }
    if (active) return;
    window[disableKey] = false;
    queue('consent', 'update', {...denied, analytics_storage:'granted'});
    if (!configured) {
      queue('config', measurementId, {
        ...page,
        send_page_view:false,
        allow_google_signals:false,
        allow_ad_personalization_signals:false,
        cookie_domain:'none',
        cookie_path:'/',
        cookie_expires:180 * 86400,
        cookie_update:false,
        cookie_flags:'SameSite=Lax;Secure'
      });
      configured = true;
    }
    if (!pageViewSent && consentGranted()) {
      queue('event', 'page_view', {...page, send_to:measurementId});
      pageViewSent = true;
    }
    active = true;
  };
  const sync = () => {
    if (!consentGranted() || !publicPaths.has(location.pathname)) { stop(); return; }
    if (loaded) { recordPage(); return; }
    if (script) return;
    window.dataLayer = window.dataLayer || [];
    queue = function () { window.dataLayer.push(arguments); };
    queue('consent', 'default', denied);
    queue('set', {...page, send_page_view:false, allow_google_signals:false, allow_ad_personalization_signals:false, ads_data_redaction:true, url_passthrough:false});
    queue('js', new Date());
    script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(measurementId);
    script.referrerPolicy = 'no-referrer';
    script.onload = () => { loaded = true; recordPage(); };
    script.onerror = () => { stop(); script.remove(); script = undefined; };
    document.head.appendChild(script);
  };
  window.addEventListener('v7-analytics-consent-changed', sync);
  window.addEventListener('pageshow', sync);
  window.addEventListener('focus', sync);
  document.addEventListener('visibilitychange', sync);
  if (typeof BroadcastChannel === 'function') {
    const channel = new BroadcastChannel('v7-cookie-consent');
    channel.addEventListener('message', sync);
  }
  // Recheck expiry and changes made in another tab even without BroadcastChannel.
  window.setInterval(() => { if (!consentGranted()) stop(); }, 1000);
  sync();
})();
