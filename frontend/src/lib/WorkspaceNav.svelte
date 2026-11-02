<script lang="ts">
  import {onMount} from 'svelte';
  import PlatformLogo from './PlatformLogo.svelte';
  import NavigationIcon from './NavigationIcon.svelte';
  import {workspaceHref,type Workspace} from './workspaceArchitecture';
  import {t} from './i18n';
  export let items:Workspace[]=[];
  export let active='home';
  export let tenant:string;
  export let base:string;
  export let platform=false;
  export let administrator=false;
  export let collapsed=false;
  export let email='';
  export let onSignOut:()=>void;
  let moreOpen=false;
  let moreMenu:HTMLDetailsElement;
  onMount(()=>{
    const closeOutside=(event:PointerEvent)=>{if(moreOpen&&event.target instanceof Node&&!moreMenu?.contains(event.target))moreOpen=false;};
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&moreOpen){moreOpen=false;moreMenu?.querySelector('summary')?.focus();}};
    document.addEventListener('pointerdown',closeOutside);document.addEventListener('keydown',escape);
    return()=>{document.removeEventListener('pointerdown',closeOutside);document.removeEventListener('keydown',escape);};
  });
  const firstView=(workspace:Workspace)=>workspace.views.find(view=>!view.hidden)||workspace.views[0];
  const hrefFor=(item:Workspace)=>workspaceHref(base,platform?'platform':item.id,platform?item.id:firstView(item).id,tenant);
  $: primary=items.slice(0,4);
  $: more=items.slice(4);
  $: if(active)moreOpen=false;
</script>

