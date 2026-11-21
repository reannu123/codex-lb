import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { useDialogState } from "@/hooks/use-dialog-state";
import { useAccountMutations } from "@/features/accounts/hooks/use-accounts";
import { ResetCreditConfirmDialog } from "@/features/accounts/components/reset-credit-confirm-dialog";
import { AccountCards } from "@/features/dashboard/components/account-cards";
import { AccountList } from "@/features/dashboard/components/account-list";
import { AccountSummaryLine } from "@/features/dashboard/components/account-summary-line";
import { AccountViewModeToggle } from "@/features/dashboard/components/account-view-mode-toggle";
import { DashboardSkeleton } from "@/features/dashboard/components/dashboard-skeleton";
import { ConversationsView } from "@/features/dashboard/components/conversations-view";
import { ConversationTimeframeSelect } from "@/features/dashboard/components/filters/conversation-timeframe-select";
import { DashboardViewSelector } from "@/features/dashboard/components/filters/dashboard-view-selector";
import { OverviewTimeframeSelect } from "@/features/dashboard/components/filters/overview-timeframe-select";
import { RequestLogsPanel } from "@/features/dashboard/components/request-logs-panel";
import { StatsGrid } from "@/features/dashboard/components/stats-grid";
import { UsageDonuts } from "@/features/dashboard/components/usage-donuts";
import { WeeklyCreditsPaceCard } from "@/features/dashboard/components/weekly-credits-pace-card";
import { useAuthStore, usePermission } from "@/features/auth/hooks/use-auth";
import { useDashboard, useDashboardProjections } from "@/features/dashboard/hooks/use-dashboard";
import { useConversations } from "@/features/dashboard/hooks/use-conversations";
import { useRequestLogs } from "@/features/dashboard/hooks/use-request-logs";
import { buildDashboardView } from "@/features/dashboard/utils";
import {
  DEFAULT_OVERVIEW_TIMEFRAME,
  parseDashboardView,
  parseConversationTimeframe,
  parseOverviewTimeframe,
  type AccountSummary,
  type ConversationTimeframe,
  type OverviewTimeframe,
} from "@/features/dashboard/schemas";
import { useDashboardPreferencesStore } from "@/hooks/use-dashboard-preferences";
import { useThemeStore } from "@/hooks/use-theme";
import { getErrorMessageOrNull } from "@/utils/errors";

type RetainedDashboardLoadError = {
  timeframe: OverviewTimeframe;
  message: string;
};

