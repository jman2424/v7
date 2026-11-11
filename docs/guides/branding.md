# Vertex Seven branding

The approved source is the supplied `vertex-seven-clean.svg`, preserved as
`dashboard/static/img/vertex-seven.svg`. Its symbol and outlined lettering are
the source for all platform logo variants; do not recreate the name with a
different font or redraw the paths.

- `vertex-seven-horizontal.svg`: the source's unchanged symbol and lettering
  arranged side by side for compact headers, footers, sign-in and the console.
  Public pages share `dashboard/templates/platform_brand.html`; the console
  uses `frontend/src/lib/PlatformLogo.svelte`.
- `vertex-seven-mark.svg`: the source symbol cropped to its bounds. `logo.svg`
  puts that symbol on a white square for browser icons and default chat avatars.
- `vertex-seven-logo.png`, PNG favicons, `apple-touch-icon.png` and `favicon.ico`
  are raster exports from this vector for crawlers and older clients.
- `vertex-seven-banner.svg` incorporates the full vector in the integrated hero
  artwork. `vertex-seven-banner.png` is its social-sharing export. Gradient
  overlays keep live text and actions readable.

All image names above live in `dashboard/static/img/`. Preserve path geometry
and colours: V `#005A32`, 7 `#505154`, Vertex lettering `#36393D` and Seven
lettering `#00552E`. Small icons use the symbol for legibility; headers use the
outlined wordmark. Keep logos compact and preserve their aspect ratios.

Colour, type, spacing and shape for the public site are defined once in
`dashboard/static/css/tokens.css` and described in `DESIGN.md`. Dark green
`#12352a` carries whole regions (hero, featured plan, closing panel); `#176446`
is the action green on light surfaces; amber `#f4c542` marks the primary action
on green. Change values in the token file, not in page stylesheets. The console
palette in `frontend/src/app.css` has not yet been moved onto these tokens.
Keep the header symbol proportionate to its wordmark and navigation.
The hero copy overlays a white fade into the supplied artwork; the conversation
preview sits below. Mobile layouts keep copy and actions above the artwork,
and sign-in puts the form before its introduction. Respect reduced motion for
the hero image fade-in and mirror its text-protection gradient in RTL layouts.

Platform artwork references include a version query so existing browsers reload
the revised assets. Company-specific logos, avatars, favicons and widget
colours continue to use each business's saved configuration.

Every visible platform logo uses the outlined SVG variants above, including the
public header/footer, sign-in, console, default chat avatar and hero artwork.
The `20261019svg` asset version refreshes existing browser caches. Organization
structured metadata also uses the SVG source. PNG social cards and legacy icon
exports remain compatibility assets rather than on-page logo images.
