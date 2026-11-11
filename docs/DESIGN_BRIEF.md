# Design brief — MangaPoisk Reborn

## Product feeling

A calm, premium Russian manga library.  Dark, cinematic, readable, fast.
Not a clone of MangaLib/HentaiLib: take their information architecture and
reader ergonomics, but give MangaPoisk its own identity built around six
atmospheric theme illustrations.

The UI must feel equally good on a 360 px phone and a 1440 px desktop.

## Theme system (6 themes)

Each theme uses one supplied illustration as an *optional* atmospheric
backdrop.  The image is never placed behind body copy.  It is used only in:

- the home hero (right/bottom area, masked and darkened),
- the auth pages (behind a solid card),
- empty states / 404 (large, low-opacity).

Everywhere else the theme is carried by its palette, typography and accent
details.  If the image would reduce contrast or fight the content, it is
dropped.  This is the rule the user explicitly asked for.

| id | image | palette | mood |
|---|---|---|---|
| `midnight` | `blue-theme.jpg` | deep navy, ice blue, cyan accent | rainy neon city, default |
| `noir` | `dark-theme.png` | black, bone white, silver | ornate gothic, serif headings |
| `oni` | `devil-dark-theme.png` | charcoal, blood red, warm paper | oni mask, dramatic |
| `crimson` | `red-dark-theme.jpg` | black, crimson, pale grey | minimal anime noir |
| `sunset` | `sunflower-theme.jpg` | plum, coral, amber, rose | temple at sunset |
| `paper` | `white-rad-theme.png` | paper white, ink, vermilion | light, airy, ukiyo-e line art |

Implementation: `<html data-theme="midnight">`, CSS custom properties in
`src/styles/themes.css`.  Theme choice persists in `localStorage` and, when
signed in, in `library/settings`.  Respect `prefers-color-scheme` on first
visit (light → `paper`, dark → `midnight`).

## Design tokens

- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64.
- Radii: 8 (controls), 14 (cards), 22 (panels), 999 (pills).
- Type: system UI stack; headings either `Manrope`-like sans (default) or
  `Georgia`/serif for `noir` and `paper`.  No external font fetch required.
- Body 15–16 px, line-height 1.6.  H1 clamp(2rem, 5vw, 4rem).
- Motion: 160–240 ms ease; `prefers-reduced-motion` disables auto-scroll and
  parallax.
- Focus ring: 2 px accent with 2 px offset, visible on all interactive items.
- Touch targets: minimum 44×44 px.

## Information architecture

Desktop (≥ 1024 px):
- sticky top bar: logo, primary nav (Каталог, Источники, Библиотека), search,
  theme switcher, auth menu;
- content max-width 1280 px, 12-column grid;
- hero with featured title + latest updates strip;
- catalogue grid 5–6 columns.

Tablet (768–1023): 3–4 columns, condensed nav.

Mobile (< 768):
- top bar with logo + search icon + avatar;
- bottom navigation: Главная, Каталог, Библиотека, Профиль;
- catalogue 2 columns, 3 on large phones;
- reader controls collapse into a bottom sheet.

## Key screens

1. **Home** — hero (featured manga), «Популярное», «Обновления», «Новые
   главы», source chips, continue-reading row when signed in.
2. **Catalogue / search** — query, source, genre, year, status, sort; infinite
   or paginated grid; skeleton cards; empty state with import CTA.
3. **Manga** — poster, title/alt titles, rating, year, status, genres, expandable
   description, bookmark, «Читать с начала»/«Продолжить», chapter list with
   search and sort, export buttons.
4. **Reader** — the most important screen:
   - vertical/webtoon continuous mode (default), horizontal paged mode;
   - auto-scroll with speed control, pause on interaction;
   - keyboard: ←/→ chapter, ↑/↓ scroll, F fullscreen, S settings;
   - page counter, chapter select, prev/next, progress bar;
   - image preloading for the next 2 pages, blur-up placeholders;
   - settings sheet: mode, fit, gap, theme, auto-scroll speed;
   - mobile tap zones left/right; swipe in horizontal mode;
   - resume prompt «Продолжить со страницы N?».
5. **Library** — bookmarks grid, continue-reading cards with progress,
   history, empty states.
6. **Auth** — login/register card over theme image; clear validation.
7. **Profile/settings** — display name, theme, reader defaults, logout,
   token-safe messaging.
8. **Sources** — cards with capabilities, language, status, legal note.
9. **404 / error** — friendly, themed.

## Responsiveness requirements

- No horizontal scroll at 320–1920 px.
- Test at 360×800, 390×844, 768×1024, 1280×800, 1440×900.
- Reader images `max-width: 100%`, `height: auto`; no layout shift (reserve
  aspect ratio from API width/height).
- Chapter list becomes a drawer on mobile.
- Sticky reader header hides on scroll down, reappears on scroll up.
- Bottom nav respects `env(safe-area-inset-bottom)`.

## Accessibility

- WCAG 2.1 AA contrast for text and controls in every theme.
- Semantic landmarks, `aria-label` on icon buttons, `aria-current` on nav.
- Reader images have meaningful alt text; decorative theme images are
  `aria-hidden`.
- Keyboard-complete; focus trapped in dialogs; Escape closes.
- Do not encode state by color alone.

## Deliverables for the design subagent

1. `docs/DESIGN_SYSTEM.md` — final tokens, component states, theme table.
2. `design/prototype/index.html` — self-contained clickable prototype for
   home, catalogue, manga, reader, library, auth using the real images.
3. `design/theme-sources/` → optimized `apps/web/public/themes/*.webp`
   (1600 px wide, quality ~80, keep aspect ratio).
4. `docs/RESPONSIVE_AUDIT.md` after the React app exists — screenshots/notes at
   the five viewport sizes and a prioritized fix list.  The frontend agent owns
   the fixes; the design agent may patch only `src/styles/**` after coordination.
