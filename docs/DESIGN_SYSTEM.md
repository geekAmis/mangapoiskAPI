# MangaPoisk Reborn — design system

Status: implementation-ready · Owner: design · Applies to: `apps/web` (React SPA), Android parity, exports.

This document is the source of truth for colour, type, spacing, component behaviour, responsive layout and the use of the six theme illustrations. The clickable reference is `design/prototype/index.html`.

---

## 1. Design principles

1. **Calm, cinematic, readable.** The interface is a quiet frame around loud artwork. Large negative space, few borders, one accent per theme, no decorative noise behind reading surfaces.
2. **Themes are palettes first, paintings second.** A theme changes tokens and type; the illustration is an *editorial accent*, not a page background. Most screens never show it.
3. **The content is the colour.** Covers and reader pages supply saturation. Chrome stays near-monochrome so that covers, status colours and accents remain meaningful.
4. **One continuous product.** The same information architecture, card, chapter row and reader controls on phone and desktop — only density and navigation change.
5. **Accessible by construction.** Every text/background pair in the shipped themes passes WCAG 2.1 AA. Focus is always visible, tap targets are 44 px, motion is optional.
6. **Russian-first typography.** Copy uses «ёлочки», em dashes, non-breaking spaces before units, and avoids all-caps for long strings.

### The art rule (non-negotiable)

> **A theme illustration may appear only in the home hero, the auth aside, and the 404 / empty state. It is never placed behind body copy, a form, a chapter list, a table, a modal or reader chrome.**

If the image reduces contrast, fights the headline, or makes a control harder to see, **drop the image**. The palette alone must carry the theme. See §8 for the complete rule set.

---

## 2. Brand

### Logo

- Mark: a 40 × 40 rounded-square seal (`--radius: 12px`) filled with `--accent`. Inside, a thin open-book / “M” monogram in `--on-accent`, plus a 1.5 px dot above the centre.
- Wordmark: `MangaPoisk` in 650–700 weight, `-0.02em` tracking, with a second line `REBORN` at 8 px, `0.22em` tracking, `--muted`.
- Minimum mark size: 28 px. Minimum clear space: 8 px.
- On `paper`, the seal is `--accent` vermilion with cream monogram. On `noir`, the seal is bone with black monogram.
- The logo is a link to `/`; accessible name «MangaPoisk — на главную».

### Voice

Short, confident, human. No exclamation marks in system messages. Actions are verbs: «Читать», «В библиотеку», «Продолжить», «Скачать CBZ». Empty states explain the next action, not the failure.

### Editorial devices

- A thin 1 px accent rule, 24–40 px long, before eyebrows.
- One oversized Japanese glyph per theme used as a **decorative watermark on a solid surface only** (`雨 夜 鬼 紅 寺 紙`), 6–8 % opacity, `aria-hidden`.
- Vertical micro-label set in `writing-mode: vertical-rl` for season / issue metadata. Never used for essential copy.
- Tabular numerals for ratings, page counts and progress.

---

## 3. Theme model

| id | Russian label | Source artwork | Web asset | Mood | Display type |
|---|---|---|---|---|---|
| `midnight` | Полночь | `blue-theme.jpg` | `themes/midnight.webp` | rainy neon city, ice blue | sans |
| `noir` | Нуар | `dark-theme.png` | `themes/noir.webp` | ornate gothic, bone and silver | serif |
| `oni` | Они | `devil-dark-theme.png` | `themes/oni.webp` | oni mask, charcoal and blood red | sans, tight caps |
| `crimson` | Багровый | `red-dark-theme.jpg` | `themes/crimson.webp` | minimal anime noir, crimson | sans |
| `sunset` | Закат | `sunflower-theme.jpg` | `themes/sunset.webp` | temple at sunset, plum and coral | sans |
| `paper` | Бумага | `white-rad-theme.png` | `themes/paper.webp` | light, airy ukiyo-e line art | serif |

### Contract

```html
<html lang="ru" data-theme="midnight">
```

- Theme ids are stable and are stored in `localStorage` under `mp-theme`, and for signed-in users in `library/settings.theme`.
- First visit: `prefers-color-scheme: light` → `paper`; otherwise → `midnight`. Never flash the wrong theme: resolve before first paint with an inline boot script or a server-rendered `data-theme`.
- Switching theme updates `data-theme` on `<html>`, `meta[name="theme-color"]`, the theme-switcher selection and any theme-dependent hero/auth artwork.
- Theme changes must not reload the page, reset scroll, clear filters or interrupt the reader.
- `color-scheme` is set per theme so native controls, scrollbars and form autofill follow the palette.
- The theme switcher is a product feature, available in the header and in reader settings. It must be keyboard accessible.

### Naming

- Core: `--bg`, `--surface`, `--surface-2`, `--surface-3`, `--text`, `--muted`, `--border`, `--border-strong`.
- Accent: `--accent` (brand/fill), `--accent-text` (accessible text/icon tint), `--accent-2` (secondary brand), `--on-accent`, `--on-accent-2`.
- Semantic: `--danger`, `--danger-text`, `--on-danger`, `--success`, `--success-text`, `--warning`.
- Effects: `--focus-ring`, `--selection-bg`, `--selection-text`, `--hero-gradient`, `--hero-image`, `--hero-filter`, `--shadow-sm`, `--shadow-md`, `--shadow-lg`, `--shadow-hero`.
- Type per theme: `--font-display`, `--display-weight`, `--display-tracking`, `--display-transform`.

`--accent-text` exists because a fill colour and a text colour have different contrast duties. In `oni`, for example, `--accent` is deep blood red for buttons and `--accent-text` is the lighter salmon used for links on dark surfaces. Use the right one:

- filled button / active indicator / focus ring → `--accent`
- link, inline icon, small accent label on a surface → `--accent-text`
- text or icon placed *on* an accent fill → `--on-accent`

Tints are derived with `color-mix()`; do not invent new hex values in components.

```css
--accent-soft: color-mix(in srgb, var(--accent) 14%, transparent);
--danger-soft: color-mix(in srgb, var(--danger) 14%, transparent);
--success-soft: color-mix(in srgb, var(--success) 14%, transparent);
--glass: color-mix(in srgb, var(--bg) 78%, transparent);
```

---

## 4. Core tokens

These do not change by theme.

