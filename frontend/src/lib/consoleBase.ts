import { resolve } from '$app/paths';

// Keep the configured prefix shared by links and client-side navigation.
export const base = resolve('').replace(/\/$/, '');
