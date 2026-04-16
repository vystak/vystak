# Vystak Docs Content — Phase 1 (Critical Path) — Design Spec

## Goal

Replace 6 placeholder pages in the Vystak docs site with real content following a tutorial-depth, code-first style. The goal is a publishable docs site that lets a new user evaluate Vystak and ship a working agent in under 10 minutes.

## Scope

### In scope (6 pages)

| Page | Source material | Target length |
|------|-----------------|---------------|
| `getting-started/intro.md` | `README.md` intro + `docs/principles.md` | ~150 lines |
| `getting-started/installation.md` | `README.md` install section | ~100 lines |
| `getting-started/quickstart.md` | `examples/minimal/` + new step-by-step | ~300 lines |
| `concepts/agents.md` | `README.md` agent section + schema | ~400 lines |
| `deploying/docker.md` | `examples/multi-agent/` + Docker provider | ~400 lines |
| `examples/overview.md` | Featured 4: `minimal`, `sessions-postgres`, `multi-agent`, `azure-multi-agent` | ~300 lines |

### Out of scope (placeholders stay)

- `concepts/models.md`
- `concepts/providers-and-platforms.md`
- `concepts/services.md`
- `concepts/channels.md`
- `deploying/azure.md`
- `deploying/gateway.md`
- `cli/reference.md`

These remain as the existing one-paragraph placeholders. Phase 2 expands them.

## Voice & style

- **Pulumi/Stripe-inspired** — direct, concrete, code-first prose
- **Show, don't tell** — every concept introduced via a working example
- **Progressive disclosure** — simplest case first, then variants and options
- **Copy-pasteable code** — every code block runs without modification (assuming env vars are set)
- **Cross-link liberally** — link concepts to their dedicated pages (even placeholders), link Quickstart to Agents, Docker page to Examples, etc.
- **Use Docusaurus admonitions** — `:::tip`, `:::warning`, `:::note` for callouts

## Content principles

1. **One canonical example per page** — pages don't share examples. Quickstart uses `minimal`, Agents page uses `sessions-postgres`, Docker page uses `multi-agent`.
2. **First section after the intro is hands-on** — no long preambles. Show the user something they can run within ~30 seconds of opening the page.
3. **Link out for depth** — when something deserves its own page (e.g., Postgres sessions config, Channel types), add a `:::note` linking to the placeholder.
4. **End with "What's next"** — every page closes with a bullet list of related pages so users can keep exploring.

## Page-by-page outline

### 1. `getting-started/intro.md` (~150 lines)

```
# Introduction

[One-paragraph value prop: Vystak is to AI agents what Pulumi is to cloud infra]

## What you can do with Vystak
- 3-5 bullets of capabilities (multi-cloud, OpenAI-compatible API, A2A, etc.)

## How it works
[Diagram in ASCII or text: Agent definition → Adapter → Provider → Running agent]

## Core concepts (brief)
- Agent — the deployable unit
- Model — the LLM
- Provider — the cloud
- Platform — where it runs
- Service — backing infra (Postgres, Redis, etc.)
- Channel — how users reach it

[Each links to its concept page or placeholder]

## What's next
- Installation
- Quickstart
```

Source: `README.md` intro paragraph + features list. `docs/principles.md` for the philosophy.

### 2. `getting-started/installation.md` (~100 lines)

```
# Installation

[Lead with: what you need, then how to install]

## Prerequisites
- Python 3.11+
- Docker (for Quickstart)
- (Optional) Azure CLI for cloud deploys

## Install Vystak
- pip / uv install commands for vystak, vystak-cli
- Optional: provider/adapter packages

## Verify
- `vystak --version`
- `vystak --help`

## What's next
- Quickstart
```

Source: `README.md` install section + actual `pip install` commands.

### 3. `getting-started/quickstart.md` (~300 lines)

The critical conversion page. Walks user from zero to deployed agent in ~5 minutes.

