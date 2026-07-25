# Control Panel UI Redesign — Design

**Date:** 2026-07-25
**Package:** `packages/typescript/vystak-panel`
**Status:** Approved approach — Tailwind CSS v4 + shadcn/ui + Vercel AI Elements ("Option A")

## Goal

Replace the unstyled, inline-`style` panel UI with a modern, themed, responsive
interface built on proven frameworks, and restructure the shell so the panel
behaves like a contemporary chat product: conversations in the sidebar, a real
chat surface with markdown and tool-call rendering, confirmations on
destructive actions, and a branded sign-in.

## Non-goals

- **No panel-channel (Python) API changes.** Every feature below uses endpoints
  that already exist (`PATCH /api/conversations/{id}` with `{title}`,
  `DELETE /api/conversations/{id}`, `DELETE /api/projects/{id}`, members CRUD,
  users CRUD).
- No changes to the auth flow (`auth.ts`, NextAuth Google provider, allow-list
  policy) beyond surfacing the existing `signOut` in the UI.
- No changes to the streaming contract. `lib/stream.ts`, `/api/chat/route.ts`,
  and the SSE mapping from the tool-call visualization plan
  (`docs/superpowers/plans/2026-07-25-tool-call-visualization.md`) are consumed
  as-is.
- No work on the placeholder TS packages; this is `vystak-panel` only.
- No automated visual/E2E testing infrastructure (Playwright etc.) in this
  iteration.

## Tech stack

| Concern | Choice | Notes |
|---|---|---|
| Styling | **Tailwind CSS v4** | CSS-first config: `@import "tailwindcss"` + `@theme` in `globals.css`; `@tailwindcss/postcss` in a package-local `postcss.config.mjs`. No `tailwind.config.js`. |
| Component primitives | **shadcn/ui** | `npx shadcn@latest init` (default style, CSS variables, neutral base). Components are **copied into the repo** under `components/ui/` — no runtime component-library dependency. |
| Chat components | **Vercel AI Elements** | `npx ai-elements` — a shadcn registry that copies chat components into `components/ai-elements/`. Built for AI SDK v5 `UIMessage.parts`, including `dynamic-tool` states. Brings `streamdown` for markdown rendering. |
| Icons | `lucide-react` | shadcn's default. |
| Dark mode | `next-themes` | Class-based (`.dark`), system default, toggle in the user menu. |

New dependencies (approximate — the shadcn/ai-elements CLIs add the exact
Radix packages per component): `tailwindcss` + `@tailwindcss/postcss` (dev),
`class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`,
`next-themes`, `streamdown`, and the Radix primitives required by the
components listed below.

**Repo constraints that survive this change:**

