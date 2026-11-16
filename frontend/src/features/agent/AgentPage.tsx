// Agent 聊天面（P7 T15）：会话列表侧栏 + 消息流 + 工具轨迹折叠 + 轮询终态停。
// 克隆范式：会话侧栏 ~ ReportsHistory 列表；轮询 ~ useAnalysisJob；轨迹 ~ ToolTrace。
// 停止按钮 = 客户端停轮询（v1 不硬杀后台 worker，留痕未竟：worker 自检取消锚点 2026-W49）。
import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, Plus, RotateCcw, Square, Trash2, User, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useQueryClient } from "@tanstack/react-query";
import { ToolTrace } from "./ToolTrace";
import { VerificationPanel } from "@/features/verification/VerificationPanel";
import {
  useAgentJob,
  useAgentMessages,
  useAgentRuns,
  useAgentSessions,
  useCreateAgentSession,
  useDeleteAgentSession,
  useRestoreAgentSession,
  useSubmitAgentRun,
} from "./useAgent";
import type { AgentRunOut, AgentSessionOut } from "@/api/types";
import { cn } from "@/lib/utils";

export function AgentPage() {
  // P9 T10：会话可软删除（可恢复）；列表默认不含已删除，勾选后出恢复入口
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const sessions = useAgentSessions(includeDeleted);
  const createSession = useCreateAgentSession();
  const deleteSession = useDeleteAgentSession();
  const restoreSession = useRestoreAgentSession();
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const items = sessions.data?.items ?? [];
  // 新会话名取「现有标签最大序号 + 1」：用 total+1 会在删除后反复撞出「会话 1」
  const nextSessionNumber = useMemo(() => {
    const max = items.reduce((acc, s) => {
      const matched = /^会话\s*(\d+)$/.exec(s.label ?? "");
      return matched ? Math.max(acc, Number(matched[1])) : acc;
    }, 0);
    return max + 1;
  }, [items]);
  const newSessionLabel = () => `会话 ${nextSessionNumber}`;

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
          {items
            .filter((s) => !s.deleted_at)
            .map((s) => (
              <option key={s.id} value={s.id}>
                {s.label || s.id.slice(0, 8)}（{s.mode}）
              </option>
            ))}
        </select>
        <Button
          size="sm"
          onClick={() =>
            createSession.mutate(
              { label: newSessionLabel() },
              { onSuccess: (s) => setSelected(s.id) },
            )
          }
        >
          <Plus className="h-4 w-4" /> 新建
        </Button>
        {/* 会话生命周期动作（<md）：桌面侧栏的删除 / 恢复在窄视口下的等价入口 */}
        <SessionActions
          session={items.find((s) => s.id === selected)}
          confirmDeleteId={confirmDeleteId}
          setConfirmDeleteId={setConfirmDeleteId}
          deleteSession={deleteSession}
          restoreSession={restoreSession}
          onDeleted={() => setSelected(null)}
          compact
        />
      </div>
      <aside className="hidden w-56 shrink-0 flex-col gap-2 overflow-auto md:flex">
        <Button
          size="sm"
          onClick={() =>
            createSession.mutate(
              { label: newSessionLabel() },
              { onSuccess: (s) => setSelected(s.id) },
            )
          }
        >
          <Plus className="h-4 w-4" /> 新建会话
        </Button>
        <label className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => setIncludeDeleted(e.target.checked)}
          />
          显示已删除
        </label>
        {items.map((s) => (
          <div
            key={s.id}
            className={cn(
              "flex items-start gap-1 rounded-md border px-2 py-1.5",
              selected === s.id && !s.deleted_at
                ? "bg-accent"
                : "hover:bg-accent/50",
            )}
          >
            <button
              className="min-w-0 flex-1 text-left text-sm disabled:opacity-60"
              disabled={Boolean(s.deleted_at)}
              onClick={() => setSelected(s.id)}
            >
              <div className="truncate font-medium">
                {s.label || s.id.slice(0, 8)}
                {s.deleted_at && (
                  <span className="ml-1 text-xs text-muted-foreground">
                    已删除
                  </span>
                )}
              </div>
              <div className="text-xs text-muted-foreground">
                {s.mode} · {s.access_level}
              </div>
            </button>
            <SessionActions
              session={s}
              confirmDeleteId={confirmDeleteId}
              setConfirmDeleteId={setConfirmDeleteId}
              deleteSession={deleteSession}
              restoreSession={restoreSession}
              onDeleted={() => selected === s.id && setSelected(null)}
            />
          </div>
        ))}
      </aside>
      <section className="min-w-0 flex-1 overflow-auto">
        {selected ? <ChatView sessionId={selected} /> : <EmptyHint />}
      </section>
    </div>
  );
}

type SessionActionsProps = {
  session?: AgentSessionOut;
  confirmDeleteId: string | null;
  setConfirmDeleteId: (id: string | null) => void;
  deleteSession: ReturnType<typeof useDeleteAgentSession>;
  restoreSession: ReturnType<typeof useRestoreAgentSession>;
  onDeleted: () => void;
  compact?: boolean;
};

/**
 * 会话生命周期动作（P9 T10）：删除（行内二次确认）/ 恢复。
 * 桌面与移动共用，避免窄视口没有删除入口；文案与 aria-label 两端一致。
 */
function SessionActions({
  session,
  confirmDeleteId,
  setConfirmDeleteId,
  deleteSession,
  restoreSession,
  onDeleted,
}: SessionActionsProps) {
  if (!session) return null;
  if (session.deleted_at) {
    return (
      <Button
        size="sm"
        variant="ghost"
        aria-label="恢复会话"
        disabled={restoreSession.isPending}
        onClick={() => restoreSession.mutate(session.id)}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </Button>
    );
  }
  if (confirmDeleteId === session.id) {
    return (
      <>
        <Button
          size="sm"
          variant="destructive"
          aria-label="确认删除会话"
          disabled={deleteSession.isPending}
          onClick={() =>
            deleteSession.mutate(session.id, {
              onSuccess: () => {
                setConfirmDeleteId(null);
                onDeleted();
              },
            })
          }
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          aria-label="取消删除会话"
          onClick={() => setConfirmDeleteId(null)}
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      </>
    );
  }
  return (
    <Button
      size="sm"
      variant="ghost"
      aria-label="删除会话"
      onClick={() => setConfirmDeleteId(session.id)}
    >
      <Trash2 className="h-3.5 w-3.5" />
    </Button>
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
      void queryClient.invalidateQueries({
        queryKey: ["agent-messages", sessionId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["agent-runs", sessionId],
      });
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
              m.role === "user" ? "ml-8 bg-muted/40" : "mr-8",
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
                <>
                  <VerificationPanel
                    verification={runById.get(m.run_id)?.verification}
                  />
                  <ToolTrace run={runById.get(m.run_id)} />
                </>
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
