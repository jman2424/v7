<script lang="ts">
  import { language, languages, setLanguage, t } from './i18n';
</script>
<label class="language-picker"><span>{$t('Language')}</span>
  <select aria-label={$t('Language')} value={$language} on:change={event => setLanguage(event.currentTarget.value)}>
    {#each languages as option}<option value={option.id}>{option.name}</option>{/each}
  </select>
</label>
<style>
  .language-picker {display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600}
  select {max-width:140px;padding:8px 10px;border:1px solid var(--v7-control-line);border-radius:10px;background:#fff;color:var(--v7-ink)}
</style>
