// 分析提交页（P6 Task 19）：选类型 -> 选材料 -> 提交 -> 轮询进度 -> 终态。
// 克隆三组既有范式（计划「UI 克隆三组既有资产」，不新增前端依赖）：
// - TaskTypePicker：features/qa/AskPanel.tsx 手写分段按钮组（{value, label, icon}
//   数组 + cn() 高亮），数据源 ANALYSIS_TASK_TYPES（九类，第二批灰显「即将上线」）；
// - 提交 / 轮询 / 进度 / 失败重试：features/ingest/IngestPage.tsx 异步全套
//   （useSubmitAnalysis -> 202 + job_id -> useAnalysisJob 轮询 -> 进度条 +
//   STAGE_LABEL 阶段文案 -> 终态），阶段词对齐 analysis/job_worker.py 进度分段；
// - 材料清单 / 空态 / Skeleton：沿用既有手写替代（无 table 依赖）。
// 权限：导航由 App.tsx access.can(ANALYZE) 隐藏式门控；页内提交禁用为双保险。
// 报告详情 / 历史页归 P6 Task 20（ReportViewer / ReportsHistory），成功态先给占位。
import { RotateCcw, Send } from "lucide-react";
import { useState } from "react";
import { useAccess } from "@/auth/useAccess";
import {
  ANALYSIS_TASK_TYPES,
  PERMISSIONS,
  type AnalysisJobRequest,
  type AnalysisTaskType,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useAnalysisDocuments, useAnalysisJob, useSubmitAnalysis } from "./useAnalysis";

/**
 * 分析 job 阶段文案（对齐 analysis/job_worker.py 进度分段：
 * gather 10 → prompt 25 → llm 60 → verify 80 → persist 95 → done 100）。
 */
const STAGE_LABEL: Record<string, string> = {
  queued: "排队中",
  gather: "收集材料",
  prompt: "构造提示",
  llm: "模型生成",
  verify: "证据校验",
  persist: "落库",
  done: "完成",
};

