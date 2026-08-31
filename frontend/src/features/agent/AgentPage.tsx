// Agent 聊天面（P7 T15）：会话列表侧栏 + 消息流 + 工具轨迹折叠 + 轮询终态停。
// 克隆范式：会话侧栏 ~ ReportsHistory 列表；轮询 ~ useAnalysisJob；轨迹 ~ ToolTrace。
// 停止按钮 = 客户端停轮询（v1 不硬杀后台 worker，留痕未竟：worker 自检取消锚点 2026-W49）。
import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Plus, Square, User } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useQueryClient } from "@tanstack/react-query";
import { ToolTrace } from "./ToolTrace";
import {
  useAgentJob,
  useAgentMessages,
  useAgentRuns,
  useAgentSessions,
  useCreateAgentSession,
  useSubmitAgentRun,
} from "./useAgent";
import type { AgentRunOut } from "@/api/types";
import { cn } from "@/lib/utils";

export function AgentPage() {
  const sessions = useAgentSessions();
  const createSession = useCreateAgentSession();
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="flex h-full flex-col gap-3 md:flex-row md:gap-4">
      {/* 移动端会话选择条（<md）：侧栏桌面专属，防窄视口挤压 */}
      <div className="flex shrink-0 gap-2 md:hidden">
        <select
          className="h-9 flex-1 rounded-md border bg-background px-2 text-sm"
          value={selected ?? ""}
          onChange={(e) => setSelected(e.target.value || null)}
        >
          <option value="">选择会话…</option>
          {(sessions.data?.items ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.label || s.id.slice(0, 8)}（{s.mode}）
            </option>
          ))}
        </select>
        <Button
          size="sm"
          onClick={() =>
            createSession.mutate(
              { label: `会话 ${(sessions.data?.total ?? 0) + 1}` },
              { onSuccess: (s) => setSelected(s.id) }
            )
          }
        >
          <Plus className="h-4 w-4" /> 新建
        </Button>
      </div>
      <aside className="hidden w-56 shrink-0 flex-col gap-2 overflow-auto md:flex">
        <Button
          size="sm"
          onClick={() =>
            createSession.mutate(
              { label: `会话 ${(sessions.data?.total ?? 0) + 1}` },
              { onSuccess: (s) => setSelected(s.id) }
            )
          }
        >
          <Plus className="h-4 w-4" /> 新建会话
        </Button>
        {(sessions.data?.items ?? []).map((s) => (
          <button
            key={s.id}
            className={cn(
              "rounded-md border px-3 py-2 text-left text-sm",
              selected === s.id ? "bg-accent" : "hover:bg-accent/50"
            )}
            onClick={() => setSelected(s.id)}
          >
            <div className="truncate font-medium">{s.label || s.id.slice(0, 8)}</div>
            <div className="text-xs text-muted-foreground">
              {s.mode} · {s.access_level}
            </div>
          </button>
        ))}
      </aside>
      <section className="min-w-0 flex-1 overflow-auto">
        {selected ? <ChatView sessionId={selected} /> : <EmptyHint />}
      </section>
    </div>
  );
}

function EmptyHint() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
      选择或新建会话开始多轮 Agent 对话
    </div>
  );
}

function ChatView({ sessionId }: { sessionId: string }) {
  const messages = useAgentMessages(sessionId);
  const runs = useAgentRuns(sessionId);
  const submit = useSubmitAgentRun(sessionId);
  const [jobId, setJobId] = useState<string | null>(null);
  const [stopped, setStopped] = useState(false);
  const [question, setQuestion] = useState("");
  const queryClient = useQueryClient();
  const job = useAgentJob(jobId && !stopped ? jobId : null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const runById = useMemo(() => {
    const m = new Map<string, AgentRunOut>();
    (runs.data ?? []).forEach((r) => m.set(r.id, r));
    return m;
  }, [runs.data]);

  // job 终态 -> 刷新消息 / 轨迹 / 会话列表
  const jobStatus = job.data?.status;
  useEffect(() => {
    if (jobStatus === "succeeded" || jobStatus === "failed") {
      setJobId(null);
      void queryClient.invalidateQueries({ queryKey: ["agent-messages", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-runs", sessionId] });
      void queryClient.invalidateQueries({ queryKey: ["agent-sessions"] });
    }
  }, [jobStatus, queryClient, sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages.data, jobStatus]);

  const busy = jobId !== null && !stopped && jobStatus !== "failed";

  const onSubmit = () => {
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    setStopped(false);
    submit.mutate({ question: q }, { onSuccess: (r) => setJobId(r.job_id) });
  };

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex-1 space-y-3 overflow-auto pr-1">
        {(messages.data ?? []).map((m) => (
          <div
            key={m.id}
            className={cn(
              "flex gap-2 rounded-md border p-3 text-sm",
              m.role === "user" ? "ml-8 bg-muted/40" : "mr-8"
            )}
          >
            {m.role === "user" ? (
              <User className="h-4 w-4 shrink-0" />
            ) : (
              <Bot className="h-4 w-4 shrink-0" />
            )}
            <div className="min-w-0 flex-1">
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.role === "assistant" && m.run_id && (
                <ToolTrace run={runById.get(m.run_id)} />
              )}
            </div>
          </div>
        ))}
        {busy && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span className="animate-pulse">Agent 思考中…</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setStopped(true);
                setJobId(null);
              }}
            >
              <Square className="h-3 w-3" /> 停止
            </Button>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="flex gap-2">
        <Textarea
          value={question}
          placeholder="输入问题，Enter 发送…"
          className="min-h-16 flex-1"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
        />
        <Button onClick={onSubmit} disabled={busy || !question.trim()}>
          提问
        </Button>
      </div>
    </div>
  );
}
