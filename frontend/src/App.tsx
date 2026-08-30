import { Library, MessageSquareText, Settings, Users, Network, FolderKanban, GitPullRequest, FileUp, Sparkles, History } from "lucide-react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/features/auth/AuthContext";
import { useAccess } from "@/auth/useAccess";
import { PERMISSIONS } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/toaster";
import { cn } from "@/lib/utils";

function NavItem({
  to,
  icon: Icon,
  label,
  end,
}: {
  to: string;
  icon: typeof Users;
  label: string;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/60"
        )
      }
    >
      <Icon className="h-4 w-4" /> {label}
    </NavLink>
  );
}

export default function AppLayout() {
  const { me, logout } = useAuth();
  const access = useAccess();
  const navigate = useNavigate();

  const onLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
        <div className="flex items-center gap-6">
          <span className="text-base font-semibold tracking-tight">Calliodesmo</span>
          <span className="text-xs text-muted-foreground">情报分析平台</span>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="secondary">{me?.username}</Badge>
          <Badge variant="outline">{me?.clearance}</Badge>
          <Button variant="ghost" size="sm" onClick={onLogout}>
            登出
          </Button>
        </div>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <nav className="flex w-56 shrink-0 flex-col gap-1 border-r p-3">
          {access.canQuery() && <NavItem to="/app/qa" icon={MessageSquareText} label="问答面板" />}
          {access.canQuery() && <NavItem to="/app/library" icon={Library} label="知识库浏览" />}
          {access.can(PERMISSIONS.INGEST) && (
            <NavItem to="/app/ingest" icon={FileUp} label="文档摄入" />
          )}
          {/* P6：分析入口（access.can(ANALYZE) 隐藏式门控，与 Task 2 常量在此会合） */}
          {access.can(PERMISSIONS.ANALYZE) && (
            <NavItem to="/app/analysis" icon={Sparkles} label="分析" end />
          )}
          {/* P6 Task 20：报告历史（ANALYZE 门控，与 /analysis 列表/详情端点同口径） */}
          {access.can(PERMISSIONS.ANALYZE) && (
            <NavItem to="/app/analysis/reports" icon={History} label="报告历史" />
          )}
          {access.canPush() && (
            <NavItem to="/app/collab" icon={GitPullRequest} label="协作推送" />
          )}
          {access.hasManageUsers() && (
            <>
              <div className="mt-3 px-3 pb-1 text-xs font-medium uppercase text-muted-foreground">
                管理
              </div>
              <NavItem to="/app/admin/users" icon={Users} label="用户管理" />
              <NavItem to="/app/admin/teams" icon={Network} label="团队 / 项目" />
              <NavItem to="/app/admin/communities" icon={FolderKanban} label="社区管理" />
            </>
          )}
          <div className="mt-auto">
            <NavItem to="/app/settings" icon={Settings} label="设置" />
          </div>
        </nav>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  );
}