# Panel UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `vystak-panel` UI on Tailwind CSS v4 + shadcn/ui + Vercel AI Elements per `docs/superpowers/specs/2026-07-25-panel-ui-redesign-design.md`: conversations in a collapsible sidebar, a real chat surface (markdown + tool-call blocks), confirmations on destructive actions, light/dark themes, branded sign-in and admin pages.

**Architecture:** Frontend-only. All data flows through existing panel-channel endpoints; the only additions are one `lib/panel.ts` function (`renameConversation`), three server actions, and two small pure helpers. shadcn/ui and AI Elements components are vendored (CLI-copied) into the repo. Server components stay server components; client boundaries are the interactive leaves.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind CSS v4 (`@tailwindcss/postcss`, CSS-first config), shadcn/ui, AI Elements, `next-themes`, `lucide-react`, AI SDK v5 (`@ai-sdk/react` — already present).

## Global Constraints

- The package's build script stays named **`build:app`** — never add a `build` script to `packages/typescript/vystak-panel/package.json` (`just typecheck-typescript` runs `pnpm -r run build` and the panel must not participate).
- The four live gates stay green after every task: `just lint-python`, `just typecheck-typescript`, `just test-python`, `just test-typescript`.
- **No Python changes anywhere in this plan.** If a task seems to need one, stop — it's a plan bug.
- Public repo: no real credentials, no local `/Users/...` paths in committed files.
- All `pnpm`/`npx` commands run **from `packages/typescript/vystak-panel/`** unless stated otherwise.
- Vendored component files (`components/ui/*`, `components/ai-elements/*`, `hooks/*`) are committed as-generated in their own commit; do not hand-edit them except where a task explicitly says so.
- The `useChat` transport configuration in `components/chat.tsx` (`DefaultChatTransport` to `/api/chat`, `prepareSendMessagesRequest` returning `{conversationId, text}`) is a working contract — preserve it byte-for-byte.
- `lib/stream.ts`, `app/api/chat/route.ts`, `auth.ts`, `lib/auth-policy.ts` are **not modified** by this plan.
- Per-task check commands: `pnpm run typecheck` and `pnpm run test` (from the package dir). Expected test baseline: the two existing suites (`tests/auth-policy.test.ts`, `tests/stream.test.ts`) pass.

## Sequencing note

This plan lands after Tasks 1–4 of `docs/superpowers/plans/2026-07-25-tool-call-visualization.md` (backend/transport). Task 6 below **implements that plan's Task 5** (tool rendering, history replay, loader). If Tasks 3–4 of that plan are not merged yet, everything here still works: `PanelMessage.parts` will simply always be absent and the fallback path renders plain text, exactly as today.

## File structure (end state)

```
packages/typescript/vystak-panel/
├── postcss.config.mjs                  # NEW  Tailwind v4 postcss plugin
├── components.json                     # NEW  shadcn CLI config (hand-written)
├── app/
│   ├── globals.css                     # REWRITE  Tailwind import + full light/dark theme
│   ├── layout.tsx                      # MODIFY  ThemeProvider + suppressHydrationWarning
│   ├── error.tsx                       # REWRITE  Alert + Button
│   ├── page.tsx                        # unchanged
│   ├── actions.ts                      # MODIFY  +rename/deleteProject/signOut; deleteConversation redirects
│   ├── signin/page.tsx                 # REWRITE  Card + Google button + Alerts
│   ├── admin/users/page.tsx            # REWRITE  Table + Badges + ConfirmAction
│   └── p/[projectId]/
│       ├── layout.tsx                  # REWRITE  SidebarProvider + AppSidebar + SidebarInset
│       ├── page.tsx                    # REWRITE  header + empty-state hero
│       └── c/[convId]/page.tsx         # REWRITE  header + parts-aware initialMessages
├── components/
│   ├── app-sidebar.tsx                 # NEW  switcher + conversations + user menu
│   ├── chat.tsx                        # REWRITE  on AI Elements
│   ├── confirm-action.tsx              # NEW  shared AlertDialog wrapper for server actions
│   ├── conversation-title.tsx          # NEW  inline-rename header title
│   ├── new-conversation-dialog.tsx     # NEW  agent picker dialog (sidebar + hero CTA)
│   ├── page-header.tsx                 # NEW  shared header shell (SidebarTrigger + border)
│   ├── project-settings.tsx            # NEW  members dialog (absorbs members.tsx)
│   ├── theme-provider.tsx              # NEW  next-themes wrapper
│   ├── sidebar.tsx                     # DELETE (task 4)
│   ├── new-conversation.tsx            # DELETE (task 4)
│   ├── members.tsx                     # DELETE (task 5)
│   ├── ui/…                            # NEW  vendored shadcn components
│   └── ai-elements/…                   # NEW  vendored AI Elements components
├── hooks/…                             # NEW  vendored (use-mobile, from sidebar)
├── lib/
│   ├── format.ts                       # NEW  relativeTime + safeParseJson (tested)
│   ├── panel.ts                        # MODIFY  +renameConversation
│   ├── types.ts                        # MODIFY  +StoredPart, PanelMessage.parts
│   └── utils.ts                        # NEW  cn() helper
└── tests/format.test.ts                # NEW
```

---

### Task 1: Styling foundation — Tailwind v4, theme tokens, ThemeProvider

**Files:**
- Create: `packages/typescript/vystak-panel/postcss.config.mjs`
- Create: `packages/typescript/vystak-panel/components.json`
- Create: `packages/typescript/vystak-panel/lib/utils.ts`
- Create: `packages/typescript/vystak-panel/components/theme-provider.tsx`
- Rewrite: `packages/typescript/vystak-panel/app/globals.css`
- Modify: `packages/typescript/vystak-panel/app/layout.tsx`
- Modify: `packages/typescript/vystak-panel/package.json` (deps only — script names untouched)

**Interfaces:**
- Consumes: nothing.
- Produces: `cn(...inputs: ClassValue[]): string` from `@/lib/utils`; themed CSS variables (`--background`, `--primary`, `--sidebar`, …) available to every later task; `<ThemeProvider>` mounted in the root layout with class-based dark mode.

- [ ] **Step 1: Install dependencies**

```bash
cd packages/typescript/vystak-panel
pnpm add class-variance-authority clsx tailwind-merge lucide-react next-themes
pnpm add -D tailwindcss @tailwindcss/postcss
```

Expected: `package.json` gains the six deps; `pnpm-lock.yaml` at repo root updates. Verify no `build` script appeared: `grep '"build"' package.json` → only `build:app`.

- [ ] **Step 2: Create `postcss.config.mjs`**

```js
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
```

- [ ] **Step 3: Create `components.json`** (hand-written instead of `shadcn init` — deterministic, and init would clobber our globals.css)

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "app/globals.css",
    "baseColor": "zinc",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 4: Create `lib/utils.ts`**

```ts
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Rewrite `app/globals.css`** — full replacement. Zinc neutrals, violet primary (violet-600 light / violet-500 dark) per the spec.

```css
@import "tailwindcss";

