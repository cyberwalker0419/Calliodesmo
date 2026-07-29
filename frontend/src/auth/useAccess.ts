import { useAuth } from "@/features/auth/AuthContext";
import {
  CLEARANCE_RANK,
  PERMISSIONS,
  type MeResponse,
  type Permission,
} from "@/api/types";

export function useAccess() {
  const { me } = useAuth();
  return makeAccess(me);
}

export function makeAccess(me: MeResponse | null) {
  const perms = new Set(me?.permissions ?? []);
  const clearance = me ? CLEARANCE_RANK[me.clearance] ?? 0 : -1;
  const scopes = new Set(me?.library_scopes ?? []);
  return {
    me,
    can: (perm: Permission) => perms.has(perm),
    hasManageUsers: () => perms.has(PERMISSIONS.MANAGE_USERS),
    hasManageCommunity: () => perms.has(PERMISSIONS.MANAGE_COMMUNITY),
    canQuery: () => perms.has(PERMISSIONS.QUERY),
    canPush: () => perms.has(PERMISSIONS.PUSH),
    canApprove: () => perms.has(PERMISSIONS.APPROVE),
    clearanceAtLeast: (level: string) =>
      (CLEARANCE_RANK[level] ?? 0) <= clearance,
    hasScope: (scope: string) => scopes.has(scope),
    teamIds: new Set(me?.team_ids ?? []),
    projectIds: new Set(me?.project_ids ?? []),
  };
}

export type Access = ReturnType<typeof makeAccess>;