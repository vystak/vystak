'use client';

import { useState } from 'react';
import { setUserPasswordAction } from '@/app/actions';
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
import { KeyRoundIcon } from 'lucide-react';

export function SetPasswordDialog({
  userId,
  email,
}: {
  userId: string;
  email: string;
}) {
  const [open, setOpen] = useState(false);
  const action = setUserPasswordAction.bind(null, userId);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <KeyRoundIcon /> Set password
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Set password</DialogTitle>
          <DialogDescription>
            Set a sign-in password for {email}. This replaces any existing
            password.
          </DialogDescription>
        </DialogHeader>
        <form
          action={async fd => {
            await action(fd);
            setOpen(false);
          }}
          className="flex gap-2"
        >
          <Input
            name="password"
            type="password"
            placeholder="Min 8 characters"
            minLength={8}
            autoComplete="new-password"
            autoFocus
            required
          />
          <Button type="submit">Save</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
