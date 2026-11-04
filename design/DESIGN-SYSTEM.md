# Git Canvas design system

Everything in `index.html` draws from the tokens at the top of its `<style>` block. Change a token, not a number.

## Grid (Figma-style 8pt grid, 4pt sub-step)
| Token | Value | Used for |
|---|---|---|
| `--s1` `--s2` `--s3` `--s4` `--s5` `--s6` `--s7` | 4 · 8 · 12 · 16 · 24 · 32 · 48 | every gap and padding |
| `--edge` | 16 | margin between floating UI and the screen edge |
| `--bar` | 56 | height of the top-left card, dock and zoom bar (40 control + 2 x 8) |
| `--c` / `--c-sm` | 40 / 32 | control height (buttons, inputs, list rows) / compact control (segmented, chips' parent) |

Canvas sizes are multiples of 8 and cards **snap to 8px when dragged**: commit card 256x128, branch title 256x128, PR card 256x120, column pitch 320 (64 gutter), row pitch 160 (32 gap), title-to-content gap 24. The dot grid is 32px.

## Typography: 4 sizes in the app (plus 1 display size on the front page), 3 weights
| Token | Font | Use |
|---|---|---|
| `--t-heading` | 700 20/28 | inspector title, big numbers |
| `--t-title` | 600 16/24 (700 for branch names) | commit messages, branch names, popover titles |
| `--t-label` | 600 14/20 | buttons, rows, field labels |
| `--t-body` | 400 14/20 | running text, inputs |
| `--t-caption` | 400 12/16 | dates, authors, helper text |
| `--t-caption-strong` | 600 12/16 | chips, badges, pills |
| `--t-overline` | 700 12/16, uppercase, +6% tracking | section labels, MERGE / SPLIT / NEW |
| `--t-display` | 700 32/40 | the front-page headline only |
| `--t-code` / `--t-code-strong` | 400 / 600 12/16 mono | hashes, file names, commands |

Never set `font-size` or `font-weight` directly; use `font: var(--t-...)`.

## Radius, elevation, color
- Radius: `--r1` 8 (rows, inner buttons) · `--r2` 12 (controls, cards, callouts) · `--r3` 16 (panels, bars, branch titles) · `--pill`.
- Elevation: `--e1` cards · `--e2` floating panels · `--e3` hover / drag.
- Color: the main line is green (`#15803d`). Every other branch gets its own hue from one **tonal step (Tailwind 700)** so they read as a family: violet `#6d28d9`, orange `#c2410c`, cyan `#0e7490`, pink `#be185d`, teal `#0f766e`, fuchsia `#a21caf`, slate `#475569`, sky `#0369a1` (white text is at least 5:1 on all). Card backgrounds are a 14% tint of the same color. Red / amber / green are reserved for conflict / warning / OK, and the UI accent is indigo `#4f46e5`. Everything else is neutral (`--ink`, `--ink-2`, `--muted`, `--faint`, `--line`, `--fill`).

## Icons
One stroke set (Lucide-style, 24px grid, 2px stroke, round caps) in an inline SVG sprite. Use `ico('name')` in JS or `<svg class="i"><use href="#i-name"/></svg>` in HTML. Sizes: `.xs` 12 (inside chips) · default 16 (buttons, rows) · `.lg` 20 (icon-only buttons). Colour comes from `currentColor`. No emoji or text glyphs as icons.

Available: branch, pr, filter, refresh, unfold, fold, fit, tidy, plus, minus, help, x, check, chevron-down, chevron-up, alert, clock, tag, github, folder, copy, external, arrow-up, arrow-down, dots.
