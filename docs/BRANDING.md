# Vertex Seven branding

The platform mark combines an incoming green ribbon folded into a V with a
charcoal 7 at the outgoing end. Keep the open space between both strokes when
resizing; do not stretch the SVG.

- `dashboard/static/img/vertex-seven.svg`: transparent mark for light surfaces.
- `dashboard/static/img/logo.svg`: square badge for sign-in, navigation, favicon
  and the customer widget's default avatar. Both assets use the same geometry.
- Logo colours: primary green `#087f5b` and charcoal `#3f4549`.
- Both logos are native vectors with explicit high-resolution intrinsic sizes.
  The transparent mark has a tight viewBox, and the square badge uses the larger
  mark without the previous fractional scale. Always preserve the aspect ratio;
  use the SVG directly rather than enlarging a raster screenshot.

The console palette is defined in `frontend/src/app.css`. Green `#087f5b`
remains the primary action colour; neutral `#f3f4f4` canvases, `#dce0e2` borders
and `#656d71` secondary text complement it. Public landing and policy styles use
the same neutral palette in `dashboard/static/css/home.css` and `privacy.css`.
Hover green is `#066547`, dark brand green is `#143c30`, and body text is
`#2f3539`. Use `#edf6f1` for green tints and `#d8e7dc` for their borders.
The landing page uses a white canvas, green actions and light grey information
sections. Keep its conversation preview and content cards compact, with clear
spacing between headings, descriptions and controls.

Platform logo references include a version query so existing browsers reload
the revised static SVGs. Company-specific logos, avatars, favicons and widget
colours continue to use each business's saved configuration.
