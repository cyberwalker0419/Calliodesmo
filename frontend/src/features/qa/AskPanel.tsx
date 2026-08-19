import { Globe, ImagePlus, Layers, MessageSquareText, Send, X } from "lucide-react";
import { useRef, useState } from "react";
import { AnswerCard } from "./AnswerCard";
import { useAsk } from "./useQuery";
import type { SearchMode } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

const MODES: { value: SearchMode; label: string; icon: typeof Layers }[] = [
  { value: "native_rag", label: "Native", icon: MessageSquareText },
  { value: "local", label: "Local", icon: Layers },
  { value: "global", label: "Global", icon: Globe },
];

export function AskPanel() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<SearchMode>("native_rag");
  const [topK, setTopK] = useState(10);
  const [image, setImage] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const ask = useAsk();

  const onPickImage = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!f.type.startsWith("image/")) return;
    setImage(f);
    setPreviewUrl(URL.createObjectURL(f));
  };

  const clearImage = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setImage(null);
    setPreviewUrl(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    ask.mutate({ question, mode, top_k: topK, image });
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold">问答面板</h1>
      <form onSubmit={onSubmit} className="space-y-3 rounded-lg border bg-card p-4">
        <Textarea
          placeholder="输入情报问题…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
        />

        {/* 图片上传（有图 -> /query/with-image 多模态识图） */}
        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={onPickImage}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => fileRef.current?.click()}
          >
            <ImagePlus className="h-4 w-4" /> 附带图片
          </Button>
          {previewUrl && image && (
            <span className="relative inline-block">
              <img
                src={previewUrl}
                alt="待提问图片"
                className="h-12 w-12 rounded-md border object-cover"
              />
              <button
                type="button"
                onClick={clearImage}
                aria-label="移除图片"
                className="absolute -right-1.5 -top-1.5 rounded-full border bg-background p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-md border">
            {MODES.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                type="button"
                onClick={() => setMode(value)}
                className={cn(
                  "inline-flex items-center gap-1.5 px-3 py-1.5 text-sm transition-colors",
                  mode === value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent"
                )}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">top_k</span>
            <Input
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(Math.max(1, Number(e.target.value) || 1))}
              className="w-20"
            />
          </div>
          <Button type="submit" disabled={ask.isPending} className="ml-auto">
            <Send className="h-4 w-4" /> 提问
          </Button>
        </div>
      </form>

      {ask.isPending && <Skeleton className="h-40 w-full" />}
      {ask.isError && (
        <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
          {ask.error instanceof Error ? ask.error.message : "查询失败"}
        </div>
      )}
      {ask.data && <AnswerCard result={ask.data} />}
    </div>
  );
}
