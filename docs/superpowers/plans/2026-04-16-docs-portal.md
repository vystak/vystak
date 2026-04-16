# Vystak Documentation Portal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold a Docusaurus 3 documentation site for Vystak at `website/`, deployed to GitHub Pages via GitHub Actions.

**Architecture:** Docusaurus 3 site with classic preset, minimal sidebar (Getting Started, Concepts, Deploying, CLI, Examples). Placeholder pages for structure. GitHub Actions builds and deploys to GitHub Pages on push to main when `website/**` changes.

**Tech Stack:** Docusaurus 3, Node 20+, pnpm workspace, GitHub Pages, GitHub Actions

---

### Important Notes for the Engineer

- **Org name:** Use `vystak` as the GitHub organization placeholder throughout. The user will rename if pushing to a different org. URLs will be `https://vystak.github.io/AgentsStack/`.
- **No tests in the traditional sense:** Docusaurus build is the test. If `npm run build` succeeds, the site works. Don't write Jest tests for placeholder markdown files.
- **Verification commands:** Each task includes a build/start command to verify the change works.

---

### Task 1: Initialize Docusaurus site in `website/`

**Files:**
- Create: `website/package.json`
- Create: `website/docusaurus.config.js`
- Create: `website/sidebars.js`
- Create: `website/src/css/custom.css`
- Create: `website/.gitignore`
- Create: `website/README.md`

- [ ] **Step 1: Create `website/` directory and package.json**

```bash
mkdir -p website/src/css website/src/pages website/static/img website/docs
```

Create `website/package.json`:

```json
{
  "name": "vystak-docs",
  "version": "0.0.0",
  "private": true,
  "scripts": {
    "docusaurus": "docusaurus",
    "start": "docusaurus start",
    "build": "docusaurus build",
    "swizzle": "docusaurus swizzle",
    "deploy": "docusaurus deploy",
    "clear": "docusaurus clear",
    "serve": "docusaurus serve",
    "write-translations": "docusaurus write-translations",
    "write-heading-ids": "docusaurus write-heading-ids"
  },
  "dependencies": {
    "@docusaurus/core": "^3.6.0",
    "@docusaurus/preset-classic": "^3.6.0",
    "@mdx-js/react": "^3.0.0",
    "clsx": "^2.0.0",
    "prism-react-renderer": "^2.3.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0"
  },
  "devDependencies": {
    "@docusaurus/module-type-aliases": "^3.6.0",
    "@docusaurus/types": "^3.6.0"
  },
  "browserslist": {
    "production": [">0.5%", "not dead", "not op_mini all"],
    "development": [
      "last 3 chrome version",
      "last 3 firefox version",
      "last 5 safari version"
    ]
  },
  "engines": {
    "node": ">=20"
  }
}
```

- [ ] **Step 2: Create `website/docusaurus.config.js`**

```javascript
// @ts-check
import {themes as prismThemes} from 'prism-react-renderer';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Vystak',
  tagline: 'Declarative AI agent orchestration',
  favicon: 'img/favicon.ico',

  url: 'https://vystak.github.io',
  baseUrl: '/AgentsStack/',
  trailingSlash: false,

  organizationName: 'vystak',
  projectName: 'AgentsStack',

  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: './sidebars.js',
          editUrl: 'https://github.com/vystak/AgentsStack/tree/main/website/',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      navbar: {
        title: 'Vystak',
        logo: {
          alt: 'Vystak Logo',
          src: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            href: 'https://github.com/vystak/AgentsStack',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {label: 'Getting Started', to: '/docs/getting-started/intro'},
              {label: 'CLI Reference', to: '/docs/cli/reference'},
            ],
          },
          {
            title: 'Community',
            items: [
              {label: 'GitHub', href: 'https://github.com/vystak/AgentsStack'},
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Vystak.`,
      },
      colorMode: {
        defaultMode: 'light',
        respectPrefersColorScheme: true,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'yaml', 'python', 'json'],
      },
    }),
};

