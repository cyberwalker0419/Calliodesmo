// 报告渲染组件（P6 Task 20）：ReportViewer 纯展示 + ReportDialog 懒加载 Dialog。
// 克隆三组既有范式（计划「UI 克隆三组既有资产」，不新增前端依赖）：
// - StatCard 元信息卡 + Radix Tabs 分节：features/collab/ContributionDetail.tsx；
// - 证据 chips 点击展开 quote：features/qa/AnswerCard.tsx 来源标注模式；
// - 懒加载详情：ContributionDetail 的 open 门控 useQuery（ReportDialog）。
// payload 按 task_type 分型渲染（第一批 5 类逐类组件；第二批 / 未知类型走通用
// GenericValue 渲染，Task 21-22 接线后天然可显）。信封元信息（model /
// prompt_version / usage / generated_at）以 StatCard 风格卡片展示；
// partial 状态横幅 + warnings 展示；导出按钮消费 export 端点（附件下载），
// 无 export 权限者禁用（守卫口径与后端 api/analysis.py export_report 一致）。
import type { ReactNode } from "react";
import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  Cpu,
  Download,
  FileText,
  Hash,
  Layers,
} from "lucide-react";
import {
  ANALYSIS_TASK_TYPES,
  type AnalysisEnvelope,
  type EntityRecognitionPayload,
  type EvidenceItem,
  type KeyInfoPayload,
  type QAPayload,
  type SummaryPayload,
  type TimelineEventPayload,
  type TimelinePayload,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { exportReportUrl } from "./api";
import { useReport } from "./useAnalysis";

/** 时间线精度中文标注（对齐 TimelineGranularity 三值）。 */
const GRANULARITY_LABEL: Record<string, string> = {
  exact: "精确",
  approximate: "约略",
  relative: "相对",
};

/** 报告状态徽章取值（ok / partial / failed；仅 ok / partial 落报告行）。 */
const STATUS_CLASS: Record<string, string> = {
  ok: "bg-emerald-600",
  partial: "bg-amber-500 text-white",
  failed: "bg-destructive",
};

/** 置信标记：两位小数徽章（与后端 CONFIDENCE_CAP 降置信口径呼应，低置信不隐藏仅标记）。 */
function ConfidenceBadge({ value }: { value: number | undefined }) {
  if (typeof value !== "number") return null;
  return (
    <Badge variant="outline" className="shrink-0 text-[10px]">
      置信 {value.toFixed(2)}
    </Badge>
  );
}

/**
 * 证据 chips（克隆 AnswerCard 来源标注模式）：点击展开原文引文 + 证据置信，
 * 再点收起；空证据给出「无证据引用」占位（与后端 md 导出占位口径一致）。
 */
function EvidenceChips({ evidence }: { evidence: EvidenceItem[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (evidence.length === 0) {
    return <p className="text-xs text-muted-foreground">（无证据引用）</p>;
  }
  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1.5">
        {evidence.map((ev, i) => {
          const isOpen = open === i;
          return (
            <button
              key={`${ev.chunk_id}-${i}`}
              type="button"
              onClick={() => setOpen(isOpen ? null : i)}
              className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs hover:bg-accent"
            >
              {isOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              {ev.chunk_id}
            </button>
          );
        })}
      </div>
      {open !== null && evidence[open] ? (
        <div className="rounded-md border bg-muted/40 p-2 text-xs leading-relaxed">
          「{evidence[open].quote}」
          {typeof evidence[open].confidence === "number" && (
            <span className="ml-2 text-muted-foreground">
              （证据置信 {evidence[open].confidence?.toFixed(2)}）
            </span>
          )}
        </div>
      ) : null}
    </div>
  );
}

/** 信封元信息卡（克隆 ContributionDetail StatCard；值放宽为 string | number）。 */
function MetaCard({
  icon,
  value,
  label,
}: {
  icon: ReactNode;
  value: string | number;
  label: string;
}) {
  return (
    <div className="flex flex-col items-center rounded-md border bg-muted/30 p-2 text-center">
      <div className="text-muted-foreground">{icon}</div>
      <div className="mt-1 break-all text-sm font-semibold leading-tight">{value}</div>
      <div className="mt-0.5 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}

/** 导出按钮：有 export 权限渲染附件下载链接（同源 cookie 随导航携带）；无权限禁用。 */
function ExportButton({
  reportId,
  format,
  label,
  enabled,
}: {
  reportId: string;
  format: "json" | "md";
  label: string;
  enabled: boolean;
}) {
  if (!enabled) {
    return (
      <Button variant="outline" size="sm" disabled title="无 export 权限，联系管理员">
        <Download className="h-3.5 w-3.5" /> {label}
      </Button>
    );
  }
  return (
    <Button asChild variant="outline" size="sm">
      <a href={exportReportUrl(reportId, format)} download>
        <Download className="h-3.5 w-3.5" /> {label}
      </a>
    </Button>
  );
}

/** 摘要节（聚合形态）：正文 + 置信 + 顶层证据。 */
function SummarySection({ payload }: { payload: Partial<SummaryPayload> }) {
  return (
    <div className="space-y-3">
      <p className="whitespace-pre-wrap text-sm leading-relaxed">
        {payload.summary ?? "（无）"}
      </p>
      <div className="flex items-center gap-2">
        <ConfidenceBadge value={payload.confidence} />
      </div>
      <EvidenceChips evidence={payload.evidence ?? []} />
    </div>
  );
}

/** 要点节：无序列表。 */
function KeyPointsSection({ points }: { points: string[] }) {
  if (points.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">（无要点）</p>;
  }
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {points.map((p, i) => (
        <li key={i}>{p}</li>
      ))}
    </ul>
  );
}

/** 关键信息节：label/value 条目集（条目形态：置信与证据在条目上）。 */
function KeyInfoSection({ payload }: { payload: Partial<KeyInfoPayload> }) {
  const items = payload.items ?? [];
  if (items.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">（无条目）</p>;
  }
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="space-y-1 rounded-md border p-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{item.label}</span>
            <span className="text-muted-foreground">：</span>
            <span>{item.value}</span>
            <ConfidenceBadge value={item.confidence} />
          </div>
          <EvidenceChips evidence={item.evidence ?? []} />
        </div>
      ))}
    </div>
  );
}

