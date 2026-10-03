<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { t } from './i18n';
  export let tenant: string;
  export let csrf: string;
  export let canEdit = false;
  export let apiPrefix = '';
  type Policy = {controller_name:string;contact_email:string;retention_days:number|null;retention_criteria:string;lawful_basis:string};
  type ResponseData = {settings:Policy;revision:string;draft:boolean;missing_details:string[];write_allowed:boolean;state?:string};
  let data: ResponseData|null = null;
  let settings: Policy = {controller_name:'',contact_email:'',retention_days:null,retention_criteria:'',lawful_basis:''};
  let retention = '';
  let busy = false;
  let error = '';
  let status = '';
  const controller = new AbortController();
  const labels: Record<string,string> = {controller_name:'Legal business name',contact_email:'Privacy contact email',retention:'Retention period or criteria',lawful_basis:'Purpose and lawful basis'};
  onMount(() => { void load(); });
  onDestroy(() => controller.abort());
  function accept(value:ResponseData) {
    data = value; settings = {...value.settings};
    retention = settings.retention_days === null ? '' : String(settings.retention_days);
  }
  async function load() {
    busy = true; error = '';
    try {
      const response = await fetch(apiPrefix+'/admin/api/privacy?tenant='+encodeURIComponent(tenant), {credentials:'same-origin',signal:controller.signal});
      if (!response.ok) throw new Error();
      accept(await response.json());
    } catch { if (!controller.signal.aborted) error = 'Could not load privacy settings. Refresh or sign in again.'; }
    finally { busy = false; }
  }
  async function save() {
    if (busy || !data || !canEdit || !data.write_allowed) return;
    busy = true; error = ''; status = '';
    try {
      const response = await fetch(apiPrefix+'/admin/api/privacy?tenant='+encodeURIComponent(tenant), {method:'PUT',credentials:'same-origin',signal:controller.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({settings:{...settings,retention_days:retention.trim()?Number(retention):null},revision:data.revision})});
      if (response.status === 409) { error = 'These settings changed in another session. Refresh before saving.'; return; }
      if (!response.ok) { error = 'Could not save privacy settings. Check the fields or sign in again.'; return; }
      accept(await response.json()); status = 'Privacy settings saved.';
    } catch { if (!controller.signal.aborted) error = 'Could not save privacy settings. Try again.'; }
    finally { busy = false; }
  }
</script>

<section class="privacy" aria-labelledby="privacy-settings-title">
  <header><div><p class="eyebrow">{$t('Data protection')}</p><h2 id="privacy-settings-title">{$t('Privacy & data')}</h2></div><button type="button" disabled={busy} on:click={load}>{$t('Refresh')}</button></header>
  <p>{$t('Provide the business details used on your customer privacy page. Undecided details remain clearly marked as a draft.')}</p>
  {#if data}
    <div class="policy-state" role="status"><strong>{$t(data.draft?'Policy awaiting business details':'Business details provided')}</strong>{#if data.missing_details.length}<span>{$t('Still needed')}: {data.missing_details.map(field=>$t(labels[field]||field)).join(', ')}</span>{/if}</div>
    {#if data.state === 'invalid'}<p class="error">{$t('Saved privacy settings could not be validated. Review every field before replacing them.')}</p>{/if}
    <form aria-busy={busy} on:submit|preventDefault={save}>
      <label>{$t('Legal business name')}<input bind:value={settings.controller_name} maxlength="200" disabled={busy||!canEdit||!data.write_allowed} autocomplete="organization"/></label>
      <label>{$t('Privacy contact email')}<input type="email" bind:value={settings.contact_email} maxlength="254" disabled={busy||!canEdit||!data.write_allowed}/></label>
      <label>{$t('Retention period (days)')}<input type="number" min="1" max="36500" step="1" bind:value={retention} disabled={busy||!canEdit||!data.write_allowed}/><small>{$t('Leave blank until decided, or describe your retention criteria below.')}</small></label>
      <label>{$t('Retention criteria')}<textarea bind:value={settings.retention_criteria} maxlength="2000" rows="3" disabled={busy||!canEdit||!data.write_allowed}></textarea></label>
      <label class="wide">{$t('Purpose and lawful basis')}<textarea bind:value={settings.lawful_basis} maxlength="2000" rows="4" disabled={busy||!canEdit||!data.write_allowed}></textarea><small>{$t('Explain why this business processes customer enquiries and the lawful basis it has chosen.')}</small></label>
      <p class="wide note">{$t('These fields describe your policy. They do not enable automatic deletion or certify legal compliance.')}</p>
      <div class="wide actions">{#if canEdit && data.write_allowed}<button class="primary" type="submit" disabled={busy}>{$t(busy?'Saving…':'Save changes')}</button>{/if}<a href={'/privacy?tenant='+encodeURIComponent(tenant)} target="_blank" rel="noopener">{$t('View customer privacy page')}</a>{#if status}<span role="status">{$t(status)}</span>{/if}</div>
    </form>
  {:else if !error}<p role="status">{$t('Loading…')}</p>{/if}
  {#if error}<p class="error" role="alert">{$t(error)}</p>{/if}
  <section class="account-data"><h3>{$t('Your account data')}</h3><p>{$t('Download the profile and security-setting summary for your own account. Secrets and other accounts are excluded.')}</p><a class="download" href={apiPrefix+'/auth/privacy/export'}>{$t('Download my account data')}</a><p>{$t('Customer data requests need identity verification. Contact the business owner or platform operator for review.')}</p></section>
</section>

<style>
  .privacy{background:#fff;border:1px solid var(--v7-line);border-radius:var(--v7-radius, 18px);padding:24px;color:var(--v7-ink);box-shadow:var(--v7-card-shadow, 0 8px 28px #203b3008);}header,.actions{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.eyebrow{font-size:11px;color:var(--v7-accent);text-transform:uppercase;letter-spacing:.1em;margin:0 0 8px;font-weight:700;}h2{margin:0;font-size:22px}p{color:var(--v7-muted);line-height:1.6;font-size:14px}.policy-state{display:grid;gap:6px;background:var(--v7-soft, #f0f6f2);padding:18px;border-radius:12px;margin:20px 0;font-size:14px;border:1px solid var(--v7-line);}.policy-state span{color:var(--v7-muted)}form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}label{display:grid;gap:8px;font-size:13px;font-weight:650}input,textarea{width:100%;min-height:44px;padding:10px;border:1px solid var(--v7-control-line, #b5c5bc);border-radius:9px;font:inherit;color:inherit;background:white}textarea{resize:vertical}input:disabled,textarea:disabled{background:#f7f7f2}small{color:var(--v7-muted);font-weight:400;line-height:1.5}.wide{grid-column:1/-1}.note{margin:0}.actions{justify-content:flex-start}button,.download{min-height:44px;padding:10px 16px;border:1px solid var(--v7-control-line, #b5c5bc);border-radius:10px;color:inherit;background:white;font:inherit}.primary{background:var(--v7-accent);color:white;border-color:var(--v7-accent)}a{font-size:13px;color:var(--v7-accent)}.download{display:inline-flex;align-items:center;text-decoration:none}.account-data{margin-top:26px;border-top:1px solid var(--v7-line);padding-top:20px;background:var(--v7-soft, #f0f6f2);padding:20px;border:1px solid var(--v7-line);border-radius:14px;}.account-data h3{margin:0}.error{color:#a61b2b}@media(max-width:700px){form{grid-template-columns:1fr}.privacy{padding:18px}}
</style>
