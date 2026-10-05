<script lang="ts">
  export let section: string;

  const paths: Record<string, string[]> = {
    platform: ['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
    companies: ['M4 21V5l8-2v18 M12 9h8v12 M7 8h2 M7 12h2 M7 16h2 M15 13h2 M15 17h2 M2 21h20'],
    pipeline: ['M4 4h16l-6 7v7l-4 2v-9z'],
    statistics: ['M4 20V10 M10 20V4 M16 20v-7 M3 20h18'],
    conversations: ['M21 11a8 8 0 0 1-8 8H7l-4 3v-7a8 8 0 0 1 8-12h2a8 8 0 0 1 8 8z M7 8h10 M7 12h7'],
    errors: ['M3 12h4l3-8 4 16 3-8h4'],
    test: ['M9 3h6 M10 3v7l-6 9a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-9V3 M8 15h8'],
    agent: ['M12 3v3 M10 3h4 M5 7h14v13H5z M8 11h1 M15 11h1 M9 16h6 M2 10v6 M22 10v6'],
    website: ['M3 4h18v16H3z M3 9h18 M7 6.5h.01 M10 6.5h.01 M9 12l-3 3 3 3 M15 12l3 3-3 3'],
    integrations: ['M8 4v5 M16 4v5 M6 9h12v3a6 6 0 0 1-12 0z M12 18v4'],
    implementation: ['M4 5h16v14H4z M4 9h16 M8 13l2 2 4-4'],
    'whatsapp-qr': ['M3 3h6v6H3z M15 3h6v6h-6z M3 15h6v6H3z M15 15h2v2h-2z M19 15h2 M19 19h2v2h-2 M12 3v4 M12 11h5 M3 12h6 M12 15v6'],
    catalog: ['M4 4h16v16H4z M4 10h16 M10 10v10'],
    offers: ['M3 4h8l10 10-7 7L3 10z M7 7h.01'],
    faqs: ['M3 4h18v14H9l-6 3z M9 8a3 3 0 0 1 6 0c0 2-3 2-3 4 M12 15h.01'],
    delivery: ['M3 6h11v12H3z M14 10h4l3 4v4h-7 M5 18a2 2 0 1 0 4 0 M16 18a2 2 0 1 0 4 0'],
    profile: ['M4 3h16v18H4z M8 7h8 M8 11h8 M8 15h5'],
    branches: ['M19 9c0 5-7 12-7 12S5 14 5 9a7 7 0 1 1 14 0z M9 9a3 3 0 1 0 6 0 3 3 0 0 0-6 0'],
    subscription: ['M3 5h18v14H3z M3 10h18 M7 15h4'],
    usage: ['M4 20V4 M4 20h17 M7 16l4-5 4 2 5-7'],
    team: ['M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-3a7 7 0 0 1 14 0v3 M17 4a4 4 0 0 1 0 8 M18 15a5 5 0 0 1 4 5v1'],
    account: ['M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M4 21v-2a8 8 0 0 1 16 0v2'],
    privacy: ['M12 3l8 3v5c0 5-8 10-8 10S4 16 4 11V6z M9 12l2 2 4-4']
  };
</script>

<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
  {#each paths[section] || paths.platform as path}<path d={path}/>{/each}
</svg>

<style>
  svg { display: block; width: 18px; height: 18px; flex: none; }
</style>
