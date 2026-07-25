export interface PanelUser {
  id: string;
  email: string;
  name: string;
  image: string;
  role: 'admin' | 'member';
  status: 'active' | 'deactivated';
  created_at: string;
}

export interface Project {
  id: string;
  name: string;
  owner_id: string;
  is_default: boolean;
  created_at: string;
}

export interface Conversation {
  id: string;
  project_id: string;
  creator_id: string;
  agent_name: string;
  title: string;
  last_response_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PanelMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  response_id: string | null;
  created_at: string;
}

export interface Bootstrap {
  setup_required: boolean;
  user: PanelUser | null;
  agents: string[];
  default_project_id: string | null;
}
