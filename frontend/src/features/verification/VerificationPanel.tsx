// 接地度侧车展示（P8 T7）：声明级判定徽标 + 汇总指标 + 证据引文展开。
// 克隆 ReportViewer 证据 chips / ReportViewer partial 横幅范式，不新增依赖。
// 旧报告 verification 为 null 时直接不渲染（向后兼容）。
import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type {
  ClaimVerdict,
  VerificationClaim,
  VerificationSidecar,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** 判定徽标文案与着色（supported 绿 / unsupported 灰 / uncertain 琥珀 / contradicted 红）。 */
export const VERDICT_META: Record<
  ClaimVerdict,
  { label: string; className: string }
> = {
  supported: { label: "有据", className: "bg-emerald-600 text-white" },
  unsupported: { label: "无据", className: "bg-slate-500 text-white" },
  uncertain: { label: "待定", className: "bg-amber-500 text-white" },
  contradicted: { label: "矛盾", className: "bg-destructive text-destructive-foreground" },
  uncited: { label: "未引注", className: "bg-muted text-muted-foreground" },
};

export function VerdictBadge({ verdict }: { verdict: ClaimVerdict }) {
  const meta = VERDICT_META[verdict] ?? VERDICT_META.uncertain;
  return (
    <Badge className={cn("shrink-0 text-[10px]", meta.className)}>{meta.label}</Badge>
  );
}

function ClaimRow({ claim }: { claim: VerificationClaim }) {
  const [open, setOpen] = useState(false);
  const evidence = claim.evidence ?? [];
  return (
    <li className="space-y-1 rounded-md border p-2">
      <div className="flex items-start gap-2">
        <VerdictBadge verdict={claim.verdict} />
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-xs leading-relaxed break-words">{claim.text}</p>
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
            {claim.cited ? (
              <span>
                {claim.chunk_id ? `引注 ${claim.chunk_id}` : "已引注"}
              </span>
            ) : (
              <span>无引注</span>
            )}
            <span>置信 {claim.calibrated_confidence.toFixed(2)}</span>
            <span className="break-all">{claim.reason}</span>
          </div>
        </div>
        {evidence.length > 0 && (
          <button
            type="button"
            className="shrink-0 text-muted-foreground hover:text-foreground"
            aria-label={open ? "收起证据" : "展开证据"}
            onClick={() => setOpen(!open)}
          >
            {open ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        )}
      </div>
      {open && evidence.length > 0 && (
        <div className="space-y-1">
          {evidence.map((ev, i) => (
            <div
              key={`${ev.chunk_id}-${i}`}
              className="rounded-md border bg-muted/40 p-2 text-[11px] leading-relaxed"
            >
              <div className="font-mono text-[10px] text-muted-foreground">
                {ev.chunk_id}（{ev.match_type === "quote" ? "直接引注" : "跨文档"}）
              </div>
              <div>「{ev.quote}」</div>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

export interface VerificationPanelProps {
  verification: VerificationSidecar | null | undefined;
  /** 默认展开声明列表（报告详情默认展开，QA / Agent 默认收起）。 */
  defaultOpen?: boolean;
  className?: string;
}

/**
 * 接地度面板：汇总（接地度 / 未支撑 / 矛盾 / 未引注）+ needs_review 提示 +
 * 可折叠的声明级判定列表（含证据引文）。
 */
export function VerificationPanel({
  verification,
  defaultOpen = false,
  className,
}: VerificationPanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  if (!verification) return null;
  const { totals, metrics, needs_review: needsReview } = verification;
  const Icon = needsReview ? ShieldAlert : ShieldCheck;

  return (
    <div className={cn("space-y-2 rounded-md border p-3", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon
          className={cn(
            "h-4 w-4 shrink-0",
            needsReview ? "text-amber-500" : "text-emerald-600"
          )}
        />
        <span className="text-sm font-medium">接地度验证</span>
        <Badge variant="outline" className="text-[10px]">
          接地 {metrics.claim_grounding.toFixed(2)}
        </Badge>
        {needsReview && (
          <Badge className="bg-amber-500 text-white text-[10px]">
            <AlertTriangle className="mr-1 h-3 w-3" /> 需复核
          </Badge>
        )}
        <button
          type="button"
          className="ml-auto inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setOpen(!open)}
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          声明级判定（{totals.claims}）
        </button>
      </div>

      <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
        <span>有据 {totals.supported}</span>
        <span>无据 {totals.unsupported}</span>
        <span>待定 {totals.uncertain}</span>
        <span className={cn(totals.contradicted > 0 && "font-medium text-destructive")}>
          矛盾 {totals.contradicted}
        </span>
        <span>未引注 {totals.uncited}</span>
        <span>引注精确率 {metrics.citation_precision.toFixed(2)}</span>
      </div>

      {open && (
        <ul className="max-h-72 space-y-1.5 overflow-auto">
          {verification.claims.length === 0 ? (
            <li className="py-2 text-center text-xs text-muted-foreground">（无声明）</li>
          ) : (
            verification.claims.map((claim, i) => (
              <ClaimRow key={`${claim.text}-${i}`} claim={claim} />
            ))
          )}
        </ul>
      )}
    </div>
  );
}