@custom-variant dark (&:is(.dark *));

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}

:root {
  --radius: 0.625rem;
  --background: oklch(1 0 0);
  --foreground: oklch(0.141 0.005 285.823);
  --card: oklch(1 0 0);
  --card-foreground: oklch(0.141 0.005 285.823);
  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.141 0.005 285.823);
  --primary: oklch(0.541 0.281 293.009);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.967 0.001 286.375);
  --secondary-foreground: oklch(0.21 0.006 285.885);
  --muted: oklch(0.967 0.001 286.375);
  --muted-foreground: oklch(0.552 0.016 285.938);
  --accent: oklch(0.967 0.001 286.375);
  --accent-foreground: oklch(0.21 0.006 285.885);
  --destructive: oklch(0.577 0.245 27.325);
  --destructive-foreground: oklch(0.985 0 0);
  --border: oklch(0.92 0.004 286.32);
  --input: oklch(0.92 0.004 286.32);
  --ring: oklch(0.541 0.281 293.009);
  --sidebar: oklch(0.985 0 0);
  --sidebar-foreground: oklch(0.141 0.005 285.823);
  --sidebar-primary: oklch(0.541 0.281 293.009);
  --sidebar-primary-foreground: oklch(0.985 0 0);
  --sidebar-accent: oklch(0.967 0.001 286.375);
  --sidebar-accent-foreground: oklch(0.21 0.006 285.885);
  --sidebar-border: oklch(0.92 0.004 286.32);
  --sidebar-ring: oklch(0.541 0.281 293.009);
}

.dark {
  --background: oklch(0.141 0.005 285.823);
  --foreground: oklch(0.985 0 0);
  --card: oklch(0.21 0.006 285.885);
  --card-foreground: oklch(0.985 0 0);
  --popover: oklch(0.21 0.006 285.885);
  --popover-foreground: oklch(0.985 0 0);
  --primary: oklch(0.606 0.25 292.717);
  --primary-foreground: oklch(0.985 0 0);
  --secondary: oklch(0.274 0.006 286.033);
  --secondary-foreground: oklch(0.985 0 0);
  --muted: oklch(0.274 0.006 286.033);
  --muted-foreground: oklch(0.705 0.015 286.067);
  --accent: oklch(0.274 0.006 286.033);
  --accent-foreground: oklch(0.985 0 0);
  --destructive: oklch(0.704 0.191 22.216);
  --destructive-foreground: oklch(0.985 0 0);
  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.606 0.25 292.717);
  --sidebar: oklch(0.21 0.006 285.885);
  --sidebar-foreground: oklch(0.985 0 0);
  --sidebar-primary: oklch(0.606 0.25 292.717);
  --sidebar-primary-foreground: oklch(0.985 0 0);
  --sidebar-accent: oklch(0.274 0.006 286.033);
  --sidebar-accent-foreground: oklch(0.985 0 0);
  --sidebar-border: oklch(1 0 0 / 10%);
  --sidebar-ring: oklch(0.606 0.25 292.717);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  body {
    @apply bg-background text-foreground;
    font-family: ui-sans-serif, system-ui, sans-serif;
  }
}
```

- [ ] **Step 6: Create `components/theme-provider.tsx`**

```tsx
'use client';

import { ThemeProvider as NextThemesProvider } from 'next-themes';

export function ThemeProvider(
  props: React.ComponentProps<typeof NextThemesProvider>,
) {
  return <NextThemesProvider {...props} />;
}
```

- [ ] **Step 7: Modify `app/layout.tsx`** — full replacement:

```tsx
import type { Metadata } from 'next';
import { ThemeProvider } from '@/components/theme-provider';
import './globals.css';

