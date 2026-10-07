<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { base } from '$app/paths';
  import type { Stats } from './statisticsTypes';

  export let data: Stats;
  export let tenant: string;
  type ReportView = 'performance' | 'products' | 'offers' | 'sales' | 'quality';
  const dispatch = createEventDispatcher<{ view: ReportView }>();
  const stages = ['Open', 'Contacted', 'Qualified', 'Won', 'Lost', 'Other'];
  const number = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'Not recorded' : value.toLocaleString('en-GB', { maximumFractionDigits: 1 });
  const money = (pence: number) => Number.isFinite(pence) ? new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(pence / 100) : 'Not recorded';
  const ratio = (part: number, total: number) => total > 0 && Number.isFinite(part) ? 100 * part / total : null;
  const percent = (value: number | null) => value === null ? 'No data' : number(value) + '%';
  const comparison = (current: number, previous: number) => previous > 0 ? `${current >= previous ? '+' : ''}${number(100 * (current - previous) / previous)}% vs previous period` : current > 0 ? 'No activity in previous period' : 'No change from previous period';
  const channelName = (name: string) => name === 'whatsapp' ? 'WhatsApp' : name === 'web' ? 'Web chat' : name;
  const topicName = (name: string) => name.replaceAll('_', ' ');
  const link = (path: string) => base + path + '?tenant=' + encodeURIComponent(tenant);

  $: replyRate = ratio(data.replies.total.replied, data.replies.total.eligible);
  $: previousReplyRate = ratio(data.previous_replies.total.replied, data.previous_replies.total.eligible);
  $: rateComparison = replyRate !== null && previousReplyRate !== null ? `${replyRate >= previousReplyRate ? '+' : ''}${number(replyRate - previousReplyRate)} percentage points vs previous period` : 'No comparable previous rate';
  $: timedReplies = data.replies.total.timed_replies ?? data.replies.total.replied;
  $: averageSeconds = timedReplies > 0 ? data.replies.total.response_seconds / timedReplies : null;
  $: unmatchedMessages = Math.max(0, data.replies.total.eligible - data.replies.total.replied);
  $: activeChannels = data.channels.filter(row => row.inbound || row.outbound || row.sessions);
  $: chartMax = Math.max(1, ...data.daily.flatMap(row => [row.inbound, row.outbound]));
  $: busiestDay = data.daily.filter(row => row.inbound > 0).reduce<(typeof data.daily)[number] | null>((best, row) => !best || row.inbound > best.inbound ? row : best, null);
  $: topProducts = data.commerce.products.filter(product => product.interest > 0).slice().sort((a, b) => b.interest - a.interest || a.name.localeCompare(b.name)).slice(0, 5);
  $: totalProductInterest = data.commerce.products.reduce((sum, product) => sum + product.interest, 0);
  $: recordedSales = data.commerce.products.reduce((sum, product) => sum + product.amount_pence, 0);
  $: topTopics = data.intents.slice().sort((a, b) => b.count - a.count || a.label.localeCompare(b.label)).slice(0, 5);
  $: largestTopic = Math.max(1, ...topTopics.map(topic => topic.count));
  $: currentProducts = data.commerce.products.filter(product => !product.archived);
  $: lowStock = currentProducts.filter(product => !product.available || (product.quantity !== null && product.quantity <= product.threshold)).length;
  $: uncountedStock = currentProducts.filter(product => product.quantity === null).length;
  $: activeOffers = data.offers.items.filter(offer => offer.status === 'active').length;
  $: pipelineTotal = Object.values(data.pipeline).reduce((sum, count) => sum + count, 0);
  $: hasActivity = Object.values(data.current).some(count => count > 0) || Boolean(totalProductInterest || recordedSales || data.offers.offer_replies) || data.commerce.sales_daily.some(row => row.entries > 0);
  $: attention = [
    ...(unmatchedMessages > 0 ? [{ label: 'Tracked messages without a matched reply', count: unmatchedMessages, detail: 'No matching reply was recorded before the report end.', view: 'performance' as ReportView, action: 'Check reply coverage' }] : []),
    ...(data.current.fallbacks > 0 ? [{ label: 'Replies flagged as fallback', count: data.current.fallbacks, detail: data.fallbacks[0] ? 'Top recorded topic: ' + topicName(data.fallbacks[0].label) + '.' : 'Review the topics and source conversations.', view: 'quality' as ReportView, action: 'Review fallback topics' }] : []),
    ...(data.current.errors > 0 ? [{ label: 'Recorded error events', count: data.current.errors, detail: 'Inspect the recorded breakdown and affected conversations.', view: 'quality' as ReportView, action: 'Inspect error breakdown' }] : []),
    ...(data.current.handoffs > 0 ? [{ label: 'Conversations requesting a person', count: data.current.handoffs, detail: 'A request count; it does not show whether a handoff was completed.', view: 'sales' as ReportView, action: 'View lead activity' }] : [])
  ];
  function points(key: 'inbound' | 'outbound') {
    return data.daily.map((row, index) => `${48 + index * 820 / Math.max(1, data.daily.length - 1)},${205 - row[key] * 170 / chartMax}`).join(' ');
  }