```css
:root {
  /* type */
  --font-sans: "Manrope", "Segoe UI Variable Text", "Segoe UI", system-ui,
               -apple-system, "Helvetica Neue", Arial, sans-serif;
  --font-serif: "Iowan Old Style", "Palatino Linotype", "Book Antiqua",
                Georgia, "Times New Roman", serif;

  --text-2xs: 0.6875rem;   /* 11px */
  --text-xs: 0.75rem;      /* 12px */
  --text-sm: 0.84375rem;   /* 13.5px */
  --text-base: 0.96875rem; /* 15.5px */
  --text-md: 1.0625rem;    /* 17px */
  --text-lg: 1.25rem;      /* 20px */
  --text-xl: 1.5rem;       /* 24px */
  --text-2xl: 2rem;        /* 32px */
  --text-3xl: 2.75rem;     /* 44px */

  --leading-none: 1;
  --leading-tight: 1.08;
  --leading-snug: 1.28;
  --leading-normal: 1.6;
  --tracking-tight: -0.035em;
  --tracking-normal: -0.01em;
  --tracking-wide: 0.12em;

  /* spacing: 4-point scale */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --space-7: 48px;
  --space-8: 64px;

  /* radii */
  --radius-xs: 6px;
  --radius-sm: 8px;    /* controls */
  --radius-md: 14px;   /* cards, covers */
  --radius-lg: 22px;   /* panels, sheets */
  --radius-xl: 28px;   /* hero */
  --radius-pill: 999px;

  /* layout */
  --content-max: 1280px;
  --gutter: clamp(16px, 3.2vw, 40px);
  --header-h: 68px;
  --header-h-mobile: 56px;
  --bottom-nav-h: 64px;
  --reader-top-h: 56px;
  --reader-bottom-h: 64px;

  /* motion */
  --duration-fast: 160ms;
  --duration-base: 220ms;
  --duration-slow: 320ms;
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);

  /* layers */
  --z-base: 0;
  --z-raised: 1;
  --z-sticky: 20;
  --z-header: 30;
  --z-bottom-nav: 35;
  --z-dropdown: 40;
  --z-backdrop: 60;
  --z-sheet: 70;
  --z-toast: 80;
  --z-tooltip: 90;
  --z-dev-chrome: 100;
}
```

Reference breakpoints (CSS custom properties cannot be used in media queries; use the literals):

| token | min width | Purpose |
|---|---:|---|
| `xs` | 320 | smallest supported phone |
| `sm` | 360 | common Android phone |
| `md` | 390 | iPhone class |
| `lg` | 768 | tablet, top navigation joins |
| `xl` | 1024 | desktop, bottom nav leaves |
| `2xl` | 1280 | full catalogue density |
| `3xl` | 1440 | design reference desktop |
| `4xl` | 1920 | large monitor; content does not stretch |

### Motion

- Micro-feedback (hover, press, chip): 160 ms.
- Standard (popover, theme fade, card hover): 220 ms.
- Screen change / sheet entrance: 240–320 ms, `--ease-out`.
- Never animate the reader page position, image scale or scroll position as decoration.
- `prefers-reduced-motion: reduce`: remove transforms, parallax, auto-scroll and smooth scrolling; keep opacity <= 120 ms. Auto-scroll must not start and must be visibly unavailable.
- No infinite looping animation except a restrained skeleton shimmer, which becomes a static surface under reduced motion.
- Never animate colours on every element; animate `background-color`, `color` and `border-color` only on the shell and interactive controls.

### Elevation

Use theme shadow tokens, never raw black shadows in components.

| token | Use |
|---|---|
| `--shadow-sm` | inputs on focus? no; chips, sticky bars, small cards |
| `--shadow-md` | manga cards on hover, dropdowns, continue cards |
| `--shadow-lg` | modals, sheets, auth card, hero |
| `--shadow-hero` | home hero / large editorial panel |

Dark themes also get a 1 px top highlight via `border: 1px solid var(--border)`; do not simulate glass with heavy white gradients.

---

## 5. Theme palettes

All pairs were measured with WCAG 2.x relative luminance. **Every value in the table passes AA for its intended use.**

| Theme | bg | surface | surface-2 | text | muted | border | border-strong | accent | accent-text | accent-2 | on-accent | danger | success | focus |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| midnight | `#081120` | `#0E1A2C` | `#15243A` | `#EAF3FF` | `#A3B9D4` | `#263B57` | `#52708F` | `#7DD3FC` | `#7DD3FC` | `#8AA6FF` | `#04121F` | `#FF7A8A` | `#5BE3B0` | `#7DD3FC` |
| noir | `#070707` | `#0F0F10` | `#171718` | `#F2EFE5` | `#A8A294` | `#2C2A25` | `#6B675E` | `#E4DCC8` | `#E4DCC8` | `#A79E8A` | `#141310` | `#F07A7A` | `#8FC49A` | `#E4DCC8` |
| oni | `#120D0C` | `#1B1413` | `#251B19` | `#F5E9DE` | `#BCA89A` | `#392724` | `#7C6059` | `#D23A31` | `#F07A6E` | `#F0A35E` | `#FFFFFF` | `#FF7C6E` | `#93C489` | `#F07A6E` |
| crimson | `#060607` | `#0D0D10` | `#151518` | `#F4F1F2` | `#AAA4AC` | `#28252B` | `#675F6D` | `#D91C32` | `#FF8A98` | `#B7A1F2` | `#FFFFFF` | `#FF6B7A` | `#5FD6A3` | `#FF8A98` |
| sunset | `#1A1124` | `#241730` | `#30203E` | `#FFF1EA` | `#C9B4C6` | `#4A3457` | `#7A5D8D` | `#FF8A65` | `#FFA184` | `#FFC46B` | `#2A120E` | `#FF7088` | `#8FD8A8` | `#FFB18F` |
| paper | `#F4F0E7` | `#FCF9F2` | `#EBE4D6` | `#1D1A16` | `#665F55` | `#D5CCBC` | `#8F8472` | `#B83427` | `#A62E23` | `#2E4A68` | `#FFF9F3` | `#A32520` | `#276A4E` | `#B83427` |

`--border` is a hairline (decorative). `--border-strong` is the minimum 3:1 boundary for form fields, switches, focus-adjacent controls and selected chips; use it wherever the boundary carries meaning.

### Measured contrast (intended pair)

| Theme | text / bg | muted / surface | accent-text / surface-2 | on-accent / accent | danger / bg | success / bg | border-strong / surface |
|---|---:|---:|---:|---:|---:|---:|---:|
| midnight | 16.88 | 8.69 | 9.36 | 11.33 | 7.56 | 11.75 | 3.39 |
| noir | 17.51 | 7.54 | 13.11 | 13.60 | 7.45 | 10.10 | 3.40 |
| oni | 16.16 | 7.96 | 6.17 | 4.78 | 7.68 | 9.64 | 3.18 |
| crimson | 18.05 | 7.96 | 8.11 | 5.05 | 7.36 | 11.22 | 3.17 |
| sunset | 16.55 | 8.73 | 7.62 | 7.62 | 6.89 | 10.92 | 3.05 |
| paper | 15.24 | 5.99 | 5.47 | 5.65 | 6.50 | 5.67 | 3.50 |

`muted` on `surface-2` is also above 4.5 in all themes (lowest: `paper` 4.98). `accent` itself is only a fill/indicator; do **not** use raw `--accent` for small text on `bg` unless the measured ratio is ≥ 4.5 (use `--accent-text`).

