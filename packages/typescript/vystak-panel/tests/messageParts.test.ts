import { describe, expect, it } from 'vitest';
import type { UIMessage } from 'ai';
import { mapPersistedParts, pendingApprovalTurns, visiblePartsAfterReset } from '../lib/messageParts';
import type { MessagePart } from '../lib/types';

type UIPart = UIMessage['parts'][number];

describe('mapPersistedParts', () => {
  it('falls back to a single text part built from content when parts is null', () => {
    expect(mapPersistedParts(null, 'hello there')).toEqual([
      { type: 'text', text: 'hello there' },
    ]);
  });

  it('falls back to a single text part built from content when parts is empty', () => {
    expect(mapPersistedParts([], 'hello there')).toEqual([
      { type: 'text', text: 'hello there' },
    ]);
  });

  it('passes text parts through unchanged', () => {
    const parts: MessagePart[] = [{ type: 'text', text: 'hello' }];
    expect(mapPersistedParts(parts, 'hello')).toEqual([{ type: 'text', text: 'hello' }]);
  });

  it('maps a successful tool part to a finished dynamic-tool part with parsed input', () => {
    const parts: MessagePart[] = [
      {
        type: 'tool',
        tool_call_id: 'call_1',
        tool_name: 'get_weather',
        input: '{"city":"Kyiv"}',
        output: '{"temp_c":22}',
        is_error: false,
      },
    ];
    expect(mapPersistedParts(parts, '')).toEqual([
      {
        type: 'dynamic-tool',
        toolCallId: 'call_1',
        toolName: 'get_weather',
        state: 'output-available',
        input: { city: 'Kyiv' },
        output: '{"temp_c":22}',
      },
    ]);
  });

  it('maps a failed tool part to output-error with errorText from output', () => {
    const parts: MessagePart[] = [
      {
        type: 'tool',
        tool_call_id: 'call_2',
        tool_name: 'get_weather',
        input: '{"city":"Nowhere"}',
        output: 'city not found',
        is_error: true,
      },
    ];
    expect(mapPersistedParts(parts, '')).toEqual([
      {
        type: 'dynamic-tool',
        toolCallId: 'call_2',
        toolName: 'get_weather',
        state: 'output-error',
        input: { city: 'Nowhere' },
        errorText: 'city not found',
      },
    ]);
  });

  it('falls back to the raw string when persisted input is not valid JSON', () => {
    const parts: MessagePart[] = [
      {
        type: 'tool',
        tool_call_id: 'call_3',
        tool_name: 'noop',
        input: 'not json',
        output: 'ok',
        is_error: false,
      },
    ];
    const [mapped] = mapPersistedParts(parts, '');
    expect(mapped).toMatchObject({ input: 'not json' });
  });

  it('maps a persisted approval-requested part to an awaiting-approval tool part', () => {
    const parts: MessagePart[] = [
      {
        type: 'tool',
        state: 'approval-requested',
        tool_call_id: 'a1',
        tool_name: 'restart_service',
        input: '{"name":"web"}',
        output: '',
        is_error: false,
      },
    ];
    const mapped = mapPersistedParts(parts, '');
    expect(mapped[0].type).toBe('dynamic-tool');
    expect((mapped[0] as { state?: string }).state).toBe('approval-requested');
    expect(mapped).toEqual([
      {
        type: 'dynamic-tool',
        toolCallId: 'a1',
        toolName: 'restart_service',
        state: 'approval-requested',
        input: { name: 'web' },
      },
    ]);
  });

  it('maps a persisted resolved approval part as a normal completed tool part', () => {
    const parts: MessagePart[] = [
      {
        type: 'tool',
        state: 'resolved',
        tool_call_id: 'a1',
        tool_name: 'restart_service',
        input: '{"name":"web"}',
        output: '',
        is_error: false,
      },
    ];
    expect(mapPersistedParts(parts, '')).toEqual([
      {
        type: 'dynamic-tool',
        toolCallId: 'a1',
        toolName: 'restart_service',
        state: 'output-available',
        input: { name: 'web' },
        output: '',
      },
    ]);
  });

  it('preserves ordering across interleaved text and tool parts', () => {
    const parts: MessagePart[] = [
      { type: 'text', text: 'checking...' },
      {
        type: 'tool',
        tool_call_id: 'call_4',
        tool_name: 'get_weather',
        input: '{}',
        output: '"sunny"',
        is_error: false,
      },
      { type: 'text', text: 'it is sunny' },
    ];
    const mapped = mapPersistedParts(parts, '');
    expect(mapped.map(p => p.type)).toEqual(['text', 'dynamic-tool', 'text']);
  });
});

describe('pendingApprovalTurns', () => {
  it('reports a marker with no later same-tool output as pending', () => {
    const parts: UIPart[] = [
      {
        type: 'dynamic-tool',
        toolCallId: 'approval:restart_service',
        toolName: 'restart_service',
        state: 'input-available',
        input: { name: 'web' },
      },
      { type: 'data-approval', data: { toolCallId: 'approval:restart_service', turnId: 't1' } },
    ];
    expect(pendingApprovalTurns(parts)).toEqual(
      new Map([['approval:restart_service', 't1']]),
    );
  });

  it('drops a marker once a later same-tool-name part has output', () => {
    const parts: UIPart[] = [
      {
        type: 'dynamic-tool',
        toolCallId: 'approval:restart_service',
        toolName: 'restart_service',
        state: 'input-available',
        input: { name: 'web' },
      },
      { type: 'data-approval', data: { toolCallId: 'approval:restart_service', turnId: 't1' } },
      {
        type: 'dynamic-tool',
        toolCallId: 'c1',
        toolName: 'restart_service',
        state: 'output-available',
        input: { name: 'web' },
        output: 'restarted web',
      },
    ];
    expect(pendingApprovalTurns(parts)).toEqual(new Map());
  });
});

describe('visiblePartsAfterReset', () => {
  it('returns everything unchanged when there is no reset marker', () => {
    const parts: UIPart[] = [
      { type: 'text', text: 'a' },
      { type: 'text', text: 'b' },
    ];
    expect(visiblePartsAfterReset(parts)).toEqual(parts);
  });

  it('drops everything up to and including the reset marker', () => {
    const parts: UIPart[] = [
      { type: 'text', text: 'stale' },
      { type: 'data-reset', data: {} },
      { type: 'text', text: 'fresh' },
    ];
    expect(visiblePartsAfterReset(parts)).toEqual([{ type: 'text', text: 'fresh' }]);
  });

  it('keeps only what follows the last of multiple reset markers', () => {
    const parts: UIPart[] = [
      { type: 'text', text: 'stale-1' },
      { type: 'data-reset', data: {} },
      { type: 'text', text: 'stale-2' },
      { type: 'data-reset', data: {} },
      { type: 'text', text: 'fresh' },
    ];
    expect(visiblePartsAfterReset(parts)).toEqual([{ type: 'text', text: 'fresh' }]);
  });

  it('returns an empty array when the marker is the last part', () => {
    const parts: UIPart[] = [{ type: 'text', text: 'stale' }, { type: 'data-reset', data: {} }];
    expect(visiblePartsAfterReset(parts)).toEqual([]);
  });
});