```
# Quickstart

[One-paragraph: by the end of this page, you'll have a chatbot running locally]

## Prerequisites
- Vystak installed (link to install)
- Docker running
- An Anthropic API key (or compatible)

## Step 1: Create a project
mkdir my-agent && cd my-agent

## Step 2: Define the agent
[Full vystak.yaml from minimal example]

## Step 3: Deploy
export ANTHROPIC_API_KEY=...
vystak apply

[Expected output]

## Step 4: Talk to it
curl + vystak-chat examples

## Step 5: Tear down
vystak destroy

## What you just did
[3-bullet recap]

## Next steps
- Concepts: Agents
- Examples: more complex setups
- Deploy to Azure (placeholder link)
```

Source: `examples/minimal/vystak.yaml` + actual command output.

### 4. `concepts/agents.md` (~400 lines)

The deepest concept page in this batch. Explains the Agent schema in detail using the `sessions-postgres` example.

```
# Agents

[One-paragraph: an agent is the central deployable unit]

## Anatomy of an agent
[Annotated YAML showing every field with comments]

## Required fields
- name, model, channels — minimum needed

## Adding tools
- skills field with code example

## Adding sessions (persistent memory)
- sessions field with Postgres example

## Adding long-term memory
- memory field

## Adding services
- services field for Redis/Qdrant

## Multi-channel agents
- channels with multiple types

## Python definition (alternative to YAML)
- Brief code example

## What's next
- Models, Services, Channels (placeholders linked)
- Examples
```

Source: README's full YAML example + `examples/sessions-postgres/`.

### 5. `deploying/docker.md` (~400 lines)

The deepest deploying page. Uses multi-agent example to show real complexity.

```
# Deploying to Docker

[One-paragraph: Docker is the default and easiest target]

## How it works
[2-3 sentences: how the Docker provider builds and runs containers]

## Single agent deploy
[Recap from Quickstart, condensed]

## Deploying multiple agents
[Walk through examples/multi-agent: 3 agents + gateway]

## Sessions and persistence
[Postgres service auto-provisioned by the Docker provider]

## Updating an agent
[Hash-based change detection, plan/apply workflow]

## Tearing down
vystak destroy --include-resources

## Troubleshooting
[Common issues: Docker daemon not running, port conflicts]

## What's next
- Examples
- Deploy to Azure (placeholder)
- Gateway (placeholder)
```

Source: `examples/multi-agent/` + Docker provider behavior.

### 6. `examples/overview.md` (~300 lines)

Curated examples page. Featured 4, then a "more examples" section.

```
# Examples

[One-paragraph: working agent definitions you can clone and run]

## Featured examples

### minimal — Hello World
[2-3 paragraphs: what it teaches, how to run, link to repo]

### sessions-postgres — Persistent conversations
[Same format]

### multi-agent — A2A collaboration
[Same format]

### azure-multi-agent — Cloud deployment
[Same format]

## All examples
[Bulleted list of remaining 6 examples with one-line descriptions and links]

## What's next
- Concepts: Agents
- Deploying to Docker
```

Source: each example folder's `vystak.yaml` and existing structure.

## Cross-linking matrix

| From | Links to |
|------|----------|
| Intro | Installation, Quickstart, all concept placeholders |
| Installation | Quickstart |
| Quickstart | Agents, Examples Overview, Docker (deploying) |
| Agents | Models, Services, Channels (placeholders), Examples Overview |
| Docker | Examples Overview, Azure (placeholder), Gateway (placeholder) |
| Examples Overview | Quickstart, Agents, Docker |

## Discovery during writing

While writing, if these are found:

- **Bug in an example** → fix the example file in the same PR
- **Inaccurate info in README.md** → update README too
- **Missing CLI flag or unexpected CLI behavior** → log in `docs/superpowers/followups.md` (create if needed), don't fix in this phase
- **Schema field doesn't match what's documented** → fix the docs to match reality, log in followups if the schema is wrong

## Definition of done

- All 6 pages have real content (no "Coming soon" markers)
- `just docs-build` succeeds with zero broken links
- `just docs-dev` renders all 6 pages correctly
- Every code block in a page can be copy-pasted and works (validated by running it)
- Cross-links between pages work (verified in dev server)

## Out of scope reminder

- Diagrams / SVG illustrations (text-only for v1)
- Search / Algolia integration
- New React components beyond what `HomepageFeatures` already provides
- Versioning the docs (still "Next" only)
- Models / Providers / Services / Channels / Azure / Gateway / CLI Reference content
