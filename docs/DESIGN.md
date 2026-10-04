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
