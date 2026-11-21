import { useCallback, useMemo, type ReactNode } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Columns3, RotateCcw } from "lucide-react";
import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SpinnerBlock } from "@/components/ui/spinner";

import { RequestFilters } from "@/features/dashboard/components/filters/request-filters";
import { RecentRequestsTable } from "@/features/dashboard/components/recent-requests-table";
import { useRequestLogTablePreferences } from "@/features/dashboard/hooks/use-request-log-table-preferences";
import type { useRequestLogs } from "@/features/dashboard/hooks/use-request-logs";
import { REQUEST_LOG_COLUMN_OPTIONS } from "@/features/dashboard/request-log-columns";
import type { AccountSummary } from "@/features/dashboard/schemas";
import { REQUEST_STATUS_LABELS } from "@/utils/constants";
import { formatModelLabel, formatCurrency, formatSlug } from "@/utils/formatters";
import { usePrivacyStore } from "@/hooks/use-privacy";

const MODEL_OPTION_DELIMITER = ":::";

type RequestLogsPanelProps = {
  state: ReturnType<typeof useRequestLogs>;
  accounts: AccountSummary[];
  canReadApiKeys: boolean;
  heading: ReactNode;
};

export function RequestLogsPanel({ state, accounts, canReadApiKeys, heading }: RequestLogsPanelProps) {
  const { t } = useTranslation();
  const { filters, emptyStateFiltersApplied, logsQuery, optionsQuery, updateFilters } = state;
  const { visibleColumns, columnWidths, toggleColumn, setColumnWidth, restoreDefaultLayout } =
    useRequestLogTablePreferences();
  const logPage = logsQuery.data;
  const handleConversationClick = useCallback(
    (conversationId: string) => {
      updateFilters({ conversationId, offset: 0 });
    },
    [updateFilters],
  );

  const handleConversationDismiss = useCallback(() => {
    updateFilters({ conversationId: null, offset: 0 });
  }, [updateFilters]);

  const accountOptions = useMemo(() => {
    const entries = new Map<string, { label: string; isEmail: boolean }>();
    for (const account of accounts) {
      const raw = account.displayName || account.email || account.accountId;
      const isEmail = !!account.email && raw === account.email;
      entries.set(account.accountId, { label: raw, isEmail });
    }
    return (optionsQuery.data?.accountIds ?? []).map((accountId) => {
      const entry = entries.get(accountId);
      return {
        value: accountId,
        label: entry?.label ?? accountId,
        isEmail: entry?.isEmail ?? false,
      };
    });
  }, [optionsQuery.data?.accountIds, accounts]);

  const apiKeyOptions = useMemo(
    () =>
      (optionsQuery.data?.apiKeys ?? []).map((option) => ({
        value: option.id,
        label: option.keyPrefix ? `${option.name} · ${option.keyPrefix}` : option.name,
      })),
    [optionsQuery.data?.apiKeys],
  );

  const modelOptions = useMemo(
    () =>
      (optionsQuery.data?.modelOptions ?? []).map((option) => ({
        value: `${option.model}${MODEL_OPTION_DELIMITER}${option.reasoningEffort ?? ""}`,
        label: formatModelLabel(option.model, option.reasoningEffort),
      })),
    [optionsQuery.data?.modelOptions],
  );

  const blurred = usePrivacyStore((s) => s.blurred);

  const conversationSummary = useMemo(() => {
    const conv = logPage?.conversation;
    if (!conv || !filters.conversationId) {
      return null;
    }
    const cost = formatCurrency(conv.aggregatedCostUsd);
    const count = conv.requestCount;
    const suffixParts: string[] = [];

    if (filters.timeframe !== "all") {
      suffixParts.push(filters.timeframe);
    }
    if (filters.statuses.length > 0) {
      const labels = filters.statuses.map(
        (s) => t(`dashboard.requestStatus.${s}`, { defaultValue: REQUEST_STATUS_LABELS[s] ?? s }),
      );
      suffixParts.push(labels.join(", "));
    }
    if (filters.modelOptions.length > 0) {
      const labels = filters.modelOptions.map((raw) => {
        const decoded = modelOptions.find((o) => o.value === raw);
        if (decoded) return decoded.label;
        // Decode from the filter value itself when options are stale/missing
        const [model, ...rest] = raw.split(MODEL_OPTION_DELIMITER);
        const effort = rest.join(MODEL_OPTION_DELIMITER);
        return formatModelLabel(model, effort || null);
      });
      suffixParts.push(labels.join(", "));
    }
    if (filters.accountIds.length > 0) {
      const labels = filters.accountIds.map((id) => {
        const opt = accountOptions.find((o) => o.value === id);
        if (!opt) return t("dashboard.filters.accounts"); // safe fallback: localized label
        const raw = opt.label;
        if (blurred && opt.isEmail) {
          return id.slice(0, 8);
        }
        return raw;
      });
      suffixParts.push(labels.join(", "));
    }
    if (filters.apiKeyIds.length > 0) {
      const labels = filters.apiKeyIds.map((id) => {
        const opt = apiKeyOptions.find((o) => o.value === id);
        return opt?.label ?? t("dashboard.filters.apiKeys"); // safe fallback
      });
      suffixParts.push(labels.join(", "));
    }
    if (filters.search) {
      suffixParts.push(`"${filters.search}"`);
    }

    const codeClass = "rounded bg-muted px-1 py-0.5 text-xs font-mono";

    if (suffixParts.length > 0) {
      return (
        <Trans
          i18nKey="dashboard.conversation.summaryWithFilters"
          values={{ id: filters.conversationId, count, cost, filters: suffixParts.join(", ") }}
          components={[
            <code key="id" className={codeClass} />,
            <code key="count" className={codeClass} />,
            <code key="cost" className={codeClass} />,
          ]}
        />
      );
    }
    return (
      <Trans
        i18nKey="dashboard.conversation.summary"
        values={{ id: filters.conversationId, count, cost }}
        components={[
          <code key="id" className={codeClass} />,
          <code key="count" className={codeClass} />,
          <code key="cost" className={codeClass} />,
        ]}
      />
    );
  }, [logPage?.conversation, filters, t, accountOptions, apiKeyOptions, modelOptions, blurred]);

  const statusOptions = useMemo(
    () =>
      (optionsQuery.data?.statuses ?? []).map((status) => ({
        value: status,
        label: t(`dashboard.requestStatus.${status}`, { defaultValue: REQUEST_STATUS_LABELS[status] ?? formatSlug(status) }),
      })),
    [optionsQuery.data?.statuses, t],
  );

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        {heading}
        <div className="h-px min-w-8 flex-1 bg-border" />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="outline" size="sm">
              <Columns3 className="mr-2 h-4 w-4" />
              {t("dashboard.requests.columnLayout.columns", {
                count: visibleColumns.length,
              })}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel>
              {t("dashboard.requests.columnLayout.visibleColumns")}
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {REQUEST_LOG_COLUMN_OPTIONS.map((column) => {
              const isVisible = visibleColumns.includes(column.id);
              return (
                <DropdownMenuCheckboxItem
                  key={column.id}
                  checked={isVisible}
                  disabled={isVisible && visibleColumns.length === 1}
                  onCheckedChange={() => toggleColumn(column.id)}
                  onSelect={(event) => event.preventDefault()}
                >
                  {t(column.translationKey)}
                </DropdownMenuCheckboxItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={t("dashboard.requests.columnLayout.restoreDefault")}
          title={t("dashboard.requests.columnLayout.restoreDefault")}
          onClick={restoreDefaultLayout}
        >
          <RotateCcw className="h-4 w-4" />
        </Button>
      </div>
      {logsQuery.error ? (
        <div className="space-y-3 rounded-xl border bg-card p-4">
          <div role="alert">
            <AlertMessage variant="error">{logsQuery.error.message}</AlertMessage>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              void logsQuery.refetch();
            }}
            disabled={logsQuery.isFetching}
          >
            {t("common.actions.retry")}
          </Button>
        </div>
      ) : null}
      {logsQuery.isPending && !logPage ? (
        <div className="rounded-xl border bg-card py-8">
          <SpinnerBlock />
        </div>
      ) : logPage ? (
        <>
          <RequestFilters
            filters={filters}
            accountOptions={accountOptions}
            apiKeyOptions={apiKeyOptions}
            modelOptions={modelOptions}
            statusOptions={statusOptions}
            showApiKeyFilter={canReadApiKeys}
            onSearchChange={(search) => updateFilters({ search, offset: 0 })}
            onTimeframeChange={(timeframe) => updateFilters({ timeframe, offset: 0 })}
            onAccountChange={(accountIds) => updateFilters({ accountIds, offset: 0 })}
            onApiKeyChange={(apiKeyIds) => updateFilters({ apiKeyIds, offset: 0 })}
            onModelChange={(modelOptionsSelected) =>
              updateFilters({ modelOptions: modelOptionsSelected, offset: 0 })
            }
            onStatusChange={(statuses) => updateFilters({ statuses, offset: 0 })}
            onConversationDismiss={handleConversationDismiss}
            onReset={() =>
              updateFilters({
                search: "",
                timeframe: "all",
                accountIds: [],
                apiKeyIds: [],
                modelOptions: [],
                statuses: [],
                conversationId: null,
                offset: 0,
              })
            }
          />
          {conversationSummary ? (
            <div className="rounded-xl border bg-card p-4">
              <p className="text-sm text-muted-foreground">{conversationSummary}</p>
            </div>
          ) : null}
          <div className="transition-opacity duration-200">
            <RecentRequestsTable
              requests={logPage.requests}
              accounts={accounts}
              total={logPage.total}
              visibleColumns={visibleColumns}
              columnWidths={columnWidths}
              onColumnWidthChange={setColumnWidth}
              limit={filters.limit}
              offset={filters.offset}
              hasMore={logPage.hasMore}
              filtersApplied={emptyStateFiltersApplied}
              onLimitChange={(limit) => updateFilters({ limit, offset: 0 })}
              onOffsetChange={(offset) => updateFilters({ offset })}
              onConversationClick={handleConversationClick}
            />
          </div>
        </>
      ) : null}
    </>
  );
}