- The package's build script stays named `build:app` — `just
  typecheck-typescript` runs `pnpm -r run build`, and `vystak-panel` must not
  participate. The four live gates (`lint-python`, `typecheck-typescript`,
  `test-python`, `test-typescript`) stay green.
- Component names from the AI Elements registry are verified at install time;
  if a name differs from this spec, the mapping adapts — the contract that
  matters is the `UIMessage.parts` shape, which is pinned by the tool-call
  plan and `tests/stream.test.ts`.

## Information architecture

Routes are unchanged (`/`, `/signin`, `/admin/users`, `/p/[projectId]`,
`/p/[projectId]/c/[convId]`). What changes is what lives where:

```
┌────────────┬──────────────────────────────────────────────┐
│ SIDEBAR    │ HEADER: conversation title (inline rename)   │
│            │         · agent badge · project settings     │
│ [Project ▾]│──────────────────────────────────────────────│
│            │                                              │
│ Conversa-  │   CHAT (max-w-3xl, centered)                 │
│ tions of   │   - user / assistant messages, markdown      │
│ active     │   - collapsible tool-call blocks             │
│ project    │   - thinking loader, scroll-to-bottom        │
│ + New conv │                                              │
│            │──────────────────────────────────────────────│
│ ┌────────┐ │   COMPOSER (sticky bottom): textarea,        │
│ │ user ▾ │ │   Enter=send, Shift+Enter=newline, Stop      │
└─┴────────┴─┴──────────────────────────────────────────────┘
```

- **Sidebar** (shadcn `Sidebar`, collapsible; off-canvas sheet below `md`):
  - **Project switcher** at the top (`DropdownMenu`): lists all projects,
    "New project…" item opening a `Dialog`, and per-project "Delete project"
    behind an `AlertDialog` (uses existing `deleteProject`).
  - **Conversation list** for the active project: title (fallback "Untitled"),
    agent name as a `Badge`, relative updated time. Active item highlighted.
    Per-item menu: Rename (inline or small `Dialog`), Delete (`AlertDialog`).
  - **New conversation** button opening a `Dialog` with an agent `Select`
    (replaces the bare form in `new-conversation.tsx`).
  - **Footer user menu** (`DropdownMenu` on avatar + name): Manage users
    (admin only), theme toggle, **Sign out** (new server action wrapping the
    existing `signOut` from `auth.ts` — currently unreachable from the UI).
- **Project page** (`/p/[projectId]`): becomes an empty-state hero ("Start a
  conversation with one of your agents") with a New-conversation CTA — the
  conversation list moves to the sidebar. The `Members` block moves into a
  **Project settings dialog** opened from the header: member list with
  remove-behind-`AlertDialog`, share-by-email input.
- **Admin users page**: proper `Table` with a header row (Email / Role /
  Status / Actions), `Badge` for role and status, invite form with shadcn
  `Input`/`Select`/`Button`, Deactivate behind an `AlertDialog`. The existing
  no-self-deactivation rule is preserved.
- **Sign-in page**: centered `Card` with the Vystak wordmark, a proper
  "Continue with Google" button, and the three existing error cases rendered
  as `Alert` (icon + text, not color-only).

## Chat surface (`components/chat.tsx` rewrite)

Built from AI Elements, preserving the current `useChat` configuration
(`DefaultChatTransport` to `/api/chat`, `prepareSendMessagesRequest` sending
`{conversationId, text}`) unchanged:

- `Conversation` / `ConversationContent` / `ConversationScrollButton` —
  auto-scroll with a scroll-to-bottom affordance.
- `Message` / `MessageContent` per role — user messages right-aligned in a
  filled bubble; assistant messages full-width on the surface.
- `Response` — renders `text` parts as markdown (streaming-safe via
  `streamdown`): code blocks, lists, tables, links.
- `Tool` (header + collapsible content with input/output sections) — renders
  `part.type === 'dynamic-tool'` in all four states (`input-streaming`,
  `input-available`, `output-available`, `output-error`). **This implements
  Task 5 of the tool-call visualization plan** — the plan's hand-rolled
  `<details>` rendering is superseded by this component; the plan's data
  contract (parts, states, history replay) is unchanged.
- `Loader` — shown while `status === 'submitted'` (sent, nothing streamed
  yet).
- `PromptInput` — auto-growing textarea, Enter submits, Shift+Enter inserts a
  newline, send button disabled when empty, **Stop** button while
  `status === 'streaming'` (wires `stop()` from `useChat`, currently unused).
- Errors: the existing `error`/`clearError` behavior rendered as a
  destructive `Alert` with a dismiss action, replacing the crimson `<p>`.
- History replay in `c/[convId]/page.tsx` keeps the tool-call plan's mapping:
  persisted `parts` → `UIMessage.parts` (`tool` → `dynamic-tool` with
  `state: 'output-available'`); `parts === null` rows synthesize a single
  text part from `content`, exactly as today.

## Theming

- shadcn CSS-variable theme in `globals.css`: neutral base (zinc), one accent
  hue — **violet** (Tailwind violet-600 as light-mode primary, violet-500 in
  dark) — used sparingly: primary buttons, active sidebar item, focus rings.
- Light and dark palettes defined together; `next-themes` with
  `defaultTheme="system"` and a toggle in the user menu. The current
  `color-scheme: light dark` browser-default behavior is replaced by real
  themed surfaces.
- Typography: keep the system font stack; establish a scale (page title,
  section, body, caption) through Tailwind utilities rather than ad-hoc
  `fontSize` inline styles.

## Component/file inventory

| File | Change |
|---|---|
| `app/globals.css` | Tailwind v4 import + `@theme` tokens + shadcn CSS variables (light/dark). |
| `postcss.config.mjs` | New — `@tailwindcss/postcss`. |
| `components.json` | New — shadcn CLI config (aliases into `components/`, `lib/`). |
| `app/layout.tsx` | Wrap in `ThemeProvider`; base body classes. |
| `app/p/[projectId]/layout.tsx` | Fetch conversations alongside projects; render new `AppSidebar` + `SidebarProvider`/`SidebarInset`; header slot. |
| `components/app-sidebar.tsx` | New — replaces `sidebar.tsx` (project switcher, conversation list, new-conversation dialog, user menu). |
| `components/chat.tsx` | Rewritten on AI Elements (above). |
| `components/project-settings.tsx` | New — dialog absorbing `members.tsx`. |
| `components/new-conversation.tsx`, `components/members.tsx`, `components/sidebar.tsx` | Deleted (absorbed). |
| `app/p/[projectId]/page.tsx` | Empty-state hero + CTA. |
| `app/admin/users/page.tsx` | shadcn Table/Badge/AlertDialog restyle. |
| `app/signin/page.tsx` | Card + Google button + Alert errors. |
| `app/error.tsx` | Styled with the same Alert/Card language. |
| `app/actions.ts` | Add `renameConversationAction`, `deleteProjectAction`, `signOutAction`. Existing actions unchanged. |
| `lib/panel.ts` | Add `renameConversation(email, convId, title)` → `PATCH /api/conversations/{convId}` body `{title}` (endpoint exists: `routes_conversations.py:66-73`). |
| `components/ui/*`, `components/ai-elements/*` | CLI-generated (committed to the repo, per shadcn model). |

Server components stay server components; client boundaries are exactly the
interactive leaves (chat, dialogs, menus, theme toggle).

## Accessibility

- Radix primitives (via shadcn) provide focus trapping, ARIA roles, and
  keyboard handling for menus/dialogs.
- Errors and statuses pair an icon with text — never color alone.
- Visible focus rings from the theme's ring token; Escape closes dialogs;
  the composer keyboard contract is Enter/Shift+Enter.

## Error handling

- Server-action failures currently throw to `app/error.tsx`; that page gets
  the new visual language but the mechanism is unchanged.
- Chat transport errors keep the `error`/`clearError` flow, restyled.
- Destructive actions (delete conversation, delete project, remove member,
  deactivate user) all confirm via `AlertDialog` before the action fires.

## Testing & verification

- Existing vitest suites (`stream.test.ts`, `auth-policy.test.ts`) are
  untouched and must stay green; `tsc --noEmit` covers the new components.
- Definition of done mirrors the repo convention — verify against the real
  example deployment (`examples/docker-panel`): sign in, create
  project/conversation, send a message that triggers a tool call (markdown +
  collapsible tool block render, loader shows, stop works), rename and delete
  a conversation, open project settings and manage members, admin
  invite/deactivate with confirmation, dark-mode toggle, and the sidebar
  collapsing at a phone-width viewport.

## Sequencing

This lands **after** Tasks 1–4 of the tool-call visualization plan (schema
migration, agent tool events, panel SSE forwarding, AI SDK chunk mapping) —
they are backend/transport work this design consumes. **Task 5 of that plan is
implemented by this redesign** (Tool component, history replay, loader)
instead of as a separate minimal pass.

## Risks

- **CLI-generated code volume:** shadcn/AI Elements copy a fair amount of
  source into the repo. Mitigation: commit generated components in a
  dedicated commit, separate from hand-written changes.
- **Registry drift:** AI Elements component APIs are newer than shadcn core.
  Mitigation: the components are vendored at install time — no runtime
  version drift; adjust names/props at install if the registry has moved.
- **Tailwind v4 in the pnpm workspace:** config is package-local
  (`postcss.config.mjs` inside `vystak-panel`), so other workspace packages
  are unaffected.
