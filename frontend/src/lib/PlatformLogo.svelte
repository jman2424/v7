<script lang="ts">
  export let lockup = false;
  export let size = 52;
  export let label = '';
</script>

<span class="platform-logo" class:lockup style={`--logo-size:${size}px`} role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : true}>
  <img src={lockup ? '/static/img/vertex-seven.svg?v=20261009svg' : '/static/img/vertex-seven-mark.svg?v=20261009svg'} width={lockup ? 1254 : 1044} height={lockup ? 1254 : 599} alt="" />
</span>

<style>
  .platform-logo { display: inline-flex; align-items: center; justify-content: center; width: var(--logo-size); height: var(--logo-size); flex: none; overflow: hidden; background: #fff; border-radius: 10px; }
  img { display: block; width: calc(100% - 8px); height: calc(100% - 8px); object-fit: contain; }
  .lockup { height: auto; aspect-ratio: 1; border-radius: 0; }
  .lockup img { width: 100%; height: 100%; }
</style>
