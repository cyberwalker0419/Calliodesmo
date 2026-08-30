// 工具轨迹折叠展示（P7 T15）：克隆 ReportViewer 证据 chips 展开范式——
// chip 列工具名 + 成败，点击展开输出 / 错误（截断口径后端已执行）。
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { AgentRunOut } from "@/api/types";

export function ToolTrace({ run }: { run: AgentRunOut | undefined }) {
  const [open, setOpen] = useState<number | null>(null);
  if (!run || run.tool_trace.length === 0) return null;
  return (
    <div className="mt-2 flex flex-col gap-2">
      <div className="flex flex-wrap gap-1">
        {run.tool_trace.map((t, i) => (
          <Button
            key={t.call.id}
            variant="outline"
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => setOpen(open === i ? null : i)}
          >
            {t.call.name}
            <Badge variant={t.result.ok ? "secondary" : "destructive"} className="ml-1 px-1">
              {t.result.ok ? "ok" : "拒"}
            </Badge>
          </Button>
        ))}
        <span className="ml-1 self-center text-xs text-muted-foreground">
          {run.steps} 步 · {run.usage?.total_tokens ?? 0} tokens
        </span>
      </div>
      {open !== null && run.tool_trace[open] ? (
        <div className="rounded-md border bg-muted/40 p-2 text-xs">
          <div className="font-medium">{run.tool_trace[open].call.name} 输出：</div>
          <pre className="mt-1 whitespace-pre-wrap">
            {run.tool_trace[open].result.output || run.tool_trace[open].result.error || "（空）"}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
