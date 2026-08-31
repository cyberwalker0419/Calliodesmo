// Agent 域 TanStack Query hooks（P7 T15）。
// 克隆 features/analysis/useAnalysis.ts 范式：提交 useMutation（202 + job_id）；
// 轮询 useQuery + refetchInterval 函数式（非终态 1200ms、终态返回 false 停）。
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  createAgentSession,
  listAgentMessages,
  listAgentRuns,
  listAgentSessions,
  submitAgentRun,
} from "./api";
import { api } from "@/api/client";
import type { AgentRunRequest, JobOut } from "@/api/types";

const TERMINAL = new Set(["succeeded", "failed"]);

export function useAgentSessions() {
  return useQuery({
    queryKey: ["agent-sessions"],
    queryFn: () => listAgentSessions(),
  });
}

export function useCreateAgentSession() {
  return useMutation({ mutationFn: createAgentSession });
}

export function useSubmitAgentRun(sessionId: string) {
  return useMutation({
    mutationFn: (req: AgentRunRequest) => submitAgentRun(sessionId, req),
  });
}

/** 轮询 agent job；终态自动停（与 useAnalysisJob 同机制，命名空间隔离）。 */
export function useAgentJob(jobId: string | null) {
  return useQuery({
    queryKey: ["agent-job", jobId],
    queryFn: () => api.get<JobOut>(`/jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 1200;
    },
  });
}

export function useAgentMessages(sessionId: string | null) {
  return useQuery({
    queryKey: ["agent-messages", sessionId],
    queryFn: () => listAgentMessages(sessionId!),
    enabled: sessionId !== null,
  });
}

export function useAgentRuns(sessionId: string | null) {
  return useQuery({
    queryKey: ["agent-runs", sessionId],
    queryFn: () => listAgentRuns(sessionId!),
    enabled: sessionId !== null,
  });
}
