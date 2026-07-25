'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import { auth } from '@/auth';
import {
  addMember,
  addUser,
  createConversation,
  createProject,
  deleteConversation,
  patchUser,
  removeMember,
} from '@/lib/panel';

async function requireEmail(): Promise<string> {
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) redirect('/signin');
  return email;
}

export async function createProjectAction(formData: FormData) {
  const email = await requireEmail();
  const name = String(formData.get('name') ?? '').trim();
  if (!name) return;
  const { project } = await createProject(email, name);
  redirect(`/p/${project.id}`);
}

export async function createConversationAction(
  projectId: string,
  formData: FormData,
) {
  const email = await requireEmail();
  const agentName = String(formData.get('agent') ?? '');
  if (!agentName) return;
  const { conversation } = await createConversation(email, projectId, agentName);
  redirect(`/p/${projectId}/c/${conversation.id}`);
}

export async function deleteConversationAction(
  projectId: string,
  convId: string,
) {
  const email = await requireEmail();
  await deleteConversation(email, convId);
  revalidatePath(`/p/${projectId}`);
}

export async function addMemberAction(projectId: string, formData: FormData) {
  const email = await requireEmail();
  const memberEmail = String(formData.get('email') ?? '').trim();
  if (memberEmail) await addMember(email, projectId, memberEmail);
  revalidatePath(`/p/${projectId}`);
}

export async function removeMemberAction(projectId: string, userId: string) {
  const email = await requireEmail();
  await removeMember(email, projectId, userId);
  revalidatePath(`/p/${projectId}`);
}

export async function addUserAction(formData: FormData) {
  const email = await requireEmail();
  const newEmail = String(formData.get('email') ?? '').trim();
  const role = String(formData.get('role') ?? 'member');
  if (newEmail) await addUser(email, newEmail, role);
  revalidatePath('/admin/users');
}

export async function setUserStatusAction(userId: string, status: string) {
  const email = await requireEmail();
  await patchUser(email, userId, { status });
  revalidatePath('/admin/users');
}
