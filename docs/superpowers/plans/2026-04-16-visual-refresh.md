# Vystak Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the Emerald + Inter design system to the Vystak Docusaurus site: split hero with live code, tabbed code showcase, three-column docs layout, categorized navbar with PyPI/npm/GitHub links.

**Architecture:** Pure frontend changes inside `website/`. Replace `custom.css` with the new design tokens. Add two React components (`Hero`, `CodeShowcase`). Update `docusaurus.config.js` (navbar items, Google Fonts). Add placeholder Blog/Pricing pages so the strict link checker stays green.

**Tech Stack:** Docusaurus 3.6, React 18, CSS modules, Inter + JetBrains Mono via Google Fonts.

---

## Critical context for the engineer

Read this before starting any task.

### Working directory and branch

- **Repo root:** `~/Developer/work/AgentsStack`
- **Branch:** create `feat/docs-visual-refresh` from `main` before Task 1
- All paths are relative to the repo root.

### Verify after each task

Every task ends with running `just docs-build` from the repo root. The build must succeed with no broken-link warnings (Docusaurus is configured with `onBrokenLinks: 'throw'`). Commit only after the build is clean.

For visual changes, also run `just docs-dev` and inspect the result at `http://localhost:3000/AgentsStack/`. Stop the dev server (Ctrl+C) before continuing.

### Color palette reference (single source of truth)

Tasks reference these tokens — copy from this table verbatim into the code, don't re-derive:

| CSS variable | Light value | Dark value |
|---|---|---|
| `--ifm-color-primary` | `#10b981` | `#34d399` |
| `--ifm-color-primary-dark` | `#059669` | `#10b981` |
| `--ifm-color-primary-darker` | `#047857` | `#059669` |
| `--ifm-color-primary-darkest` | `#065f46` | `#047857` |
| `--ifm-color-primary-light` | `#34d399` | `#6ee7b7` |
| `--ifm-color-primary-lighter` | `#6ee7b7` | `#a7f3d0` |
| `--ifm-color-primary-lightest` | `#a7f3d0` | `#d1fae5` |
| `--ifm-background-color` | `#ffffff` | `#020617` |
| `--ifm-background-surface-color` | `#f8fafc` | `#0f172a` |
| `--ifm-color-content` | `#0f172a` | `#e2e8f0` |
| `--ifm-color-content-secondary` | `#64748b` | `#94a3b8` |
| `--ifm-color-emphasis-300` | `#e2e8f0` | `#1e293b` |

### Where the placeholder pages live

Docusaurus serves `website/src/pages/*.{js,md,mdx}` at the matching URL. So `website/src/pages/blog.md` becomes `/blog`. We need both `blog.md` and `pricing.md` so the navbar links don't break the build.

---

## Task list

7 tasks. Do them in order — each builds on the previous.

---

### Task 1: Setup branch + base CSS variables

**Files:**
- Create branch `feat/docs-visual-refresh`
- Replace: `website/src/css/custom.css`

**Goal:** Apply the new color palette and typography. This single CSS change should already make the existing pages look different (emerald primary instead of blue).

- [ ] **Step 1: Create branch from main**

```bash
cd ~/Developer/work/AgentsStack
git checkout main && git pull --ff-only origin main 2>/dev/null || true
git checkout -b feat/docs-visual-refresh
```