<aside class="primary-sidebar" class:collapsed aria-label={platform?'Platform administration':'Business workspace'}>
  <a class="brand" href={workspaceHref(base,platform?'platform':'home','overview',tenant)} aria-label="Vertex Seven home"><PlatformLogo horizontal={!collapsed} size={collapsed?32:166}/></a>
  {#if administrator}
    <a class="workspace-switch" aria-label={$t(platform?'Open business workspace':'Platform administration')} href={workspaceHref(base,platform?'home':'platform','overview',tenant)}><span class="switch-mark" aria-hidden="true">⇄</span><span>{platform?$t('Open business workspace'):$t('Platform administration')}</span></a>
  {/if}
  <nav aria-label={platform?'Platform navigation':'Main workspace navigation'}>
    <p class="nav-caption">{platform?$t('Administration'):$t('Your workspace')}</p>
    {#each items as item}
      <a class:active={active===item.id} aria-label={$t(item.label)} aria-current={active===item.id?'page':undefined} title={$t(item.label)} href={hrefFor(item)} data-sveltekit-reload={item.id==='channels'||undefined}><NavigationIcon section={item.icon}/><span>{$t(item.label)}</span>{#if active===item.id}<span class="active-dot" aria-hidden="true"></span>{/if}</a>
    {/each}
  </nav>
  <div class="sidebar-bottom">
    <button class="collapse-control" on:click={()=>collapsed=!collapsed} aria-label={collapsed?'Expand navigation':'Collapse navigation'} title={collapsed?'Expand navigation':'Collapse navigation'}><span aria-hidden="true">{collapsed?'→':'←'}</span><span>{$t('Collapse navigation')}</span></button>
    <div class="account-strip"><span class="avatar" aria-hidden="true">{email.charAt(0).toUpperCase()||'V'}</span><div><strong>{platform?$t('Platform operator'):$t('Your account')}</strong><small>{email}</small></div><button on:click={onSignOut} aria-label={$t('Sign out')} title={$t('Sign out')}>↗</button></div>
  </div>
</aside>

<nav class="mobile-navigation" aria-label={platform?'Mobile administration':'Mobile workspace navigation'}>
  {#each primary as item}
    <a class:active={active===item.id} aria-current={active===item.id?'page':undefined} href={hrefFor(item)} data-sveltekit-reload={item.id==='channels'||undefined}><NavigationIcon section={item.icon}/><span>{$t(item.id==='customers'?'Customers':item.label)}</span></a>
  {/each}
    <details class="mobile-more" bind:this={moreMenu} bind:open={moreOpen}>
      <summary class:active={more.some(item=>item.id===active)}><span class="more-icon" aria-hidden="true">•••</span><span>{$t('More')}</span></summary>
      <div class="more-menu" role="group" aria-label="More workspaces">
        {#each more as item}<a href={hrefFor(item)} data-sveltekit-reload={item.id==='channels'||undefined} on:click={()=>moreOpen=false}><NavigationIcon section={item.icon}/><span>{$t(item.label)}</span></a>{/each}
        {#if administrator}<a href={workspaceHref(base,platform?'home':'platform','overview',tenant)}>{$t(platform?'Business workspace':'Platform administration')}</a>{/if}
        <button on:click={onSignOut}>{$t('Sign out')}</button>
      </div>
    </details>
</nav>

<style>
  .primary-sidebar{position:sticky;top:0;height:100dvh;min-height:600px;display:flex;flex-direction:column;padding:28px 16px 14px;background:var(--v7-brand);color:#e8f0e9;min-width:0;z-index:20}
  .brand{display:flex;align-items:center;min-height:46px;align-self:flex-start;padding:8px 10px;border-radius:10px;background:white;margin:0 8px 25px;text-decoration:none}
  .workspace-switch{display:flex;align-items:center;gap:10px;color:#d4e6d9;border:1px solid #ffffff24;padding:11px 12px;margin:0 0 25px;border-radius:9px;font-size:12px;line-height:1.4;text-decoration:none;min-height:44px}
  .switch-mark{font-size:20px}.nav-caption{margin:0 13px 12px;color:#a9c3b4;text-transform:uppercase;font-size:10px;font-weight:650;letter-spacing:.12em}
  nav{display:grid;gap:6px}nav>a{display:flex;align-items:center;gap:12px;min-height:47px;padding:12px 14px;border-radius:10px;color:#d2e0d7;text-decoration:none;font-weight:500;font-size:13px;white-space:nowrap;position:relative}
  nav>a:hover{background:#ffffff0c;color:white}nav>a.active{background:#eaf3ed;color:#153f2e;font-weight:650}.active-dot{margin-inline-start:auto;width:5px;height:5px;border-radius:50%;background:#206b4e}
  .sidebar-bottom{margin-top:auto;padding-top:30px}.collapse-control{display:flex;align-items:center;gap:12px;width:100%;padding:12px;color:#afc8b8;background:none;border:0;font:inherit;font-size:11px;text-align:start;min-height:44px}
  .account-strip{border-top:1px solid #ffffff1c;padding:17px 2px 0;margin-top:8px;display:flex;align-items:center;gap:10px;min-width:0}.avatar{width:33px;height:33px;border-radius:10px;display:grid;place-items:center;background:#ffffff14;color:#d2e5d8;font-weight:650;flex:none}.account-strip>div{min-width:0;display:grid;gap:3px}.account-strip strong{font-size:11px;font-weight:600}.account-strip small{max-width:132px;overflow:hidden;text-overflow:ellipsis;font-size:10px;color:#a9c3b4}.account-strip button{margin-inline-start:auto;min-width:30px;min-height:40px;background:none;border:0;color:#c9ddce;font:inherit;font-size:19px}
  .collapsed{padding-inline:11px}.collapsed .brand{padding:7px;margin-inline:5px}.collapsed :is(nav>a>span,.nav-caption,.workspace-switch>span:not(.switch-mark),.collapse-control>span+span,.account-strip>div,.account-strip>button){display:none}.collapsed nav>a{justify-content:center;padding-inline:0}.collapsed .workspace-switch{justify-content:center}.collapsed .account-strip{justify-content:center}.collapsed .collapse-control{justify-content:center}
  a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid #a4d7b7;outline-offset:3px}.mobile-navigation{display:none}
  @media(max-width:850px){
    .primary-sidebar{display:none}.mobile-navigation{position:fixed;bottom:0;inset-inline:0;display:flex;align-items:stretch;justify-content:space-around;padding:7px 8px max(7px,env(safe-area-inset-bottom));background:#fffffff7;border-top:1px solid var(--v7-line);z-index:60;gap:0;backdrop-filter:blur(12px)}
    .mobile-navigation>a,.mobile-more>summary{display:flex;flex:1;min-width:0;flex-direction:column;align-items:center;justify-content:center;gap:5px;color:var(--v7-muted);font-size:10px;font-weight:600;min-height:48px;padding:5px 4px;border-radius:9px;text-decoration:none;white-space:nowrap;list-style:none;cursor:pointer}.mobile-navigation>a.active,.mobile-more>summary.active{color:var(--v7-accent);background:var(--v7-tint)}
    .mobile-more{flex:1;min-width:0}.mobile-more>summary::-webkit-details-marker{display:none}.more-icon{height:18px;font-size:17px;line-height:12px;letter-spacing:2px}.more-menu{position:absolute;bottom:calc(100% + 8px);inset-inline-end:12px;width:min(270px,calc(100vw - 24px));padding:8px;background:white;border:1px solid var(--v7-line);border-radius:14px;box-shadow:var(--v7-elevation-menu);display:grid;gap:3px}.more-menu a,.more-menu button{display:flex;align-items:center;gap:10px;padding:12px;min-height:46px;color:var(--v7-ink);text-decoration:none;background:none;border:0;border-radius:8px;font:inherit;font-size:13px;text-align:start}.more-menu a:hover,.more-menu button:hover{background:var(--v7-soft)}
  }
</style>