export default config;
```

- [ ] **Step 3: Create `website/sidebars.js`**

```javascript
// @ts-check

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: [
        'getting-started/intro',
        'getting-started/installation',
        'getting-started/quickstart',
      ],
    },
    {
      type: 'category',
      label: 'Concepts',
      items: [
        'concepts/agents',
        'concepts/models',
        'concepts/providers-and-platforms',
        'concepts/services',
        'concepts/channels',
      ],
    },
    {
      type: 'category',
      label: 'Deploying',
      items: [
        'deploying/docker',
        'deploying/azure',
        'deploying/gateway',
      ],
    },
    {
      type: 'category',
      label: 'CLI',
      items: ['cli/reference'],
    },
    {
      type: 'category',
      label: 'Examples',
      items: ['examples/overview'],
    },
  ],
};

export default sidebars;
```

- [ ] **Step 4: Create `website/src/css/custom.css`**

```css
/**
 * Vystak custom theme — minimal overrides on Infima defaults.
 */

:root {
  --ifm-color-primary: #2563eb;
  --ifm-color-primary-dark: #1e54d5;
  --ifm-color-primary-darker: #1d4fc9;
  --ifm-color-primary-darkest: #1841a5;
  --ifm-color-primary-light: #3a72ee;
  --ifm-color-primary-lighter: #4779ef;
  --ifm-color-primary-lightest: #6993f2;
  --ifm-code-font-size: 95%;
  --docusaurus-highlighted-code-line-bg: rgba(0, 0, 0, 0.1);
}

[data-theme='dark'] {
  --ifm-color-primary: #60a5fa;
  --ifm-color-primary-dark: #4396f9;
  --ifm-color-primary-darker: #358df9;
  --ifm-color-primary-darkest: #0972f6;
  --ifm-color-primary-light: #7db4fb;
  --ifm-color-primary-lighter: #8bbdfb;
  --ifm-color-primary-lightest: #b6d3fc;
  --docusaurus-highlighted-code-line-bg: rgba(0, 0, 0, 0.3);
}
```

- [ ] **Step 5: Create `website/.gitignore`**

```
# Dependencies
/node_modules

# Production
/build

# Generated files
.docusaurus
.cache-loader

# Misc
.DS_Store
.env.local
.env.development.local
.env.test.local
.env.production.local

npm-debug.log*
yarn-debug.log*
yarn-error.log*
```

- [ ] **Step 6: Create `website/README.md`**

```markdown
# Vystak Documentation

