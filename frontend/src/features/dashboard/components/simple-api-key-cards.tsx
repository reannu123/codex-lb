import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { SpinnerBlock } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import type { AccountSummary } from "@/features/accounts/schemas";
import { apiKeyAccountScope, sameAccountScope } from "@/features/api-keys/account-scope";
import { ApiKeyEditDialog } from "@/features/api-keys/components/api-key-edit-dialog";
import { useApiKeys } from "@/features/api-keys/hooks/use-api-keys";
import type { ApiKey, ApiKeyAccountScope, ApiKeyUpdateRequest } from "@/features/api-keys/schemas";
import { useDialogState } from "@/hooks/use-dialog-state";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { isAccountAssignmentSelectable } from "@/utils/account-status";

type ScopeDraft = { expected: ApiKeyAccountScope; next: ApiKeyAccountScope };

type SimpleApiKeyCardsProps = {
  accounts: AccountSummary[];
  canEdit: boolean;
  canEditAccounts: boolean;
};

type ApiKeyCardProps = SimpleApiKeyCardsProps & {
  apiKey: ApiKey;
  busy: boolean;
  onEdit: () => void;
  onSaveScope: (payload: ApiKeyUpdateRequest) => Promise<unknown>;
};

function ApiKeyCard({ apiKey, accounts, canEdit, canEditAccounts, busy, onEdit, onSaveScope }: ApiKeyCardProps) {
  const { t } = useTranslation();
  const blurred = usePrivacyStore((state) => state.blurred);
  const [draft, setDraft] = useState<ScopeDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const saved = apiKeyAccountScope(apiKey);
  const stale = draft !== null && !sameAccountScope(draft.expected, saved);
  const scope = stale ? saved : (draft?.next ?? saved);
  const all = !scope.accountAssignmentScopeEnabled;
  const assignable = accounts.filter((account) => isAccountAssignmentSelectable(account.status));
  const visibleAccounts = accounts.filter((account) =>
    assignable.includes(account) || scope.assignedAccountIds.includes(account.accountId),
  );
  const allowedToEdit = canEdit && canEditAccounts;
  const closed = saved.accountAssignmentScopeEnabled && saved.assignedAccountIds.length === 0;

  function changeScope(next: ApiKeyAccountScope) {
    setDraft({ expected: draft?.expected ?? saved, next });
    setError(null);
  }

  function toggleAccount(accountId: string, checked: boolean) {
    const current = all ? assignable.map((account) => account.accountId) : scope.assignedAccountIds;
    const assignedAccountIds = checked
      ? [...current, accountId]
      : current.filter((id) => id !== accountId);
    changeScope({ accountAssignmentScopeEnabled: true, assignedAccountIds });
  }

  async function save() {
    if (!draft || stale) return;
    setError(null);
    try {
      await onSaveScope({ accountScopeUpdate: { ...draft.next, expected: draft.expected } });
      setDraft(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t("apiKeys.toasts.updateFailed"));
    }
  }

  return (
    <article className="space-y-3 rounded-xl border bg-card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{apiKey.name}</h3>
          <p className="text-xs text-muted-foreground">{apiKey.keyPrefix}</p>
        </div>
        {canEdit ? (
          <Button type="button" variant="outline" size="sm" onClick={onEdit} disabled={busy}>
            {t("common.actions.edit")}
          </Button>
        ) : null}
      </div>
      <p className={closed ? "text-sm text-destructive" : "text-sm text-muted-foreground"}>
        {closed ? t("apiKeys.accountScope.closed") : saved.accountAssignmentScopeEnabled
          ? t("apiKeys.accountSelect.selected", { count: saved.assignedAccountIds.length })
          : t("apiKeys.accountScope.useAll")}
      </p>

      {canEditAccounts ? (
        <div className="space-y-2">
          <label className="flex items-center justify-between gap-3 text-sm">
            <span>{t("apiKeys.accountScope.useAll")}</span>
            <Switch
              checked={all}
              disabled={!allowedToEdit || busy || stale}
              onCheckedChange={(checked) => changeScope({
                accountAssignmentScopeEnabled: !checked,
                assignedAccountIds: checked ? [] : assignable.map((account) => account.accountId),
              })}
            />
          </label>
          {visibleAccounts.map((account) => (
            <label key={account.accountId} className="flex items-center justify-between gap-3 text-sm">
              <span className={blurred && (!account.displayName || account.displayName === account.email)
                ? "truncate privacy-blur" : "truncate"}>
                {account.displayName || account.email}
              </span>
              <Switch
                checked={all || scope.assignedAccountIds.includes(account.accountId)}
                disabled={!allowedToEdit || busy || stale}
                onCheckedChange={(checked) => toggleAccount(account.accountId, checked)}
              />
            </label>
          ))}
          {draft && !stale && !all && scope.assignedAccountIds.length === 0 ? (
            <p className="text-sm text-destructive">{t("apiKeys.accountScope.emptyWarning")}</p>
          ) : null}
          {stale ? <AlertMessage variant="error">{t("apiKeys.accountScope.stale")}</AlertMessage> : null}
          {allowedToEdit && draft ? (
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={busy || stale || sameAccountScope(draft.next, saved)}
                onClick={() => void save()}
              >
                {t("simpleDashboard.saveScope")}
              </Button>
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => {
                setDraft(null);
                setError(null);
              }}>
                {t(stale ? "apiKeys.accountScope.review" : "common.cancel")}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
    </article>
  );
}

export function SimpleApiKeyCards({ accounts, canEdit, canEditAccounts }: SimpleApiKeyCardsProps) {
  const { t } = useTranslation();
  const { apiKeysQuery, updateMutation } = useApiKeys();
  const editor = useDialogState<string>();
  const keys = apiKeysQuery.data ?? [];

  return (
    <section className="space-y-3" aria-labelledby="simple-api-keys">
      <h2 id="simple-api-keys" className="text-lg font-semibold">{t("apiKeys.section.title")}</h2>
      {apiKeysQuery.error ? <AlertMessage variant="error">{apiKeysQuery.error.message}</AlertMessage> : null}
      {apiKeysQuery.isPending ? <SpinnerBlock /> : null}
      {apiKeysQuery.isSuccess && keys.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("simpleDashboard.noKeys")}</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {keys.map((apiKey) => (
          <ApiKeyCard
            key={apiKey.id}
            apiKey={apiKey}
            accounts={accounts}
            canEdit={canEdit}
            canEditAccounts={canEditAccounts}
            busy={updateMutation.isPending}
            onEdit={() => editor.show(apiKey.id)}
            onSaveScope={(payload) => updateMutation.mutateAsync({ keyId: apiKey.id, payload })}
          />
        ))}
      </div>
      {canEdit && editor.data ? (
        <ApiKeyEditDialog
          open={editor.open}
          apiKey={keys.find((apiKey) => apiKey.id === editor.data) ?? null}
          canEditAccounts={canEditAccounts}
          busy={updateMutation.isPending}
          onOpenChange={editor.onOpenChange}
          onSubmit={async (payload) => {
            if (editor.data) await updateMutation.mutateAsync({ keyId: editor.data, payload });
          }}
        />
      ) : null}
    </section>
  );
}
