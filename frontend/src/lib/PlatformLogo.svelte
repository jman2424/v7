<script lang="ts">
  export let lockup = false;
  export let size = 52;
  export let label = '';
</script>

<span class="platform-logo" class:lockup style={`--logo-size:${size}px`} role={label ? 'img' : undefined} aria-label={label || undefined} aria-hidden={label ? undefined : true}>
  <span class="logo-viewport"><img src="/static/img/vertex-seven-logo.png?v=20261008a" width="1254" height="1254" alt="" /></span>
</span>

<style>
  .platform-logo { display: inline-flex; align-items: center; justify-content: center; width: var(--logo-size); height: var(--logo-size); flex: none; overflow: hidden; background: #fff; border-radius: 10px; }
  .logo-viewport { display: block; position: relative; width: calc(100% - 8px); aspect-ratio: 1075 / 630; overflow: hidden; }
  img { position: absolute; width: 116.6512%; max-width: none; height: auto; left: -8.3721%; top: -34.127%; }
  .lockup { height: auto; aspect-ratio: 1075 / 835; border-radius: 0; }
  .lockup .logo-viewport { width: 100%; height: 100%; aspect-ratio: auto; }
  .lockup img { top: -25.7485%; }
</style>
