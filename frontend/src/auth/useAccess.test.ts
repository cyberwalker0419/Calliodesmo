/**
 * P6 Task 2：analyze 权限前端常量与门控单测。
 *
 * 后端为权限唯一真相：此处仅锁定前端常量与便捷方法对齐后端
 * `Permission.ANALYZE`（src/calliodesmo/auth/models.py）。
 * 导航渲染断言归 Task 19（`/app/analysis` 路由落地同批）。
 */
import { describe, expect, it } from "vitest";
import { PERMISSIONS, type MeResponse } from "@/api/types";
import { makeAccess } from "./useAccess";

function makeMe(permissions: string[]): MeResponse {
  return {
    user_id: "u-1",
    username: "analyst-1",
    clearance: "INTERNAL",
    permissions,
    library_scopes: ["personal"],
    team_ids: [],
    project_ids: [],
  };
}

describe("PERMISSIONS.ANALYZE 常量", () => {
  it("与后端 Permission.ANALYZE 值一致", () => {
    expect(PERMISSIONS.ANALYZE).toBe("analyze");
  });
});

describe("makeAccess.canAnalyze", () => {
  it("持 analyze 权限 → true（can 泛用入口同样可用）", () => {
    const access = makeAccess(makeMe(["query", "analyze"]));
    expect(access.canAnalyze()).toBe(true);
    expect(access.can(PERMISSIONS.ANALYZE)).toBe(true);
  });

  it("无 analyze 权限 → false", () => {
    const access = makeAccess(makeMe(["query", "export"]));
    expect(access.canAnalyze()).toBe(false);
  });

  it("未登录（me=null）→ false", () => {
    expect(makeAccess(null).canAnalyze()).toBe(false);
  });
});
