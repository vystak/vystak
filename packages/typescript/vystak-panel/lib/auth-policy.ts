import type { Bootstrap } from './types';

export type SignInDecision = 'setup' | 'allow' | 'deny';

/** Channel is the authority: bootstrap.user is null for unknown or
 * deactivated emails, so 'allow' means an active invited user. */
export function evaluateSignIn(bootstrap: Bootstrap): SignInDecision {
  if (bootstrap.setup_required) return 'setup';
  return bootstrap.user !== null ? 'allow' : 'deny';
}
