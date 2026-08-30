// Agent 域 API 客户端（P7 T15）：端点与后端 src/calliodesmo/api/agent.py 对齐。
import { api } from "@/api/client";
import type {
  AgentMessageOut,
  AgentRunAccepted,
  AgentRunOut,
  AgentRunRequest,
  AgentSessionListOut,
  AgentSessionOut,
} from "@/api/types";

export function listAgentSessions(
  params: { limit?: number; offset?: number } = {}
): Promise<AgentSessionListOut> {
  return api.get<AgentSessionListOut>("/agent/sessions", {
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  });
}

export function createAgentSession(req: {
  mode?: string;
  label?: string;
}): Promise<AgentSessionOut> {
  return api.post<AgentSessionOut>("/agent/sessions", req);
}

export function submitAgentRun(
  sessionId: string,
  req: AgentRunRequest
): Promise<AgentRunAccepted> {
  return api.post<AgentRunAccepted>(`/agent/sessions/${sessionId}/runs`, req);
}

export function listAgentMessages(sessionId: string): Promise<AgentMessageOut[]> {
  return api.get<AgentMessageOut[]>(`/agent/sessions/${sessionId}/messages`);
}

export function listAgentRuns(sessionId: string): Promise<AgentRunOut[]> {
  return api.get<AgentRunOut[]>(`/agent/sessions/${sessionId}/runs`);
}