### 5.1 Complete theme CSS

```css
/* ——— midnight ————————————————————————————————————— */
[data-theme="midnight"] {
  color-scheme: dark;
  --bg: #081120;
  --surface: #0E1A2C;
  --surface-2: #15243A;
  --surface-3: #1C2E47;
  --text: #EAF3FF;
  --muted: #A3B9D4;
  --border: #263B57;
  --border-strong: #52708F;
  --accent: #7DD3FC;
  --accent-text: #7DD3FC;
  --accent-2: #8AA6FF;
  --on-accent: #04121F;
  --on-accent-2: #061024;
  --danger: #FF7A8A;
  --danger-text: #FF9AA6;
  --on-danger: #280A0E;
  --success: #5BE3B0;
  --success-text: #7DEBC3;
  --warning: #FFC46B;
  --focus-ring: #7DD3FC;
  --selection-bg: #7DD3FC;
  --selection-text: #04121F;
  --hero-image: url("themes/midnight.webp");
  --hero-filter: saturate(0.84) contrast(1.06) brightness(0.86);
  --hero-gradient:
    linear-gradient(100deg, #081120 0%, rgba(8,17,32,.96) 28%,
      rgba(8,17,32,.55) 55%, rgba(8,17,32,.06) 88%, rgba(8,17,32,0) 100%),
    linear-gradient(0deg, rgba(8,17,32,.70) 0%, rgba(8,17,32,0) 55%);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.38);
  --shadow-md: 0 16px 40px -20px rgba(0,0,0,.82), 0 2px 8px rgba(0,0,0,.30);
  --shadow-lg: 0 48px 120px -40px rgba(0,0,0,.92), 0 12px 32px rgba(0,0,0,.42);
  --shadow-hero: 0 32px 100px -46px rgba(0,0,0,.95);
  --font-display: var(--font-sans);
  --display-weight: 700;
  --display-tracking: -0.04em;
  --display-transform: none;
}

/* ——— noir ————————————————————————————————————————— */
[data-theme="noir"] {
  color-scheme: dark;
  --bg: #070707;
  --surface: #0F0F10;
  --surface-2: #171718;
  --surface-3: #1F1F20;
  --text: #F2EFE5;
  --muted: #A8A294;
  --border: #2C2A25;
  --border-strong: #6B675E;
  --accent: #E4DCC8;
  --accent-text: #E4DCC8;
  --accent-2: #A79E8A;
  --on-accent: #141310;
  --on-accent-2: #12110E;
  --danger: #F07A7A;
  --danger-text: #F49A9A;
  --on-danger: #240909;
  --success: #8FC49A;
  --success-text: #AED9B6;
  --warning: #D8B878;
  --focus-ring: #E4DCC8;
  --selection-bg: #E4DCC8;
  --selection-text: #141310;
  --hero-image: url("themes/noir.webp");
  --hero-filter: grayscale(0.25) contrast(1.10) brightness(0.82);
  --hero-gradient:
    linear-gradient(100deg, #070707 0%, rgba(7,7,7,.97) 30%,
      rgba(7,7,7,.52) 58%, rgba(7,7,7,.04) 100%),
    linear-gradient(0deg, rgba(7,7,7,.74) 0%, rgba(7,7,7,0) 56%);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.55);
  --shadow-md: 0 18px 44px -22px rgba(0,0,0,.96), 0 0 0 1px rgba(228,220,200,.04);
  --shadow-lg: 0 52px 130px -42px rgba(0,0,0,.98), 0 12px 34px rgba(0,0,0,.55);
  --shadow-hero: 0 40px 120px -48px rgba(0,0,0,1);
  --font-display: var(--font-serif);
  --display-weight: 600;
  --display-tracking: -0.025em;
  --display-transform: none;
}

/* ——— oni ——————————————————————————————————————————— */
[data-theme="oni"] {
  color-scheme: dark;
  --bg: #120D0C;
  --surface: #1B1413;
  --surface-2: #251B19;
  --surface-3: #2F2220;
  --text: #F5E9DE;
  --muted: #BCA89A;
  --border: #392724;
  --border-strong: #7C6059;
  --accent: #D23A31;
  --accent-text: #F07A6E;
  --accent-2: #F0A35E;
  --on-accent: #FFFFFF;
  --on-accent-2: #2B1608;
  --danger: #FF7C6E;
  --danger-text: #FF9C90;
  --on-danger: #2A0B08;
  --success: #93C489;
  --success-text: #ADD5A5;
  --warning: #F0A35E;
  --focus-ring: #F07A6E;
  --selection-bg: #D23A31;
  --selection-text: #FFFFFF;
  --hero-image: url("themes/oni.webp");
  --hero-filter: saturate(0.90) contrast(1.08) brightness(0.86);
  --hero-gradient:
    linear-gradient(100deg, #120D0C 0%, rgba(18,13,12,.95) 30%,
      rgba(18,13,12,.48) 60%, rgba(18,13,12,.04) 100%),
    linear-gradient(0deg, rgba(18,13,12,.74) 0%, rgba(18,13,12,0) 55%);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.42);
  --shadow-md: 0 16px 42px -20px rgba(8,2,1,.88), 0 2px 8px rgba(0,0,0,.34);
  --shadow-lg: 0 48px 120px -38px rgba(8,2,1,.94), 0 12px 32px rgba(0,0,0,.48);
  --shadow-hero: 0 36px 110px -44px rgba(8,2,1,.98);
  --font-display: var(--font-sans);
  --display-weight: 800;
  --display-tracking: -0.045em;
  --display-transform: none;
}

/* ——— crimson ——————————————————————————————————————— */
[data-theme="crimson"] {
  color-scheme: dark;
  --bg: #060607;
  --surface: #0D0D10;
  --surface-2: #151518;
  --surface-3: #1D1D21;
  --text: #F4F1F2;
  --muted: #AAA4AC;
  --border: #28252B;
  --border-strong: #675F6D;
  --accent: #D91C32;
  --accent-text: #FF8A98;
  --accent-2: #B7A1F2;
  --on-accent: #FFFFFF;
  --on-accent-2: #1A1229;
  --danger: #FF6B7A;
  --danger-text: #FF93A0;
  --on-danger: #2A0810;
  --success: #5FD6A3;
  --success-text: #86E5BB;
  --warning: #F0C078;
  --focus-ring: #FF8A98;
  --selection-bg: #D91C32;
  --selection-text: #FFFFFF;
  --hero-image: url("themes/crimson.webp");
  --hero-filter: grayscale(0.15) saturate(0.95) contrast(1.08) brightness(0.82);
  --hero-gradient:
    linear-gradient(100deg, #060607 0%, rgba(6,6,7,.96) 30%,
      rgba(6,6,7,.50) 58%, rgba(6,6,7,.04) 100%),
    linear-gradient(0deg, rgba(6,6,7,.74) 0%, rgba(6,6,7,0) 55%);
  --shadow-sm: 0 1px 2px rgba(0,0,0,.50);
  --shadow-md: 0 16px 40px -20px rgba(0,0,0,.90), 0 2px 8px rgba(0,0,0,.35);
  --shadow-lg: 0 50px 130px -40px rgba(0,0,0,.96), 0 12px 32px rgba(0,0,0,.50);
  --shadow-hero: 0 36px 110px -44px rgba(0,0,0,1);
  --font-display: var(--font-sans);
  --display-weight: 750;
  --display-tracking: -0.04em;
  --display-transform: none;
}

/* ——— sunset ———————————————————————————————————————— */
[data-theme="sunset"] {
  color-scheme: dark;
  --bg: #1A1124;
  --surface: #241730;
  --surface-2: #30203E;
  --surface-3: #3C294C;
  --text: #FFF1EA;
  --muted: #C9B4C6;
  --border: #4A3457;
  --border-strong: #7A5D8D;
  --accent: #FF8A65;
  --accent-text: #FFA184;
  --accent-2: #FFC46B;
  --on-accent: #2A120E;
  --on-accent-2: #2B1A07;
  --danger: #FF7088;
  --danger-text: #FF9AA9;
  --on-danger: #2A0B14;
  --success: #8FD8A8;
  --success-text: #B0E6C2;
  --warning: #FFC46B;
  --focus-ring: #FFB18F;
  --selection-bg: #FF8A65;
  --selection-text: #2A120E;
  --hero-image: url("themes/sunset.webp");
  --hero-filter: saturate(0.92) contrast(1.04) brightness(0.88);
  --hero-gradient:
    linear-gradient(100deg, #1A1124 0%, rgba(26,17,36,.95) 30%,
      rgba(26,17,36,.52) 58%, rgba(26,17,36,.05) 100%),
    linear-gradient(0deg, rgba(26,17,36,.70) 0%, rgba(26,17,36,0) 55%);
  --shadow-sm: 0 1px 2px rgba(9,4,14,.35);
  --shadow-md: 0 16px 44px -20px rgba(9,4,14,.80), 0 2px 8px rgba(9,4,14,.30);
  --shadow-lg: 0 48px 120px -40px rgba(9,4,14,.90), 0 12px 32px rgba(9,4,14,.42);
  --shadow-hero: 0 34px 100px -44px rgba(9,4,14,.92);
  --font-display: var(--font-sans);
  --display-weight: 700;
  --display-tracking: -0.035em;
  --display-transform: none;
}

/* ——— paper ————————————————————————————————————————— */
[data-theme="paper"] {
  color-scheme: light;
  --bg: #F4F0E7;
  --surface: #FCF9F2;
  --surface-2: #EBE4D6;
  --surface-3: #E0D6C4;
  --text: #1D1A16;
  --muted: #665F55;
  --border: #D5CCBC;
  --border-strong: #8F8472;
  --accent: #B83427;
  --accent-text: #A62E23;
  --accent-2: #2E4A68;
  --on-accent: #FFF9F3;
  --on-accent-2: #F7F2E8;
  --danger: #A32520;
  --danger-text: #8E1F1B;
  --on-danger: #FFF8F4;
  --success: #276A4E;
  --success-text: #1F5A41;
  --warning: #8A5A12;
  --focus-ring: #B83427;
  --selection-bg: #B83427;
  --selection-text: #FFF9F3;
  --hero-image: url("themes/paper.webp");
  --hero-filter: saturate(0.90) contrast(1.04) brightness(1.02);
  --hero-gradient:
    linear-gradient(100deg, #F4F0E7 0%, rgba(244,240,231,.97) 30%,
      rgba(244,240,231,.58) 58%, rgba(244,240,231,.06) 100%),
    linear-gradient(0deg, rgba(244,240,231,.60) 0%, rgba(244,240,231,0) 52%);
  --shadow-sm: 0 1px 2px rgba(72,56,32,.08);
  --shadow-md: 0 14px 32px -18px rgba(72,56,32,.22), 0 2px 6px rgba(72,56,32,.08);
  --shadow-lg: 0 40px 90px -30px rgba(72,56,32,.30), 0 10px 26px rgba(72,56,32,.10);
  --shadow-hero: 0 30px 80px -40px rgba(72,56,32,.26);
  --font-display: var(--font-serif);
  --display-weight: 600;
  --display-tracking: -0.03em;
  --display-transform: none;
}
```