/** 时间线节：有序列表 + granularity 中文标注 + 归一化日期（relative 缺省不臆造）。 */
function TimelineSection({ payload }: { payload: Partial<TimelinePayload> }) {
  const items = payload.items ?? [];
  if (items.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">（无条目）</p>;
  }
  return (
    <ol className="space-y-2">
      {items.map((ev, i) => (
        <TimelineRow key={i} event={ev} />
      ))}
    </ol>
  );
}

function TimelineRow({ event }: { event: TimelineEventPayload }) {
  return (
    <li className="space-y-1 rounded-md border p-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge variant="outline" className="shrink-0 text-[10px]">
          {GRANULARITY_LABEL[event.granularity] ?? event.granularity}
        </Badge>
        <span className="font-medium">{event.date_raw}</span>
        {event.date_normalized ? (
          <span className="font-mono text-xs text-muted-foreground">
            {event.date_normalized}
          </span>
        ) : null}
        <ConfidenceBadge value={event.confidence} />
      </div>
      {event.description ? (
        <p className="text-sm text-muted-foreground">{event.description}</p>
      ) : null}
      <EvidenceChips evidence={event.evidence ?? []} />
    </li>
  );
}

/** 实体识别节：名称 / 类型 / 描述条目集。 */
function EntitySection({ payload }: { payload: Partial<EntityRecognitionPayload> }) {
  const items = payload.items ?? [];
  if (items.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">（无条目）</p>;
  }
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="space-y-1 rounded-md border p-2">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">{item.name}</span>
            {item.type ? (
              <Badge variant="secondary" className="text-[10px]">
                {item.type}
              </Badge>
            ) : null}
            <ConfidenceBadge value={item.confidence} />
          </div>
          {item.description ? (
            <p className="text-sm text-muted-foreground">{item.description}</p>
          ) : null}
          <EvidenceChips evidence={item.evidence ?? []} />
        </div>
      ))}
    </div>
  );
}

