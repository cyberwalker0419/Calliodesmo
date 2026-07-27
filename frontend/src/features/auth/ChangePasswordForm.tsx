import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/use-toast";

export function ChangePasswordForm() {
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        old_password: oldPw,
        new_password: newPw,
      });
      toast({ title: "密码已修改", description: "请重新登录。" });
      setOldPw("");
      setNewPw("");
    } catch (err) {
      toast({
        variant: "destructive",
        title: "修改失败",
        description: err instanceof Error ? err.message : "未知错误",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-md space-y-4">
      <div className="flex items-center gap-2">
        <KeyRound className="h-5 w-5 text-primary" />
        <h2 className="text-lg font-semibold">修改密码</h2>
      </div>
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="old-pw">旧密码</Label>
          <Input
            id="old-pw"
            type="password"
            value={oldPw}
            onChange={(e) => setOldPw(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new-pw">新密码（至少 6 位）</Label>
          <Input
            id="new-pw"
            type="password"
            value={newPw}
            onChange={(e) => setNewPw(e.target.value)}
            minLength={6}
            required
          />
        </div>
        <Button type="submit" disabled={busy}>
          提交修改
        </Button>
      </form>
    </div>
  );
}