---

## 6. Typography

### Families

- Body/UI: `--font-sans`, a system stack led by Manrope then Segoe UI Variable. No network font is required.
- Display: `--font-display` is set per theme. `noir` and `paper` use the serif stack; all other themes use the sans stack.
- Display transform: none. `oni` uses heavier weight and tighter tracking rather than all-caps, which harms Russian readability.

### Scale

| Token | Size / line-height | Weight | Tracking | Use |
|---|---|---|---|---:|---|
| Display XL | `clamp(2.5rem, 4.8vw, 4.5rem)` / 1.0 | `--display-weight` | `--display-tracking` | home hero title |
| Display L | `clamp(2rem, 3.6vw, 3.25rem)` / 1.05 | `--display-weight` | `--display-tracking` | page title, auth heading |
| H1 | `clamp(1.75rem, 3.2vw, 2.75rem)` / 1.1 | 700 | -0.03em | screen title |
| H2 | 1.5rem / 1.2 | 700 | -0.02em | section title |
| H3 | 1.125rem / 1.3 | 650 | -0.01em | card group, panel title |
| Body L | 1.0625rem / 1.65 | 400 | 0 | hero description, article |
| Body | 0.96875rem / 1.6 | 400 | 0 | default |
| Body S | 0.84375rem / 1.5 | 400 | 0 | card meta, helper |
| Caption | 0.75rem / 1.4 | 600 | 0.08em | labels, uppercase |
| Micro | 0.6875rem / 1.2 | 650 | 0.1em | badges, nav labels |

- Headings use `text-wrap: balance`; paragraphs use `text-wrap: pretty`.
- Reading measure: 60–72 characters. Hero description ≤ 46 ch. Auth copy ≤ 48 ch.
- Body text is never smaller than 13.5 px on web, 11 px only for badges/labels.
- Ratings, page counters, chapters and prices use `font-variant-numeric: tabular-nums`.
- Russian quotes: «…»; nested „…“; em dash with non-breaking space before units: `15,5 px`, `2026 г.`.
- Do not use letter-spacing on Cyrillic body text; uppercase only for short labels.
- `font-optical-sizing: auto` if the variable font supports it.

---

## 7. Layout and responsive rules

### Page shell

```
┌ header (56/64/68, sticky, blurred, 1 px border)
│
├ main (internal scroll, --content-max 1280, gutter)
│
├ bottom nav (mobile only: 64 + env(safe-area-inset-bottom))
```

