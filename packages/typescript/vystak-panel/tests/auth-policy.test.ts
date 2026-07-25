import { describe, expect, it } from 'vitest';
import { evaluateSignIn } from '../lib/auth-policy';
import type { Bootstrap } from '../lib/types';

const base: Bootstrap = {
  setup_required: false,
  user: null,
  agents: [],
  default_project_id: null,
};

const user = {
  id: 'u1',
  email: 'a@example.com',
  name: 'A',
  image: '',
  role: 'member' as const,
  status: 'active' as const,
  created_at: '2026-01-01T00:00:00Z',
};

describe('evaluateSignIn', () => {
  it('first ever sign-in claims setup', () => {
    expect(evaluateSignIn({ ...base, setup_required: true })).toBe('setup');
  });
  it('known active user allowed', () => {
    expect(evaluateSignIn({ ...base, user })).toBe('allow');
  });
  it('unknown user denied after setup', () => {
    expect(evaluateSignIn(base)).toBe('deny');
  });
});
