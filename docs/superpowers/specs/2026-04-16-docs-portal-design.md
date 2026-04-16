# Vystak Documentation Portal — Design Spec

## Goal

Scaffold a Docusaurus 3 documentation site for Vystak, deployed to GitHub Pages. Structure-first — minimal placeholder pages to prove the site builds and deploys, with content added later.

## Decisions

| Decision | Choice |
|----------|--------|
| Framework | Docusaurus 3 |
| Location | `website/` at repo root |
| Content scope | Scaffold only — structure, config, landing page, placeholder pages |
| Hosting | GitHub Pages via GitHub Actions |
| Versioning | "Next" only until first PyPI release, then `npx docusaurus docs:version X.Y.Z` |
| Sidebar | Minimal — Getting Started, Concepts, Deploying, CLI, Examples |
| Search | None initially (add Algolia when there's content) |
| Blog | No |
| i18n | No |

## Site Structure

```
website/
├── docusaurus.config.js
├── sidebars.js
├── package.json
├── src/
│   ├── css/custom.css
│   └── pages/
│       └── index.js                ← landing page
├── docs/
│   ├── getting-started/
│   │   ├── intro.md
│   │   ├── installation.md
│   │   └── quickstart.md
│   ├── concepts/
│   │   ├── agents.md
│   │   ├── models.md
│   │   ├── providers-and-platforms.md
│   │   ├── services.md
│   │   └── channels.md
│   ├── deploying/
│   │   ├── docker.md
│   │   ├── azure.md
│   │   └── gateway.md
│   ├── cli/
│   │   └── reference.md
│   └── examples/
│       └── overview.md
└── static/
    └── img/
```

## Sidebar

```js
module.exports = {
  docs: [
    {
      type: 'category',
      label: 'Getting Started',
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
```

## Docusaurus Config

```js
module.exports = {
  title: 'Vystak',
  tagline: 'Declarative AI agent orchestration',
  url: 'https://<org>.github.io',
  baseUrl: '/AgentsStack/',
  onBrokenLinks: 'throw',
  onBrokenMarkdownLinks: 'warn',
  favicon: 'img/favicon.ico',
  organizationName: '<org>',
  projectName: 'AgentsStack',
  trailingSlash: false,

  presets: [
    ['classic', {
      docs: {
        sidebarPath: require.resolve('./sidebars.js'),
        editUrl: 'https://github.com/<org>/AgentsStack/tree/main/website/',
      },
      blog: false,
      theme: {
        customCss: require.resolve('./src/css/custom.css'),
      },
    }],
  ],

  themeConfig: {
    navbar: {
      title: 'Vystak',
      items: [
        { type: 'docSidebar', sidebarId: 'docs', position: 'left', label: 'Docs' },
        { href: 'https://github.com/<org>/AgentsStack', label: 'GitHub', position: 'right' },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            { label: 'Getting Started', to: '/docs/getting-started/intro' },
            { label: 'CLI Reference', to: '/docs/cli/reference' },
          ],
        },
        {
          title: 'Community',
          items: [
            { label: 'GitHub', href: 'https://github.com/<org>/AgentsStack' },
          ],
        },
      ],
      copyright: `Copyright ${new Date().getFullYear()} Vystak.`,
    },
    colorMode: {
      defaultMode: 'light',
      respectPrefersColorScheme: true,
    },
  },
};
```

Note: `<org>` placeholders will be replaced with the actual GitHub organization name during implementation.

## Landing Page

Hero section with:
- **Title:** "Vystak"
- **Subtitle:** "Define once, deploy everywhere. Declarative orchestration for AI agents."
- **CTA:** "Get Started" button linking to `/docs/getting-started/intro`
- **Code snippet:** Side-by-side YAML agent definition showing simplicity

Feature cards (3):
1. **Multi-Cloud** — "Deploy to Docker, Azure Container Apps, or any platform from a single definition"
2. **OpenAI-Compatible API** — "Every agent exposes /v1/chat/completions and /v1/responses out of the box"
3. **Agent Collaboration** — "Built-in A2A protocol, gateway routing, and multi-agent orchestration"

## GitHub Pages Deployment

GitHub Actions workflow at `.github/workflows/deploy-docs.yml`:

- **Trigger:** Push to `main` that touches `website/**`
- **Steps:**
  1. Checkout
  2. Setup Node 20
  3. `cd website && npm ci && npm run build`
  4. Deploy to GitHub Pages via `actions/deploy-pages`
- **Permissions:** `pages: write`, `id-token: write`

## Justfile Integration

```
docs-dev:
  cd website && npm start

docs-build:
  cd website && npm run build
```

## Placeholder Page Content

Each placeholder `.md` page will have:
- Title (frontmatter `title:` and `sidebar_label:`)
- One sentence describing what the page will cover
- "Coming soon" note

Example:
```markdown
---
title: Agents
sidebar_label: Agents
---

# Agents

An agent is the central deployable unit in Vystak — it defines what model to use, what tools are available, and how to deploy.

*Detailed documentation coming soon.*
```

## Versioning

No version snapshots initially. When ready to publish v0.1.0:

```bash
cd website
npx docusaurus docs:version 0.1.0
```

This creates `versioned_docs/version-0.1.0/` and a version dropdown in the navbar.

## pnpm Workspace

Add `website` to `pnpm-workspace.yaml` so it's part of the monorepo:

```yaml
packages:
  - packages/typescript/*
  - website
```

## Out of Scope

- Actual documentation content (this is scaffold only)
- Search (Algolia — add when there's content worth searching)
- Blog
- i18n / multi-language
- Custom React components or plugins
- API reference auto-generation
- Version snapshots
