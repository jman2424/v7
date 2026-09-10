<script lang="ts">
  import '../app.css';
  import Console from '$lib/Console.svelte';
  import { page } from '$app/state';

  let { children } = $props();
</script>

<Console section={page.params.section || 'pipeline'} />
{@render children()}
