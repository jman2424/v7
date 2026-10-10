<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { widgetStyles, brandPalettes, widgetTheme, isHexColour, appearancePresets, applyAppearancePreset, appearancePresetMatches } from './widgetAppearance';
  import type { Widget, ColourKey, PreviewTheme } from './widgetAppearance';
  export let widget: Widget;
  export let previewTheme: PreviewTheme = {};
  export let tenant: string;
  export let saving = false;
  export let canEdit = false;
  export let dirty = false;
  export let status = '';
  export let error = false;
  const dispatch = createEventDispatcher<{ save: void }>();
  const colourFields: { key: ColourKey; label: string; theme: 'accent' | 'background' | 'surface' | 'text' | 'bubble' }[] = [
    { key:'accent_color', label:'Brand accent', theme:'accent' }, { key:'background_color', label:'Chat background', theme:'background' },
    { key:'surface_color', label:'Header & fields', theme:'surface' }, { key:'text_color', label:'Message text', theme:'text' },
    { key:'bubble_color', label:'Customer bubble', theme:'bubble' }
  ];
  $: theme = widgetTheme(widget,previewTheme);
  $: previewCss = '--chat-accent:'+theme.accent+';--chat-accent-text:'+theme.accentText+';--chat-bg:'+theme.background+';--chat-bg-text:'+theme.backgroundText+';--chat-panel:'+theme.surface+';--chat-field:'+theme.field+';--chat-text:'+theme.panelText+';--chat-field-text:'+theme.fieldText+';--chat-muted:'+theme.muted+';--chat-border:'+theme.border+';--chat-bubble:'+theme.bubble+';--chat-bubble-text:'+theme.bubbleText+';--chat-radius:'+theme.style.radius+'px;--chat-font:'+theme.fontFamily;
  const asset = (url: string) => import.meta.env.DEV && url.startsWith('/') && !url.startsWith('//') ? '/api'+url : url;
  function setColour(key: ColourKey, value: string) { widget = { ...widget, [key]:value.toUpperCase() }; }
  function usePalette(palette: (typeof brandPalettes)[number]) { const { name, ...colours } = palette; widget = { ...widget, ...colours }; }
  function resetColours() { widget = { ...widget, accent_color:'#3EEA8C', background_color:'', surface_color:'', text_color:'', bubble_color:'' }; }
</script>

