import { useAuth } from "@/features/auth/AuthContext";
import { ChangePasswordForm } from "@/features/auth/ChangePasswordForm";
import { Badge } from "@/components/ui/badge";

export function SettingsPage() {
  const { me } = useAuth();
  if (!me) return null;
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-lg font-semibold">设置</h1>
      <div className="space-y-3 rounded-md border bg-card p-4">
        <h2 className="text-base font-semibold">账户信息</h2>
        <dl className="grid grid-cols-[140px_1fr] gap-y-1 text-sm">
          <dt className="text-muted-foreground">用户名</dt>
          <dd>{me.username}</dd>
          <dt className="text-muted-foreground">访问等级</dt>
          <dd><Badge variant="outline">{me.clearance}</Badge></dd>
          <dt className="text-muted-foreground">库范围</dt>
          <dd className="flex flex-wrap gap-1">
            {me.library_scopes.map((s) => (
              <Badge key={s} variant="secondary">{s}</Badge>
            ))}
          </dd>
          <dt className="text-muted-foreground">权限</dt>
          <dd className="flex flex-wrap gap-1">
            {me.permissions.map((p) => (
              <Badge key={p} variant="outline">{p}</Badge>
            ))}
          </dd>
        </dl>
      </div>
      <ChangePasswordForm />
    </div>
  );
}