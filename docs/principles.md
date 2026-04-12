# AgentStack Principles

AgentStack is a declarative, platform-agnostic orchestration layer for AI agents. It defines, provisions, deploys, updates, and manages agents across any framework, any platform, and any cloud — from a single codebase.

AgentStack builds nothing. It wires everything.

Terraform and Pulumi didn't build AWS. They gave you one language to describe what you want and provisioned it. AgentStack does the same for AI agents.

---

## 1. Agents are infrastructure

An agent is not a script. It is a deployable unit with dependencies — models, memory, tools, skills, secrets, compute, and a workspace. It should be defined, versioned, tested, and deployed with the same rigor as any production service.

*In practice:* Agent definitions live in version control. They have schemas, they pass validation, they get hashed for change detection. Deploying an agent looks like deploying a service, not running a notebook.

## 2. Define once, deploy everywhere

A single agent definition deploys to Docker, AWS AgentCore, Azure Foundry, DigitalOcean Gradient, Kubernetes, or any other platform. The definition is the contract. The platform is a deployment detail.

*In practice:* You write one agent definition. To switch from Docker to AWS, you change the platform target — not the agent code. The same definition works on any supported platform.

## 3. Build nothing, integrate everything

AgentStack does not build runtimes, tracing backends, vector stores, session stores, workflow engines, or sandbox environments. It integrates with existing best-in-class products through thin adapter plugins. Every external product is a provider.

*In practice:* Need a vector store? AgentStack provisions Pinecone, Chroma, or Qdrant — it doesn't build its own. Need tracing? It hooks into Langfuse, LangSmith, or Datadog. The plugin system means any product can be integrated.

## 4. Code over config

Use real programming languages (Python, TypeScript) for agent definitions. Loops, conditionals, functions, type safety, IDE autocomplete. YAML is available as a simple on-ramp but code is the primary API.

*In practice:* Agent definitions are Python or TypeScript, not YAML or JSON. You get the full power of a programming language — composition, abstraction, type checking — instead of a constrained config format.

## 5. Progressive complexity

Three lines to deploy your first agent. Full infrastructure-as-code when you need it. Complexity is opt-in, never required.

```
Level 1:  ast.Agent("bot", model="claude-sonnet-4-20250514")
Level 2:  add tools, channels
Level 3:  add skills, sessions
Level 4:  add workspace, explicit resources and providers
Level 5:  fleet management, environments, promotion
```

*In practice:* A beginner starts with a model and a name. As needs grow, they add tools, then skills, then infrastructure. Each level builds on the last without requiring a rewrite.

## 6. Stateless tool

AgentStack holds no state. No state files, no remote backend, no state locking. The agent definition is the desired state. The platform is the actual state. AgentStack diffs the two using content hashes stored as platform labels.

*In practice:* There is no `agentstack.tfstate` equivalent. Run `agentstack plan` on any machine and it computes the diff from scratch by hashing your definition and comparing it to what's deployed. No state corruption, no locking conflicts.

## 7. The framework is a runtime target, not an abstraction

AgentStack does not abstract frameworks. It targets them. Each framework adapter generates native code using that framework's idioms. Mastra adapter produces Mastra code. LangChain adapter produces LangChain code. No lowest common denominator.

*In practice:* When you choose Mastra as your framework, the generated code is idiomatic Mastra — not a generic wrapper. You can read it, debug it, and extend it using Mastra's documentation. AgentStack doesn't hide the framework from you.

---

## The Seven Concepts

Everything in AgentStack maps to one of seven concepts:

| Concept | What it is | Example |
|---------|-----------|---------|
| **Agent** | What it does — model, skills, guardrails | A support bot powered by Claude with refund handling |
| **Skill** | What it can do — tools + prompts + config | A reusable "refund handling" capability bundle |
| **Channel** | How users reach it — I/O adapter | Slack, REST API, voice, widget, webhook |
| **Resource** | What backs it — infrastructure | Session store, vector store, database, queue |
| **Workspace** | Where it operates — execution environment | Sandbox, filesystem, mounted drive |
| **Provider** | Who provisions it — cloud/service | AWS, Anthropic, Docker, E2B |
| **Platform** | Where it runs — deployment target | AgentCore, Gradient, Cloud Run, Kubernetes |

Every deployment is a combination of three independent choices:

- **Framework adapter** — HOW the agent thinks (Mastra, LangChain, CrewAI)
- **Platform provider** — WHERE the agent runs (Docker, AWS, K8s)
- **Channel adapter** — HOW users reach it (API, Slack, voice)

Any combination works. The definition doesn't change — only the target config changes.