Desktop: content centered in a 1280 px column, 12-column reference grid with 16 px gutters. Mobile: 4-column reference grid with 12–16 px gutters. No horizontal scroll at any supported width.

### Breakpoint table

| Width | Gutter | Header | Navigation | Catalogue columns | Hero | Notes |
|---:|---:|---|---|---:|---|---|
| 320–359 | 16 | 56 | bottom nav | 2 | stacked art 220 + copy | smallest target; hide nonessential metadata, buttons can go full-width |
| 360–389 | 16 | 56 | bottom nav | 2 | stacked art 240 | common Android |
| 390–767 | 16–20 | 56 | bottom nav | 2 (3 ≥ 480) | stacked art 240–300 | iPhone reference 390×844 |
| 768–1023 | 24 | 64 | top nav, condensed | 4 | split 55/45 | tablet; bottom nav hidden; search icon only |
| 1024–1279 | 32 | 68 | top nav | 4–5 | split 56/44 | desktop; search field can appear ≥ 1200 |
| 1280–1439 | 40 | 68 | top nav + search | 6 | split 58/42 | full density |
| 1440–1919 | 40 | 68 | top nav + search | 6 | max height 560 | design reference 1440×900 |
| ≥1920 | 48 | 68 | top nav + search | 6 | max 560 | content remains 1280 |

- **320/360/390:** header shows logo, search icon, theme button, avatar. Bottom nav has 44 px targets and safe-area padding. Hero text never overlaps art. Chapter rows become two-line rows. Tables/feature panels stack.
- **768:** top nav replaces bottom nav; the nav collapses to 3 items until 1024 if space is tight; hero is split and art is masked on the left.
- **1024:** full top nav; catalogue 4 columns; detail page uses poster + info columns; reader max page width 760.
- **1280:** 6-column catalogue; 12-column composition for hero and detail.
- **1440:** verify hero at 1440×900 and 390×844. Nothing should exceed 1280 content width; margin is intentional.
- **1920:** do not scale type up beyond the clamps; keep the reading column.
- **Container queries:** the approved prototype places the whole SPA in a 390 px container on a 1440 stage. Therefore layout rules in the prototype use `@container` on `.device`. In the real app use viewport media queries, or `@container` on the app shell if embedded previews are ever needed. Never mix `vw` units inside a container-preview.
- **Safe areas:** bottom nav and reader footer use `padding-bottom: max(8px, env(safe-area-inset-bottom))`; sheets add the same inset.
- **Reader images:** `max-width:100%; height:auto`; reserve `aspect-ratio` from API width/height. No layout shift. Vertical mode page max width 780 px; horizontal mode fits one page to the smaller of available width and height.
- **Chapter list on mobile:** opens as a bottom sheet / drawer from the detail page; the row itself stays a 44 px target.
- **Sticky reader header:** in the approved prototype it stays pinned; a hide-on-scroll enhancement (after 24 px, reappears on scroll up) is optional, must keep controls reachable, and respects reduced motion.

### Density

- Section vertical rhythm: 48–64 px desktop, 32–40 px mobile.
- Card gaps: 12 px at 320–389, 16 px at 390–1023, 20 px at ≥1024.
- Panel padding: 16 mobile, 24 tablet, 28–32 desktop.
- Buttons in a group: 8–12 px gap; mobile primary actions stack full width at ≤ 359 if needed.
- Do not use more than two accent-filled controls in one viewport. Primary is singular.

---

## 8. Theme artwork rules (must follow)

The six images are atmospheric, not UI wallpaper. They are used with restraint.

### Allowed placements

| Placement | Rules |
|---|---|
| **Home hero** | One image in a dedicated art panel. Text lives on a solid `--surface` column, never over the image. On mobile the image becomes a 220–300 px banner above the copy. Mask the seam into `--bg`/`--surface`; apply `--hero-filter` and a scrim of at least 0.70 alpha at the edges. |
| **Auth** | A separate right-hand visual panel, or a 160–220 px banner on mobile. The form sits in a solid `--surface` card. The image never sits behind labels, inputs, buttons or validation copy. |
| **404 / empty state** | Large, low-opacity (12–18 %) image behind a **solid** message card, or a dedicated illustration panel next to the message. Never behind the body paragraph. |
| **Theme preview** | 64–96 px thumbnail inside theme switcher only. Not a page background. |

### Forbidden placements

- Body copy, headings, forms, settings, chapter lists, tables, modals, bottom sheets, toasts, tooltips.
- Reader chrome or reader controls. Reader *content* images are a different asset class and may fill the page; theme art is not reader content.
- Repeated as a page background or fixed/parallax background.
- Behind navigation, search results, library cards or footer.
- Anywhere the image competes with a poster/cover. One artwork per viewport is the limit.

### Composition and contrast

1. **Solid text column.** Text occupies a surface with no image underneath. On desktop, hero copy and art are separate grid columns; the mask starts after the copy column.
2. **Scrim.** Use `--hero-gradient` over the art. If any text ever sits on the image (allowed only for decorative labels such as a chapter number, never body copy), the local scrim must be ≥ 0.86 alpha plus 8–12 px blur, and the measured contrast must still be AA.
3. **Light theme.** `paper` uses the line-art image on `--surface-2` with `mix-blend-mode: multiply` or a paper-coloured scrim. Keep the vermilion accent from the drawing; do not invert it.
4. **Drop test.** Toggle the image off. If the hero still communicates and looks intentional, the composition is correct. If the image is carrying the hierarchy, redesign. If contrast drops below 4.5:1 for body or 3:1 for UI, remove the image.
5. **Crops.** Never crop a face in half or place a UI edge through a focal point. Use per-theme `object-position`:
   - midnight `38% 48%`; noir `64% 42%`; oni `58% 34%`; crimson `76% 40%`; sunset `34% 52%`; paper `62% 46%`.
6. **Mobile.** Art is a separate banner; the copy card starts below it. Do not use the art as a background behind the title to save vertical space.
7. **Motion.** No parallax, pan or Ken Burns on theme art. A one-time opacity crossfade ≤ 220 ms on theme switch is allowed.
8. **Semantics.** Decorative art uses `alt=""` and `aria-hidden="true"`; if rendered with CSS, keep it in a presentational element. It never carries meaning.
9. **Performance.** Serve 1600 px WebP (`midnight.webp` etc.) and the 24 px `-blur.webp` as the inline background placeholder. Hero image `fetchpriority="high"`, `decoding="async"`; everything below the fold `loading="lazy"`.
10. **Credit/signature.** Do not crop an artist signature if it is legible in the chosen crop; if the crop contains it, leave it visible and do not paint over it.
11. **No new AI images.** Only the six supplied artworks and their optimised derivatives.

### Image asset map

