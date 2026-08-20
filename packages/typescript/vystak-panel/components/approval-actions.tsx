'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * Approve/Deny controls for a parked HITL tool call. Rendered by chat.tsx
 * inside a <Tool>'s <ToolContent> for a dynamic-tool part that is still
 * awaiting a decision (see the caller for how that's determined on the
 * live vs. persisted-history path).
 *
 * POSTs straight to the Next route (not a server action) — `lib/panel.ts`'s
 * `postApproval` is `server-only` and this runs client-side, same reason
 * `components/chat.tsx`'s `sendMessage` transport hits `/api/chat` rather
 * than importing `lib/panel.ts` directly.
 */
export function ApprovalActions({
  conversationId,
  turnId,
  onDecided,
}: {
  conversationId: string;
  turnId: string | null;
  // Called after a successful (200) decision so the caller can try to pull
  // the resumed turn's content into view (e.g. reopening the resume-stream
  // connection) without a full page reload.
  onDecided?: () => void;
}) {
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resolved, setResolved] = useState(false);

  if (resolved) return null;

  const decide = async (approved: boolean) => {
    if (!turnId) {
      setError('no active turn to decide');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/conversations/${conversationId}/approval`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ turn_id: turnId, approved, note: note.trim() || null }),
      });
      if (!res.ok) {
        const text = await res.text();
        setError(text || `request failed (${res.status})`);
        setBusy(false);
        return;
      }
      setResolved(true);
      onDecided?.();
    } catch {
      setError('could not reach the panel — try again');
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2 border-t p-3">
      <div className="flex items-center gap-2">
        <Input
          placeholder="Note (optional)"
          value={note}
          disabled={busy}
          onChange={e => setNote(e.target.value)}
        />
        <Button size="sm" disabled={busy} onClick={() => decide(true)}>
          Approve
        </Button>
        <Button
          size="sm"
          variant="destructive"
          disabled={busy}
          onClick={() => decide(false)}
        >
          Deny
        </Button>
      </div>
      {error && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
