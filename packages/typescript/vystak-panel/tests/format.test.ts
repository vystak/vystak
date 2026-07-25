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
