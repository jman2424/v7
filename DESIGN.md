# Design system

The visual rules for Vertex Seven's own surfaces. Product facts are in `PRODUCT.md`.
Values live in `dashboard/static/css/tokens.css`; this file explains how to use them.

## Status

| Surface | State |
|---|---|
| Public site (`dashboard/templates`, `site.css`, `home.css`) | On the tokens (November 2026). |
| Owner console (`frontend/`) | Not yet migrated. Uses its own `--v7-*` values in `frontend/src/app.css`. |
| Chat widget (`widget.css`) | Not yet migrated. Stays themeable per business; only type scale and spacing should be shared. |

## Identity

- The approved Vertex Seven logo is used unchanged, always on a light surface.
- Dark green is the brand. It is used as a **field** that owns a whole region (hero,
  featured plan, closing panel), not as small accents on white.
- Amber (`--v7-signal`) appears only on a green field and only for the one thing to
  act on: the primary button, the headline's second line, list markers.
- Light surfaces use `--v7-accent` green for links and actions.

## Colour roles

| Token | Use |
|---|---|
| `--v7-brand`, `--v7-brand-deep`, `--v7-brand-line` | Green fields, their inset panels and their rules. |
| `--v7-on-brand`, `--v7-on-brand-muted` | Text on green. Never grey. |
| `--v7-signal`, `--v7-on-signal` | Primary action on green. |
| `--v7-accent`, `--v7-accent-hover` | Links and actions on light surfaces. |
| `--v7-ink`, `--v7-ink-soft`, `--v7-muted` | Headings, body, secondary text. |
| `--v7-surface`, `--v7-canvas`, `--v7-soft`, `--v7-tint` | White, band background, quiet panel, green tint. |
| `--v7-line`, `--v7-control-line` | Rules, and borders of controls. |
| `--v7-focus` | Keyboard focus ring on light; `--v7-signal` on green. |

## Type

- Headings: Bricolage Grotesque, weight 600, tight tracking, balanced wrapping.
- Text and controls: Hanken Grotesk.
- Both are self-hosted in `dashboard/static/fonts/` (SIL Open Font Licence). The
  Content-Security-Policy does not allow third-party font hosts.
- Use the scale tokens (`--v7-text-xs` to `--v7-text-display`). Do not add sizes.
- No uppercase tracked labels above headings.

## Layout

- Page width is `--v7-page`; spacing uses `--v7-space-1` to `--v7-space-9`.
- Sections are separated by a rule or a band of `--v7-canvas`, not by boxing content.
- Lists of related items are ruled rows. Cards are reserved for things that are
  genuinely separate objects (plans, the three customer questions).
- Numerals mark real sequences only (setup steps).
- Radii: `--v7-radius-control` for controls, `--v7-radius-panel` for panels,
  `--v7-radius-field` for green fields and plan cards.

## Components

- **Buttons:** `.button-dark` (primary), `.button-secondary`, `.text-link`. On a green
  field the primary becomes amber and the secondary becomes an outline.
- **Header:** logo, section links, language, sign-in. Below 1050px links move into the
  menu; below 720px sign-in is in the menu only.
- **Plans:** three cards; the recommended plan is a green field.
- **FAQ:** native `details`, ruled, with a plus that rotates to a cross.
- **Policy pages:** a single 46rem reading column, no card.

## Motion

One authored moment: the hero headline and assistant panel settle in on load. Other
motion is limited to short hover and press feedback on transform and colour. All of
it is disabled under `prefers-reduced-motion`.

## Rules for changes

1. Change a value in `tokens.css`, never in a page stylesheet.
2. Use logical properties (`inline`, `block`) so right-to-left layouts keep working.
3. Keep copy that carries a `data-i18n` attribute unchanged, or update the matching
   key in `dashboard/static/i18n/`.
4. No claims, customers or numbers that `PRODUCT.md` does not record.
