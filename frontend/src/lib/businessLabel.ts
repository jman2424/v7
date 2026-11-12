import { writable } from 'svelte/store';

/*
  The selected business's display name, set by Console.svelte. Screens show this to
  people; the internal key (for example EXAMPLE) stays in requests and confirmations
  where the exact identifier matters.
*/
export const businessLabel = writable('');