<section class="designer" aria-label="Widget appearance">
  <form on:submit|preventDefault={() => dispatch('save')}>
    <fieldset disabled={!canEdit || saving}>
      <div class="settings">
        <section class="panel">
          <header><div><span class="eyebrow">Brand identity</span><h2>Make it your business</h2><p>The name, welcome message and images customers see.</p></div></header>
          <div class="identity-grid">
            <label>Assistant name<input bind:value={widget.assistant_name} maxlength="80" placeholder="e.g. Alex" required /></label>
            <label>Chat title<input bind:value={widget.chat_title} maxlength="80" required /><small>A short description below the name.</small></label>
            <label class="full">Welcome message<textarea bind:value={widget.greeting} maxlength="240" rows="3" required></textarea></label>
            <label>Company logo URL<input bind:value={widget.company_logo_url} inputmode="url" placeholder="https://assets.yourcompany.com/logo.png" /><small>HTTPS image or a V7 image path. Used in the header and launcher.</small></label>
            <label>Assistant avatar URL<input bind:value={widget.avatar} inputmode="url" placeholder="https://assets.yourcompany.com/avatar.png" /><small>Leave blank for the default assistant icon.</small></label>
          </div>
        </section>
        <section class="panel">
          <header><div><span class="eyebrow">Layout & character</span><h2>Choose a style</h2><p>Ten layouts, from simple business chat to a distinctive brand experience.</p></div></header>
          <div class="appearance-presets" aria-label="Complete appearance presets">
            {#each appearancePresets as preset}
              <button type="button" class="appearance-preset" class:chosen={appearancePresetMatches(widget,preset)} aria-pressed={appearancePresetMatches(widget,preset)} on:click={() => widget = applyAppearancePreset(widget,preset)}>
                <span class="preset-swatches" aria-hidden="true"><i style:background={preset.settings.accent_color}></i><i style:background={preset.settings.surface_color}></i><i style:background={preset.settings.bubble_color}></i></span>
                <span><strong>{preset.name}</strong><small>{preset.description}</small></span>
                <span class="preset-action" aria-hidden="true">{appearancePresetMatches(widget,preset) ? 'Applied' : 'Apply design'}</span>
              </button>
            {/each}
          </div>
          <div class="style-grid">
            {#each widgetStyles as option}
              <label class="style-option" class:selected={widget.style === option.id}>
                <input type="radio" name="widget-style" value={option.id} bind:group={widget.style} />
                <span class="style-sample" data-style={option.id} style={'--sample-bg:'+option.palette.background+';--sample-panel:'+option.palette.surface+';--sample-field:'+option.palette.field+';--sample-bubble:'+option.palette.bubble+';--sample-accent:'+theme.accent+';--sample-radius:'+Math.min(14,option.radius)+'px'} aria-hidden="true"><span></span><i></i><b></b></span>
                <strong>{option.name}</strong><small>{option.description}</small>
              </label>
            {/each}
          </div>
        </section>
        <section class="panel">
          <header><div><span class="eyebrow">Brand palette</span><h2>Match your colours</h2><p>Start with a palette or use any six-digit hex colour.</p></div><button type="button" class="text-button" on:click={resetColours}>Use style defaults</button></header>
          <div class="palette-grid" aria-label="Starting colour palettes">
            {#each brandPalettes as palette}<button type="button" on:click={() => usePalette(palette)}><span class="palette-colours" aria-hidden="true"><i style:background={palette.accent_color}></i><i style:background={palette.background_color}></i><i style:background={palette.bubble_color}></i></span>{palette.name}</button>{/each}
          </div>
          <div class="colour-grid">
            {#each colourFields as field}
              <div class="colour-field">
                <label for={'colour-'+field.key}>{field.label}</label>
                <div class="colour-controls">
                  <input type="color" aria-label={field.label+' picker'} value={isHexColour(widget[field.key]) ? widget[field.key] : theme[field.theme]} on:input={(event) => setColour(field.key,event.currentTarget.value)} />
                  <input id={'colour-'+field.key} aria-label={field.label+' hex'} value={widget[field.key]} on:input={(event) => setColour(field.key,event.currentTarget.value)} placeholder={theme[field.theme].toUpperCase()} pattern={'#[0-9A-Fa-f]{6}'} maxlength="7" required={field.key === 'accent_color'} spellcheck="false" />
                  <button type="button" aria-label={'Reset '+field.label.toLowerCase()} title={'Reset '+field.label.toLowerCase()} on:click={() => setColour(field.key,field.key === 'accent_color' ? '#3EEA8C' : '')}>↺</button>
                </div>
              </div>
            {/each}
          </div>
          <p class="note">Blank optional colours use the style palette. Colours stay when you switch layouts. Text uses a readable dark or light alternative where your chosen colour has insufficient contrast.</p>
        </section>
      </div>
    </fieldset>
    <footer><div><strong>{dirty ? 'Unsaved changes' : 'Saved appearance'}</strong><p class:error role={error ? 'alert' : 'status'}>{status || (canEdit ? 'Save to apply this appearance to new widget loads.' : 'You have viewing access. Ask your owner to change widget settings.')}</p></div><button class="primary" type="submit" disabled={!canEdit || saving}>{saving ? 'Saving…' : 'Save widget'}</button></footer>
  </form>
  <aside class="preview-stage" aria-label="Widget appearance preview">
    <div class="preview-caption"><span class="eyebrow">Appearance preview</span><strong>{theme.style.name}</strong><span>{dirty ? 'Unsaved preview' : tenant}</span></div>
    <div class="chat-preview" data-style={widget.style} style={previewCss}>
      <header><div class="chat-identity"><span class="avatar">{#if widget.avatar}<img src={asset(widget.avatar)} alt="" />{:else}<svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true"><path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>{/if}</span><div><strong>{widget.assistant_name || 'Sales Assistant'}</strong>{#if widget.chat_title !== widget.assistant_name}<small>{widget.chat_title || 'Sales assistant'}</small>{/if}</div></div>{#if widget.company_logo_url}<img class="logo" src={asset(widget.company_logo_url)} alt="Company logo" />{/if}</header>
      <div class="chat-body"><span class="conversation-start">Conversation preview</span><p class="agent-bubble">{widget.greeting || 'Hi! How can I help you today?'}</p><span class="preview-playback"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m5 9 4 0 5-4v14l-5-4H5V9Zm12-1a6 6 0 0 1 0 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg> Listen to reply</span><p class="customer-bubble">I'd like to know more about your business.</p><p class="agent-bubble">Tell me what you need and I can help you find the next step.</p></div>
      <div class="chat-composer"><span>Type your message…</span><span class="mic-preview" aria-label="Microphone control preview"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3" stroke="currentColor" stroke-width="1.8"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3m-4 0h8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></span><span class="send-preview">Send</span></div>
    </div>
    <div class="launcher-preview" data-style={widget.style} style={'background:'+theme.launcherBackground+';color:'+theme.launcherText+';border-radius:'+theme.launcherRadius+'px;--launcher-accent:'+theme.accent}>{#if widget.company_logo_url}<img src={asset(widget.company_logo_url)} alt="" />{:else}<svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 12a8 8 0 0 1-8 8H4l-2 2V12a8 8 0 1 1 18 0Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/></svg>{/if}<span>{widget.assistant_name || 'Chat with us'}</span></div>
    <p class="note">This sample shows your appearance settings. Use Test conversation to check real answers with saved business information.</p>
    <a href={'/chat_ui?tenant='+encodeURIComponent(tenant)} target="_blank" rel="noopener noreferrer">Open saved customer widget ↗</a>
  </aside>
</section>

<style>
  .designer {display:grid;grid-template-columns:minmax(0,1.7fr) minmax(300px,1fr);gap:20px;align-items:start;color:var(--v7-ink,#172b26);min-width:0}
  form,fieldset,.settings {min-width:0} fieldset {margin:0;padding:0;border:0} .settings {display:grid;gap:18px}
  .panel {padding:22px;border:1px solid var(--v7-line,#e1e7e4);border-radius:12px;background:#fff;min-width:0}
  header {display:flex;justify-content:space-between;align-items:start;flex-wrap:wrap;gap:12px;margin-bottom:20px}
  header>div {flex:1 1 210px;min-width:0} h2 {margin:4px 0 6px;font-size:18px;letter-spacing:-.025em} p {margin:0;font-size:12px;line-height:1.6;color:var(--v7-muted,#64716d)}
  .eyebrow {font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--v7-accent,#087f5b);font-weight:700}
  .identity-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 14px} .full {grid-column:1/-1}
  label {display:grid;gap:7px;font-size:12px;font-weight:600;min-width:0} small {font-size:11px;line-height:1.5;font-weight:400;color:var(--v7-muted,#64716d)}
  input,textarea,button {box-sizing:border-box;font:inherit;max-width:100%;min-width:0;border:1px solid var(--v7-control-line,#cbd6d0);border-radius:8px;background:#fff;color:var(--v7-ink,#172b26);font-size:12px}
  input,textarea {width:100%;padding:10px 12px} input,button {min-height:44px} textarea {resize:vertical;line-height:1.6}
  button {cursor:pointer;padding:10px 14px;font-weight:600} button:hover:not(:disabled){border-color:var(--v7-accent,#087f5b);background:var(--v7-soft,#edf6f1)} button:disabled {opacity:.6;cursor:default}
  :is(button,input,textarea,a):focus-visible {outline:3px solid var(--v7-focus,#81baa1);outline-offset:3px}
  .appearance-presets {margin-bottom:16px}.appearance-preset {display:flex;align-items:center;gap:12px;width:100%;padding:14px;text-align:start;background:#f7faf8}.appearance-preset.chosen {border-color:var(--v7-accent,#087f5b)}.appearance-preset>span:nth-child(2) {flex:1;min-width:0}.appearance-preset strong,.appearance-preset small {display:block}.appearance-preset small {margin-top:4px}.preset-swatches {display:flex;flex:none}.preset-swatches i {width:18px;height:28px;border:1px solid #27332f20}.preset-swatches i:first-child {border-radius:5px 0 0 5px}.preset-swatches i:last-child {border-radius:0 5px 5px 0}.preset-action {font-size:11px;color:var(--v7-accent,#087f5b);flex:none}
  .style-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.style-option {position:relative;padding:9px;border:1px solid var(--v7-line,#e1e7e4);border-radius:8px;gap:6px;cursor:pointer}
  .style-option.selected {border-color:var(--v7-accent,#087f5b);box-shadow:0 0 0 1px var(--v7-accent,#087f5b)}
  .style-option input {position:absolute;width:14px;height:14px;min-height:0;top:13px;right:13px;margin:0;accent-color:var(--v7-accent,#087f5b)}.style-option strong {font-size:11px}.style-option small {font-size:10px}
  .style-sample {position:relative;display:block;height:60px;background:var(--sample-bg);border:1px solid #64716d44;border-radius:var(--sample-radius);overflow:hidden}.style-sample>span {display:block;height:18px;background:var(--sample-panel)}
  .style-sample i,.style-sample b {position:absolute;display:block;height:9px;border-radius:5px}.style-sample i {top:26px;left:7px;width:45%;background:var(--sample-field)}.style-sample b {bottom:7px;right:7px;width:33%;background:var(--sample-accent)}
  .style-sample[data-style="bold"]>span {background:var(--sample-accent)}.style-sample[data-style="editorial"]>span {border-bottom:3px double #a89f8f}.style-sample[data-style="daylight"]>span {border-top:3px solid var(--sample-accent)}.style-sample[data-style="neon"] {border-color:var(--sample-accent)}.style-sample[data-style="minimal"] i {border-left:2px solid var(--sample-accent);border-radius:0}
  .palette-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin-bottom:20px}.palette-grid button {display:flex;align-items:center;gap:8px;font-size:11px;padding:8px}
  .palette-colours {display:flex;flex:none}.palette-colours i {width:13px;height:20px;border:1px solid #172b2612}.palette-colours i:first-child {border-radius:4px 0 0 4px}.palette-colours i:last-child {border-radius:0 4px 4px 0}
  .colour-grid {display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.colour-field>label {margin-bottom:7px}.colour-controls {display:flex;gap:6px;min-width:0}.colour-controls input[type="color"] {width:44px;flex:none;padding:4px;cursor:pointer}.colour-controls input:not([type="color"]) {font-family:ui-monospace,monospace;flex:1;width:70px}.colour-controls button {width:34px;flex:none;padding:8px;font-size:18px}
  .text-button {padding:6px 0;border:0;background:transparent;color:var(--v7-accent,#087f5b);font-size:11px}.note {margin-top:16px;font-size:11px}
  footer {display:flex;justify-content:space-between;align-items:center;gap:18px;padding:18px 0}footer strong {font-size:12px}footer p {margin-top:5px;font-size:11px}.primary {flex:none;background:var(--v7-accent,#087f5b);border-color:var(--v7-accent,#087f5b);color:#fff}.primary:hover:not(:disabled){background:var(--v7-accent-hover,#066547);color:#fff}.error {color:#b42318}
  .preview-stage {position:sticky;top:20px;padding:20px;border:1px solid var(--v7-line,#e1e7e4);border-radius:12px;background:var(--v7-canvas);min-width:0}.preview-caption {display:grid;gap:6px;margin-bottom:20px}.preview-caption strong {font-size:16px}.preview-caption>span:last-child {font-size:11px;color:var(--v7-muted,#64716d)}
  .chat-preview {overflow:hidden;border-radius:var(--chat-radius);border:1px solid var(--chat-border);background:var(--chat-panel);color:var(--chat-text);box-shadow:0 8px 24px #172b2614;min-width:0;font-family:var(--chat-font)}
  .chat-preview header {margin:0;padding:16px;display:flex;align-items:center;justify-content:space-between;flex-wrap:nowrap;gap:10px;border-bottom:1px solid var(--chat-border)}.chat-preview .chat-identity {display:flex;align-items:center;gap:9px;flex:1;min-width:0}.chat-identity>div {display:grid;gap:3px;overflow-wrap:anywhere}.chat-identity strong {font-size:13px}.chat-identity small {font-size:10px;color:var(--chat-muted)}
  .avatar {display:grid;place-items:center;flex:none;width:34px;height:34px;overflow:hidden;border-radius:50%;background:var(--chat-accent);color:var(--chat-accent-text)}.avatar img {width:100%;height:100%;object-fit:cover}.logo {width:40px;height:30px;object-fit:contain;flex:none}
  .chat-body {display:flex;flex-direction:column;gap:14px;padding:18px 14px;min-height:290px;background:var(--chat-bg)}.conversation-start {text-align:center;color:var(--chat-bg-text);font-size:9px;opacity:.8}.chat-body p {padding:10px 12px;font-size:12px;line-height:1.55;max-width:87%;overflow-wrap:anywhere;margin:0;border:1px solid var(--chat-border);border-radius:12px}
  .agent-bubble {background:var(--chat-field);color:var(--chat-field-text)}.customer-bubble {align-self:flex-end;background:var(--chat-bubble);color:var(--chat-bubble-text)}.preview-playback {display:flex;align-items:center;gap:6px;color:var(--chat-bg-text);font-size:10px}
  .chat-composer {display:flex;align-items:center;gap:8px;padding:12px;border-top:1px solid var(--chat-border);font-size:10px}.chat-composer>span:first-child {flex:1;color:var(--chat-muted)}.mic-preview {display:grid;place-items:center;color:var(--chat-text)}.send-preview {padding:8px 10px;border-radius:7px;color:var(--chat-accent-text);background:var(--chat-accent);font-size:11px;font-weight:700}
  .launcher-preview {display:flex;align-items:center;gap:8px;width:fit-content;margin:16px 0 0 auto;max-width:100%;padding:10px 14px;border-radius:24px;font-size:12px;font-weight:600;overflow-wrap:anywhere}
  .preview-stage a {display:inline-flex;align-items:center;min-height:44px;margin-top:8px;color:var(--v7-accent,#087f5b);font-size:12px;text-underline-offset:3px}
  .chat-preview[data-style="daylight"] header {border-top:5px solid var(--chat-accent)}.chat-preview:is([data-style="daylight"],[data-style="studio"]) .avatar {border-radius:9px}
  .chat-preview[data-style="studio"] header {padding:18px;border-top:3px solid var(--chat-accent)}.chat-preview[data-style="studio"] .avatar {width:42px;height:42px;border-radius:12px}.chat-preview[data-style="studio"] .chat-body p {border-radius:10px;box-shadow:0 2px 6px #172b2609}
  .chat-preview[data-style="minimal"] header {justify-content:center;border:0;padding:22px}.chat-preview[data-style="minimal"] .chat-identity {flex-direction:column;text-align:center}.chat-preview[data-style="minimal"] .chat-body p {border:0;border-left:2px solid var(--chat-accent);border-radius:0}.chat-preview[data-style="minimal"] .customer-bubble {border-left:0;border-right:2px solid var(--chat-accent)}
  .chat-preview[data-style="editorial"] {box-shadow:6px 8px 0 #463f3026}.chat-preview[data-style="editorial"] header {border-bottom:3px double var(--chat-border)}.chat-preview[data-style="editorial"] .chat-body p,.chat-preview[data-style="editorial"] .send-preview {border-radius:0}
  .chat-preview[data-style="neon"] {border-color:var(--chat-accent);box-shadow:0 0 14px color-mix(in srgb,var(--chat-accent) 35%,transparent)}.chat-preview[data-style="neon"] header {border-bottom-color:var(--chat-accent)}.chat-preview[data-style="neon"] .chat-body p {border-radius:4px}
  .chat-preview:is([data-style="warm"],[data-style="soft"]) .agent-bubble {border-radius:18px 18px 18px 4px}.chat-preview:is([data-style="warm"],[data-style="soft"]) .customer-bubble {border-radius:18px 18px 4px 18px}.chat-preview[data-style="soft"] .send-preview {border-radius:22px}
  .chat-preview[data-style="glass"] {box-shadow:0 14px 32px #14233b30}.chat-preview[data-style="glass"] .chat-body p {border-radius:17px}.chat-preview[data-style="bold"] header {background:var(--chat-accent);color:var(--chat-accent-text)}.chat-preview[data-style="bold"] header small {color:inherit}.chat-preview[data-style="bold"] .avatar {background:var(--chat-accent-text);color:var(--chat-accent)}
  .launcher-preview img {width:24px;height:24px;object-fit:contain}.launcher-preview:is([data-style="daylight"],[data-style="minimal"],[data-style="studio"],[data-style="soft"]) {border:1px solid var(--launcher-accent)}.launcher-preview[data-style="editorial"] {font-family:Georgia,serif;border:1px solid #c9bba5}.launcher-preview[data-style="neon"] {border:1px solid var(--launcher-accent);box-shadow:0 0 12px var(--launcher-accent)}.launcher-preview[data-style="bold"] {border:2px solid var(--launcher-accent);box-shadow:4px 4px 0 #0f172a33}
  @media(max-width:1250px){.style-grid {grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1050px){.designer {grid-template-columns:1fr}.preview-stage {position:static}.chat-preview {max-width:400px;margin:auto}.launcher-preview {margin-right:auto}.preview-stage>.note {max-width:440px}.style-grid {grid-template-columns:repeat(5,minmax(0,1fr))}}
  @media(max-width:600px){.panel,.preview-stage {padding:16px}.identity-grid,.colour-grid {grid-template-columns:1fr}.style-grid {grid-template-columns:repeat(2,minmax(0,1fr))}.palette-grid {grid-template-columns:repeat(2,minmax(0,1fr))}footer {align-items:start;flex-direction:column}.primary {width:100%}}
</style>
