import 'server-only';
import type {
  Bootstrap,
  Conversation,
  PanelMessage,
  PanelUser,
  Project,
} from './types';

const API_URL = () => process.env.PANEL_API_URL ?? 'http://localhost:18100';
const TOKEN = () => process.env.PANEL_SERVICE_TOKEN ?? '';

export async function panelFetch(
  user: string | null,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${TOKEN()}`);
  if (user) headers.set('X-Panel-User', user);
  if (init.body) headers.set('Content-Type', 'application/json');
  return fetch(`${API_URL()}${path}`, { ...init, headers, cache: 'no-store' });
}

async function json<T>(user: string | null, path: string, init?: RequestInit): Promise<T> {
  const resp = await panelFetch(user, path, init);
  if (!resp.ok) throw new Error(`panel API ${path} -> ${resp.status}`);
  return (await resp.json()) as T;
}

async function ok(user: string | null, path: string, init?: RequestInit): Promise<void> {
  const resp = await panelFetch(user, path, init);
  if (!resp.ok) throw new Error(`panel API ${path} -> ${resp.status}`);
}

export const getBootstrap = (email: string) =>
  json<Bootstrap>(email, '/api/bootstrap');

// The channel requires X-Panel-User on /api/setup and rejects a body email
// that disagrees with it, so the acting email is sent as the user here — it
// must not be null.
export const setupAdmin = (body: { email: string; name: string; image: string }) =>
  json<{ user: PanelUser }>(body.email, '/api/setup', {
    method: 'POST',
    body: JSON.stringify(body),
  });

export const listProjects = (email: string) =>
  json<{ projects: Project[] }>(email, '/api/projects');

export const createProject = (email: string, name: string) =>
  json<{ project: Project }>(email, '/api/projects', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

export const deleteProject = (email: string, id: string) =>
  ok(email, `/api/projects/${id}`, { method: 'DELETE' });

export const listMembers = (email: string, id: string) =>
  json<{ members: PanelUser[] }>(email, `/api/projects/${id}/members`);

export const addMember = (email: string, id: string, memberEmail: string) =>
  ok(email, `/api/projects/${id}/members`, {
    method: 'POST',
    body: JSON.stringify({ email: memberEmail }),
  });

export const removeMember = (email: string, id: string, userId: string) =>
  ok(email, `/api/projects/${id}/members/${userId}`, {
    method: 'DELETE',
  });

export const listUsers = (email: string) =>
  json<{ users: PanelUser[] }>(email, '/api/users');

export const addUser = (email: string, newEmail: string, role: string) =>
  ok(email, '/api/users', {
    method: 'POST',
    body: JSON.stringify({ email: newEmail, role }),
  });

export const patchUser = (
  email: string,
  userId: string,
  patch: { role?: string; status?: string },
) =>
  ok(email, `/api/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const listConversations = (email: string, projectId: string) =>
  json<{ conversations: Conversation[] }>(
    email,
    `/api/projects/${projectId}/conversations`,
  );

export const createConversation = (
  email: string,
  projectId: string,
  agentName: string,
) =>
  json<{ conversation: Conversation }>(
    email,
    `/api/projects/${projectId}/conversations`,
    { method: 'POST', body: JSON.stringify({ agent_name: agentName }) },
  );

export const deleteConversation = (email: string, convId: string) =>
  ok(email, `/api/conversations/${convId}`, { method: 'DELETE' });

export const renameConversation = (email: string, convId: string, title: string) =>
  ok(email, `/api/conversations/${convId}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  });

export const listMessages = (email: string, convId: string) =>
  json<{ messages: PanelMessage[] }>(
    email,
    `/api/conversations/${convId}/messages`,
  );

export const streamConversationMessage = (
  email: string,
  convId: string,
  text: string,
) =>
  panelFetch(email, `/api/conversations/${convId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
