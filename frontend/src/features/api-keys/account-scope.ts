import type { ApiKeyAccountScope } from "@/features/api-keys/schemas";

export function apiKeyAccountScope(key: ApiKeyAccountScope): ApiKeyAccountScope {
  return {
    accountAssignmentScopeEnabled: key.accountAssignmentScopeEnabled,
    assignedAccountIds: key.assignedAccountIds,
  };
}

export function sameAccountScope(left: ApiKeyAccountScope, right: ApiKeyAccountScope): boolean {
  return (
    left.accountAssignmentScopeEnabled === right.accountAssignmentScopeEnabled &&
    left.assignedAccountIds.length === right.assignedAccountIds.length &&
    left.assignedAccountIds.every((id) => right.assignedAccountIds.includes(id))
  );
}