(The `git pull` is a no-op if there's no remote; the `|| true` keeps the script alive.)

- [ ] **Step 2: Replace `website/src/css/custom.css` with the full design system**

```css
/**
 * Vystak custom theme — Emerald + Inter design system.
 * See docs/superpowers/specs/2026-04-16-visual-refresh-design.md
 */

/* Light mode (default) */
:root {
  /* Emerald primary scale */
  --ifm-color-primary: #10b981;
  --ifm-color-primary-dark: #059669;
  --ifm-color-primary-darker: #047857;
  --ifm-color-primary-darkest: #065f46;
  --ifm-color-primary-light: #34d399;
  --ifm-color-primary-lighter: #6ee7b7;
  --ifm-color-primary-lightest: #a7f3d0;

  /* Surfaces */
  --ifm-background-color: #ffffff;
  --ifm-background-surface-color: #f8fafc;

  /* Text */
  --ifm-color-content: #0f172a;
  --ifm-color-content-secondary: #64748b;

  /* Borders / dividers */
  --ifm-color-emphasis-300: #e2e8f0;

  /* Typography */
  --ifm-font-family-base: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --ifm-font-family-monospace: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  --ifm-heading-font-weight: 700;
  --ifm-line-height-base: 1.65;
  --ifm-h1-font-size: 2.75rem;
  --ifm-h2-font-size: 2rem;
  --ifm-h3-font-size: 1.5rem;
  --ifm-code-font-size: 93%;

  /* Code highlighting */
  --docusaurus-highlighted-code-line-bg: rgba(16, 185, 129, 0.12);
}

/* Dark mode */
[data-theme='dark'] {
  --ifm-color-primary: #34d399;
  --ifm-color-primary-dark: #10b981;
  --ifm-color-primary-darker: #059669;
  --ifm-color-primary-darkest: #047857;
  --ifm-color-primary-light: #6ee7b7;
  --ifm-color-primary-lighter: #a7f3d0;
  --ifm-color-primary-lightest: #d1fae5;

  --ifm-background-color: #020617;
  --ifm-background-surface-color: #0f172a;

  --ifm-color-content: #e2e8f0;
  --ifm-color-content-secondary: #94a3b8;

  --ifm-color-emphasis-300: #1e293b;

  --docusaurus-highlighted-code-line-bg: rgba(52, 211, 153, 0.15);
}

/* Tighten heading letter-spacing */
h1, h2 {
  letter-spacing: -0.025em;
}
h3, h4 {
  letter-spacing: -0.02em;
}

/* Sidebar — emerald accent on active item */
.menu__link--active {
  border-left: 3px solid var(--ifm-color-primary);
  padding-left: calc(var(--ifm-menu-link-padding-horizontal) - 3px);
}

/* Sidebar category labels — uppercase + tight */
.menu__list .menu__list-item-collapsible .menu__link {
  font-weight: 600;
}

/* Tabs — emerald active indicator */
.tabs__item--active {
  border-bottom-color: var(--ifm-color-primary);
  color: var(--ifm-color-primary);
}

/* Code blocks — slightly more rounded, subtle border in light mode */
.theme-code-block {
  border-radius: 8px;
  border: 1px solid var(--ifm-color-emphasis-300);
}
[data-theme='dark'] .theme-code-block {
  border-color: transparent;
}

/* On-this-page TOC — emerald left-border on active heading */
.table-of-contents__link--active {
  color: var(--ifm-color-primary);
  font-weight: 600;
}

/* Navbar — thin border-bottom, no shadow */
.navbar {
  box-shadow: none;
  border-bottom: 1px solid var(--ifm-color-emphasis-300);
}
```

- [ ] **Step 3: Build and verify**

```bash
just docs-build
```

Expected: clean build (warnings about `headTags` being missing for fonts are normal — we add fonts in Task 2).

- [ ] **Step 4: Visual spot-check**

```bash
just docs-dev
```

Open `http://localhost:3000/AgentsStack/`. Verify the primary color shifted from blue to green. Verify the active sidebar item has a green accent. Stop the server (Ctrl+C).

- [ ] **Step 5: Commit**

```bash
git add website/src/css/custom.css
git commit -m "feat(docs): apply Emerald + Inter design tokens to custom.css"
```

---

### Task 2: Load Inter and JetBrains Mono via Google Fonts

**Files:**
- Modify: `website/docusaurus.config.js`

**Goal:** Add the two font families so the typography from Task 1 actually renders (right now they're falling back to system-ui).

- [ ] **Step 1: Add `headTags` to `website/docusaurus.config.js`**

Add a `headTags` array right after the `i18n` block (before `presets`). The new block goes between lines 23 and 25 of the current file. Insert this block:

```javascript
  headTags: [
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    },
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    },
    {
      tagName: 'link',
      attributes: {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap',
      },
    },
  ],
```

The complete file should look like this around the change:

```javascript
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  headTags: [
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
    },
    {
      tagName: 'link',
      attributes: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: 'anonymous' },
    },
    {
      tagName: 'link',
      attributes: {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap',
      },
    },
  ],

  presets: [
    ...
```

- [ ] **Step 2: Build**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 3: Visual spot-check**

```bash
just docs-dev
```

Open `http://localhost:3000/AgentsStack/`. The body and headings should now be Inter (look at the lowercase 'a' — Inter has a distinctive single-story 'a'). Code blocks should render in JetBrains Mono. Stop the server.

- [ ] **Step 4: Commit**

```bash
git add website/docusaurus.config.js
git commit -m "feat(docs): load Inter and JetBrains Mono via Google Fonts"
```

---

### Task 3: Update navbar items (Docs, Examples, Blog, Pricing + PyPI, npm, GitHub)

**Files:**
- Modify: `website/docusaurus.config.js`
- Create: `website/src/pages/blog.md`
- Create: `website/src/pages/pricing.md`

**Goal:** Replace the minimal navbar with the categorized layout. Add placeholder Blog and Pricing pages so the strict link-checker doesn't fail the build.

- [ ] **Step 1: Create `website/src/pages/blog.md`**

```markdown
---
title: Blog
description: Vystak blog — coming soon.
---

# Blog

The Vystak blog is coming soon. In the meantime, follow updates on [GitHub](https://github.com/vystak/AgentsStack).
```

- [ ] **Step 2: Create `website/src/pages/pricing.md`**

```markdown
---
title: Pricing
description: Vystak is free and open source.
---

# Pricing

Vystak is free and open source under the Apache 2.0 license.

A managed cloud offering with team features (remote state, dashboards, RBAC, replay testing) is in the planning stage. [Sign up for updates on GitHub](https://github.com/vystak/AgentsStack).
```

- [ ] **Step 3: Replace the `navbar.items` array in `website/docusaurus.config.js`**

In `website/docusaurus.config.js`, find the `navbar.items` array (currently lines 51-63) and replace it with:

```javascript
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/docs/examples/overview',
            label: 'Examples',
            position: 'left',
          },
          {
            to: '/blog',
            label: 'Blog',
            position: 'left',
          },
          {
            to: '/pricing',
            label: 'Pricing',
            position: 'left',
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
```

- [ ] **Step 4: Build and verify**

```bash
just docs-build
```

Expected: clean build (no broken-link errors, since `/blog` and `/pricing` now exist).

- [ ] **Step 5: Visual spot-check**

```bash
just docs-dev
```

Open `http://localhost:3000/AgentsStack/`. The navbar should show **Docs · Examples · Blog · Pricing** on the left and **PyPI · npm · GitHub · ☼/☾** on the right. Click each navbar item to verify they all navigate. Stop the server.

- [ ] **Step 6: Commit**

```bash
git add website/docusaurus.config.js website/src/pages/blog.md website/src/pages/pricing.md
git commit -m "feat(docs): categorized navbar with PyPI, npm, GitHub links"
```

---

### Task 4: Build the Hero component (split layout: copy left, code right)

**Files:**
- Create: `website/src/components/Hero/index.js`
- Create: `website/src/components/Hero/styles.module.css`

**Goal:** A reusable `<Hero />` React component that renders the new split-hero layout. Doesn't change the homepage yet — that's Task 6.

- [ ] **Step 1: Create `website/src/components/Hero/index.js`**

```javascript
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import CodeBlock from '@theme/CodeBlock';
import styles from './styles.module.css';

const HERO_YAML = `name: hello-bot
instructions: You are a friendly assistant.
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider: { name: docker, type: docker }
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
`;

export default function Hero() {
  return (
    <header className={styles.hero}>
      <div className="container">
        <div className={styles.grid}>
          <div className={styles.copy}>
            <h1 className={styles.title}>Vystak</h1>
            <p className={styles.tagline}>Declarative AI agent orchestration</p>
            <p className={styles.description}>
              Define your agent once. Deploy to Docker, Azure Container Apps, or
              any platform — from a single command.
            </p>
            <div className={styles.actions}>
              <Link
                className={clsx('button button--primary button--lg', styles.cta)}
                to="/docs/getting-started/intro">
                Get Started →
              </Link>
              <Link
                className={clsx('button button--secondary button--lg', styles.ghost)}
                to="https://github.com/vystak/AgentsStack">
                View on GitHub
              </Link>
            </div>
          </div>
          <div className={styles.codePane}>
            <div className={styles.codeWindow}>
              <div className={styles.codeWindowHeader}>
                <span className={styles.dot} style={{background: '#ef4444'}}></span>
                <span className={styles.dot} style={{background: '#f59e0b'}}></span>
                <span className={styles.dot} style={{background: '#10b981'}}></span>
                <span className={styles.codeWindowTitle}>vystak.yaml</span>
              </div>
              <CodeBlock language="yaml" className={styles.codeBlock}>
                {HERO_YAML}
              </CodeBlock>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Create `website/src/components/Hero/styles.module.css`**

```css
.hero {
  padding: 5rem 0 4rem;
  border-top: 3px solid var(--ifm-color-primary);
  background: var(--ifm-background-color);
  overflow: hidden;
}

.grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3rem;
  align-items: center;
}

@media (max-width: 996px) {
  .grid {
    grid-template-columns: 1fr;
    gap: 2rem;
  }
  .hero {
    padding: 3rem 0 2.5rem;
  }
}

.copy {
  max-width: 560px;
}

.title {
  font-size: 4rem;
  font-weight: 800;
  letter-spacing: -0.04em;
  margin-bottom: 0.5rem;
  line-height: 1;
}

@media (max-width: 996px) {
  .title {
    font-size: 3rem;
  }
}

.tagline {
  font-size: 1.5rem;
  color: var(--ifm-color-primary);
  font-weight: 600;
  margin-bottom: 1.25rem;
  letter-spacing: -0.02em;
}

.description {
  font-size: 1.125rem;
  color: var(--ifm-color-content-secondary);
  line-height: 1.6;
  margin-bottom: 2rem;
}

.actions {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.cta,
.ghost {
  text-decoration: none;
}

.codePane {
  display: flex;
  justify-content: flex-end;
}

.codeWindow {
  width: 100%;
  max-width: 560px;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 20px 60px -20px rgba(15, 23, 42, 0.4),
              0 8px 24px -8px rgba(15, 23, 42, 0.2);
  border: 1px solid var(--ifm-color-emphasis-300);
}

.codeWindowHeader {
  background: #1e293b;
  padding: 0.625rem 0.875rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}

.codeWindowTitle {
  margin-left: 0.75rem;
  color: #94a3b8;
  font-family: var(--ifm-font-family-monospace);
  font-size: 0.8125rem;
}

/* Reset Docusaurus default code-block padding inside our window */
.codeBlock {
  margin: 0 !important;
  border-radius: 0 !important;
  border: none !important;
}
```

- [ ] **Step 3: Build**

```bash
just docs-build
```

Expected: clean build. The Hero component isn't used yet (we use it in Task 6), but the import-resolution and CSS-module compilation should succeed.

- [ ] **Step 4: Commit**

```bash
git add website/src/components/Hero/
git commit -m "feat(docs): add Hero component (split layout with live YAML)"
```

---

### Task 5: Build the CodeShowcase component (tabbed YAML/Python)

**Files:**
- Create: `website/src/components/CodeShowcase/index.js`
- Create: `website/src/components/CodeShowcase/styles.module.css`

**Goal:** A section component that shows the same agent in YAML and Python via Docusaurus's built-in `Tabs` UI.

- [ ] **Step 1: Create `website/src/components/CodeShowcase/index.js`**

```javascript
import CodeBlock from '@theme/CodeBlock';
import Tabs from '@theme/Tabs';
import TabItem from '@theme/TabItem';
import styles from './styles.module.css';

const SHOWCASE_YAML = `name: hello-bot
instructions: You are a friendly assistant.
model:
  name: claude
  provider: { name: anthropic, type: anthropic }
  model_name: claude-sonnet-4-20250514
platform:
  name: docker
  type: docker
  provider: { name: docker, type: docker }
channels:
  - name: api
    type: api
secrets:
  - name: ANTHROPIC_API_KEY
`;

const SHOWCASE_PYTHON = `import vystak

anthropic = vystak.Provider(name="anthropic", type="anthropic")
docker = vystak.Provider(name="docker", type="docker")

agent = vystak.Agent(
    name="hello-bot",
    instructions="You are a friendly assistant.",
    model=vystak.Model(
        name="claude",
        provider=anthropic,
        model_name="claude-sonnet-4-20250514",
    ),
    platform=vystak.Platform(name="docker", type="docker", provider=docker),
    channels=[vystak.Channel(name="api", type=vystak.ChannelType.API)],
    secrets=[vystak.Secret(name="ANTHROPIC_API_KEY")],
)
`;

export default function CodeShowcase() {
  return (
    <section className={styles.section}>
      <div className="container">
        <div className={styles.header}>
          <h2 className={styles.heading}>Define once. Deploy anywhere.</h2>
          <p className={styles.subhead}>The same agent, in YAML or Python.</p>
        </div>
        <div className={styles.tabs}>
          <Tabs groupId="agent-language">
            <TabItem value="yaml" label="YAML" default>
              <CodeBlock language="yaml">{SHOWCASE_YAML}</CodeBlock>
            </TabItem>
            <TabItem value="python" label="Python">
              <CodeBlock language="python">{SHOWCASE_PYTHON}</CodeBlock>
            </TabItem>
          </Tabs>
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Create `website/src/components/CodeShowcase/styles.module.css`**

```css
.section {
  padding: 4rem 0 5rem;
  background: var(--ifm-background-surface-color);
}

.header {
  text-align: center;
  margin-bottom: 2.5rem;
}

.heading {
  font-size: 2.25rem;
  font-weight: 700;
  letter-spacing: -0.025em;
  margin-bottom: 0.5rem;
}

.subhead {
  font-size: 1.125rem;
  color: var(--ifm-color-content-secondary);
  margin: 0;
}

.tabs {
  max-width: 760px;
  margin: 0 auto;
}
```

- [ ] **Step 3: Build**

```bash
just docs-build
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
git add website/src/components/CodeShowcase/
git commit -m "feat(docs): add CodeShowcase component (tabbed YAML/Python)"
```

---

### Task 6: Wire new components into the homepage; remove HomepageFeatures

**Files:**
- Replace: `website/src/pages/index.js`
- Delete: `website/src/pages/index.module.css`
- Delete: `website/src/components/HomepageFeatures/index.js`
- Delete: `website/src/components/HomepageFeatures/styles.module.css`

**Goal:** Swap the homepage to use the new Hero + CodeShowcase. Remove the now-unused HomepageFeatures component and its index.module.css.

- [ ] **Step 1: Replace `website/src/pages/index.js`**

```javascript
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import Hero from '@site/src/components/Hero';
import CodeShowcase from '@site/src/components/CodeShowcase';

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} — ${siteConfig.tagline}`}
      description="Declarative AI agent orchestration. Define once, deploy everywhere.">
      <Hero />
      <main>
        <CodeShowcase />
      </main>
    </Layout>
  );
}
```

- [ ] **Step 2: Delete the unused files**

```bash
rm website/src/pages/index.module.css
rm -rf website/src/components/HomepageFeatures
```

- [ ] **Step 3: Build**

```bash
just docs-build
```

Expected: clean build. If you see "module not found: HomepageFeatures", the import in step 1 wasn't removed — recheck.

- [ ] **Step 4: Visual spot-check**

```bash
just docs-dev
```

Open `http://localhost:3000/AgentsStack/`. Verify:
- Split hero: title + tagline + description + 2 buttons on the left, code window with macOS-style header on the right
- Below the hero: "Define once. Deploy anywhere." section with YAML/Python tabs
- No old "HomepageFeatures" 3-column grid visible
- Toggle dark mode (top-right ☼/☾ icon) — verify both look good

Resize the browser below 996px wide — the hero should stack into a single column. Stop the server.

- [ ] **Step 5: Commit**

```bash
git add website/src/pages/index.js
git rm website/src/pages/index.module.css
git rm -r website/src/components/HomepageFeatures
git commit -m "feat(docs): replace homepage with Hero + CodeShowcase; drop HomepageFeatures"
```

---

### Task 7: Final verification + clean build

**Files:** None (verification only).

- [ ] **Step 1: Clean build from scratch**

```bash
rm -rf website/build website/.docusaurus
just docs-build
```

Expected: build succeeds, ends with `[SUCCESS] Generated static files in "build".`

- [ ] **Step 2: Check for broken-link warnings explicitly**

```bash
just docs-build 2>&1 | grep -i "broken\|warn\|error" | grep -v "deprecat" || echo "Clean — no warnings or errors"
```

Expected: prints `Clean — no warnings or errors`.

- [ ] **Step 3: Spot-check the docs section**

```bash
just docs-dev
```

Visit each in the browser:
- `http://localhost:3000/AgentsStack/` — homepage with split hero + code showcase
- `http://localhost:3000/AgentsStack/docs/getting-started/intro` — Docs intro; sidebar should show emerald accent on the active item; on-this-page TOC visible on the right
- `http://localhost:3000/AgentsStack/docs/concepts/agents` — long page; verify on-this-page TOC links to each H2/H3 and emerald-highlights the active one as you scroll
- `http://localhost:3000/AgentsStack/blog` — placeholder Blog page renders
- `http://localhost:3000/AgentsStack/pricing` — placeholder Pricing page renders

For each, toggle dark mode and verify it looks good. Stop the server.

- [ ] **Step 4: Push and ready for merge**

```bash
git log --oneline feat/docs-visual-refresh ^main
```

Expected: shows the 6 commits from Tasks 1-6.

- [ ] **Step 5: Done**

The branch `feat/docs-visual-refresh` is ready to merge into `main`. To merge:

```bash
git checkout main
git merge feat/docs-visual-refresh --no-ff -m "Merge feat/docs-visual-refresh: Emerald + Inter design system"
```

If anything looks off in the spot-check, fix it on the branch before merging. Don't merge a half-finished visual refresh.
