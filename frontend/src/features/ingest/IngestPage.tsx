import { FileUp, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAccess } from "@/auth/useAccess";
import { PERMISSIONS } from "@/api/types";
import type { IngestStats } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";
import { useIngest, useJob } from "./useIngest";

/** clearance 前缀（文件名 <prefix>__slug.ext -> 数据 access_level，缺省 INTERNAL）。 */
const LEVELS = [
  { value: "internal__", label: "INTERNAL（默认）" },
  { value: "public__", label: "PUBLIC" },
  { value: "confidential__", label: "CONFIDENTIAL" },
] as const;

const STAGE_LABEL: Record<string, string> = {
  queued: "排队中",
  extract: "抽取（切分 + 实体/关系识别）",
  cognify: "建图（消解 + 社区检测）",
  load: "落库（三层知识图谱）",
  done: "完成",
};

function StatsCard({ result }: { result: IngestStats }) {
  const items: [string, number][] = [
    ["文档", result.documents],
    ["文本块", result.chunks],
    ["实体", result.entities],
    ["关系", result.relations],
    ["社区", result.communities],
    ["档案卡", result.profile_cards],
  ];
  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="font-medium">摄入完成</h3>
        <Badge className="bg-emerald-600">succeeded</Badge>
      </div>
      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        {items.map(([label, value]) => (
          <div key={label} className="rounded-md border p-2 text-center">
            <div className="text-lg font-semibold">{value}</div>
            <div className="text-xs text-muted-foreground">{label}</div>
          </div>
        ))}
      </div>
      <Button asChild variant="outline" size="sm">
        <Link to="/app/library">去库浏览 →</Link>
      </Button>
    </div>
  );
}

export function IngestPage() {
  const access = useAccess();
  const canIngest = access.can(PERMISSIONS.INGEST);
  const [file, setFile] = useState<File | null>(null);
  const [level, setLevel] = useState<string>("internal__");
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const ingest = useIngest();
  const job = useJob(ingest.data?.job_id ?? null);

  const onPick = (f: File | null) => {
    if (!f) return;
    setFile(f);
  };

  // 上传文件名带 clearance 前缀（后端 _DemoAccessLoader 按前缀定 access_level）
  const uploadFile =
    file && level !== "internal__"
      ? new File([file], `${level}${file.name}`, { type: file.type })
      : file;

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !canIngest) return;
    ingest.mutate({ file: uploadFile ?? file });
  };

  const onReset = () => {
    ingest.reset();
    setFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const status = job.data?.status ?? (ingest.isPending ? "pending" : null);
  const isTerminal = status === "succeeded" || status === "failed";

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">文档摄入</h1>
        {file && <Badge variant="outline">{file.name}</Badge>}
      </div>

      <form onSubmit={onSubmit} className="space-y-4 rounded-lg border bg-card p-4">
        {/* 拖拽 / 选择文件 */}
        <div
          role="button"
          tabIndex={0}
          aria-label="选择或拖拽文档"
          onClick={() => canIngest && fileRef.current?.click()}
          onKeyDown={(e) => e.key === "Enter" && canIngest && fileRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            onPick(e.dataTransfer.files?.[0] ?? null);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed p-8 text-center transition-colors",
            dragOver ? "border-primary bg-accent/40" : "border-border hover:bg-accent/20",
            !canIngest && "pointer-events-none opacity-50"
          )}
        >
          <FileUp className="h-8 w-8 text-muted-foreground" />
          <p className="text-sm font-medium">
            {file ? file.name : "拖拽文档到此处，或点击选择文件"}
          </p>
          <p className="text-xs text-muted-foreground">
            支持 md / txt / org / rst / html / json / csv 等文本格式；图片走 OCR，PDF/Office 需装对应 extra
          </p>
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(e) => onPick(e.target.files?.[0] ?? null)}
          />
        </div>

        {/* clearance 前缀选择 */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">访问等级（文件名前缀）</span>
          <div className="inline-flex rounded-md border">
            {LEVELS.map((l) => (
              <button
                key={l.value}
                type="button"
                disabled={!canIngest}
                onClick={() => setLevel(l.value)}
                className={cn(
                  "px-3 py-1.5 text-sm transition-colors disabled:opacity-50",
                  level === l.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent"
                )}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button type="submit" disabled={!file || !canIngest || ingest.isPending}>
            <Upload className="h-4 w-4" /> 上传并建图
          </Button>
          {ingest.isError && (
            <span className="text-sm text-destructive">
              {ingest.error instanceof Error ? ingest.error.message : "上传失败"}
            </span>
          )}
          {!canIngest && (
            <span className="text-sm text-muted-foreground">无 ingest 权限，联系管理员</span>
          )}
        </div>
      </form>

      {/* 进度 + 终态 */}
      {(ingest.data || job.data) && !isTerminal && (
        <div className="space-y-2 rounded-lg border bg-card p-4">
          <div className="flex items-center justify-between">
            <h3 className="font-medium">{job.data?.filename ?? "上传中…"}</h3>
            <Badge variant="secondary">{status ?? "pending"}</Badge>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.max(5, job.data?.progress ?? 0)}%` }}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {STAGE_LABEL[job.data?.progress_stage ?? ""] ?? "排队等待 ECL 管线…"}
          </p>
        </div>
      )}

      {job.data?.status === "succeeded" && job.data.result && (
        <>
          <StatsCard result={job.data.result} />
          <Button variant="ghost" size="sm" onClick={onReset}>
            <Trash2 className="h-3.5 w-3.5" /> 清除，再传一份
          </Button>
        </>
      )}

      {job.data?.status === "failed" && (
        <div className="space-y-2 rounded-md border border-destructive bg-destructive/10 p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-destructive">摄入失败</span>
            <Button variant="ghost" size="sm" onClick={onReset}>
              重试
            </Button>
          </div>
          <Separator />
          <p className="break-all text-sm text-destructive">{job.data.error ?? "未知错误"}</p>
        </div>
      )}
    </div>
  );
}