/** 九类选择器：克隆 AskPanel MODES 手写分段按钮组；第二批未注册，灰显「即将上线」不可选。 */
function TaskTypePicker({
  value,
  onChange,
  disabled,
}: {
  value: AnalysisTaskType;
  onChange: (v: AnalysisTaskType) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {ANALYSIS_TASK_TYPES.map(({ value: v, label, icon: Icon, batch }) => {
        const active = value === v;
        // 第二批 4 类尚未注册（提交会 400），前端先灰显「即将上线」（P6 Task 21-22 接线）
        const locked = batch === 2;
        return (
          <button
            key={v}
            type="button"
            disabled={disabled || locked}
            aria-pressed={active}
            onClick={() => onChange(v)}
            title={locked ? "第二批类型尚未交付（P6 Task 21-22）" : undefined}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
              active
                ? "border-primary bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent",
              locked && "cursor-not-allowed opacity-50"
            )}
          >
            <Icon className="h-4 w-4" /> {label}
            {locked && (
              <span className="rounded bg-muted px-1 text-[10px] leading-4">即将上线</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** 材料选择：消费 GET /analysis/documents 出参（多选；不选 = 全可见范围）。 */
function MaterialPicker({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (docId: string) => void;
}) {
  const docs = useAnalysisDocuments();
  if (docs.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (docs.isError) {
    return (
      <p className="text-sm text-destructive">
        加载可见文档失败：{docs.error instanceof Error ? docs.error.message : "未知错误"}
      </p>
    );
  }
  const items = docs.data ?? [];
  if (items.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        暂无可见文档（先摄入文档，或当前权限范围内无可分析材料）。
      </p>
    );
  }
  return (
    <ul className="max-h-56 space-y-1 overflow-auto rounded-md border p-2">
      {items.map((d) => (
        <li key={d.doc_id}>
          <label className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent/40">
            <input
              type="checkbox"
              checked={selected.includes(d.doc_id)}
              onChange={() => onToggle(d.doc_id)}
              className="h-4 w-4 accent-primary"
            />
            <span className="min-w-0 flex-1 truncate">{d.label}</span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {d.access_level}
            </Badge>
            <span className="shrink-0 text-xs text-muted-foreground">{d.chunk_count} 块</span>
          </label>
        </li>
      ))}
    </ul>
  );
}

export function AnalysisPage() {
  const access = useAccess();
  const canAnalyze = access.can(PERMISSIONS.ANALYZE);
  const [taskType, setTaskType] = useState<AnalysisTaskType>("summary");
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const [questionError, setQuestionError] = useState<string | null>(null);
  // 提交时锁定类型标签（进度/终态展示不随用户后续切换漂移）
  const [submittedType, setSubmittedType] = useState<AnalysisTaskType | null>(null);
  const submit = useSubmitAnalysis();
  const job = useAnalysisJob(submit.data?.job_id ?? null);

  const toggleDoc = (docId: string) =>
    setSelectedDocs((prev) =>
      prev.includes(docId) ? prev.filter((d) => d !== docId) : [...prev, docId]
    );

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canAnalyze || submit.isPending) return;
    // qa 必填校验：前端拦截先于后端 400（后端同口径兜底，api/analysis.py）
    if (taskType === "qa" && !question.trim()) {
      setQuestionError("问答分析需要填写问题");
      return;
    }
    const req: AnalysisJobRequest = { task_type: taskType, doc_ids: [...selectedDocs] };
    if (taskType === "qa") req.question = question.trim();
    setQuestionError(null);
    setSubmittedType(taskType);
    submit.mutate(req);
  };

  const onReset = () => {
    submit.reset();
    setSubmittedType(null);
  };

  const status = job.data?.status ?? (submit.isPending ? "pending" : null);
  const isTerminal = status === "succeeded" || status === "failed";
  const submittedLabel =
    ANALYSIS_TASK_TYPES.find((t) => t.value === submittedType)?.label ?? "分析";

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold">分析任务</h1>

      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border bg-card p-4">
        {/* 分析类型（九类；第二批灰显） */}
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-muted-foreground">分析类型（九类）</div>
          <TaskTypePicker
            value={taskType}
            onChange={(v) => {
              setTaskType(v);
              setQuestionError(null);
            }}
            disabled={!canAnalyze}
          />
        </div>

        {/* 材料范围：不选 = 全可见范围（后端按三维可见性兜底过滤） */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              材料范围（不选 = 全可见范围）
            </span>
            {selectedDocs.length > 0 && (
              <button
                type="button"
                onClick={() => setSelectedDocs([])}
                className="text-xs text-primary hover:underline"
              >
                清空已选（{selectedDocs.length}）
              </button>
            )}
          </div>
          <MaterialPicker selected={selectedDocs} onToggle={toggleDoc} />
        </div>

        {/* qa 类：问题输入（必填校验）+ 全可见库范围文案（与风险表落点对齐） */}
        {taskType === "qa" && (
          <div className="space-y-1.5">
            <Textarea
              placeholder="输入要分析的问题…"
              value={question}
              onChange={(e) => {
                setQuestion(e.target.value);
                if (questionError) setQuestionError(null);
              }}
              rows={2}
            />
            {questionError ? (
              <p className="text-xs text-destructive">{questionError}</p>
            ) : (
              <p className="text-xs text-muted-foreground">
                问答范围为全可见库（文档范围限定待 P9）。
              </p>
            )}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={!canAnalyze || submit.isPending}>
            <Send className="h-4 w-4" /> 提交分析
          </Button>
          {!canAnalyze && (
            <span className="text-sm text-muted-foreground">无 analyze 权限，联系管理员</span>
          )}
        </div>
      </form>

      {/* 提交即失败（400/503 等请求边界错误）-> destructive 错误盒 */}
      {submit.isError && (
        <div className="space-y-2 rounded-md border border-destructive bg-destructive/10 p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-destructive">提交失败</span>
            <Button variant="ghost" size="sm" onClick={onReset}>
              重试
            </Button>
          </div>
          <p className="break-all text-sm text-destructive">
            {submit.error instanceof Error ? submit.error.message : "提交失败"}
          </p>
        </div>
      )}

      {/* 进度条 + 阶段文案（轮询中，非终态；克隆 IngestPage 进度范式） */}
      {(submit.data || job.data) && !isTerminal && !submit.isError && (
        <div className="space-y-2 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">{submittedLabel}分析进行中</h3>
            <Badge variant="secondary">{status ?? "pending"}</Badge>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.max(5, job.data?.progress ?? 0)}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {STAGE_LABEL[job.data?.progress_stage ?? ""] ?? "排队等待分析管线…"}
          </p>
        </div>
      )}

      {/* 终态成功：报告入口占位（报告详情 / 历史页归 P6 Task 20） */}
      {job.data?.status === "succeeded" && (
        <div className="space-y-3 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">分析完成</h3>
            <Badge className="bg-emerald-600">succeeded</Badge>
          </div>
          {job.data.report_id && (
            <p className="text-sm text-muted-foreground">
              报告 ID：<span className="font-mono">{job.data.report_id}</span>
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            报告详情与历史页建设中（P6 Task 20 交付）。
          </p>
          <Button variant="outline" size="sm" onClick={onReset}>
            <RotateCcw className="h-3.5 w-3.5" /> 再来一单
          </Button>
        </div>
      )}

      {/* 终态失败：错误盒 + 重试面板 */}
      {job.data?.status === "failed" && (
        <div className="space-y-2 rounded-md border border-destructive bg-destructive/10 p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-destructive">分析失败</span>
            <Button variant="ghost" size="sm" onClick={onReset}>
              重试
            </Button>
          </div>
          <p className="break-all text-sm text-destructive">{job.data.error ?? "未知错误"}</p>
        </div>
      )}
    </div>
  );
}
