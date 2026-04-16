# Vystak Visual Refresh — Design Spec

## Goal

Replace the default Docusaurus look of the Vystak documentation site with a custom HashiCorp/Stripe-inspired design system: emerald primary, Inter typography, split hero with live code, three-column docs layout, and tabbed multi-language code blocks.

## Decisions captured during brainstorming

| Area | Choice |
|------|--------|
| Primary color | Emerald `#10b981` |
| Body & heading font | Inter |
| Code font | JetBrains Mono |
| Hero style | Split — copy + CTA left, live code right |
| Landing sections | Hero + code showcase only |
| Navbar | Categorized: Docs · Examples · Blog · Pricing + PyPI · npm · GitHub · ⌘K · Theme toggle |
| Docs layout | Three columns: sidebar | content | on-this-page TOC |
| Code blocks | Tabbed groups for multi-language; single-language uses header-bar style |

## Color palette

### Light mode

| Token | Hex | Use |
|-------|-----|-----|
| `--ifm-color-primary` | `#10b981` | Buttons, links, active sidebar items |
| `--ifm-color-primary-dark` | `#059669` | Hover states |
| `--ifm-color-primary-darker` | `#047857` | Pressed states |
| `--ifm-color-primary-darkest` | `#065f46` | High-contrast accents |
| `--ifm-color-primary-light` | `#34d399` | Light accents |
| `--ifm-color-primary-lighter` | `#6ee7b7` | Backgrounds |
| `--ifm-color-primary-lightest` | `#a7f3d0` | Soft surfaces |
| `--ifm-background-color` | `#ffffff` | Page background |
| `--ifm-background-surface-color` | `#f8fafc` | Card/code background |
| `--ifm-color-content` | `#0f172a` | Body text |
| `--ifm-color-content-secondary` | `#64748b` | Muted text |
| `--ifm-color-emphasis-300` | `#e2e8f0` | Borders, dividers |

### Dark mode

| Token | Hex | Use |
|-------|-----|-----|
| `--ifm-color-primary` | `#34d399` | Same role; lighter for legibility on dark |
| `--ifm-color-primary-dark` | `#10b981` | |
| `--ifm-color-primary-darker` | `#059669` | |
| `--ifm-color-primary-darkest` | `#047857` | |
| `--ifm-color-primary-light` | `#6ee7b7` | |
| `--ifm-color-primary-lighter` | `#a7f3d0` | |
| `--ifm-color-primary-lightest` | `#d1fae5` | |
| `--ifm-background-color` | `#020617` | Page background |
| `--ifm-background-surface-color` | `#0f172a` | Card/code background |
| `--ifm-color-content` | `#e2e8f0` | Body text |
| `--ifm-color-content-secondary` | `#94a3b8` | Muted text |
| `--ifm-color-emphasis-300` | `#1e293b` | Borders, dividers |

## Typography

- **Body & headings:** Inter, loaded from Google Fonts via Docusaurus `headTags` config (variable weight 100–900).
- **Code:** JetBrains Mono, loaded the same way (variable weight 100–800).
- **Heading scale (h1–h6):** Inter at 700 weight, tightened letter-spacing (`-0.025em` for h1/h2, `-0.02em` for h3/h4).
- **Body line-height:** 1.65 (slightly more open than Docusaurus default of 1.5 for readability).
- **Body size:** 16px (default), 15px in code blocks.

## Hero (`website/src/pages/index.js`)

Replace the current centered hero with a split two-column layout. New file `website/src/components/Hero/index.js`:

