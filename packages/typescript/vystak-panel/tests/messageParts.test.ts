import { describe, expect, it } from 'vitest';
import {
  mapPersistedParts,
  parseToolInput,
  stringifyToolValue,
  toolStateLabel,
} from '../lib/messageParts';
import type { MessagePart } from '../lib/types';

describe('toolStateLabel', () => {
  it('labels input-streaming and input-available as running', () => {
    expect(toolStateLabel('input-streaming')).toBe('running…');
    expect(toolStateLabel('input-available')).toBe('running…');
  });

  it('labels output-available as done', () => {
    expect(toolStateLabel('output-available')).toBe('done');
  });

  it('labels output-error as failed', () => {
    expect(toolStateLabel('output-error')).toBe('failed');
  });
});

describe('stringifyToolValue', () => {
  it('passes strings through unchanged', () => {
    expect(stringifyToolValue('Kyiv')).toBe('Kyiv');
    expect(stringifyToolValue('')).toBe('');
  });

  it('returns an empty string for undefined (a running tool has no output yet)', () => {
    expect(stringifyToolValue(undefined)).toBe('');
  });

  it('JSON-stringifies objects and arrays with indentation', () => {
    expect(stringifyToolValue({ city: 'Kyiv' })).toBe(JSON.stringify({ city: 'Kyiv' }, null, 2));
    expect(stringifyToolValue([1, 2, 3])).toBe(JSON.stringify([1, 2, 3], null, 2));
  });

  it('stringifies primitives other than string', () => {
    expect(stringifyToolValue(42)).toBe('42');
    expect(stringifyToolValue(true)).toBe('true');
    expect(stringifyToolValue(null)).toBe('null');
  });

  it('falls back instead of throwing on a value JSON.stringify cannot serialize', () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(() => stringifyToolValue(circular)).not.toThrow();
    expect(typeof stringifyToolValue(circular)).toBe('string');
  });
});

describe('parseToolInput', () => {
  it('parses valid JSON into a structured value', () => {
    expect(parseToolInput('{"city":"Kyiv"}')).toEqual({ city: 'Kyiv' });
  });

  it('falls back to the raw string on parse failure', () => {
    expect(parseToolInput('not json')).toBe('not json');
  });

  it('falls back to the raw string for an empty string', () => {
    expect(parseToolInput('')).toBe('');
  });
});

describe('mapPersistedParts', () => {
  it('passes text parts through unchanged', () => {
    const parts: MessagePart[] = [{ type: 'text', text: 'hello' }];
    expect(mapPersistedParts(parts)).toEqual([{ type: 'text', text: 'hello' }]);
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
    expect(mapPersistedParts(parts)).toEqual([
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
    expect(mapPersistedParts(parts)).toEqual([
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
    const [mapped] = mapPersistedParts(parts);
    expect(mapped).toMatchObject({ input: 'not json' });
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
    const mapped = mapPersistedParts(parts);
    expect(mapped.map(p => p.type)).toEqual(['text', 'dynamic-tool', 'text']);
  });
});