| Theme | Full | Blur placeholder | Intrinsic size |
|---|---|---|---|
| midnight | `themes/midnight.webp` | `themes/midnight-blur.webp` | 1600 × 768 |
| noir | `themes/noir.webp` | `themes/noir-blur.webp` | 1600 × 900 |
| oni | `themes/oni.webp` | `themes/oni-blur.webp` | 1365 × 740 |
| crimson | `themes/crimson.webp` | `themes/crimson-blur.webp` | 1600 × 900 |
| sunset | `themes/sunset.webp` | `themes/sunset-blur.webp` | 1600 × 900 |
| paper | `themes/paper.webp` | `themes/paper-blur.webp` | 1600 × 687 |

---

## 9. Components

Class names below are suggestions; behaviour and measurements are mandatory.

### 9.1 Buttons

| Variant | Background | Foreground | Border | Hover |
|---|---|---|---|---|
| Primary | `--accent` | `--on-accent` | transparent | `color-mix(in srgb, var(--accent) 88%, var(--text))` |
| Secondary | `--surface-2` | `--text` | 1 px `--border` | `--surface-3` |
| Ghost | transparent | `--muted` → `--text` | transparent | `--surface-2` |
| Danger | `--danger-soft` | `--danger-text` | 1 px `color-mix(in srgb, var(--danger) 38%, transparent)` | 18 % danger tint |
| Destructive | `--danger` | `--on-danger` | transparent | darken/lighten 6 % |

- Heights: `sm` 36 (dense desktop toolbars only, with a 44 px hit area), `md` 44, `lg` 52. Radius 8. Padding-inline: 14/18/24. Gap 8. Font 14 px / 600.
- States: rest, hover (pointer devices only), active (`translateY(1px)`), focus-visible (`outline: 2px solid var(--focus-ring); outline-offset: 2px`), disabled (opacity .45, no pointer), loading (spinner 16 px, label remains, width fixed).
- Icon-only: 44 × 44, radius 12 (or pill in toolbars); accessible name required. Icon 20 px, stroke 1.8.
- On touch, every button is at least 44 × 44 even if its visual height is 36. Never rely on hover.
- One primary action per region. In the reader, controls are icon-only and use ghost style on a dark surface.
- Buttons never contain links; use `<a class="btn">` for navigation.

### 9.2 Inputs, selects, textareas

- Height 44 (textarea min 120). Radius 8. Background `--surface-2`. Border 1 px `--border-strong`. Text `--text`; placeholder `--muted` at 0.8 opacity.
- Padding 12/14; optional leading icon 18 px, 10 px gap. Label above: 13 px/600, 6 px gap. Helper 12.5 px `--muted`; error 12.5 px `--danger-text`.
- Focus: border `--accent`, plus `box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 26%, transparent)` and the standard focus outline. Do not remove the outline.
- Error: border `--danger`, error icon, `aria-invalid="true"`, `aria-describedby` pointing at the message. Error is never colour-only.
- Disabled: `--surface`, `--muted`, cursor not-allowed.
- Search: leading magnifier, optional `kbd` hint `/`, clear button 44 px when non-empty. Full-width on mobile, 240–300 px in desktop header.
- Select: native element with custom chevron; use `appearance:none` but preserve keyboard behaviour; 44 px.
- Checkbox/radio: 20 px visual, 44 px target, 2 px `--border-strong` border, accent fill when checked with a white/ink check. Focus ring on the control.
- Switch: 44 × 24 track, 20 px thumb, 44 px target. Off = `--surface-3` + `--border-strong`; on = `--accent`; label is always visible.

### 9.3 Cards and panels

- Base card: `--surface`, 1 px `--border`, radius 14, `--shadow-sm`, padding 16/20/24.
- Panel: radius 22, padding 24/28, `--shadow-md` only when floating; otherwise no shadow.
- Hover (pointer only): translateY(-2px) and `--shadow-md`; 180 ms. Never move a card containing an input.
- Manga card: cover aspect-ratio 3/4, radius 14, overflow hidden; cover image `object-fit:cover`; bottom scrim `linear-gradient(180deg, transparent 38%, rgba(0,0,0,.86) 100%)`; title 15.5/1.25, meta 11.5 muted-on-dark. Badge top-left, save button top-right 36 (44 hit), rank optional. Progress bar 3 px at bottom for continue-reading cards.
- Card must have one clear primary link. A bookmark button is a **sibling** of the link, never nested inside it.
- Card headlines clamp to 2 lines. Do not hide the title on small screens.
- `noir`/`paper` use the serif display face only for titles ≥ 20 px; card titles stay sans for legibility.

### 9.4 Chips / tags

- Height 28–32 visual, pill, padding 0 10–12, font 12/600.
- Default: transparent or `--surface-2`, 1 px `--border`, `--muted`.
- Active/filter: `--accent-soft`, `--accent-text`, border `color-mix(in srgb, var(--accent) 42%, transparent)`.
- Removable: trailing × 16 px with 44 px hit area; `aria-label="Убрать фильтр …"`.
- Genre tags are links on detail pages, filters on catalogue. They must be keyboard-focusable and show a visible pressed state.

### 9.5 Tabs

- Underline tabs: 44 px height, label 14/600, `--muted`; active `--text` + 2 px `--accent` underline; focus ring.
- Segmented control: shell `--surface-2`, radius 10, 4 px padding; option 36–40 px, active `--surface` + `--text` + `--shadow-sm`.
- `role=tablist`; arrow keys move focus and activate; `aria-selected`; panels `role=tabpanel`.
- Home period tabs reorder the catalogue; library tabs switch continue/bookmarks/history. Tab state is not encoded by colour alone — active has weight + indicator.

### 9.6 Badges

- Height 20–22, radius pill, padding 0 8, font 11/700, uppercase, tracking .08em.
- Neutral (`--surface-2`/`--muted`), accent (`--accent-soft`/`--accent-text`), success, danger, warning. Use only for status: «Онгоинг», «Новое», «18+», «Прочитано», «Ошибка».
- Do not place a badge over a face/eyes; top-left corner of covers.
- Non-colour cue: dot/icon or text.

### 9.7 Skeletons

- Base `--surface-2`; shimmer `linear-gradient(90deg, transparent, color-mix(in srgb, var(--surface-3) 80%, var(--text) 4%), transparent)` moving 1.6 s; static under reduced motion.
- Shapes match final geometry exactly (cover 3/4, title 2 lines, meta 1 line, chip 32). Reserve space so no layout shift.
- Use a skeleton for initial catalogue load, next page and chapter list. Do not show more than 6 skeletons on mobile at once.
- A skeleton is `aria-busy="true"` on the region and hidden from screen readers.

### 9.8 Modal and bottom sheet

