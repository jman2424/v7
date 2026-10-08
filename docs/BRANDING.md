# Vertex Seven branding

The approved artwork is the supplied Vertex Seven Geometric Monogram logo and
Vertex Seven Analytics Horizon banner. Preserve the original artwork and its
aspect ratio.

- `dashboard/static/img/vertex-seven-logo.png`: original 1254 × 1254 logo,
  including the supplied wordmark. Header, footer and sign-in display it through
  a CSS viewport that removes excess white margins without altering the file.
- `dashboard/static/img/vertex-seven-banner.png`: original 1672 × 941 banner,
  displayed uncropped on the homepage and sign-in introduction.
- `frontend/src/lib/PlatformLogo.svelte`: reusable full logo or compact symbol
  viewport using the same supplied PNG. The sidebar shows the symbol alone.
- `dashboard/static/img/vertex-seven.svg` and `logo.svg`: compact vector
  companions matching the supplied symbol's proportions, deep green #00572f
  and charcoal #48494b. The square companion serves favicons and small default
  chat avatars; existing SVG URLs remain available.

The console palette is defined in `frontend/src/app.css`. Green `#087f5b`
remains the primary action colour; neutral `#f3f4f4` canvases, `#dce0e2` borders
and `#656d71` secondary text complement it. Public landing and policy styles use
the same neutral palette in `dashboard/static/css/home.css` and `privacy.css`.
Hover green is `#066547`, dark brand green is `#143c30`, and body text is
`#2f3539`. Use `#edf6f1` for green tints and `#d8e7dc` for their borders.
The landing page uses a white canvas, green actions and light grey information
sections. Keep its conversation preview and content cards compact, with clear
spacing between headings, descriptions and controls.

Platform artwork references include a version query so existing browsers reload
the revised assets. Company-specific logos, avatars, favicons and widget
colours continue to use each business's saved configuration.