</script>

<div class="overview">
  {#if !hasActivity}
    <div class="empty-report"><span class="empty-mark" aria-hidden="true">—</span><div><h3>No recorded activity in this view</h3><p>Try a longer period or another channel. Your current pipeline and business setup are shown below.</p></div></div>
  {/if}

  <section class="kpi-strip" aria-label="Selected period at a glance">
    <article><h3>Active conversations</h3><strong>{number(data.current.sessions)}</strong><p>{comparison(data.current.sessions, data.previous.sessions)}</p><span>Distinct channel / session pairs</span></article>
    <article><h3>Customer messages</h3><strong>{number(data.current.inbound)}</strong><p>{comparison(data.current.inbound, data.previous.inbound)}</p><span>{number(data.current.outbound)} agent replies recorded</span></article>
    <article><h3>Contacts captured</h3><strong>{number(data.current.contacts)}</strong><p>{comparison(data.current.contacts, data.previous.contacts)}</p><span>Distinct recorded lead IDs in this period</span></article>
    <article><h3>Tracked reply rate</h3><strong>{percent(replyRate)}</strong><p>{rateComparison}</p><span>{number(data.replies.total.replied)} of {number(data.replies.total.eligible)} tracked messages</span></article>
  </section>

  <div class="report-grid">
    <article class="card activity-card">
      <header><div><h3>Customer activity</h3><p>Daily customer messages and agent replies</p></div><button class="text-button" on:click={() => dispatch('view', 'performance')}>Explore trends <span aria-hidden="true">↗</span></button></header>
      {#if data.current.inbound || data.current.outbound}
        <div class="legend"><span class="customer"><i aria-hidden="true"></i>Customer messages</span><span class="agent"><i aria-hidden="true"></i>Agent replies</span></div>
        <svg viewBox="0 0 920 245" role="img" aria-label="Daily customer messages and agent replies. Exact daily figures are available below.">
          {#each [0, .5, 1] as fraction}<line x1="48" x2="868" y1={205 - fraction * 170} y2={205 - fraction * 170} stroke="var(--v7-line)"/><text x="40" y={209 - fraction * 170} text-anchor="end">{number(chartMax * fraction)}</text>{/each}
          <polygon points={'48,205 ' + points('inbound') + ' 868,205'} fill="#087f5b0c"/>
          <polyline points={points('inbound')} fill="none" stroke="#087f5b" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <polyline points={points('outbound')} fill="none" stroke="#64716d" stroke-width="3" stroke-dasharray="7 4" stroke-linecap="round" stroke-linejoin="round"/>
          <text x="48" y="233">{data.daily[0]?.day || ''}</text><text x="868" y="233" text-anchor="end">{data.daily[data.daily.length - 1]?.day || ''}</text>
        </svg>
        <div class="activity-summary"><span><strong>{data.current.sessions ? number(data.current.inbound / data.current.sessions) : 'No data'}</strong> customer messages per conversation</span>{#if busiestDay}<span><strong>{busiestDay.day}</strong> busiest day · {number(busiestDay.inbound)} messages</span>{/if}</div>
      {:else}<div class="section-empty"><strong>No messages recorded</strong><p>Daily trends appear as customer activity is recorded for this view.</p></div>{/if}
      <details><summary>View daily figures</summary>
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll this table horizontally.) -->
        <div class="table-scroll" role="region" aria-label="Daily customer activity figures" tabindex="0"><table class="daily-table"><caption>Daily activity · UTC calendar days</caption><thead><tr><th scope="col">Day</th><th scope="col">Conversations</th><th scope="col">Customer messages</th><th scope="col">Agent replies</th><th scope="col">Fallback replies</th><th scope="col">Errors</th></tr></thead><tbody>{#each data.daily as row}<tr><th scope="row">{row.day}</th><td>{number(row.sessions)}</td><td>{number(row.inbound)}</td><td>{number(row.outbound)}</td><td>{number(row.fallbacks)}</td><td>{number(row.errors)}</td></tr>{:else}<tr><td colspan="6">No daily figures recorded.</td></tr>{/each}</tbody></table></div>
        <p class="note">A conversation can be active on several days, so daily conversation counts do not add up to unique conversations.</p>
      </details>
    </article>

    <article class="card channel-card">
      <header><div><h3>Channel mix</h3><p>Share of customer messages in this view</p></div></header>
      <div class="channel-list">{#each activeChannels as row}<div class="channel-row"><div class="row-heading"><strong>{channelName(row.channel)}</strong><span>{percent(ratio(row.inbound, data.current.inbound))}</span></div><div class="track" aria-hidden="true"><span style:width={Math.min(100, ratio(row.inbound, data.current.inbound) ?? 0) + '%'}></span></div><div class="channel-figures"><span><b>{number(row.sessions)}</b> conversations</span><span><b>{number(row.inbound)}</b> messages</span><span><b>{number(row.outbound)}</b> replies</span></div></div>{:else}<div class="section-empty"><strong>No channel activity</strong><p>Web chat and WhatsApp figures appear when messages are recorded.</p></div>{/each}</div>
      <p class="note">The selected channel filter applies to these figures. Conversations are sessions, not unique people.</p>
    </article>
  </div>

  <div class="report-grid">
    <article class="card">
      <header><div><h3>Response coverage & quality</h3><p>Recorded reply behaviour for the selected period</p></div><button class="text-button" on:click={() => dispatch('view', 'performance')}>Reply detail <span aria-hidden="true">↗</span></button></header>
      <div class="quality-metrics"><div><span>Average generation time</span><strong>{averageSeconds === null ? 'No data' : number(averageSeconds) + 's'}</strong><p>{number(timedReplies)} matched replies with valid timing</p></div><div><span>Fallback reply share</span><strong>{percent(ratio(data.current.fallbacks, data.current.outbound))}</strong><p>{number(data.current.fallbacks)} flagged replies of {number(data.current.outbound)} recorded</p></div><div><span>Without a matched reply</span><strong>{data.replies.total.eligible > 0 ? number(unmatchedMessages) : 'No data'}</strong><p>Among {number(data.replies.total.eligible)} messages with tracking IDs</p></div></div>
      <div class="coverage-row"><div><span>Matched non-fallback answers</span><strong>{number(data.replies.total.answered)} <small>of {number(data.replies.total.eligible)} tracked messages</small></strong></div><div><span>Recorded errors</span><strong>{number(data.current.errors)} <small>events</small></strong></div></div>
      <p class="note">Generation time excludes delivery and read receipts. Answer classifications and fallback flags are technical measures, not an accuracy or satisfaction score.</p>
    </article>

    <article class="card attention-card">
      <header><div><h3>Areas to review</h3><p>Follow the recorded signals to their detail</p></div></header>
      <ul class="attention-list">{#each attention as item}<li><div class="attention-heading"><strong>{item.label}</strong><span>{number(item.count)}</span></div><p>{item.detail}</p><button class="text-button" on:click={() => dispatch('view', item.view)}>{item.action} <span aria-hidden="true">→</span></button></li>{:else}<li class="attention-empty"><strong>No recorded review signals in this view</strong><p>No fallback replies, error events, person requests or unmatched tracked messages are shown. This does not confirm delivery or service uptime.</p><button class="text-button" on:click={() => dispatch('view', 'quality')}>View response detail <span aria-hidden="true">→</span></button></li>{/each}</ul>
    </article>
  </div>

  <div class="report-grid">
    <article class="card">
      <header><div><h3>Product demand & recorded sales</h3><p>Product matches and owner-entered sales in this view</p></div><button class="text-button" on:click={() => dispatch('view', 'products')}>Explore products <span aria-hidden="true">↗</span></button></header>
      <div class="commerce-summary"><div><span>Product matches in replies</span><strong>{number(totalProductInterest)}</strong></div><div><span>Recorded sales · GBP</span><strong>{money(recordedSales)}</strong></div></div>
      {#if topProducts.length}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex (Keyboard users need to scroll this table horizontally.) -->
        <div class="table-scroll" role="region" aria-label="Five products with most recorded reply matches" tabindex="0"><table class="product-table"><caption>Top 5 products by matches in recorded replies</caption><thead><tr><th scope="col">Product</th><th scope="col">Matches</th><th scope="col">Recorded sales GBP</th></tr></thead><tbody>{#each topProducts as product}<tr><th scope="row">{product.name}<small>{product.sku}{product.archived ? ' · removed from catalogue' : ''}</small></th><td>{number(product.interest)}</td><td>{money(product.amount_pence)}</td></tr>{/each}</tbody></table></div>
      {:else}<div class="section-empty"><strong>No product enquiry matches yet</strong><p>Matched catalogue products appear here as replies reference them.</p></div>{/if}
      <p class="note">One reply can match several products. Sales are owner-entered line totals, not checkout revenue or sales attributed to a conversation.</p>
    </article>

    <article class="card topics-card">
      <header><div><h3>What customers ask about</h3><p>Top topics classified from recorded replies</p></div></header>
      <ol class="topic-list">{#each topTopics as topic}<li><div class="row-heading"><span>{topicName(topic.label)}</span><strong>{number(topic.count)}</strong></div><div class="track" aria-hidden="true"><span style:width={100 * topic.count / largestTopic + '%'}></span></div></li>{:else}<li class="topic-empty"><strong>No reply topics recorded</strong><p>Topic summaries appear when classified replies are retained.</p></li>{/each}</ol>
      <button class="text-button" on:click={() => dispatch('view', 'quality')}>Explore topics <span aria-hidden="true">→</span></button>
      <div class="offer-summary"><h4>Offer activity</h4><div><span><strong>{number(data.offers.offer_replies)}</strong> offer-related replies</span><span><strong>{number(data.offers.conversations)}</strong> conversations about offers</span></div><button class="text-button" on:click={() => dispatch('view', 'offers')}>View offer detail <span aria-hidden="true">→</span></button></div>
    </article>
  </div>

  <section class="current-state" aria-label="Current business position across all dates and channels">
    <div class="scope-heading"><div><h3>Current business position</h3><p>These figures show your business now, across all dates and channels.</p></div><span class="scope-badge">Independent of report filters</span></div>
    <div class="report-grid">
      <article class="card pipeline-card"><header><div><h3>Lead pipeline</h3><p>{number(pipelineTotal)} leads in current owner-managed stages</p></div><a href={link('/pipeline')}>Open pipeline <span aria-hidden="true">↗</span></a></header><div class="stage-grid">{#each stages as stage}<div><span>{stage}</span><strong>{number(data.pipeline[stage])}</strong></div>{/each}</div>{#if !pipelineTotal}<p class="note">No lead stages recorded yet. Leads appear as they are captured and managed.</p>{:else}<p class="note">“Won” is a managed lead status. It does not confirm payment or a product purchase.</p>{/if}</article>
      <article class="card setup-card"><header><div><h3>Catalogue & offers now</h3><p>Current availability and promotion setup</p></div></header><dl><div><dt>Current catalogue products</dt><dd>{number(currentProducts.length)}</dd></div><div><dt>Low or out of stock</dt><dd>{number(lowStock)}</dd></div><div><dt>Products without a quantity</dt><dd>{number(uncountedStock)}</dd></div><div><dt>Active offers</dt><dd>{number(activeOffers)}</dd></div></dl><p class="note">Low stock uses each product’s saved threshold. A product can be unavailable without a recorded quantity.</p><div class="setup-links"><a href={link('/catalog')}>Manage catalogue <span aria-hidden="true">↗</span></a><a href={link('/offers')}>Manage offers <span aria-hidden="true">↗</span></a></div></article>
    </div>
  </section>
</div>

<style>
  .overview { display:grid; gap:18px; min-width:0; color:var(--v7-ink, #172b26); overflow-wrap:anywhere; }
  h3, h4, p { margin:0; }
  h3 { font-size:16px; font-weight:650; line-height:1.45; letter-spacing:-.02em; }
  p { color:var(--v7-muted, #64716d); font-size:12px; line-height:1.6; }
  strong, b, dd { font-variant-numeric:tabular-nums; }
  .kpi-strip { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); overflow:hidden; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:#fff; }
  .kpi-strip article { min-width:0; padding:22px; }
  .kpi-strip article + article { border-left:1px solid var(--v7-line, #e1e7e4); }
  .kpi-strip h3 { color:var(--v7-muted, #64716d); font-size:12px; font-weight:500; letter-spacing:0; }
  .kpi-strip strong { display:block; margin:12px 0 10px; font-size:clamp(29px, 3vw, 37px); line-height:1.15; letter-spacing:-.045em; }
  .kpi-strip article:first-child strong { color:var(--v7-accent, #087f5b); }
  .kpi-strip p { font-size:11px; }
  .kpi-strip article > span { display:block; margin-top:7px; color:var(--v7-muted, #64716d); font-size:11px; line-height:1.5; }
  .report-grid { display:grid; grid-template-columns:minmax(0, 1.85fr) minmax(0, 1fr); gap:18px; align-items:start; }
  .card { min-width:0; padding:22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:#fff; }
  header { display:flex; flex-wrap:wrap; align-items:start; justify-content:space-between; gap:8px 16px; }
  header > div { flex:1 1 190px; }
  header p { margin-top:5px; }
  a, .text-button { display:inline-flex; align-items:center; justify-content:flex-start; gap:8px; box-sizing:border-box; min-height:44px; max-width:100%; padding:8px 0; border:0; border-radius:4px; background:transparent; color:var(--v7-accent, #087f5b); font:inherit; font-size:12px; font-weight:600; line-height:1.5; text-align:left; text-decoration:none; cursor:pointer; }
  a:hover, .text-button:hover { text-decoration:underline; text-underline-offset:3px; }
  header > :is(a, .text-button) { margin-top:-7px; }
  .legend { display:flex; flex-wrap:wrap; gap:18px; margin:22px 0 12px; font-size:11px; color:var(--v7-muted, #64716d); }
  .legend span { display:inline-flex; align-items:center; gap:8px; }
  .legend i { width:20px; border-top:3px solid var(--v7-accent, #087f5b); }
  .legend .agent i { border-top-style:dashed; border-color:var(--v7-muted, #64716d); }
  svg { display:block; width:100%; height:auto; min-height:140px; }
  svg text { font:11px system-ui; fill:var(--v7-muted, #64716d); }
  .activity-summary { display:flex; flex-wrap:wrap; gap:10px 24px; padding-top:14px; color:var(--v7-muted, #64716d); font-size:11px; line-height:1.6; }
  .activity-summary strong { color:var(--v7-ink, #172b26); font-weight:600; }
  details { margin-top:16px; padding-top:4px; border-top:1px solid var(--v7-line, #e1e7e4); }
  summary { min-height:44px; align-content:center; cursor:pointer; color:var(--v7-accent, #087f5b); font-size:12px; font-weight:600; }
  .table-scroll { overflow:auto; max-height:380px; margin-top:12px; border:1px solid var(--v7-line, #e1e7e4); border-radius:8px; }
  table { width:100%; border-collapse:collapse; text-align:left; font-size:12px; overflow-wrap:normal; }
  .daily-table { min-width:700px; }
  .product-table { min-width:400px; }
  caption { padding:12px 14px; text-align:left; font-size:11px; color:var(--v7-muted, #64716d); border-bottom:1px solid var(--v7-line, #e1e7e4); }
  th, td { padding:12px 14px; border-bottom:1px solid var(--v7-line, #e1e7e4); vertical-align:top; font-variant-numeric:tabular-nums; }
  thead th { background:var(--v7-canvas, #f5f7f7); color:var(--v7-muted, #64716d); font-size:11px; font-weight:600; }
  tbody th { font-weight:500; }
  tbody tr:last-child :is(th, td) { border-bottom:0; }
  tbody tr:hover { background:var(--v7-soft, #edf6f1); }
  tbody small { display:block; margin-top:4px; color:var(--v7-muted, #64716d); font-size:11px; }
  .channel-list { margin-top:22px; }
  .channel-row + .channel-row { margin-top:24px; }
  .row-heading { display:flex; align-items:baseline; justify-content:space-between; gap:12px; font-size:12px; }
  .row-heading strong { font-weight:600; }
  .row-heading > span:last-child { color:var(--v7-muted, #64716d); }
  .track { overflow:hidden; height:6px; margin-top:11px; border-radius:4px; background:var(--v7-soft, #edf6f1); }
  .track > span { display:block; height:100%; border-radius:4px; background:var(--v7-accent, #087f5b); }
  .channel-figures { display:flex; flex-wrap:wrap; gap:7px 14px; margin-top:12px; color:var(--v7-muted, #64716d); font-size:11px; }
  .channel-figures b { color:var(--v7-ink, #172b26); font-weight:600; }
  .note { margin-top:16px; font-size:11px; line-height:1.6; }
  .quality-metrics { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:20px; margin-top:25px; }
  .quality-metrics > div > span { color:var(--v7-muted, #64716d); font-size:11px; line-height:1.5; }
  .quality-metrics strong { display:block; margin:10px 0; font-size:28px; font-weight:650; line-height:1.2; letter-spacing:-.035em; }
  .quality-metrics p { font-size:11px; }
  .coverage-row { display:flex; flex-wrap:wrap; gap:20px; margin-top:22px; padding:17px 0 0; border-top:1px solid var(--v7-line, #e1e7e4); }
  .coverage-row > div { flex:1 1 150px; }
  .coverage-row span { display:block; margin-bottom:6px; font-size:11px; color:var(--v7-muted, #64716d); }
  .coverage-row strong { font-size:16px; font-weight:600; }
  .coverage-row small { font-size:11px; color:var(--v7-muted, #64716d); font-weight:400; }
  .attention-list, .topic-list { list-style:none; margin:18px 0 0; padding:0; }
  .attention-list li + li { margin-top:14px; padding-top:14px; border-top:1px solid var(--v7-line, #e1e7e4); }
  .attention-heading { display:flex; align-items:baseline; justify-content:space-between; gap:12px; }
  .attention-heading strong, .attention-empty > strong { font-size:12px; font-weight:600; line-height:1.5; }
  .attention-heading > span { flex-shrink:0; min-width:26px; padding:3px 6px; border-radius:5px; background:var(--v7-canvas, #f5f7f7); font-size:12px; font-weight:600; text-align:center; font-variant-numeric:tabular-nums; }
  .attention-list p { margin-top:6px; font-size:11px; }
  .attention-list .text-button { font-size:11px; }
  .commerce-summary { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:20px; margin:22px 0 18px; }
  .commerce-summary span { color:var(--v7-muted, #64716d); font-size:11px; }
  .commerce-summary strong { display:block; margin-top:9px; font-size:27px; font-weight:650; line-height:1.2; letter-spacing:-.035em; }
  .topic-list li + li { margin-top:16px; }
  .topic-list .row-heading > span { text-transform:capitalize; }
  .topic-list .track { height:5px; margin-top:8px; }
  .topic-empty strong { font-size:12px; }
  .topic-empty p { margin-top:6px; }
  .topics-card > .text-button { margin-top:10px; }
  .offer-summary { margin-top:14px; padding-top:17px; border-top:1px solid var(--v7-line, #e1e7e4); }
  .offer-summary h4 { font-size:12px; font-weight:600; }
  .offer-summary > div { display:grid; gap:7px; margin:12px 0 2px; font-size:11px; color:var(--v7-muted, #64716d); }
  .offer-summary strong { color:var(--v7-ink, #172b26); font-size:16px; font-weight:600; }
  .current-state { display:grid; gap:14px; margin-top:8px; padding-top:22px; border-top:1px solid var(--v7-line, #e1e7e4); }
  .scope-heading { display:flex; flex-wrap:wrap; justify-content:space-between; align-items:center; gap:12px; }
  .scope-heading h3 { font-size:18px; }
  .scope-heading p { margin-top:5px; }
  .scope-badge { padding:6px 9px; border:1px solid var(--v7-line, #e1e7e4); border-radius:5px; background:#fff; color:var(--v7-muted, #64716d); font-size:10px; font-weight:600; }
  .stage-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:16px 22px; margin-top:24px; }
  .stage-grid > div { padding-bottom:14px; border-bottom:1px solid var(--v7-line, #e1e7e4); }
  .stage-grid span { display:block; color:var(--v7-muted, #64716d); font-size:11px; }
  .stage-grid strong { display:block; margin-top:8px; font-size:26px; font-weight:650; line-height:1.2; letter-spacing:-.03em; }
  dl { margin:18px 0 0; }
  dl > div { display:flex; justify-content:space-between; align-items:baseline; gap:15px; padding:10px 0; border-bottom:1px solid var(--v7-line, #e1e7e4); }
  dt { color:var(--v7-muted, #64716d); font-size:12px; }
  dd { margin:0; font-size:16px; font-weight:600; }
  .setup-links { display:flex; flex-wrap:wrap; gap:0 16px; margin-top:7px; }
  .empty-report { display:flex; align-items:center; gap:15px; padding:18px 22px; border:1px solid var(--v7-line, #e1e7e4); border-radius:12px; background:#fff; }
  .empty-report h3 { font-size:14px; }
  .empty-report p { margin-top:5px; }
  .empty-mark { display:grid; place-items:center; flex-shrink:0; width:38px; height:38px; border-radius:8px; background:var(--v7-soft, #edf6f1); color:var(--v7-accent, #087f5b); font-size:22px; }
  .section-empty { margin-top:20px; padding:22px 16px; border:1px dashed var(--v7-line, #e1e7e4); border-radius:8px; background:var(--v7-canvas, #f5f7f7); }
  .section-empty strong { display:block; font-size:12px; font-weight:600; }
  .section-empty p { margin-top:6px; }
  :is(a, button, summary, .table-scroll):focus-visible { outline:3px solid var(--v7-focus, #81baa1); outline-offset:3px; }
  @media(max-width:1150px) { .kpi-strip { grid-template-columns:repeat(2, minmax(0, 1fr)); } .kpi-strip article:nth-child(3) { border-left:0; } .kpi-strip article:nth-child(n + 3) { border-top:1px solid var(--v7-line, #e1e7e4); } .report-grid { grid-template-columns:minmax(0, 1.5fr) minmax(0, 1fr); } .quality-metrics { gap:14px; } }
  @media(max-width:950px) { .report-grid { grid-template-columns:1fr; } .channel-list { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:22px; } .channel-row + .channel-row { margin-top:0; } .attention-list { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px 22px; } .attention-list li + li { margin-top:0; padding-top:0; border-top:0; } }
  @media(max-width:600px) { .overview, .report-grid { gap:14px; } .card, .kpi-strip article { padding:16px; } .kpi-strip strong { font-size:29px; } .kpi-strip p, .kpi-strip article > span { font-size:10px; } .quality-metrics { grid-template-columns:1fr; gap:16px; } .quality-metrics > div { display:grid; grid-template-columns:minmax(0, 1fr) auto; gap:3px 16px; align-items:baseline; } .quality-metrics strong { margin:0; font-size:24px; } .quality-metrics p { grid-column:1 / -1; } .channel-list, .attention-list { grid-template-columns:1fr; } .attention-list li + li { padding-top:14px; border-top:1px solid var(--v7-line, #e1e7e4); } .commerce-summary { gap:12px; } .commerce-summary strong { font-size:24px; } .stage-grid { gap:15px; } .stage-grid strong { font-size:24px; } .empty-report { align-items:flex-start; padding:16px; } .scope-heading h3 { font-size:16px; } }
</style>