- Desktop modal: max-width 520 (wide 720), radius 22, padding 28, `--shadow-lg`, centred, backdrop `rgba(0,0,0,.62)` + `backdrop-filter: blur(6px)`.
- Mobile: bottom sheet, top radius 22, max-height 90dvh, drag handle 36 × 4 (decorative), padding 20 + safe-area bottom. It can be dismissed by backdrop, Escape, close button and drag (optional).
- Focus is trapped; first focusable gets focus; return focus to the trigger. `aria-modal="true"`, labelled by the title.
- Scroll lock on the app shell, not on `<body>` if the SPA is embedded.
- Headers/footers of sheets stay visible; body scrolls.
- Theme switcher, reader settings, chapter list and filters all use this component.

### 9.9 Toasts

- Bottom-centre above bottom nav / reader controls: `bottom: calc(var(--bottom-nav-h) + 16px + env(safe-area-inset-bottom))`; desktop 24 px.
- Max-width 420, radius 14, padding 12/14, `--surface-3`, 1 px border, `--shadow-lg`, icon + message + optional action.
- Types: success, error, info. Error lives 6 s; others 4 s. Dismiss on click/Enter. `aria-live="polite"` (assertive only for blocking errors).
- One toast at a time; queue beyond two. Do not use a toast for information required to complete a task.

### 9.10 Header

- Desktop 68 px: logo (32 px mark), primary nav (14 px, gap 24), search (240–300), theme button, notifications, avatar (36 visual / 44 target).
- Sticky, `background: color-mix(in srgb, var(--bg) 82%, transparent)`, `backdrop-filter: blur(18px)`, 1 px bottom border.
- Active nav: text `--text`, 2 px accent underline or 6 px dot; `aria-current="page"`.
- Tablet 64 px: condensed nav, search icon.
- Mobile 56 px: logo, search icon, theme, avatar. No hamburger for the four primary destinations — use bottom nav.
- Search `/` focus shortcut on desktop, Escape clears.
- The header never covers content; it is a flex sibling of the scroll region.

### 9.11 Bottom navigation

- Mobile only (< 1024 in production): 64 px + safe area, 4 items: Главная, Каталог, Библиотека, Профиль.
- Icon 22, label 10.5/600, gap 4. Active: `--accent-text`, filled icon variant, 3 px top indicator or 4 px dot; `aria-current="page"`.
- Background `color-mix(in srgb, var(--bg) 92%, transparent)` + border-top. No labels hidden.
- Profile opens a sheet if the account UI is not a full screen; it must not navigate to a blank tab.
- Reader and auth hide the bottom nav.

### 9.12 Reader controls

- Top bar 56 px: back, manga title (truncate 1 line) + chapter label, bookmark, settings, fullscreen. Background `rgba(5,5,5,.82)` + blur; 1 px white/8 border.
- Progress: 2 px accent line under the top bar; `role=progressbar` with `aria-valuenow`; page counter uses tabular numerals.
- Bottom bar 64 px + safe area: previous chapter, page navigation (`‹ 3 / 42 ›`), mode switch (vertical / horizontal), settings. Icon buttons 44; labels only on ≥ 768.
- Tap zones in horizontal mode: left 30 % previous, right 30 % next, centre 40 % toggles chrome. In vertical mode, tap centre toggles chrome; side taps do nothing.
- Swipe in horizontal mode: 48 px threshold, rubber-band at ends. Keyboard: ←/→ page or chapter boundary per spec, ↑/↓ scroll, F fullscreen, S settings, Escape closes sheet.
- Settings sheet: mode, fit (width/height/original), gap 0–32, auto-scroll switch, speed 10–100 (default 30), theme, page numbers. Changes apply live.
- Auto-scroll pauses on wheel, touch, key or sheet open; it never fights the user. Disabled with `prefers-reduced-motion`.
- Resume prompt: inline banner «Вы остановились на странице 7» + «Продолжить» / «С начала», not a blocking modal.
- Reader content is always dark (`#050505`) regardless of the theme; the accent and controls follow the active theme.

### 9.13 Chapter rows

- Height ≥ 56; grid: 44 px number badge / title + date / page count / actions. 1 px divider; hover `--surface-2`; current/read state uses a 2 px accent bar + muted title.
- Number badge: 32–36 circle, `--surface-2`, 13/700. Current: accent-soft + accent-text.
- New chapter: accent dot + «Новое» text, not colour alone.
- Download/export icon 44 target. Row opens the reader with the chapter.
- Mobile: 48–56 height, two lines (title + «Глава 12 · 18 стр. · 12 мин»), actions move under a kebab or stay as a 44 icon. The full list becomes a bottom sheet from the detail screen.
- Long titles wrap to 2 lines; never truncate the chapter number.

### 9.14 Pagination

- Page buttons 40 × 40 (44 target), radius 8, 13/600. Current: accent fill + on-accent. Disabled: muted, no shadow. Ellipsis is non-interactive.
- Mobile shows `‹  3 / 24  ›` plus current/next, not all page numbers.
- Changing page scrolls to the top of the results grid and updates `aria-live` count; no full-page reload.
- Keep pagination if SEO/export requires it; otherwise infinite scroll with a visible «Показать ещё» button, never only auto-load.

### 9.15 Theme switcher

- Header trigger: 44 px palette icon with a small dot in the current accent; `aria-haspopup="dialog"`, `aria-expanded`.
- Panel up to 660 px (desktop centred dialog; mobile bottom sheet). Title «Оформление», subtitle «Шесть настроений для чтения».
- 2 × 3 grid of options. Each option: 16:9 thumbnail (64–72 high) + palette dots + Russian label + short mood; selected = 2 px accent border + check.
- Selection applies immediately. Keyboard: arrows move, Enter/Space selects; Escape closes and returns focus.
- Show a one-line rule: «Иллюстрация используется только в hero и на входе».
- Persist `mp-theme`; never play a full-page ripple/flash.

### 9.16 Empty state / 404

- Centred card max 520, padding 32, radius 22, solid surface. Decorative glyph 64–96 (from the theme) + title 24–32 + one sentence + primary action + secondary link.
- Optional theme image allowed at 12–18 % opacity in a **separate** panel or behind the card, never behind the text itself.
- 404 copy: «Эта страница потерялась между главами». Action «Вернуться в каталог».
- Empty library: «Здесь пока тихо» + «Найти первую историю».
- Error states include a retry and a short human sentence; never dump a stack trace.

### 9.17 Auth

- Desktop: two columns, form surface 46 %, visual aside 54 %. Mobile: form full width; image may be a 160–220 px banner above the form or hidden entirely.
- Form card max 440, padding 32/40, radius 22, `--shadow-lg`. Heading 32–40, supporting line 15.5.
- Fields: email, password (show/hide 44), optional display name in register mode; inline validation on blur and submit, not on every keystroke.
- Primary button full width 48–52. Secondary link «Продолжить без аккаунта». Legal note 12.5 `--muted`.
- The visual aside uses the active theme image with a solid caption card; no input or label sits on the image.
- Loading state prevents double submit; error summary at top for screen readers.

