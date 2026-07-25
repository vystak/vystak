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
