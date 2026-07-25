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

// Persisted message parts (see vystak_channel_panel.routes_messages.gen):
// an ordered rendering of a turn, text segments interleaved with completed
// tool calls. `input`/`output` are raw strings exactly as the panel SSE
// carried them (`arguments` / `output`) — the Python side never parses
// them as JSON, so consumers that want structured values must parse here.
//
// Live/replay parity note for history replay (Task 5): lib/stream.ts
// JSON.parse()s a live tool_call's `arguments` into `input` (falling back
// to the raw string only on parse failure) before handing it to the AI SDK
// as a `dynamic-tool` part's `input`. To render identically after a
// reload, replay must apply that same JSON.parse-with-raw-fallback to
// ToolMessagePart.input here — otherwise the same call renders as an
// object live and a raw string after reload. `output` has no such gap:
// both the live path and this persisted shape leave it as the raw string.
export interface TextMessagePart {
  type: 'text';
  text: string;
}

export interface ToolMessagePart {
  type: 'tool';
  tool_call_id: string;
  tool_name: string;
  input: string;
  output: string;
  is_error: boolean;
}

export type MessagePart = TextMessagePart | ToolMessagePart;

export interface PanelMessage {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  response_id: string | null;
  created_at: string;
  parts: MessagePart[] | null;
}

export interface Bootstrap {
  setup_required: boolean;
  user: PanelUser | null;
  agents: string[];
  default_project_id: string | null;
}

// Persisted message parts (panel channel schema v2, tool-call visualization plan).
export type StoredPart =
  | { type: 'text'; text: string }
  | {
      type: 'tool';
      tool_call_id: string;
      tool_name: string;
      input: string;
      output: string;
    };
