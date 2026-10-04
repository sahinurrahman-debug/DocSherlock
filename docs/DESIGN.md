# DocSherlock design system

Goal: calm, humane and trustworthy - a lamplit study rather than a control room. Everything lives in `frontend/src/index.css` as tokens, so components never hard-code colours.
A style board for this direction was generated in Canva: https://canva.link/x54p7aqa7v9hj1b

## Colour
One accent (teal) for actions, one decorative lamp-amber, and four status hues that only ever carry meaning. No pure black/white, no default browser blue.

| Token | Light (warm paper) | Dark (warm forest-charcoal) | Use |
|---|---|---|---|
| `bg` / `surface` / `surface-2` | `#f7f2e9` / `#fffdf8` / `#f1ebdf` | `#161917` / `#1d211f` / `#252a27` | page, cards, raised areas |
| `ink` / `muted` / `line` | `#2a2620` / `#6a6356` / `#e3dacb` | `#ece6da` / `#aaa496` / `#343a36` | text, secondary text, borders |
| `brand` | `#1f6f68` | `#86c9bb` | primary actions, links, focus |
| `lamp` | `#c98a2b` | `#e3b05f` | logo handle, illustration accents, ambient glow |
| `ok` | `#29703f` | `#93cfa2` | sources agree / high confidence |
| `warn` | `#86560f` | `#e5b872` | caution / medium confidence |
| `bad` | `#a4452a` | `#ee9879` | conflict / low confidence |
| `none` | `#666072` | `#b8b0c8` | unknown / not found |

Every text/background pair used was checked against WCAG AA (4.5:1) in both themes. Colour is never the only signal: statuses also carry an icon and a label.

## Type
Two families: **Fraunces** (warm serif) for headings and key figures, **Inter** for everything else. Body 16px / line-height 1.6, answer text 17px / 2rem, nothing smaller than 13px (labels and chips).

## Space, shape, depth
Generous padding (cards 20-28px), 16px card radius, 12px controls, soft warm-tinted shadows. Touch targets are at least 40px (32px for compact buttons).

## Motion
Short and purposeful: content rises in (350-500ms, staggered by 70ms), theme changes cross-fade, buttons press in 2%, the thinking indicator breathes. Animations use opacity/transform only
and are switched off entirely under `prefers-reduced-motion`.

## States
* **Empty:** `EmptyState` + line illustrations (`illustrations.tsx`) with a headline, one line of help and the next action - never a bare "No data".
* **Loading:** `Skeleton` shimmer placeholders (stats, document list, conflicts, comparison, source page); status text for long jobs (processing stepper, "thinking" stages).
* **Theme:** light and dark, following the OS until the user chooses; a script in `index.html` applies it before first paint so there is no flash.

## Logo
One mark, one lockup, everywhere: a lens over a plus sign on a rounded teal tile with an amber handle, beside a serif "DocSherlock" wordmark.
* In the app it is always `<Logo />` (`components/Logo.tsx`; sizes `md` and `lg`, optional tagline). Nothing else may draw its own mark - a test fails if another source file contains the geometry or imports the bare `LogoMark`.
* Outside the app (favicon, README, PDF evidence-pack cover, `apple-touch-icon.png`) the same shape comes from one file, `frontend/public/favicon.svg`. Its light colours are plain attributes (so every renderer honours them) and its dark-mode colours sit in a `prefers-color-scheme` rule; a test checks that its geometry equals the React mark and that its colours equal the design tokens.
* The README heading is `frontend/public/logo-lockup.svg`: the same mark and the wordmark placed together in one image, so the logo and title are aligned and left-aligned in any Markdown renderer (HTML alignment attributes are not reliable across them). It has a dark-mode variant and a test keeps it identical to the mark.
* The tile and handle follow the theme tokens (`brand`, `brand-ink`, `lamp`), so the mark is teal in light mode and soft sage in dark mode.

## Header
One row of three equal-weight zones from 1024 px (logo | navigation | controls), so the navigation is centred on the page; below that the logo and controls share the first row and the navigation sits full width underneath, with four equal links.
* Every control is **40 px tall** with the same radius, border and hover style (the navigation track, the status control, the engine selector, the theme toggle), and everything sits on one centre line.
* The four status badges became **one status control** ("Ready", "Limited" or "Degraded", with a dot). It opens a small panel with the answer engine, database, vector store, search mode and OCR; on screens narrower than 1280 px the engine selector lives in that panel instead of crowding the bar.
* The navigation is a segmented track that shrinks below the width of its links (`min-w-0`) so it can scroll inside itself rather than stretching the page. Tests assert the shared height and shape, the grid, and the shrink rule; measurements at 1280, 1024, 768 and 375 px showed a centring offset of 0 and equal side margins.
