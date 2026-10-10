<script lang="ts">
  export let lockup = false;
  export let horizontal = false;
  export let size = 52;
  export let label = '';
</script>

<span class="platform-logo" class:lockup class:horizontal style={`--logo-size:${size}px`} role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : true}>
  <img src={horizontal ? '/static/img/vertex-seven-horizontal.svg?v=20261010logo' : lockup ? '/static/img/vertex-seven.svg?v=20261010logo' : '/static/img/vertex-seven-mark.svg?v=20261010logo'} width={horizontal ? 240 : lockup ? 1254 : 1044} height={horizontal ? 40 : lockup ? 1254 : 599} alt="" />
</span>

<style>
  .platform-logo { display: inline-flex; align-items: center; justify-content: center; width: var(--logo-size); height: var(--logo-size); flex: none; overflow: hidden; background: #fff; border-radius: 10px; }
  img { display: block; width: calc(100% - 8px); height: calc(100% - 8px); object-fit: contain; }
  .lockup { height: auto; aspect-ratio: 1; border-radius: 0; }
  .lockup img { width: 100%; height: 100%; }
  .horizontal { height: auto; padding: 7px 8px; border-radius: 7px; }
  .horizontal img { width: 100%; height: auto; }
</style>
