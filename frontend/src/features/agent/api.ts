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
  params: { limit?: number; offset?: number; includeDeleted?: boolean } = {}
): Promise<AgentSessionListOut> {
  return api.get<AgentSessionListOut>("/agent/sessions", {
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
    include_deleted: params.includeDeleted ? true : undefined,
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

/** DELETE /agent/sessions/{id}：软删除（可恢复；消息与执行记录不硬删）。 */
export function deleteAgentSession(sessionId: string): Promise<AgentSessionOut> {
  return api.del<AgentSessionOut>(`/agent/sessions/${sessionId}`);
}

/** POST /agent/sessions/{id}/restore：恢复已软删除会话。 */
export function restoreAgentSession(sessionId: string): Promise<AgentSessionOut> {
  return api.post<AgentSessionOut>(`/agent/sessions/${sessionId}/restore`);
}

export function listAgentRuns(sessionId: string): Promise<AgentRunOut[]> {
  return api.get<AgentRunOut[]>(`/agent/sessions/${sessionId}/runs`);
}
