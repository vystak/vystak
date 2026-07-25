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
              <span suppressHydrationWarning>{relativeTime(c.updated_at)}</span>
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
            <DialogDescription>Give this conversation a new name.</DialogDescription>
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
            <DropdownMenuItem onSelect={() => void signOutAction()}>
              <LogOutIcon /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