- **Left column:** Vystak title (Inter 700, ~48px), tagline (Inter 400, ~18px, secondary color), description paragraph (~16px), two CTA buttons: primary "Get Started" (emerald solid) and ghost "View on GitHub".
- **Right column:** A code window with a fake macOS-style header bar, showing a `vystak.yaml` snippet with syntax highlighting. Uses Prism for highlighting at build time, not at runtime.
- **Background:** light, with a thin (`3px`) emerald top border on the section.
- **Responsive:** stacks to single column below 996px (Docusaurus's standard tablet breakpoint).

## Code showcase (`website/src/components/CodeShowcase/index.js`)

Section below the hero. A single tabbed code block showing the same agent in YAML and Python:

- Two tabs: "YAML" (default) and "Python"
- Tabs styled with emerald underline indicator on the active tab
- Code surface uses the dark theme (`#0f172a` background, syntax highlighted)
- Section heading: "Define once. Deploy anywhere."
- Section subhead: "The same agent, in YAML or Python."

## Top navigation (`website/docusaurus.config.js`)

Update `themeConfig.navbar.items`:

```js
navbar: {
  title: 'Vystak',
  logo: { alt: 'Vystak', src: 'img/logo.svg' },
  items: [
    { type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'Docs' },
    { to: '/docs/examples/overview', label: 'Examples', position: 'left' },
    { to: '/blog', label: 'Blog', position: 'left' },
    { to: '/pricing', label: 'Pricing', position: 'left' },
    {
      type: 'search',
      position: 'right',
    },
    {
      href: 'https://pypi.org/project/vystak/',
      label: 'PyPI',
      position: 'right',
    },
    {
      href: 'https://www.npmjs.com/package/@vystak/core',
      label: 'npm',
      position: 'right',
    },
    {
      href: 'https://github.com/vystak/AgentsStack',
      label: 'GitHub',
      position: 'right',
    },
  ],
},
```

- **Search**: Docusaurus's built-in search slot. Algolia integration is out of scope for this phase — leave the slot present so we can wire it up later. Until Algolia is configured, `type: 'search'` renders a no-op input that does nothing. To avoid a broken-looking search box, omit the search item until Algolia is configured. **Decision: omit `type: 'search'` for this phase.** Add a follow-up note to enable Algolia later.
- **Blog & Pricing pages**: Docusaurus `onBrokenLinks: 'throw'` will fail the build if these pages don't exist. Create minimal placeholder pages at `website/src/pages/blog.md` and `website/src/pages/pricing.md` saying "Coming soon" so the build stays green.

## Docs page layout (three columns)

Docusaurus Classic preset already supports the three-column layout (sidebar, content, on-this-page TOC). The on-this-page TOC is enabled per-page via the doc preset's `showLastUpdateTime` and `tableOfContents` defaults — already on by default.

What we need to style (in `custom.css`):

- **Sidebar** — emerald accent bar (3px) on the active item, thinner padding, slightly reduced font size (14px), uppercase category labels.
- **Content** — max-width 720px, generous bottom padding, larger headings.
- **On-this-page TOC** — emerald left-border on the active heading link, smaller font (13px), muted unselected items.

No new React components needed for the docs layout — just CSS.

## Code blocks

### Tabbed multi-language groups

Docusaurus has a built-in `Tabs` MDX component. For multi-language examples, wrap them in tabs:

```mdx
<Tabs>
  <TabItem value="yaml" label="YAML" default>
    ```yaml
    name: hello-bot
    ...
    ```
  </TabItem>
  <TabItem value="python" label="Python">
    ```python
    import vystak
    ...
    ```
  </TabItem>
</Tabs>
```

Add to `custom.css`: emerald underline on active tab, restyle the tab list border.

### Single-language blocks

Default Docusaurus code blocks already have a copy button. We add:

- Header bar at the top of every code block showing the language label
- Slightly more rounded corners (8px)
- Subtle border in light mode

This is achieved via CSS — no swizzling required.

## Files to create / modify

| File | Action | Purpose |
|------|--------|---------|
| `website/docusaurus.config.js` | Modify | Add Google Fonts headTags, update navbar items |
| `website/src/css/custom.css` | Replace | Full redesign per palette + components |
| `website/src/components/Hero/index.js` | Create | Split hero component |
| `website/src/components/Hero/styles.module.css` | Create | Hero styles |
| `website/src/components/CodeShowcase/index.js` | Create | Tabbed YAML/Python showcase |
| `website/src/components/CodeShowcase/styles.module.css` | Create | Showcase styles |
| `website/src/pages/index.js` | Modify | Use new Hero + CodeShowcase, drop old HomepageFeatures |
| `website/src/pages/blog.md` | Create | "Coming soon" placeholder |
| `website/src/pages/pricing.md` | Create | "Coming soon" placeholder |
| `website/src/components/HomepageFeatures/` | Delete | Replaced by CodeShowcase |

## Definition of done

- `just docs-build` succeeds with zero broken-link or markdown warnings.
- `just docs-dev` renders correctly in light and dark mode.
- Hero shows split layout on desktop, stacks to single column at <996px.
- Navbar shows Docs · Examples · Blog · Pricing on the left, PyPI · npm · GitHub · theme toggle on the right.
- Code showcase shows YAML/Python tabs with emerald active indicator.
- Sidebar shows emerald accent on the active page.
- Three-column docs layout: sidebar | content | on-this-page TOC, with TOC visible on `/docs/concepts/agents`.
- Inter loads correctly (no FOUT, no fallback to system font visible).

## Out of scope

- Algolia / DocSearch integration (deferred — note added to PROJECT_PLAN follow-ups)
- Real Blog content (placeholder only)
- Real Pricing page (placeholder only)
- Custom 404 page
- Custom illustrations / marketing graphics
- Sidebar mega-menu in navbar
- Provider logo row, "How it works" section, bottom CTA panel (rejected during brainstorming)
- Light/dark theme switcher icon redesign
