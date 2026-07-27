import { useAccess } from "@/auth/useAccess";

/** 可选库范围（null=全部）。 */
export type ScopeValue = "personal" | "project" | "team" | null;

const OPTIONS: { value: ScopeValue; label: string }[] = [
  { value: null, label: "全部" },
  { value: "personal", label: "个人库" },
  { value: "project", label: "项目库" },
  { value: "team", label: "团队库" },
];

/**
 * 库范围切换器（Task 5 Step 10）。
 * 按 AccessContext 有权 scope 切换：personal 恒有；project/team 需有成员关系
 * （与后端 visible_to 一致；不用 library_scopes，因角色 scope 与实际可见数据未必同步）。
 * 无权 scope 禁用不可选。切换后列表与子图均随 scope 过滤。
 */
export function ScopeSwitcher({
  value,
  onChange,
}: {
  value: ScopeValue;
  onChange: (v: ScopeValue) => void;
}) {
  const access = useAccess();
  const enabled: Record<string, boolean> = {
    all: true,
    personal: true,
    project: access.projectIds.size > 0,
    team: access.teamIds.size > 0,
  };
  return (
    <div className="inline-flex items-center rounded-md border">
      <span className="px-2 py-1 text-xs text-muted-foreground">库范围</span>
      {OPTIONS.map((opt) => {
        const key = opt.value ?? "all";
        const isOn = opt.value === value;
        const disabled = !enabled[key];
        return (
          <button
            key={key}
            type="button"
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            title={disabled ? "无此库范围权限" : undefined}
            className={
              "px-2.5 py-1 text-xs transition-colors " +
              (isOn ? "bg-primary text-primary-foreground" : "") +
              (disabled ? " cursor-not-allowed opacity-40" : " hover:bg-accent/60")
            }
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}