The Vystak documentation site, built with [Docusaurus 3](https://docusaurus.io/).

## Development

```bash
cd website
pnpm install
pnpm start
```

The site runs at `http://localhost:3000/AgentsStack/`.

## Build

```bash
pnpm build
```

The static site is generated in `website/build/`.

## Deployment

The site auto-deploys to GitHub Pages on push to `main` when `website/**` changes.
See `.github/workflows/deploy-docs.yml`.
```

- [ ] **Step 7: Commit**

```bash
git add website/
git commit -m "feat(docs): scaffold Docusaurus site"
```

---

### Task 2: Add placeholder doc pages

**Files:**
- Create 13 placeholder markdown files under `website/docs/`

- [ ] **Step 1: Create getting-started pages**

Create `website/docs/getting-started/intro.md`:

```markdown
---
title: Introduction
sidebar_label: Introduction
sidebar_position: 1
slug: /getting-started/intro
---

# Introduction

Vystak is a declarative, platform-agnostic orchestration layer for AI agents. Define your agent once and deploy it anywhere — Docker, Azure Container Apps, or any future platform.

*Detailed introduction coming soon.*
```

Create `website/docs/getting-started/installation.md`:

```markdown
---
title: Installation
sidebar_label: Installation
sidebar_position: 2
---

# Installation

How to install the Vystak CLI and Python packages.

*Installation guide coming soon.*
```

Create `website/docs/getting-started/quickstart.md`:

```markdown
---
title: Quickstart
sidebar_label: Quickstart
sidebar_position: 3
---

# Quickstart

Deploy your first agent in five minutes.

*Quickstart guide coming soon.*
```

- [ ] **Step 2: Create concepts pages**

Create `website/docs/concepts/agents.md`:

```markdown
---
title: Agents
sidebar_label: Agents
---

# Agents

An agent is the central deployable unit in Vystak — it defines what model to use, what tools are available, and how to deploy.

*Detailed documentation coming soon.*
```

Create `website/docs/concepts/models.md`:

```markdown
---
title: Models
sidebar_label: Models
---

# Models

A model defines which LLM the agent uses and how to call it. Vystak supports any model exposed through an OpenAI- or Anthropic-compatible API.

*Detailed documentation coming soon.*
```

Create `website/docs/concepts/providers-and-platforms.md`:

```markdown
---
title: Providers and Platforms
sidebar_label: Providers & Platforms
---

# Providers and Platforms

A provider is a cloud account or service. A platform is where an agent runs. Both are independent and composable.

*Detailed documentation coming soon.*
```

Create `website/docs/concepts/services.md`:

```markdown
---
title: Services
sidebar_label: Services
---

# Services

Services are typed infrastructure dependencies — Postgres for sessions, Redis for cache, Qdrant for vectors.

*Detailed documentation coming soon.*
```

Create `website/docs/concepts/channels.md`:

```markdown
---
title: Channels
sidebar_label: Channels
---

# Channels

Channels are how users reach an agent — REST API, Slack, webhook, voice, or any other I/O adapter.

*Detailed documentation coming soon.*
```

- [ ] **Step 3: Create deploying pages**

Create `website/docs/deploying/docker.md`:

```markdown
---
title: Deploying to Docker
sidebar_label: Docker
---

# Deploying to Docker

Run agents as Docker containers on your local machine or any Docker-compatible host.

*Detailed guide coming soon.*
```

Create `website/docs/deploying/azure.md`:

```markdown
---
title: Deploying to Azure Container Apps
sidebar_label: Azure Container Apps
---

# Deploying to Azure Container Apps

Deploy agents to Azure Container Apps with managed Postgres, ACR, and Log Analytics.

*Detailed guide coming soon.*
```

Create `website/docs/deploying/gateway.md`:

```markdown
---
title: Deploying the Gateway
sidebar_label: Gateway
---

# Deploying the Gateway

The Vystak gateway is a unified entry point for all agents — routing, registration, and health tracking.

*Detailed guide coming soon.*
```

- [ ] **Step 4: Create CLI reference page**

Create `website/docs/cli/reference.md`:

```markdown
---
title: CLI Reference
sidebar_label: Reference
---

# CLI Reference

The `vystak` command-line interface.

*Detailed reference coming soon.*
```

- [ ] **Step 5: Create examples page**

Create `website/docs/examples/overview.md`:

```markdown
---
title: Examples
sidebar_label: Overview
---

# Examples

Sample agent definitions in the `examples/` directory of the repository.

*Detailed examples coming soon.*
```

- [ ] **Step 6: Commit**

```bash
git add website/docs/
git commit -m "feat(docs): add placeholder documentation pages"
```

---

### Task 3: Create landing page

**Files:**
- Create: `website/src/pages/index.js`
- Create: `website/src/pages/index.module.css`
- Create: `website/src/components/HomepageFeatures/index.js`
- Create: `website/src/components/HomepageFeatures/styles.module.css`

- [ ] **Step 1: Create `website/src/pages/index.js`**

```javascript
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';

import styles from './index.module.css';

function HomepageHeader() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <header className={clsx('hero hero--primary', styles.heroBanner)}>
      <div className="container">
        <h1 className="hero__title">{siteConfig.title}</h1>
        <p className="hero__subtitle">{siteConfig.tagline}</p>
        <p className={styles.heroDescription}>
          Define your agent once. Deploy to Docker, Azure Container Apps, or any
          platform — from a single command.
        </p>
        <div className={styles.buttons}>
          <Link
            className="button button--secondary button--lg"
            to="/docs/getting-started/intro">
            Get Started →
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home() {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={`${siteConfig.title} — ${siteConfig.tagline}`}
      description="Declarative AI agent orchestration. Define once, deploy everywhere.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
```

- [ ] **Step 2: Create `website/src/pages/index.module.css`**

```css
.heroBanner {
  padding: 4rem 0;
  text-align: center;
  position: relative;
  overflow: hidden;
}

@media screen and (max-width: 996px) {
  .heroBanner {
    padding: 2rem;
  }
}

.heroDescription {
  font-size: 1.1rem;
  margin-top: 1rem;
  max-width: 720px;
  margin-left: auto;
  margin-right: auto;
}

.buttons {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 2rem;
}
```

- [ ] **Step 3: Create `website/src/components/HomepageFeatures/index.js`**

```javascript
import clsx from 'clsx';
import Heading from '@theme/Heading';
import styles from './styles.module.css';

const FeatureList = [
  {
    title: 'Multi-Cloud',
    description: (
      <>
        Deploy to Docker, Azure Container Apps, or any platform from a single
        agent definition. Switch targets without changing the agent.
      </>
    ),
  },
  {
    title: 'OpenAI-Compatible API',
    description: (
      <>
        Every agent exposes <code>/v1/chat/completions</code> and{' '}
        <code>/v1/responses</code> out of the box. Drop-in replacement for any
        OpenAI client.
      </>
    ),
  },
  {
    title: 'Agent Collaboration',
    description: (
      <>
        Built-in A2A protocol, gateway routing, and multi-agent orchestration.
        Agents can discover and call each other natively.
      </>
    ),
  },
];

function Feature({title, description}) {
  return (
    <div className={clsx('col col--4')}>
      <div className="text--center padding-horiz--md">
        <Heading as="h3">{title}</Heading>
        <p>{description}</p>
      </div>
    </div>
  );
}

export default function HomepageFeatures() {
  return (
    <section className={styles.features}>
      <div className="container">
        <div className="row">
          {FeatureList.map((props, idx) => (
            <Feature key={idx} {...props} />
          ))}
        </div>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Create `website/src/components/HomepageFeatures/styles.module.css`**

```css
.features {
  display: flex;
  align-items: center;
  padding: 4rem 0;
  width: 100%;
}
```

- [ ] **Step 5: Commit**

```bash
git add website/src/
git commit -m "feat(docs): add landing page with hero and feature cards"
```

---

### Task 4: Add static assets (favicon and logo)

**Files:**
- Create: `website/static/img/favicon.ico` (placeholder)
- Create: `website/static/img/logo.svg`

- [ ] **Step 1: Create `website/static/img/logo.svg`**

A simple text-based SVG logo (placeholder until a real logo is designed):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect width="32" height="32" rx="6" fill="#2563eb"/>
  <text x="16" y="22" font-family="system-ui, sans-serif" font-size="18" font-weight="700"
        fill="white" text-anchor="middle">V</text>
</svg>
```

- [ ] **Step 2: Create a placeholder `website/static/img/favicon.ico`**

For the favicon, copy the SVG and rely on Docusaurus serving the SVG as a fallback. To create an actual `.ico` file:

```bash
# Use the SVG as both — modern browsers accept SVG favicons
cp website/static/img/logo.svg website/static/img/favicon.ico
```

If a real `.ico` is needed later, generate one from the SVG with an online tool or `imagemagick`. For now, the SVG-as-ICO works for development.

- [ ] **Step 3: Commit**

```bash
git add website/static/
git commit -m "feat(docs): add placeholder logo and favicon"
```

---

### Task 5: Add `website` to pnpm workspace

**Files:**
- Modify: `pnpm-workspace.yaml`

- [ ] **Step 1: Update `pnpm-workspace.yaml`**

Replace the file content:

```yaml
packages:
  - "packages/typescript/*"
  - "website"
```

- [ ] **Step 2: Install dependencies**

```bash
pnpm install
```

Expected: pnpm installs Docusaurus and its dependencies. Should complete without errors.

- [ ] **Step 3: Commit**

```bash
git add pnpm-workspace.yaml pnpm-lock.yaml
git commit -m "chore: add website to pnpm workspace"
```

---

### Task 6: Verify the site builds and runs locally

**Files:** None (verification only)

- [ ] **Step 1: Build the site**

```bash
cd website && pnpm build
```

Expected: Successful build. Output should end with something like:
```
[SUCCESS] Generated static files in "build".
```

If the build fails, fix any errors before continuing. Common issues:
- Missing pages referenced in sidebar → add the missing markdown file
- Broken markdown links → fix the link or change `onBrokenLinks` setting
- Missing `favicon.ico` → ensure Task 4 was completed

- [ ] **Step 2: Run the dev server**

```bash
cd website && pnpm start
```

Expected: Dev server starts on `http://localhost:3000/AgentsStack/`. Browser opens automatically.

Manually verify:
- Landing page loads with hero and three feature cards
- Clicking "Get Started →" navigates to `/docs/getting-started/intro`
- Sidebar shows all 5 categories with correct items
- Each placeholder page renders with its title

Stop the dev server with Ctrl+C.

- [ ] **Step 3: No commit needed**

This task is verification only.

---

### Task 7: Add Justfile commands

**Files:**
- Modify: `Justfile`

- [ ] **Step 1: Append docs commands to Justfile**

Add at the end of `Justfile`:

```
# Run docs site locally
docs-dev:
    cd website && pnpm start

# Build docs site
docs-build:
    cd website && pnpm build

# Serve built docs
docs-serve:
    cd website && pnpm serve
```

- [ ] **Step 2: Verify Justfile commands work**

```bash
just docs-build
```

Expected: Same successful build as Task 6 step 1.

- [ ] **Step 3: Commit**

```bash
git add Justfile
git commit -m "chore: add docs Justfile commands"
```

---

### Task 8: Create GitHub Actions workflow for GitHub Pages deployment

**Files:**
- Create: `.github/workflows/deploy-docs.yml`

- [ ] **Step 1: Create `.github/workflows/deploy-docs.yml`**

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - 'website/**'
      - '.github/workflows/deploy-docs.yml'
  workflow_dispatch:

# Required for GitHub Pages deployment
permissions:
  contents: read
  pages: write
  id-token: write

# Allow only one concurrent deployment
concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    name: Build
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup pnpm
        uses: pnpm/action-setup@v4
        with:
          version: 9.15.4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm

      - name: Install dependencies
        run: pnpm install --frozen-lockfile

      - name: Build site
        run: cd website && pnpm build

      - name: Setup Pages
        uses: actions/configure-pages@v5

      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: website/build

  deploy:
    name: Deploy
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Verify the workflow file syntax**

```bash
# If actionlint is installed:
actionlint .github/workflows/deploy-docs.yml || echo "actionlint not installed — skip"
```

If `actionlint` isn't installed, just verify the YAML parses:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-docs.yml'))" && echo "YAML valid"
```

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-docs.yml
git commit -m "ci: add GitHub Actions workflow for docs deployment"
```

---

### Task 9: Update PROJECT_PLAN.md

**Files:**
- Modify: `PROJECT_PLAN.md`

- [ ] **Step 1: Add a note about the docs portal**

Find the "What's Planned" section in `PROJECT_PLAN.md` and update or add:

In the "Documentation:" subsection under "Near Term", change:
```markdown
- [ ] Documentation site (VitePress or Starlight)
```

To:
```markdown
- [x] Documentation site scaffold (Docusaurus 3 at `website/`, deployed to GitHub Pages)
- [ ] Documentation content (writing the actual guides, references, examples)
```

- [ ] **Step 2: Commit**

```bash
git add PROJECT_PLAN.md
git commit -m "docs: mark documentation site scaffold as complete in PROJECT_PLAN"
```

---

### Task 10: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Clean install and full build**

```bash
rm -rf website/node_modules website/build website/.docusaurus
pnpm install
just docs-build
```

Expected: Successful build from clean state.

- [ ] **Step 2: Verify file structure**

```bash
ls -la website/
ls -la website/docs/
ls -la website/src/
ls -la website/static/
ls -la .github/workflows/deploy-docs.yml
```

Expected: All files exist. `website/build/` directory created from build.

- [ ] **Step 3: Verify Justfile integration**

```bash
just --list | grep docs
```

Expected: Shows `docs-build`, `docs-dev`, `docs-serve` commands.

- [ ] **Step 4: Done**

The documentation portal scaffold is complete. The site can be developed locally with `just docs-dev` and will auto-deploy to GitHub Pages on push to `main` once the repo has a remote configured and GitHub Pages is enabled in repo settings (Settings → Pages → Source: GitHub Actions).
