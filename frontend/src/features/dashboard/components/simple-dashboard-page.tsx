import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { SpinnerBlock } from "@/components/ui/spinner";
import { ManualWarmupConfirmDialog } from "@/features/accounts/components/manual-warmup-confirm-dialog";
import { useAccounts } from "@/features/accounts/hooks/use-accounts";
import { useAuthStore, usePermission } from "@/features/auth/hooks/use-auth";
import { AccountCard } from "@/features/dashboard/components/account-card";
import { RequestLogsPanel } from "@/features/dashboard/components/request-logs-panel";
import { SimpleApiKeyCards } from "@/features/dashboard/components/simple-api-key-cards";
import { useRequestLogs } from "@/features/dashboard/hooks/use-request-logs";
import { QuickRoutingStrategy } from "@/features/settings/components/quick-routing-strategy";
import { useDialogState } from "@/hooks/use-dialog-state";

export function SimpleDashboardPage() {
  const { t } = useTranslation();
  const canReadAccounts = usePermission("accounts:read");
  const canWriteAccounts = usePermission("accounts:write");
  const canReadApiKeys = usePermission("api_keys:read");
  const canWrite = useAuthStore((state) => state.canWrite);
  const { accountsQuery, manualWarmupMutation } = useAccounts(canReadAccounts);
  const warmupDialog = useDialogState<string>();
  const canReadConversations = usePermission("conversations:read");
  const requestLogs = useRequestLogs({
    allowApiKeyFilters: canReadApiKeys,
    allowConversationFilters: canReadConversations,
  });
  const [now, setNow] = useState(Date.now);

  useEffect(() => {
    if (!canReadAccounts) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [canReadAccounts]);

  const accounts = canReadAccounts ? accountsQuery.data ?? [] : [];
  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">{t("nav.simpleDashboard")}</h1>

      {canReadAccounts ? (
        <section className="space-y-3" aria-labelledby="simple-accounts">
          <h2 id="simple-accounts" className="text-lg font-semibold">{t("accounts.page.title")}</h2>
          {accountsQuery.error ? <AlertMessage variant="error">{accountsQuery.error.message}</AlertMessage> : null}
          {accountsQuery.isPending ? <SpinnerBlock /> : null}
          {accountsQuery.isSuccess && accounts.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("apiKeys.accountSelect.empty")}</p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {accounts.map((account) => (
              <AccountCard
                key={account.accountId}
                account={account}
                compactNow={now}
                compactAction={canWriteAccounts ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={account.status !== "active" || manualWarmupMutation.isPending}
                    onClick={() => warmupDialog.show(account.accountId)}
                    title={t("accounts.actions.manualWarmupHelp")}
                  >
                    {t("accounts.actions.manualWarmup")}
                  </Button>
                ) : null}
              />
            ))}
          </div>
          {manualWarmupMutation.error ? (
            <AlertMessage variant="error">{manualWarmupMutation.error.message}</AlertMessage>
          ) : null}
          {canWriteAccounts ? (
            <ManualWarmupConfirmDialog
              open={warmupDialog.open}
              onOpenChange={warmupDialog.onOpenChange}
              onConfirm={() => {
                if (!warmupDialog.data || manualWarmupMutation.isPending) return;
                manualWarmupMutation.mutate(warmupDialog.data);
                warmupDialog.hide();
              }}
            />
          ) : null}
        </section>
      ) : null}

      {canReadApiKeys ? (
        <SimpleApiKeyCards
          accounts={accounts}
          canEdit={canWrite}
          canEditAccounts={canReadAccounts && accountsQuery.isSuccess}
        />
      ) : null}

      <QuickRoutingStrategy accounts={accounts} canWrite={canWrite} />

      <section className="space-y-4" aria-labelledby="simple-logs">
        {requestLogs.optionsQuery.error ? (
          <AlertMessage variant="error">{requestLogs.optionsQuery.error.message}</AlertMessage>
        ) : null}
        <RequestLogsPanel
          heading={<h2 id="simple-logs" className="text-lg font-semibold">{t("dashboard.views.request-logs")}</h2>}
          state={requestLogs}
          accounts={accounts}
          canReadApiKeys={canReadApiKeys}
        />
      </section>
    </div>
  );
}
