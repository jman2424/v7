<script lang="ts">
  import '../app.css';
  import Console from '#lib/Console.svelte';
  import { page } from '$app/state';
  import { resolveWorkspace } from '../lib/workspaceArchitecture';

  let { children } = $props();
  const location = $derived(resolveWorkspace(page.params.section || 'home',page.url.searchParams.get('view') || '',page.url.searchParams.get('panel') || ''));
</script>

<Console section={location.section} workspace={location.workspace} workspaceView={location.view} workspacePanel={location.panel || ''} />
{@render children()}