---

## 10. Accessibility

### Contrast

- Body/UI text ≥ 4.5:1; large text (≥ 24 px regular or ≥ 18.66 px bold) ≥ 3:1; UI boundaries/focus indicators ≥ 3:1; icons that carry meaning ≥ 3:1.
- All shipped theme pairs are measured in §5. Re-measure after any change. Do not “eyeball” a new tint.
- Muted text is still text: `paper` muted on surface-2 is 4.98, the lowest allowed value; do not reduce opacity further.
- Disabled controls are exempt from contrast but must be clearly disabled and not the only way to access information.
- Do not encode status, selection or errors by colour alone. Add text, icon, underline, weight or shape.

### Focus and keyboard

- `:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }` on every interactive element, including cards and reader pages.
- Never `outline: none` without an equivalent visible replacement.
- Skip link «К содержанию» at the top of the app.
- Logical DOM order; no positive `tabindex`; `tabindex="-1"` only on the main landmark and dialog headings.
- Dialogs trap focus, close on Escape, restore focus to the trigger. Menus close on outside click and Escape.
- Tabs: arrow keys, Home/End. Reader: ←/→, ↑/↓, F, S, Escape. Search: `/` focus, Escape clear.
- On route change, move focus to the screen heading (`tabindex="-1"`) and announce the title; do not steal focus during reader scrolling.

### Touch and pointer

- Minimum 44 × 44 CSS px for every interactive target, with at least 8 px separation.
- Cards may be large targets, but their bookmark button must be a separate 44 px target.
- Do not use hover as the only affordance. Hover effects only under `@media (hover: hover) and (pointer: fine)`.
- Swipe gestures always have visible previous/next buttons as an alternative.

### Motion and reading

- Respect `prefers-reduced-motion`: disable auto-scroll, parallax, screen-slide animation, smooth scrolling and skeleton shimmer. Keep instant state changes.
- Reader auto-scroll is off by default and pauses on any interaction.
- Do not auto-play audio/video. Do not auto-advance chapters.
- Progress announcements are throttled: update visual progress continuously, announce page changes at most once per second.

### Semantics

- `<html lang="ru">`; landmarks: `header`, `nav`, `main`, `footer`.
- One `h1` per screen; headings in order. Buttons are `<button>`, navigation is `<a>`, tabs use `role=tablist`/`tab`/`tabpanel`.
- Icon-only buttons have `aria-label`; decorative icons `aria-hidden="true"`.
- Theme image `alt=""`; content images (posters, pages) have meaningful alt: «Обложка манги „Маска они“», «Страница 7 из 42».
- `aria-current="page"` on nav; `aria-pressed` on bookmark/auto-scroll; `aria-expanded` on disclosures.
- Forms have visible labels (not placeholder-only), `autocomplete` attributes, and error text linked with `aria-describedby`.
- Use `aria-live="polite"` for toasts, filter counts and reader page changes. Use `role="alert"` only for blocking errors.
- Respect 200 % zoom and 320 px reflow; no fixed heights on text containers.

### Colour vision

- Success/danger are paired with icons and words («Готово», «Ошибка»).
- Selected theme options use border + check + label, not only colour.
- Link text is underlined on hover/focus or has a visible icon; body links are distinguishable without colour.

---

## 11. Content rules

- Russian UI. Use «ё» consistently in copy. Titles may keep the author’s transliteration.
- Chapter labels: `Глава 42` + optional `Том 5`; dates as `12 нояб. 2026`; relative time `12 мин назад` for < 24 h, then absolute dates.
- Counts: `42 главы`, `1 глава`, `5 глав`; pages `18 стр.`; reading time `~12 мин`.
- Ratings: one decimal, `9,2` with a comma in Russian UI. Use tabular numerals.
- Buttons: sentence case, no trailing punctuation. Destructive actions name the object: «Удалить закладку».
- Error copy: what happened + what to do. No raw HTTP codes in the primary message; put the code in a secondary line if support needs it.
- Legal: «MangaPoisk не хранит чужие изображения и не обходит платный доступ. Источники подключаются по правилам каждой платформы.» Keep visible in the footer and sources screen.
- Adult content: `18+` badge + blur setting; never auto-reveal. Blur must be removable only by explicit action.

---

## 12. Frontend implementation notes

1. Put tokens in `src/styles/tokens.css` and the six blocks in `src/styles/themes.css`; import both once. Components must consume variables, never hex values.
2. Set `data-theme` on `<html>` before first paint. Read `localStorage.mp-theme`; fall back to `matchMedia('(prefers-color-scheme: light)')`.
3. Provide `useTheme()` / a tiny store; update `meta[name="theme-color"]` and persist when signed in. Do not couple theme to React Query.
4. Build primitives first: `Button`, `IconButton`, `Field`, `Card`, `Chip`, `Badge`, `Tabs`, `Sheet`, `Toast`, `Skeleton`, `EmptyState`. Use the measurements in §9.
5. Header and bottom nav are layout, not per-screen components. Reader and auth set an `immersive` shell state that hides them.
6. All covers use a wrapper with `aspect-ratio: 3 / 4` and an `<img>` with explicit width/height or the API aspect ratio. Add the blur placeholder as the wrapper background; image fades in on load.
7. Theme image usage is limited by a single `ThemeArtwork` component with `placement` restricted to `"hero" | "auth" | "empty"`. Code review should reject any other placement.
8. Container-query the prototype shell only. In the app, use media queries; if a screen is embedded, use `@container`.
9. Test with `prefers-reduced-motion`, forced colours (Windows high contrast), 200 % zoom, keyboard only, and at 320, 390, 768, 1024, 1440, 1920.
10. The design audit after implementation will check: 390×844 and 1440×900, all six themes, no image behind body copy, all text ratios, focus visibility and 44 px targets.

---

## 13. Prototype reference

Open `design/prototype/index.html` directly in a browser — no build, no network, no external fonts. Images are copied into `design/prototype/themes/`.

Controls:

- **Device:** the studio panel (bottom-left) switches between a 390 × 844 phone frame and full desktop canvas. Use it at 1440×900 to inspect the phone layout without resizing the window.
- **Theme:** palette button in the header, or the swatches in the studio panel. Six themes, live switching, persisted where `localStorage` permits.
- **Screens:** Главная → hero/catalogue; cards → detail; «Читать» / chapter row → reader; Библиотека; profile → login; Источники.
- **Reader:** vertical/horizontal toggle, fit, gap, auto-scroll, page counter, chapter navigation, keyboard (`←` `→` `F` `S` `Esc`).
- **Auth:** any valid email + ≥ 6 characters; inline errors are shown for invalid input.

The prototype is a design reference, not production code. Copy behaviour, measurements and tokens — not the one-file JavaScript architecture.
