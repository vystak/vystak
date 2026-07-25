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
              <span className="min-w-0 flex-1 truncate">{m.email}</span>
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
