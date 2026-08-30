import { useState } from "react";
import { Library, Menu, MessageSquareText, Settings, Users, Network, FolderKanban, GitPullRequest, FileUp, Sparkles, History } from "lucide-react";
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
  // P7 T1：移动端（<md）折叠侧栏——桌面固定侧栏，移动端汉堡抽屉
  const [navOpen, setNavOpen] = useState(false);

  const onLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const navBody = (
    <>
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
    </>
  );

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4">
        <div className="flex min-w-0 items-center gap-3">
          {/* P7 T1：移动端汉堡按钮（<md 可见），展开抽屉导航 */}
          <Button
            variant="ghost"
            size="sm"
            className="md:hidden"
            aria-label="打开导航菜单"
            onClick={() => setNavOpen(true)}
          >
            <Menu className="h-4 w-4" />
          </Button>
          <div className="flex min-w-0 items-center gap-6">
            <span className="whitespace-nowrap text-base font-semibold tracking-tight">
              Calliodesmo
            </span>
            {/* 窄视口隐藏副标题与密级徽标，防顶栏挤压竖排（P7 T1 移动闭环） */}
            <span className="hidden whitespace-nowrap text-xs text-muted-foreground sm:inline">
              情报分析平台
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <Badge variant="secondary">{me?.username}</Badge>
          <Badge variant="outline" className="hidden sm:inline-flex">
            {me?.clearance}
          </Badge>
          <Button variant="ghost" size="sm" onClick={onLogout}>
            登出
          </Button>
        </div>
      </header>
      <div className="flex flex-1 overflow-hidden">
        {/* 桌面固定侧栏（≥md） */}
        <nav className="hidden w-56 shrink-0 flex-col gap-1 border-r p-3 md:flex">
          {navBody}
        </nav>
        {/* P7 T1：移动端抽屉（<md）——遮罩 + 左滑面板，点导航项或遮罩收起 */}
        {navOpen && (
          <div
            className="fixed inset-0 z-40 md:hidden"
            role="dialog"
            aria-modal="true"
            aria-label="导航菜单"
          >
            <div
              className="absolute inset-0 bg-black/40"
              data-testid="drawer-backdrop"
              aria-hidden
              onClick={() => setNavOpen(false)}
            />
            <nav
              className="absolute inset-y-0 left-0 flex w-64 flex-col gap-1 overflow-auto border-r bg-background p-3"
              onClick={() => setNavOpen(false)}
            >
              {navBody}
            </nav>
          </div>
        )}
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
      <Toaster />
    </div>
  );
}