/** 问答节：问题 / 答案 + 来源引注（引注为材料块 id，沿用 [chunk_id] 约定）。 */
function QASection({ payload }: { payload: Partial<QAPayload> }) {
  const citations = payload.citations ?? [];
  return (
    <div className="space-y-3">
      <p className="text-sm">
        <span className="font-medium">问题：</span>
        {payload.question ?? "（无）"}
      </p>
      <p className="whitespace-pre-wrap rounded-md bg-muted/30 p-3 text-sm leading-relaxed">
        {payload.answer ?? "（无）"}
      </p>
      {citations.length > 0 && (
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted-foreground">来源引注</div>
          <div className="flex flex-wrap gap-1.5">
            {citations.map((id) => (
              <span
                key={id}
                className="rounded-md border px-2 py-0.5 font-mono text-xs"
              >
                {id}
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="flex items-center gap-2">
        <ConfidenceBadge value={payload.confidence} />
      </div>
      <EvidenceChips evidence={payload.evidence ?? []} />
    </div>
  );
}

/** dict 条目 -> 「键：值」字段行（嵌套对象内联 JSON，保确定性）。 */
function EntryFields({ entry }: { entry: Record<string, unknown> }) {
  return (
    <div className="space-y-0.5">
      {Object.entries(entry).map(([k, v]) => (
        <div key={k} className="text-xs">
          <span className="font-medium">{k}：</span>
          <span className="break-all text-muted-foreground">
            {v !== null && typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** 通用值渲染（第二批类型 / 未知 payload 键的兜底分节）。 */
function GenericValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <p className="text-sm text-muted-foreground">（无）</p>;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return <p className="whitespace-pre-wrap break-all text-sm">{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <p className="text-sm text-muted-foreground">（无）</p>;
    }
    return (
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {value.map((item, i) => (
          <li key={i}>
            {typeof item === "object" && item !== null ? (
              <EntryFields entry={item as Record<string, unknown>} />
            ) : (
              String(item)
            )}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "object") {
    return <EntryFields entry={value as Record<string, unknown>} />;
  }
  return <p className="text-sm">{String(value)}</p>;
}

/** 材料节：信封 source_chunk_ids 清单（克隆 DetailList 空态口径）。 */
function MaterialsSection({ chunkIds }: { chunkIds: string[] }) {
  if (chunkIds.length === 0) {
    return <p className="py-4 text-center text-sm text-muted-foreground">（无材料块）</p>;
  }
  return (
    <ul className="max-h-64 space-y-1 overflow-auto py-1 text-sm">
      {chunkIds.map((id) => (
        <li key={id} className="rounded-sm bg-muted/30 px-2 py-1 font-mono text-xs break-all">
          {id}
        </li>
      ))}
    </ul>
  );
}

interface Section {
  value: string;
  label: string;
  node: ReactNode;
}

/** payload 按 task_type 分型建节（第一批 5 类逐类；其余走通用渲染）+ 固定材料节。 */
function buildSections(envelope: AnalysisEnvelope): Section[] {
  const payload = (envelope.payload ?? {}) as Record<string, unknown>;
  let sections: Section[];
  switch (envelope.task_type) {
    case "summary": {
      const p = payload as Partial<SummaryPayload>;
      sections = [
        { value: "summary", label: "摘要", node: <SummarySection payload={p} /> },
        { value: "key-points", label: "要点", node: <KeyPointsSection points={p.key_points ?? []} /> },
      ];
      break;
    }
    case "key_information":
      sections = [
        {
          value: "items",
          label: "关键信息条目",
          node: <KeyInfoSection payload={payload as Partial<KeyInfoPayload>} />,
        },
      ];
      break;
    case "timeline":
      sections = [
        {
          value: "items",
          label: "时间线",
          node: <TimelineSection payload={payload as Partial<TimelinePayload>} />,
        },
      ];
      break;
    case "entity_recognition":
      sections = [
        {
          value: "items",
          label: "识别实体",
          node: <EntitySection payload={payload as Partial<EntityRecognitionPayload>} />,
        },
      ];
      break;
    case "qa":
      sections = [
        { value: "answer", label: "答案", node: <QASection payload={payload as Partial<QAPayload>} /> },
      ];
      break;
    default: {
      // 第二批（关系映射 / 任务 / 概念 / 自定义）与未知类型：按顶层键通用渲染
      const entries = Object.entries(payload);
      sections =
        entries.length > 0
          ? entries.map(([key, value]) => ({
              value: key,
              label: key,
              node: <GenericValue value={value} />,
            }))
          : [
              {
                value: "empty",
                label: "内容",
                node: (
                  <p className="py-4 text-center text-sm text-muted-foreground">（无内容）</p>
                ),
              },
            ];
    }
  }
  sections.push({
    value: "materials",
    label: "材料",
    node: <MaterialsSection chunkIds={envelope.source_chunk_ids ?? []} />,
  });
  return sections;
}

/** ISO 时刻 -> 「YYYY-MM-DD HH:mm:ss」展示（截断式样，不做时区换算）。 */
function formatGeneratedAt(iso: string): string {
  return iso.slice(0, 19).replace("T", " ");
}

export interface ReportViewerProps {
  envelope: AnalysisEnvelope;
  reportId: string;
  /** 当前用户是否持 export 权限（无则导出按钮禁用；后端守卫为最终闸）。 */
  canExport?: boolean;
}

/**
 * ReportViewer：信封分节渲染（纯展示，数据经 ReportDialog / 父组件注入）。
 * 结构：状态横幅与告警 → 元信息卡 → Radix Tabs 分节（按 task_type）→ 导出按钮。
 */
export function ReportViewer({ envelope, reportId, canExport = false }: ReportViewerProps) {
  const typeLabel =
    ANALYSIS_TASK_TYPES.find((t) => t.value === envelope.task_type)?.label ??
    envelope.task_type;
  const sections = buildSections(envelope);
  const usageEntries = Object.entries(envelope.usage ?? {});

  return (
    <div className="space-y-4">
      {/* 状态横幅：partial 降级 / failed 防御（落库口径仅 ok / partial） */}
      {envelope.status === "partial" && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/60 bg-amber-500/10 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
          <div className="space-y-0.5">
            <p className="text-sm font-medium text-amber-600 dark:text-amber-400">
              部分状态报告
            </p>
            <p className="text-xs text-muted-foreground">
              部分内容经降级抢救或证据校验失配，结论请谨慎使用。
            </p>
          </div>
        </div>
      )}
      {envelope.status === "failed" && (
        <div className="flex items-start gap-2 rounded-md border border-destructive bg-destructive/10 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <p className="text-sm font-medium text-destructive">报告生成失败</p>
        </div>
      )}

      {/* warnings 展示（降级与证据失配等可读告警） */}
      {envelope.warnings.length > 0 && (
        <div className="space-y-1 rounded-md border p-3">
          <div className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
            <AlertTriangle className="h-3 w-3" /> 告警
          </div>
          <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted-foreground">
            {envelope.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* 头部：类型 / 状态 + 导出按钮 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{typeLabel}</Badge>
          <Badge className={STATUS_CLASS[envelope.status] ?? "bg-secondary"}>
            {envelope.status}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <ExportButton reportId={reportId} format="json" label="导出 JSON" enabled={canExport} />
          <ExportButton reportId={reportId} format="md" label="导出 MD" enabled={canExport} />
        </div>
      </div>

      {/* 信封元信息（StatCard 风格）：model / prompt_version / generated_at / usage */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        <MetaCard icon={<Cpu className="h-4 w-4" />} value={envelope.model} label="模型" />
        <MetaCard
          icon={<FileText className="h-4 w-4" />}
          value={envelope.prompt_version}
          label="提示词版本"
        />
        <MetaCard
          icon={<Clock className="h-4 w-4" />}
          value={formatGeneratedAt(envelope.generated_at)}
          label="生成时间"
        />
        {usageEntries.map(([key, value]) => (
          <MetaCard key={key} icon={<Hash className="h-4 w-4" />} value={value} label={key} />
        ))}
      </div>

      {/* 报告分节（Radix Tabs，克隆 ContributionDetail 用法） */}
      <Tabs defaultValue={sections[0]?.value}>
        <TabsList className="h-auto flex-wrap justify-start">
          {sections.map((s) => (
            <TabsTrigger key={s.value} value={s.value}>
              {s.label}
            </TabsTrigger>
          ))}
        </TabsList>
        {sections.map((s) => (
          <TabsContent key={s.value} value={s.value} className="mt-2">
            {s.node}
          </TabsContent>
        ))}
      </Tabs>

      {/* 材料节外的低占用提示：分析对象块数 */}
      <p className="flex items-center gap-1 text-xs text-muted-foreground">
        <Layers className="h-3 w-3" />
        本次分析消费 {envelope.source_chunk_ids.length} 个材料块
      </p>
    </div>
  );
}

export interface ReportDialogProps {
  reportId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  canExport?: boolean;
}

/**
 * ReportDialog：报告详情 Dialog（懒加载，克隆 ContributionDetail 范式）。
 * 仅 ``open`` 时拉取信封（useReport(open ? id : null) enabled 门控）。
 */
export function ReportDialog({
  reportId,
  open,
  onOpenChange,
  canExport = false,
}: ReportDialogProps) {
  const { data: envelope, isLoading, error } = useReport(open ? reportId : null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] w-full max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>报告详情</span>
            {reportId && (
              <span className="truncate font-mono text-xs font-normal text-muted-foreground">
                {reportId}
              </span>
            )}
          </DialogTitle>
        </DialogHeader>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : error ? (
          <p className="text-sm text-destructive">
            加载报告失败：{(error as Error).message}
          </p>
        ) : envelope && reportId ? (
          <ReportViewer envelope={envelope} reportId={reportId} canExport={canExport} />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