export const metadata: Metadata = {
  title: 'Vystak Panel',
  description: 'Control panel for deployed Vystak agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
```

`suppressHydrationWarning` is required: next-themes mutates the `<html>` class before hydration.

- [ ] **Step 8: Verify**

```bash
pnpm run typecheck   # expected: exit 0
pnpm run test        # expected: 2 files, all passing (auth-policy, stream)
pnpm run dev         # open http://localhost:3000/signin — page renders (unstyled but functional), no console errors; stop the server
```

- [ ] **Step 9: Commit**

```bash
git add packages/typescript/vystak-panel pnpm-lock.yaml
git commit -m "feat(panel): Tailwind v4 foundation, theme tokens, next-themes provider"
```

---

### Task 2: Vendor shadcn/ui and AI Elements components

**Files:**
- Create (CLI-generated): `components/ui/*.tsx`, `components/ai-elements/*.tsx`, `hooks/use-mobile.ts` (or `.tsx`), possibly small additions to `lib/`
- Modify (CLI-managed): `package.json`, root `pnpm-lock.yaml`

**Interfaces:**
- Consumes: `components.json`, `cn()` from Task 1.
- Produces (used by Tasks 4–8): shadcn exports — `Button`, `Input`, `Textarea`, `Select/SelectContent/SelectItem/SelectTrigger/SelectValue`, `Dialog/DialogContent/DialogDescription/DialogHeader/DialogTitle/DialogTrigger`, `AlertDialog/*`, `DropdownMenu/*`, `Badge`, `Table/TableBody/TableCell/TableHead/TableHeader/TableRow`, `Card/CardContent/CardDescription/CardHeader/CardTitle`, `Alert/AlertDescription/AlertTitle`, `Avatar/AvatarFallback/AvatarImage`, `Separator`, `Sidebar/SidebarProvider/SidebarInset/SidebarTrigger/SidebarHeader/SidebarContent/SidebarFooter/SidebarGroup/SidebarGroupAction/SidebarGroupContent/SidebarGroupLabel/SidebarMenu/SidebarMenuItem/SidebarMenuButton/SidebarMenuAction`. AI Elements exports — `Conversation/ConversationContent/ConversationScrollButton`, `Message/MessageContent`, `Response`, `Tool/ToolHeader/ToolContent/ToolInput/ToolOutput`, `Loader`, `PromptInput/PromptInputTextarea/PromptInputSubmit`.

- [ ] **Step 1: Add shadcn components**

```bash
cd packages/typescript/vystak-panel
npx shadcn@latest add button input textarea select dialog alert-dialog dropdown-menu badge table card alert avatar separator sidebar
```

Expected: files appear under `components/ui/` (sidebar also pulls `sheet`, `skeleton`, `tooltip`, `separator`, `button`, `input` and creates `hooks/use-mobile`); Radix deps land in `package.json`. If the CLI asks about a framework or path, the answers are already pinned by `components.json`.

- [ ] **Step 2: Add AI Elements components**

```bash
npx ai-elements@latest add conversation message response tool loader prompt-input
```

Expected: files under `components/ai-elements/`; deps such as `streamdown` and `use-stick-to-bottom` added. If the `ai-elements` CLI fails in the monorepo, the fallback is the shadcn registry route: `npx shadcn@latest add https://registry.ai-sdk.dev/conversation.json` (repeat per component).

- [ ] **Step 3: Read the vendored AI Elements files** (`components/ai-elements/*.tsx`) and note the exact prop names of `PromptInput` (`onSubmit` message shape), `PromptInputSubmit` (`status` prop values), `ToolHeader` (`type`, `state` props), `ToolOutput` (`output`, `errorText`). Task 6 contains reference code written against the documented API — **the vendored source is authoritative**; if a prop differs, Task 6's code adapts to it.

- [ ] **Step 4: Verify**

```bash
grep '"build"' package.json        # expected: only "build:app" — the CLIs must not have added one
pnpm run typecheck                  # expected: exit 0
pnpm run test                       # expected: existing suites pass
```

If typecheck fails inside a vendored file (version skew), fix is allowed but must be a comment-marked minimal edit: `// vystak: <reason>`.

- [ ] **Step 5: Commit (vendored code alone, per spec)**

```bash
git add packages/typescript/vystak-panel pnpm-lock.yaml
git commit -m "feat(panel): vendor shadcn/ui and AI Elements components"
```

---

### Task 3: Data layer — `renameConversation`, part types, format helpers, server actions

**Files:**
- Modify: `packages/typescript/vystak-panel/lib/panel.ts`
- Modify: `packages/typescript/vystak-panel/lib/types.ts`
- Create: `packages/typescript/vystak-panel/lib/format.ts`
- Modify: `packages/typescript/vystak-panel/app/actions.ts`
- Test: `packages/typescript/vystak-panel/tests/format.test.ts`

**Interfaces:**
- Consumes: existing `panelFetch`/`ok` helpers in `lib/panel.ts`; `requireEmail()` pattern in `actions.ts`; `signOut` from `@/auth`.
- Produces:
  - `renameConversation(email: string, convId: string, title: string): Promise<void>`
  - `type StoredPart = { type: 'text'; text: string } | { type: 'tool'; tool_call_id: string; tool_name: string; input: string; output: string }` and `PanelMessage.parts?: StoredPart[] | null`
  - `relativeTime(iso: string, now?: Date): string` and `safeParseJson(text: string): unknown` from `@/lib/format`
  - Server actions: `renameConversationAction(projectId: string, convId: string, formData: FormData)`, `deleteProjectAction(projectId: string)`, `signOutAction()`; `deleteConversationAction` now **redirects** to `/p/${projectId}` instead of revalidating.

- [ ] **Step 1: Write the failing tests** — `tests/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { relativeTime, safeParseJson } from '../lib/format';

describe('relativeTime', () => {
  const now = new Date('2026-07-25T12:00:00Z');

  it('returns "just now" under a minute', () => {
    expect(relativeTime('2026-07-25T11:59:30Z', now)).toBe('just now');
  });

  it('returns minutes', () => {
    expect(relativeTime('2026-07-25T11:15:00Z', now)).toBe('45m ago');
  });

  it('returns hours', () => {
    expect(relativeTime('2026-07-25T05:00:00Z', now)).toBe('7h ago');
  });

  it('returns days under a week', () => {
    expect(relativeTime('2026-07-22T12:00:00Z', now)).toBe('3d ago');
  });

  it('falls back to a date beyond a week', () => {
    expect(relativeTime('2026-07-10T12:00:00Z', now)).not.toMatch(/ago|just now/);
  });

  it('treats timezone-naive timestamps as UTC', () => {
    expect(relativeTime('2026-07-25T11:59:30', now)).toBe('just now');
  });

  it('handles explicit offsets', () => {
    expect(relativeTime('2026-07-25T13:59:30+02:00', now)).toBe('just now');
  });

  it('clamps small clock skew to "just now"', () => {
    expect(relativeTime('2026-07-25T12:00:05Z', now)).toBe('just now');
  });
});

describe('safeParseJson', () => {
  it('parses valid JSON', () => {
    expect(safeParseJson('{"city": "Kyiv"}')).toEqual({ city: 'Kyiv' });
  });

  it('returns the raw string when not JSON', () => {
    expect(safeParseJson('plain text output')).toBe('plain text output');
  });
});
```

- [ ] **Step 2: Run to verify failure**

```bash
pnpm exec vitest run tests/format.test.ts
```

Expected: FAIL — cannot resolve `../lib/format`.

- [ ] **Step 3: Create `lib/format.ts`**

```ts
// SQLite timestamps from the panel store may arrive timezone-naive; they are UTC.
export function relativeTime(iso: string, now: Date = new Date()): string {
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(iso);
  const then = new Date(hasTz ? iso : `${iso}Z`);
  const s = Math.max(0, Math.floor((now.getTime() - then.getTime()) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d ago`;
  return then.toLocaleDateString();
}

export function safeParseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pnpm exec vitest run tests/format.test.ts   # expected: 10 passing
```

- [ ] **Step 5: Add `StoredPart` to `lib/types.ts`** — append at the end, and add the optional field on `PanelMessage`:

```ts
// Persisted message parts (panel channel schema v2, tool-call visualization plan).
export type StoredPart =
  | { type: 'text'; text: string }
  | {
      type: 'tool';
      tool_call_id: string;
      tool_name: string;
      input: string;
      output: string;
    };
```

In `PanelMessage`, after `content: string;` add:

```ts
  parts?: StoredPart[] | null;
```

- [ ] **Step 6: Add `renameConversation` to `lib/panel.ts`** — insert next to `deleteConversation`:

```ts
export const renameConversation = (email: string, convId: string, title: string) =>
  ok(email, `/api/conversations/${convId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });
```

(Endpoint exists: `routes_conversations.py:66-73`, body `{title: str}`.)

- [ ] **Step 7: Update `app/actions.ts`** — add to the imports from `@/lib/panel`: `deleteProject`, `renameConversation`; add `signOut` to the import from `@/auth` (`import { auth, signOut } from '@/auth';`). Replace `deleteConversationAction` and append the three new actions:

```ts
export async function deleteConversationAction(
  projectId: string,
  convId: string,
) {
  const email = await requireEmail();
  await deleteConversation(email, convId);
  redirect(`/p/${projectId}`);
}

export async function renameConversationAction(
  projectId: string,
  convId: string,
  formData: FormData,
) {
  const email = await requireEmail();
  const title = String(formData.get('title') ?? '').trim();
  if (!title) return;
  await renameConversation(email, convId, title);
  revalidatePath(`/p/${projectId}`);
}

export async function deleteProjectAction(projectId: string) {
  const email = await requireEmail();
  await deleteProject(email, projectId);
  redirect('/');
}

export async function signOutAction() {
  await signOut({ redirectTo: '/signin' });
}
```

`deleteConversationAction` redirects because the sidebar lets you delete the conversation you are currently viewing — revalidate alone would leave you on a dead route.

- [ ] **Step 8: Verify and commit**

```bash
pnpm run typecheck   # expected: exit 0
pnpm run test        # expected: 3 files passing (auth-policy, stream, format)
git add packages/typescript/vystak-panel
git commit -m "feat(panel): rename/delete-project/sign-out actions, stored part types, format helpers"
```

---

### Task 4: App shell — ConfirmAction, NewConversationDialog, AppSidebar, project layout

**Files:**
- Create: `packages/typescript/vystak-panel/components/confirm-action.tsx`
- Create: `packages/typescript/vystak-panel/components/new-conversation-dialog.tsx`
- Create: `packages/typescript/vystak-panel/components/app-sidebar.tsx`
- Rewrite: `packages/typescript/vystak-panel/app/p/[projectId]/layout.tsx`
- Delete: `packages/typescript/vystak-panel/components/sidebar.tsx`, `packages/typescript/vystak-panel/components/new-conversation.tsx`

**Interfaces:**
- Consumes: Task 2 shadcn components; Task 3 actions (`createProjectAction`, `createConversationAction`, `deleteConversationAction`, `deleteProjectAction`, `renameConversationAction`, `signOutAction`), `relativeTime`; types `Project`, `Conversation`, `PanelUser`.
- Produces:
  - `ConfirmAction({ action, title, description, confirmLabel, trigger?, open?, onOpenChange? })` — client component; `action: () => Promise<void>`; supports trigger-based or controlled usage. Reused by Tasks 5 and 7.
  - `NewConversationDialog({ projectId, agents, trigger }: { projectId: string; agents: string[]; trigger: React.ReactNode })` — reused by Task 5's hero CTA.
  - `AppSidebar({ projects, conversations, activeProjectId, user, agents })` — active conversation derived internally via `usePathname()`.

- [ ] **Step 1: Create `components/confirm-action.tsx`**

```tsx
'use client';

import { useTransition } from 'react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';

export function ConfirmAction({
  action,
  title,
  description,
  confirmLabel,
  trigger,
  open,
  onOpenChange,
}: {
  action: () => Promise<void>;
  title: string;
  description: string;
  confirmLabel: string;
  trigger?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [pending, startTransition] = useTransition();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {trigger ? <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger> : null}
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            onClick={() => startTransition(async () => action())}
          >
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

Bound server actions are passed from callers as `someAction.bind(null, id)` — legal in client components; React serializes bound arguments.

- [ ] **Step 2: Create `components/new-conversation-dialog.tsx`**

```tsx
'use client';

import { createConversationAction } from '@/app/actions';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

export function NewConversationDialog({
  projectId,
  agents,
  trigger,
}: {
  projectId: string;
  agents: string[];
  trigger: React.ReactNode;
}) {
  const action = createConversationAction.bind(null, projectId);
  return (
    <Dialog>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New conversation</DialogTitle>
          <DialogDescription>Pick the agent to talk to.</DialogDescription>
        </DialogHeader>
        <form action={action} className="flex flex-col gap-3">
          <Select name="agent" required>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Choose an agent…" />
            </SelectTrigger>
            <SelectContent>
              {agents.map(a => (
                <SelectItem key={a} value={a}>
                  {a}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit">Start conversation</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Create `components/app-sidebar.tsx`** — the whole file:

```tsx
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { useTheme } from 'next-themes';
import {
  createProjectAction,
  deleteConversationAction,
  deleteProjectAction,
  renameConversationAction,
  signOutAction,
} from '@/app/actions';
import type { Conversation, PanelUser, Project } from '@/lib/types';
import { relativeTime } from '@/lib/format';
import { ConfirmAction } from '@/components/confirm-action';
import { NewConversationDialog } from '@/components/new-conversation-dialog';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar';
import {
  ChevronsUpDownIcon,
  FolderIcon,
  LogOutIcon,
  MonitorIcon,
  MoonIcon,
  MoreHorizontalIcon,
  PencilIcon,
  PlusIcon,
  SunIcon,
  TrashIcon,
  UsersIcon,
} from 'lucide-react';

export function AppSidebar({
  projects,
  conversations,
  activeProjectId,
  user,
  agents,
}: {
  projects: Project[];
  conversations: Conversation[];
  activeProjectId: string;
  user: PanelUser;
  agents: string[];
}) {
  const activeProject = projects.find(p => p.id === activeProjectId);
  return (
    <Sidebar>
      <SidebarHeader>
        <ProjectSwitcher projects={projects} activeProject={activeProject} />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Conversations</SidebarGroupLabel>
          <NewConversationDialog
            projectId={activeProjectId}
            agents={agents}
            trigger={
              <SidebarGroupAction aria-label="New conversation">
                <PlusIcon />
              </SidebarGroupAction>
            }
          />
          <SidebarGroupContent>
            <SidebarMenu>
              {conversations.map(c => (
                <ConversationItem
                  key={c.id}
                  conversation={c}
                  projectId={activeProjectId}
                />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <UserMenu user={user} />
      </SidebarFooter>
    </Sidebar>
  );
}

function ProjectSwitcher({
  projects,
  activeProject,
}: {
  projects: Project[];
  activeProject?: Project;
}) {
  const [newOpen, setNewOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg">
              <div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <FolderIcon className="size-4" />
              </div>
              <span className="truncate font-medium">
                {activeProject?.name ?? 'Projects'}
              </span>
              <ChevronsUpDownIcon className="ml-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>Projects</DropdownMenuLabel>
            {projects.map(p => (
              <DropdownMenuItem key={p.id} asChild>
                <Link href={`/p/${p.id}`}>{p.name}</Link>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => setNewOpen(true)}>
              <PlusIcon /> New project
            </DropdownMenuItem>
            {activeProject && !activeProject.is_default && (
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => setDeleteOpen(true)}
              >
                <TrashIcon /> Delete project
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
      <Dialog open={newOpen} onOpenChange={setNewOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New project</DialogTitle>
            <DialogDescription>
              Projects group conversations and can be shared with teammates.
            </DialogDescription>
          </DialogHeader>
          <form action={createProjectAction} className="flex gap-2">
            <Input name="name" placeholder="Project name" autoFocus required />
            <Button type="submit">Create</Button>
          </form>
        </DialogContent>
      </Dialog>
      {activeProject && (
        <ConfirmAction
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
          action={deleteProjectAction.bind(null, activeProject.id)}
          title="Delete project?"
          description={`"${activeProject.name}" and all its conversations will be permanently deleted.`}
          confirmLabel="Delete"
        />
      )}
    </SidebarMenu>
  );
}

function ConversationItem({
  conversation: c,
  projectId,
}: {
  conversation: Conversation;
  projectId: string;
}) {
  const pathname = usePathname();
  const [renameOpen, setRenameOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const rename = renameConversationAction.bind(null, projectId, c.id);
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={pathname === `/p/${projectId}/c/${c.id}`}
        className="h-auto py-1.5"
      >
        <Link href={`/p/${projectId}/c/${c.id}`}>
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate">{c.title || 'Untitled'}</span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Badge variant="outline" className="px-1 py-0 text-[10px]">
                {c.agent_name}
              </Badge>
              {relativeTime(c.updated_at)}
            </span>
          </div>
        </Link>
      </SidebarMenuButton>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction showOnHover aria-label="Conversation actions">
            <MoreHorizontalIcon />
          </SidebarMenuAction>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuItem onSelect={() => setRenameOpen(true)}>
            <PencilIcon /> Rename
          </DropdownMenuItem>
          <DropdownMenuItem
            variant="destructive"
            onSelect={() => setDeleteOpen(true)}
          >
            <TrashIcon /> Delete
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
          </DialogHeader>
          <form
            action={async fd => {
              await rename(fd);
              setRenameOpen(false);
            }}
            className="flex gap-2"
          >
            <Input name="title" defaultValue={c.title} autoFocus required />
            <Button type="submit">Save</Button>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmAction
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        action={deleteConversationAction.bind(null, projectId, c.id)}
        title="Delete conversation?"
        description={`"${c.title || 'Untitled'}" and its messages will be permanently deleted.`}
        confirmLabel="Delete"
      />
    </SidebarMenuItem>
  );
}

function UserMenu({ user }: { user: PanelUser }) {
  const { setTheme } = useTheme();
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg">
              <Avatar className="size-8">
                <AvatarImage src={user.image} alt="" />
                <AvatarFallback>
                  {(user.name || user.email).slice(0, 1).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="flex min-w-0 flex-col text-left">
                <span className="truncate text-sm font-medium">
                  {user.name || user.email}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {user.email}
                </span>
              </div>
              <ChevronsUpDownIcon className="ml-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent side="top" align="start" className="w-56">
            {user.role === 'admin' && (
              <>
                <DropdownMenuItem asChild>
                  <Link href="/admin/users">
                    <UsersIcon /> Manage users
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
              </>
            )}
            <DropdownMenuLabel>Theme</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => setTheme('light')}>
              <SunIcon /> Light
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setTheme('dark')}>
              <MoonIcon /> Dark
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setTheme('system')}>
              <MonitorIcon /> System
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => signOutAction()}>
              <LogOutIcon /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
```

Note: if the vendored `DropdownMenuItem` has no `variant` prop (older template), replace `variant="destructive"` with `className="text-destructive focus:text-destructive"`.

- [ ] **Step 4: Rewrite `app/p/[projectId]/layout.tsx`**

```tsx
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { AppSidebar } from '@/components/app-sidebar';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { getBootstrap, listConversations, listProjects } from '@/lib/panel';

export default async function ProjectLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');
  const [{ projects }, { conversations }] = await Promise.all([
    listProjects(email),
    listConversations(email, projectId),
  ]);
  return (
    <SidebarProvider>
      <AppSidebar
        projects={projects}
        conversations={conversations}
        activeProjectId={projectId}
        user={bootstrap.user}
        agents={bootstrap.agents}
      />
      <SidebarInset>{children}</SidebarInset>
    </SidebarProvider>
  );
}
```

- [ ] **Step 5: Delete the absorbed components**

```bash
git rm packages/typescript/vystak-panel/components/sidebar.tsx \
       packages/typescript/vystak-panel/components/new-conversation.tsx
```

`app/p/[projectId]/page.tsx` still imports `NewConversation` — it breaks typecheck until Task 5. To keep the task independently green, apply Task 5's minimal stub now: in `app/p/[projectId]/page.tsx`, remove the `NewConversation` import and the `<NewConversation …/>` line (the full page rewrite lands in Task 5).

- [ ] **Step 6: Verify**

```bash
pnpm run typecheck   # expected: exit 0
pnpm run test        # expected: 3 files passing
pnpm run dev         # manual: sidebar renders with project switcher, conversation list,
                     # user menu; theme switching works; sign out works; stop server
```

- [ ] **Step 7: Commit**

```bash
git add -A packages/typescript/vystak-panel
git commit -m "feat(panel): app shell — collapsible sidebar with projects, conversations, user menu"
```

---

### Task 5: Project page — header, empty-state hero, project-settings dialog

**Files:**
- Create: `packages/typescript/vystak-panel/components/page-header.tsx`
- Create: `packages/typescript/vystak-panel/components/project-settings.tsx`
- Rewrite: `packages/typescript/vystak-panel/app/p/[projectId]/page.tsx`
- Delete: `packages/typescript/vystak-panel/components/members.tsx`

**Interfaces:**
- Consumes: `ConfirmAction`, `NewConversationDialog` (Task 4); `addMemberAction`, `removeMemberAction`; `listMembers`, `listProjects`, `getBootstrap` from `@/lib/panel`.
- Produces:
  - `PageHeader({ children })` — server-compatible header shell; used by Task 6's conversation page.
  - `ProjectSettings({ projectId, members }: { projectId: string; members: PanelUser[] })` — client dialog; used by Task 6's conversation page too.

- [ ] **Step 1: Create `components/page-header.tsx`**

```tsx
import { Separator } from '@/components/ui/separator';
import { SidebarTrigger } from '@/components/ui/sidebar';

export function PageHeader({ children }: { children: React.ReactNode }) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="h-5" />
      {children}
    </header>
  );
}
```

- [ ] **Step 2: Create `components/project-settings.tsx`**

```tsx
'use client';

import { addMemberAction, removeMemberAction } from '@/app/actions';
import type { PanelUser } from '@/lib/types';
import { ConfirmAction } from '@/components/confirm-action';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Settings2Icon, XIcon } from 'lucide-react';

export function ProjectSettings({
  projectId,
  members,
}: {
  projectId: string;
  members: PanelUser[];
}) {
  const add = addMemberAction.bind(null, projectId);
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <Settings2Icon /> Project settings
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Project settings</DialogTitle>
          <DialogDescription>
            People with access to this project.
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-1">
          {members.map(m => (
            <li
              key={m.id}
              className="flex items-center justify-between rounded-md px-2 py-1.5 text-sm"
            >
              <span className="truncate">{m.email}</span>
              <ConfirmAction
                action={removeMemberAction.bind(null, projectId, m.id)}
                title="Remove member?"
                description={`${m.email} will lose access to this project.`}
                confirmLabel="Remove"
                trigger={
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={`Remove ${m.email}`}
                  >
                    <XIcon />
                  </Button>
                }
              />
            </li>
          ))}
        </ul>
        <form action={add} className="flex gap-2">
          <Input
            name="email"
            type="email"
            placeholder="person@example.com"
            required
          />
          <Button type="submit">Share</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Rewrite `app/p/[projectId]/page.tsx`**

```tsx
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { NewConversationDialog } from '@/components/new-conversation-dialog';
import { PageHeader } from '@/components/page-header';
import { ProjectSettings } from '@/components/project-settings';
import { Button } from '@/components/ui/button';
import { getBootstrap, listMembers, listProjects } from '@/lib/panel';
import { MessagesSquareIcon, PlusIcon } from 'lucide-react';

export default async function ProjectPage({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');
  const [{ projects }, { members }] = await Promise.all([
    listProjects(email),
    listMembers(email, projectId),
  ]);
  const project = projects.find(p => p.id === projectId);
  return (
    <div className="flex h-svh flex-col">
      <PageHeader>
        <h1 className="truncate text-sm font-medium">
          {project?.name ?? 'Project'}
        </h1>
        <div className="ml-auto">
          <ProjectSettings projectId={projectId} members={members} />
        </div>
      </PageHeader>
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="flex max-w-sm flex-col items-center gap-4 text-center">
          <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-primary">
            <MessagesSquareIcon className="size-6" />
          </div>
          <h2 className="text-lg font-semibold">Start a conversation</h2>
          <p className="text-sm text-muted-foreground">
            Pick one of your deployed agents and start chatting. Conversations
            appear in the sidebar.
          </p>
          <NewConversationDialog
            projectId={projectId}
            agents={bootstrap.agents}
            trigger={
              <Button>
                <PlusIcon /> New conversation
              </Button>
            }
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Delete `components/members.tsx`**

```bash
git rm packages/typescript/vystak-panel/components/members.tsx
```

- [ ] **Step 5: Verify**

```bash
pnpm run typecheck   # expected: exit 0
pnpm run test        # expected: 3 files passing
pnpm run dev         # manual: project page shows hero + working New-conversation CTA;
                     # Project settings dialog lists members, add/remove works with confirm
```

- [ ] **Step 6: Commit**

```bash
git add -A packages/typescript/vystak-panel
git commit -m "feat(panel): project page hero and project-settings members dialog"
```

---

### Task 6: Chat surface — AI Elements chat, conversation header, parts-aware replay

**Files:**
- Rewrite: `packages/typescript/vystak-panel/components/chat.tsx`
- Create: `packages/typescript/vystak-panel/components/conversation-title.tsx`
- Rewrite: `packages/typescript/vystak-panel/app/p/[projectId]/c/[convId]/page.tsx`

**Interfaces:**
- Consumes: AI Elements components (Task 2 — **read the vendored files first; their prop names are authoritative** over the reference code below); `PageHeader`, `ProjectSettings` (Task 5); `renameConversationAction`, `safeParseJson`, `StoredPart` (Task 3).
- Produces: `Chat({ conversationId, initialMessages, agentName })` — same props as today; `ConversationTitle({ projectId, convId, title })`.

- [ ] **Step 1: Read the vendored AI Elements sources** (`components/ai-elements/prompt-input.tsx`, `tool.tsx`, `conversation.tsx`, `message.tsx`, `response.tsx`, `loader.tsx`) and confirm: the `PromptInput` submit payload shape, `PromptInputSubmit`'s `status` prop, `ToolHeader`'s `type`/`state` props, `ToolOutput`'s `output`/`errorText` props. Adapt the code below where the vendored API differs.

- [ ] **Step 2: Create `components/conversation-title.tsx`**

```tsx
'use client';

import { useState } from 'react';
import { renameConversationAction } from '@/app/actions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PencilIcon } from 'lucide-react';

export function ConversationTitle({
  projectId,
  convId,
  title,
}: {
  projectId: string;
  convId: string;
  title: string;
}) {
  const [editing, setEditing] = useState(false);
  const action = renameConversationAction.bind(null, projectId, convId);
  if (!editing) {
    return (
      <div className="flex min-w-0 items-center gap-1">
        <h1 className="truncate text-sm font-medium">{title || 'Untitled'}</h1>
        <Button
          variant="ghost"
          size="icon"
          className="size-6"
          aria-label="Rename conversation"
          onClick={() => setEditing(true)}
        >
          <PencilIcon className="size-3.5" />
        </Button>
      </div>
    );
  }
  return (
    <form
      action={async fd => {
        await action(fd);
        setEditing(false);
      }}
      className="flex items-center gap-2"
    >
      <Input
        name="title"
        defaultValue={title}
        autoFocus
        required
        className="h-8 w-64"
        onKeyDown={e => {
          if (e.key === 'Escape') setEditing(false);
        }}
      />
      <Button type="submit" size="sm">
        Save
      </Button>
    </form>
  );
}
```

- [ ] **Step 3: Rewrite `components/chat.tsx`** — the `useChat` block is copied verbatim from the current file (working contract); everything around it is new:

```tsx
'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';
import type { UIMessage } from 'ai';
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from '@/components/ai-elements/conversation';
import { Loader } from '@/components/ai-elements/loader';
import { Message, MessageContent } from '@/components/ai-elements/message';
import {
  PromptInput,
  PromptInputSubmit,
  PromptInputTextarea,
} from '@/components/ai-elements/prompt-input';
import { Response } from '@/components/ai-elements/response';
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from '@/components/ai-elements/tool';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { AlertCircleIcon } from 'lucide-react';

export function Chat({
  conversationId,
  initialMessages,
  agentName,
}: {
  conversationId: string;
  initialMessages: UIMessage[];
  agentName: string;
}) {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, error, clearError, stop } = useChat({
    id: conversationId,
    messages: initialMessages,
    transport: new DefaultChatTransport({
      api: '/api/chat',
      prepareSendMessagesRequest({ messages }) {
        const last = messages[messages.length - 1];
        const text = last.parts
          .filter(p => p.type === 'text')
          .map(p => p.text)
          .join('');
        return { body: { conversationId, text } };
      },
    }),
  });

  const busy = status === 'submitted' || status === 'streaming';

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Conversation className="flex-1">
        <ConversationContent className="mx-auto w-full max-w-3xl">
          {messages.map(message => (
            <Message from={message.role} key={message.id}>
              <MessageContent>
                {message.parts.map((part, i) => {
                  if (part.type === 'text') {
                    return (
                      <Response key={`${message.id}-${i}`}>{part.text}</Response>
                    );
                  }
                  if (part.type === 'dynamic-tool') {
                    return (
                      <Tool
                        key={part.toolCallId}
                        defaultOpen={part.state === 'output-error'}
                      >
                        <ToolHeader
                          type={`tool-${part.toolName}`}
                          state={part.state}
                        />
                        <ToolContent>
                          <ToolInput input={part.input} />
                          <ToolOutput
                            output={
                              part.state === 'output-available' ? (
                                <Response>
                                  {'```json\n' +
                                    JSON.stringify(part.output, null, 2) +
                                    '\n```'}
                                </Response>
                              ) : undefined
                            }
                            errorText={
                              part.state === 'output-error'
                                ? part.errorText
                                : undefined
                            }
                          />
                        </ToolContent>
                      </Tool>
                    );
                  }
                  return null;
                })}
              </MessageContent>
            </Message>
          ))}
          {status === 'submitted' && <Loader />}
        </ConversationContent>
        <ConversationScrollButton />
      </Conversation>
      {error && (
        <Alert
          variant="destructive"
          className="mx-auto mb-2 w-full max-w-3xl shrink-0"
        >
          <AlertCircleIcon />
          <AlertTitle>Agent error</AlertTitle>
          <AlertDescription className="flex items-center justify-between gap-2">
            <span>{error.message}</span>
            <Button variant="outline" size="sm" onClick={() => clearError()}>
              Dismiss
            </Button>
          </AlertDescription>
        </Alert>
      )}
      <div className="mx-auto w-full max-w-3xl shrink-0 p-4 pt-0">
        <PromptInput
          onSubmit={message => {
            if (busy) {
              stop();
              return;
            }
            const text = message.text?.trim() ?? input.trim();
            if (!text) return;
            sendMessage({ text });
            setInput('');
          }}
        >
          <PromptInputTextarea
            value={input}
            placeholder={`Message ${agentName}…`}
            onChange={e => {
              if (error) clearError();
              setInput(e.target.value);
            }}
          />
          <PromptInputSubmit status={status} />
        </PromptInput>
      </div>
    </div>
  );
}
```

Behavior contract regardless of vendored prop details: Enter sends, Shift+Enter inserts a newline (PromptInput's default), the submit button becomes a Stop control while `busy` (wired to `stop()`), and the input clears only on successful send.

- [ ] **Step 4: Rewrite `app/p/[projectId]/c/[convId]/page.tsx`**

```tsx
import { redirect } from 'next/navigation';
import type { UIMessage } from 'ai';
import { auth } from '@/auth';
import { Chat } from '@/components/chat';
import { ConversationTitle } from '@/components/conversation-title';
import { PageHeader } from '@/components/page-header';
import { ProjectSettings } from '@/components/project-settings';
import { Badge } from '@/components/ui/badge';
import { safeParseJson } from '@/lib/format';
import {
  getBootstrap,
  listConversations,
  listMembers,
  listMessages,
} from '@/lib/panel';
import type { StoredPart } from '@/lib/types';

type UIPart = UIMessage['parts'][number];

function toUIParts(parts: StoredPart[] | null | undefined, content: string): UIPart[] {
  if (!parts?.length) return [{ type: 'text', text: content }];
  return parts.map<UIPart>(p =>
    p.type === 'tool'
      ? ({
          type: 'dynamic-tool',
          toolCallId: p.tool_call_id,
          toolName: p.tool_name,
          state: 'output-available',
          input: safeParseJson(p.input),
          output: safeParseJson(p.output),
        } as UIPart)
      : { type: 'text', text: p.text },
  );
}

export default async function ConversationPage({
  params,
}: {
  params: Promise<{ projectId: string; convId: string }>;
}) {
  const { projectId, convId } = await params;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  if (!bootstrap.user) redirect('/signin?error=AccessDenied');

  const [{ conversations }, { messages }, { members }] = await Promise.all([
    listConversations(email, projectId),
    listMessages(email, convId),
    listMembers(email, projectId),
  ]);
  const conversation = conversations.find(c => c.id === convId);
  if (!conversation) redirect(`/p/${projectId}`);

  const initialMessages: UIMessage[] = messages.map(m => ({
    id: m.id,
    role: m.role,
    parts: toUIParts(m.parts, m.content),
  }));

  return (
    <div className="flex h-svh flex-col">
      <PageHeader>
        <ConversationTitle
          projectId={projectId}
          convId={convId}
          title={conversation.title}
        />
        <Badge variant="secondary">{conversation.agent_name}</Badge>
        <div className="ml-auto">
          <ProjectSettings projectId={projectId} members={members} />
        </div>
      </PageHeader>
      <Chat
        conversationId={convId}
        initialMessages={initialMessages}
        agentName={conversation.agent_name}
      />
    </div>
  );
}
```

The `as UIPart` cast on the dynamic-tool branch is deliberate: the AI SDK's `DynamicToolUIPart` output-available variant carries optional metadata fields we don't persist. If typecheck rejects the cast shape, match the exact variant from `ai`'s `.d.ts` rather than loosening types elsewhere.

- [ ] **Step 5: Verify**

```bash
pnpm run typecheck   # expected: exit 0
pnpm run test        # expected: 3 files passing
pnpm run dev         # manual, against a running docker-panel deployment:
                     # send a message → user bubble right-aligned, markdown renders,
                     # loader shows before first token, stop button appears while streaming,
                     # tool call renders as collapsible block (if backend Tasks 2-4 deployed),
                     # reload → history replays including tool blocks
```

- [ ] **Step 6: Commit**

```bash
git add -A packages/typescript/vystak-panel
git commit -m "feat(panel): AI Elements chat surface with markdown, tool blocks, and inline rename"
```

---

### Task 7: Admin users page restyle

**Files:**
- Rewrite: `packages/typescript/vystak-panel/app/admin/users/page.tsx`

**Interfaces:**
- Consumes: `ConfirmAction` (Task 4); `Table`/`Badge`/`Select`/`Input`/`Button` (Task 2); existing `addUserAction`, `setUserStatusAction`.
- Produces: nothing new.

- [ ] **Step 1: Rewrite the page**

```tsx
import Link from 'next/link';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import { addUserAction, setUserStatusAction } from '@/app/actions';
import { ConfirmAction } from '@/components/confirm-action';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getBootstrap, listUsers } from '@/lib/panel';
import { ArrowLeftIcon } from 'lucide-react';

export default async function UsersPage() {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  const bootstrap = await getBootstrap(email);
  const me = bootstrap.user;
  if (me?.role !== 'admin') redirect('/');
  const { users } = await listUsers(email);

  return (
    <main className="mx-auto w-full max-w-3xl p-6">
      <div className="mb-6 flex items-center gap-2">
        <Button variant="ghost" size="icon" asChild aria-label="Back to panel">
          <Link href="/">
            <ArrowLeftIcon />
          </Link>
        </Button>
        <h1 className="text-lg font-semibold">Users</h1>
      </div>
      <form action={addUserAction} className="mb-6 flex gap-2">
        <Input
          name="email"
          type="email"
          placeholder="person@example.com"
          required
        />
        <Select name="role" defaultValue="member">
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="member">member</SelectItem>
            <SelectItem value="admin">admin</SelectItem>
          </SelectContent>
        </Select>
        <Button type="submit">Invite</Button>
      </form>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Email</TableHead>
            <TableHead>Role</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="w-32 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map(u => (
            <TableRow key={u.id}>
              <TableCell className="font-medium">{u.email}</TableCell>
              <TableCell>
                <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
                  {u.role}
                </Badge>
              </TableCell>
              <TableCell>
                <Badge
                  variant={u.status === 'active' ? 'outline' : 'destructive'}
                >
                  {u.status}
                </Badge>
              </TableCell>
              <TableCell className="text-right">
                {/* No self-deactivation: the channel only refuses removing
                    the LAST admin, so with a second admin present one stray
                    click would end your own session. */}
                {u.id === me.id ? (
                  <span className="text-sm text-muted-foreground">you</span>
                ) : u.status === 'active' ? (
                  <ConfirmAction
                    action={setUserStatusAction.bind(null, u.id, 'deactivated')}
                    title="Deactivate user?"
                    description={`${u.email} will immediately lose access to the panel.`}
                    confirmLabel="Deactivate"
                    trigger={
                      <Button variant="outline" size="sm">
                        Deactivate
                      </Button>
                    }
                  />
                ) : (
                  <form action={setUserStatusAction.bind(null, u.id, 'active')}>
                    <Button variant="outline" size="sm" type="submit">
                      Reactivate
                    </Button>
                  </form>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </main>
  );
}
```

Reactivation is not destructive, so it keeps a plain form; only Deactivate confirms.

- [ ] **Step 2: Verify and commit**

```bash
pnpm run typecheck && pnpm run test    # expected: green
git add -A packages/typescript/vystak-panel
git commit -m "feat(panel): admin users table with badges and deactivate confirmation"
```

---

### Task 8: Sign-in page and error page restyle

**Files:**
- Rewrite: `packages/typescript/vystak-panel/app/signin/page.tsx`
- Rewrite: `packages/typescript/vystak-panel/app/error.tsx`

**Interfaces:**
- Consumes: `Card`/`Alert`/`Button` (Task 2). Auth flow (`signIn('google', …)` inline server action) unchanged.
- Produces: nothing new.

- [ ] **Step 1: Rewrite `app/signin/page.tsx`**

```tsx
import { redirect } from 'next/navigation';
import { auth, signIn } from '@/auth';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { AlertCircleIcon } from 'lucide-react';

function GoogleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-4">
      <path
        fill="currentColor"
        d="M21.35 11.1H12v2.9h5.35c-.25 1.4-1.02 2.58-2.17 3.38v2.8h3.5c2.05-1.9 3.22-4.7 3.22-8.03 0-.66-.06-1.3-.15-1.05Z"
      />
      <path
        fill="currentColor"
        d="M12 22c2.7 0 4.97-.9 6.63-2.42l-3.5-2.8c-.9.6-2.05.96-3.13.96-2.4 0-4.44-1.62-5.17-3.8H3.2v2.88C4.85 19.98 8.2 22 12 22Z"
        opacity=".8"
      />
      <path
        fill="currentColor"
        d="M6.83 13.94A5.9 5.9 0 0 1 6.5 12c0-.67.12-1.33.33-1.94V7.18H3.2A9.98 9.98 0 0 0 2 12c0 1.62.39 3.15 1.2 4.82l3.63-2.88Z"
        opacity=".6"
      />
      <path
        fill="currentColor"
        d="M12 6.25c1.47 0 2.79.5 3.83 1.5l2.87-2.87C16.96 3.3 14.7 2.3 12 2.3 8.2 2.3 4.85 4.32 3.2 7.18l3.63 2.88C7.56 7.88 9.6 6.25 12 6.25Z"
        opacity=".9"
      />
    </svg>
  );
}