export function DashboardPage() {
  const { t, i18n } = useTranslation();
  const resolvedLanguage = i18n.resolvedLanguage;
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const isDark = useThemeStore((s) => s.theme === "dark");
  const showAccountBurnrate = useDashboardPreferencesStore((s) => s.accountBurnrateEnabled);
  const accountViewMode = useDashboardPreferencesStore((s) => s.accountViewMode);
  const accountListSort = useDashboardPreferencesStore((s) => s.accountListSort);
  const setAccountViewMode = useDashboardPreferencesStore((s) => s.setAccountViewMode);
  const setAccountListSort = useDashboardPreferencesStore((s) => s.setAccountListSort);
  // Each surface follows the permission its backend route demands, not the
  // coarse `write` alias: conversations and archives need `conversations:read`,
  // account actions `accounts:write`, the API-key filter `api_keys:read`.
  const canWriteAccounts = usePermission("accounts:write");
  const canReadApiKeys = usePermission("api_keys:read");
  const initialized = useAuthStore((state) => state.initialized);
  const hasConversationsRead = usePermission("conversations:read");
  const canReadConversations = initialized && hasConversationsRead;
  const overviewTimeframe = useMemo(
    () => parseOverviewTimeframe(searchParams.get("overviewTimeframe")),
    [searchParams],
  );
  const conversationTimeframe = useMemo(
    () => parseConversationTimeframe(searchParams.get("conversationTimeframe")),
    [searchParams],
  );
  const requestedDashboardView = useMemo(
    () => parseDashboardView(searchParams.get("view")),
    [searchParams],
  );
  const dashboardView = canReadConversations ? requestedDashboardView : "request-logs";
  useEffect(() => {
    if (!initialized || canReadConversations || searchParams.get("view") !== "conversations") {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("view");
    setSearchParams(next, { replace: true });
  }, [initialized, canReadConversations, searchParams, setSearchParams]);
  // Conversation stats must follow the timeframe restored for the active
  // view, including when that state came from a bookmarked URL.
  const dashboardTimeframe =
    dashboardView === "conversations" ? conversationTimeframe : overviewTimeframe;
  const dashboardQuery = useDashboard(dashboardTimeframe);
  const [retainedDashboardLoadError, setRetainedDashboardLoadError] =
    useState<RetainedDashboardLoadError | null>(null);
  const [overviewRetryTimeframe, setOverviewRetryTimeframe] =
    useState<OverviewTimeframe | null>(null);
  const projectionsQuery = useDashboardProjections(Boolean(dashboardQuery.data));
  const conversationsState = useConversations({
    enabled: canReadConversations && dashboardView === "conversations",
  });
  const { conversationsQuery } = conversationsState;
  // Read-only sessions never see the API-key filter control, so they must not
  // query with one either (URL-carried `apiKeyId` is dropped).
  const requestLogsState = useRequestLogs({
    enabled: dashboardView === "request-logs",
    allowApiKeyFilters: canReadApiKeys,
    allowConversationFilters: canReadConversations,
  });
  const { logsQuery, optionsQuery } = requestLogsState;
  const { resumeMutation, limitWarmupMutation } = useAccountMutations();
  type ResetCreditDialogTarget = { accountId: string; availableResetCredits: number };
  const resetCreditDialog = useDialogState<ResetCreditDialogTarget>();

  const activeListIsFetching = dashboardView === "request-logs"
    ? logsQuery.isFetching
    : conversationsQuery.isFetching;
  const isRefreshing = dashboardQuery.isFetching || projectionsQuery.isFetching || activeListIsFetching;

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [queryClient]);

  const handleOverviewTimeframeChange = useCallback(
    (timeframe: OverviewTimeframe) => {
      const next = new URLSearchParams(searchParams);
      if (timeframe === DEFAULT_OVERVIEW_TIMEFRAME) {
        next.delete("overviewTimeframe");
      } else {
        next.set("overviewTimeframe", timeframe);
      }
      setSearchParams(next);
    },
    [searchParams, setSearchParams],
  );

  const handleConversationTimeframeChange = useCallback(
    (timeframe: ConversationTimeframe) => {
      conversationsState.updateFilters({ timeframe, offset: 0 });
    },
    [conversationsState],
  );

  const handleDashboardViewChange = useCallback(
    (nextView: "request-logs" | "conversations") => {
      if (nextView === "conversations" && !canReadConversations) {
        return;
      }
      const next = new URLSearchParams(searchParams);
      if (nextView === "request-logs") {
        next.delete("view");
      } else {
        next.set("view", nextView);
      }
      setSearchParams(next);
    },
    [canReadConversations, searchParams, setSearchParams],
  );

  const handleAccountAction = useCallback(
    (account: AccountSummary, action: string) => {
      switch (action) {
        case "details":
          navigate(`/accounts?selected=${account.accountId}`);
          break;
        case "resume":
          if (canWriteAccounts) {
            void resumeMutation.mutateAsync(account.accountId);
          }
          break;
        case "reauth":
          navigate(`/accounts?selected=${account.accountId}`);
          break;
        case "warmup-toggle":
          if (canWriteAccounts) {
            void limitWarmupMutation.mutateAsync({
              accountId: account.accountId,
              enabled: !account.limitWarmupEnabled,
            });
          }
          break;
        case "reset-credit":
          resetCreditDialog.show({
            accountId: account.accountId,
            availableResetCredits: account.availableResetCredits ?? 0,
          });
          break;
      }
    },
    [canWriteAccounts, limitWarmupMutation, navigate, resetCreditDialog, resumeMutation],
  );

  const overview = dashboardQuery.data;
  const logPage = logsQuery.data;

  const view = useMemo(() => {
    void resolvedLanguage;
    if (!overview) {
      return null;
    }
    return buildDashboardView(
      overview,
      logPage?.requests ?? [],
      {
        isDark,
        showAccountBurnrate,
      },
      projectionsQuery.data,
    );
  }, [overview, logPage, isDark, showAccountBurnrate, projectionsQuery.data, resolvedLanguage]);

  const dashboardLoadError = getErrorMessageOrNull(dashboardQuery.error);
  if (
    retainedDashboardLoadError !== null &&
    (overview || retainedDashboardLoadError.timeframe !== dashboardTimeframe)
  ) {
    setRetainedDashboardLoadError(null);
  } else if (
    !overview &&
    dashboardLoadError !== null &&
    (retainedDashboardLoadError === null ||
      retainedDashboardLoadError.message !== dashboardLoadError)
  ) {
    setRetainedDashboardLoadError({
      timeframe: dashboardTimeframe,
      message: dashboardLoadError,
    });
  }
  const displayedDashboardLoadError =
    dashboardLoadError ??
    (retainedDashboardLoadError?.timeframe === dashboardTimeframe
      ? retainedDashboardLoadError.message
      : null);
  const overviewRetryBusy =
    dashboardQuery.isFetching || overviewRetryTimeframe === dashboardTimeframe;
  const errorMessage =
    (overview ? dashboardLoadError : null) ||
    (dashboardView === "request-logs" && optionsQuery.error instanceof Error && optionsQuery.error.message) ||
    null;

  const dashboardViewSelector = (
    <DashboardViewSelector
      value={dashboardView}
      onChange={handleDashboardViewChange}
      showConversations={canReadConversations}
    />
  );

  return (
    <div className="animate-fade-in-up space-y-8">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("dashboard.page.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("dashboard.page.subtitle")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dashboardView === "request-logs" ? (
            <OverviewTimeframeSelect
              value={overviewTimeframe}
              onChange={handleOverviewTimeframeChange}
            />
          ) : null}
          {dashboardView === "conversations" ? (
            <ConversationTimeframeSelect
              value={conversationTimeframe}
              onChange={handleConversationTimeframeChange}
            />
          ) : null}
          <button
            type="button"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
            aria-label={t("dashboard.page.refresh")}
            title={t("dashboard.page.refresh")}
          >
            <RefreshCw className={`h-4 w-4${isRefreshing ? " animate-spin" : ""}`} aria-hidden="true" />
          </button>
        </div>
      </div>

      {errorMessage ? <AlertMessage variant="error">{errorMessage}</AlertMessage> : null}

      {(dashboardQuery.isPending || dashboardQuery.isFetching) &&
      !view &&
      displayedDashboardLoadError === null ? (
        <DashboardSkeleton />
      ) : !view ? (
        <div className="space-y-3 rounded-xl border bg-card p-4">
          <div role="alert">
            <AlertMessage variant="error">{displayedDashboardLoadError ?? "Request failed"}</AlertMessage>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-busy={overviewRetryBusy}
            disabled={overviewRetryBusy}
            onClick={() => {
              const retryTimeframe = dashboardTimeframe;
              setRetainedDashboardLoadError({
                timeframe: retryTimeframe,
                message: displayedDashboardLoadError ?? "Request failed",
              });
              setOverviewRetryTimeframe(retryTimeframe);
              void dashboardQuery.refetch().finally(() => {
                setOverviewRetryTimeframe((current) =>
                  current === retryTimeframe ? null : current,
                );
              });
            }}
          >
            {t("common.actions.retry")}
          </Button>
        </div>
      ) : (
        <>
          <StatsGrid stats={view.stats} />

          {view.weeklyCreditPace ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
              <UsageDonuts
                primaryItems={view.primaryUsageItems}
                secondaryItems={view.secondaryUsageItems}
                primaryTotal={overview?.summary.primaryWindow.capacityCredits ?? 0}
                secondaryTotal={overview?.summary.secondaryWindow?.capacityCredits ?? 0}
                primaryCenterValue={view.primaryTotal}
                secondaryCenterValue={view.secondaryTotal}
                safeLinePrimary={view.safeLinePrimary}
                safeLineSecondary={view.safeLineSecondary}
              />
              <WeeklyCreditsPaceCard pace={view.weeklyCreditPace} />
            </div>
          ) : (
            <UsageDonuts
              primaryItems={view.primaryUsageItems}
              secondaryItems={view.secondaryUsageItems}
              primaryTotal={overview?.summary.primaryWindow.capacityCredits ?? 0}
              secondaryTotal={overview?.summary.secondaryWindow?.capacityCredits ?? 0}
              primaryCenterValue={view.primaryTotal}
              secondaryCenterValue={view.secondaryTotal}
              safeLinePrimary={view.safeLinePrimary}
              safeLineSecondary={view.safeLineSecondary}
            />
          )}

          <section className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex min-w-0 flex-wrap items-center gap-3">
                <h2 className="text-[13px] font-medium uppercase tracking-wider text-muted-foreground">{t("accounts.page.title")}</h2>
                <AccountSummaryLine accounts={overview?.accounts ?? []} />
              </div>
              <div className="h-px min-w-8 flex-1 bg-border" />
              <AccountViewModeToggle value={accountViewMode} onChange={setAccountViewMode} />
            </div>
            {accountViewMode === "list" ? (
              <AccountList
                accounts={overview?.accounts ?? []}
                readOnly={!canWriteAccounts}
                sort={accountListSort}
                onSortChange={setAccountListSort}
                onAction={handleAccountAction}
              />
            ) : (
              <AccountCards accounts={overview?.accounts ?? []} readOnly={!canWriteAccounts} onAction={handleAccountAction} />
            )}
          </section>

          <section className="space-y-4">
            {canReadConversations && dashboardView === "conversations" ? (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  {dashboardViewSelector}
                  <div className="h-px min-w-8 flex-1 bg-border" />
                </div>
                <ConversationsView state={conversationsState} accounts={overview?.accounts ?? []} />
              </>
            ) : (
              <RequestLogsPanel
                heading={dashboardViewSelector}
                state={requestLogsState}
                accounts={overview?.accounts ?? []}
                canReadApiKeys={canReadApiKeys}
              />
            )}
          </section>
        </>
      )}

      {resetCreditDialog.data ? (
        <ResetCreditConfirmDialog
          open={resetCreditDialog.open}
          accountId={resetCreditDialog.data.accountId}
          summaryAvailableCount={resetCreditDialog.data.availableResetCredits}
          onOpenChange={resetCreditDialog.onOpenChange}
        />
      ) : null}

    </div>
  );
}
