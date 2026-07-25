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