export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await searchParams;
  const session = await auth();
  if (session?.user?.email && !error) redirect('/');
  return (
    <main className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex size-10 items-center justify-center rounded-lg bg-primary text-lg font-bold text-primary-foreground">
            V
          </div>
          <CardTitle className="text-xl">Vystak Panel</CardTitle>
          <CardDescription>
            Sign in with your invited Google account.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error === 'AccessDenied' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Not invited</AlertTitle>
              <AlertDescription>
                This Google account has not been invited. Ask an administrator
                to add your email.
              </AlertDescription>
            </Alert>
          )}
          {error === 'PanelUnavailable' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Panel unreachable</AlertTitle>
              <AlertDescription>
                Could not reach the control panel API. Try again, or contact an
                administrator.
              </AlertDescription>
            </Alert>
          )}
          {error && error !== 'AccessDenied' && error !== 'PanelUnavailable' && (
            <Alert variant="destructive">
              <AlertCircleIcon />
              <AlertTitle>Sign-in failed</AlertTitle>
              <AlertDescription>
                Contact an administrator if this persists.
              </AlertDescription>
            </Alert>
          )}
          <form
            action={async () => {
              'use server';
              await signIn('google', { redirectTo: '/' });
            }}
          >
            <Button type="submit" variant="outline" className="w-full">
              <GoogleIcon /> Continue with Google
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
```

- [ ] **Step 2: Rewrite `app/error.tsx`**

```tsx
'use client';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { AlertCircleIcon } from 'lucide-react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <div className="flex w-full max-w-md flex-col items-center gap-4">
        <Alert variant="destructive">
          <AlertCircleIcon />
          <AlertTitle>Something went wrong</AlertTitle>
          <AlertDescription>
            The control panel could not complete that request. The panel API
            may be unavailable.
          </AlertDescription>
        </Alert>
        <Button onClick={() => reset()}>Try again</Button>
      </div>
    </main>
  );
}
```

(The generic copy is intentional — `error.message` from a server component is redacted in production, so printing it adds nothing.)

- [ ] **Step 3: Verify and commit**

```bash
pnpm run typecheck && pnpm run test    # expected: green
git add -A packages/typescript/vystak-panel
git commit -m "feat(panel): branded sign-in card and styled error page"
```

---

### Task 9: Full verification against the live example

**Files:** none (verification only; fix-up commits allowed).

- [ ] **Step 1: Repo gates**

```bash
cd <repo root>
just lint-python           # expected: pass (nothing Python changed — confirms it)
just test-python           # expected: pass
just typecheck-typescript  # expected: pass (also proves no stray `build` script)
just test-typescript       # expected: pass — includes tests/format.test.ts
```

- [ ] **Step 2: Deploy the example** (skip redeploy if the docker-panel deployment from the tool-call branch is already running):

```bash
cd examples/docker-panel && vystak apply --force
```

- [ ] **Step 3: Manual checklist from the spec** — run `pnpm run dev` in `packages/typescript/vystak-panel` against the deployment and verify each item:

- [ ] Sign in via Google → branded card, error states render as alerts.
- [ ] Create a project from the switcher; create a conversation from the sidebar **and** from the hero CTA.
- [ ] Send a message that triggers a tool call ("What is the weather in Kyiv?"): markdown renders, loader shows before first token, tool block appears with state transitions, stop button works mid-stream.
- [ ] Reload the conversation → history replays, tool block intact (requires tool-call branch Tasks 1–4 deployed; otherwise text-only replay is the correct fallback).
- [ ] Rename a conversation from the header pencil and from the sidebar item menu; delete a conversation (confirm dialog; deleting the open conversation lands on the project page).
- [ ] Project settings: add a member by email, remove with confirmation.
- [ ] Admin: invite a user, deactivate with confirmation, reactivate, "you" guard on self.
- [ ] Theme: toggle Light/Dark/System from the user menu; both themes look deliberate (no unstyled surfaces); choice survives reload.
- [ ] Sign out from the user menu → back to sign-in.
- [ ] Narrow the window to phone width → sidebar collapses to the off-canvas sheet via the header trigger; no horizontal scroll in chat.

- [ ] **Step 4: Final commit** (only if fixes were needed) and report results against the spec's Definition of Done.

---

## Self-review notes

- Spec coverage: shell/sidebar (T4), project page + members dialog (T5), chat + tool rendering + replay + loader + stop (T6), admin (T7), sign-in + error (T8), theming (T1), vendored components (T2), data additions (T3), verification (T9). Spec's "delete project" and "rename conversation" land in T4/T6 via T3's actions.
- The only intentional deviation from current behavior: `deleteConversationAction` redirects instead of revalidating (reason documented in T3).
- Vendored-API drift is handled by explicit "read the vendored file first" steps (T2 S3, T6 S1) — reference code is written to the documented API and marked adaptable.
