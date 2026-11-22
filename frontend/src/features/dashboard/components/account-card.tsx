import type { ReactNode } from "react";
import { Clock, ExternalLink, Play, RotateCcw, Zap } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePrivacyStore } from "@/hooks/use-privacy";
import { useDateDisplayFormatStore } from "@/hooks/use-date-format";
import { useSmoothPercent } from "@/hooks/use-smooth-percent";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import {
  accountSubscriptionCredits,
  formatCreditValue,
  formatPurchasedCredits,
} from "@/features/dashboard/account-credit-display";
import { cn } from "@/lib/utils";
import type { AccountSummary } from "@/features/dashboard/schemas";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import {
  normalizeStatus,
  quotaBarColor,
  quotaBarTrack,
} from "@/utils/account-status";
import {
  formatDateTimeInline,
  formatPercentNullable,
  formatLocalResetTime,
  formatQuotaObservation,
  formatQuotaResetCountdown,
  formatQuotaResetLabel,
  parseDate,
  formatSingleUnitRemaining,
  formatSlug,
} from "@/utils/formatters";

export type AccountAction = "details" | "resume" | "reauth" | "warmup-toggle" | "reset-credit";

export type AccountCardProps = {
  account: AccountSummary;
  showAccountId?: boolean;
  readOnly?: boolean;
  compactNow?: number;
  compactAction?: ReactNode;
  onAction?: (account: AccountSummary, action: AccountAction) => void;
};

function formatWarmupWindow(window: string): string {
  return window === "primary" || window === "primary_idle" ? "5h" : "weekly";
}

function QuotaBar({
  label,
  percent,
  resetAt,
  compactNow,
  observationLabel,
}: {
  label: string;
  percent: number | null;
  resetAt: string | null | undefined;
  compactNow?: number;
  observationLabel: string | null;
}) {
  const clamped = percent === null ? 0 : Math.max(0, Math.min(100, percent));
  const hasPercent = percent !== null;
  const resetDate = compactNow === undefined || observationLabel !== null ? null : parseDate(resetAt);
  const resetLabel = observationLabel ?? (compactNow === undefined
    ? formatQuotaResetLabel(resetAt)
    : formatQuotaResetCountdown(resetDate, compactNow));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span
          className={cn(
            "tabular-nums font-medium",
            !hasPercent
              ? "text-muted-foreground"
              : clamped >= 70
                ? "text-emerald-600 dark:text-emerald-400"
                : clamped >= 30
                  ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400",
          )}
        >
          {formatPercentNullable(percent, 1)}
        </span>
      </div>
      <div className={cn("h-1.5 w-full overflow-hidden rounded-full", quotaBarTrack(clamped))}>
        <div
          className={cn("h-full rounded-full transition-colors duration-500 ease-out", quotaBarColor(clamped))}
          style={{ width: `${clamped}%` }}
        />
      </div>
      <div className="flex items-center gap-1 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3 shrink-0" />
        <span>{resetLabel}</span>
      </div>
      {compactNow !== undefined && resetDate !== null && resetDate.getTime() > 0 ? (
        <time dateTime={resetDate.toISOString()} className="block text-[11px] text-muted-foreground">
          {formatLocalResetTime(resetDate)}
        </time>
      ) : null}
    </div>
  );
}

export function AccountCard({ account, showAccountId = false, readOnly = false, compactNow, compactAction, onAction }: AccountCardProps) {
  const { t } = useTranslation();
  const blurred = usePrivacyStore((s) => s.blurred);
  const dateDisplayFormat = useDateDisplayFormatStore((s) => s.dateDisplayFormat);
  const status = normalizeStatus(account.status);
  const primaryState = useSmoothPercent(account.usage?.primaryRemainingPercent ?? null);
  const secondaryState = useSmoothPercent(account.usage?.secondaryRemainingPercent ?? null);
  const monthlyState = useSmoothPercent(account.usage?.monthlyRemainingPercent ?? null);
  const primaryRemaining = primaryState.percent;
  const secondaryRemaining = secondaryState.percent;
  const monthlyRemaining = monthlyState.percent;
  const hasPrimaryWindow = account.primaryWindowNotStarted || account.windowMinutesPrimary != null || primaryState.everKnown ||
    (compactNow !== undefined && account.resetAtPrimary != null);
  const hasSecondaryWindow = account.windowMinutesSecondary != null || secondaryState.everKnown ||
    (compactNow !== undefined && account.resetAtSecondary != null);
  const hasMonthlyWindow = account.windowMinutesMonthly != null || monthlyState.everKnown ||
    (compactNow !== undefined && account.resetAtMonthly != null);
  const weeklyOnly = !hasPrimaryWindow && hasSecondaryWindow;
  const monthlyOnly = hasMonthlyWindow && !hasPrimaryWindow && !hasSecondaryWindow;
  const showPrimary = compactNow === undefined ? !weeklyOnly && !monthlyOnly : hasPrimaryWindow;
  const showSecondary = compactNow === undefined ? !monthlyOnly : hasSecondaryWindow;
  const subscriptionCreditsLabel = formatCreditValue(accountSubscriptionCredits(account));
  const purchasedCreditsLabel = formatPurchasedCredits(account, t("common.states.unlimited"));

  const title = account.displayName || account.email;
  const compactId = formatCompactAccountId(account.accountId);
  const planLabel = formatSlug(account.planType);
  const emailSubtitle =
    account.displayName && account.displayName !== account.email
      ? account.email
      : null;
  const idSuffix = showAccountId ? ` | ID ${compactId}` : "";
  const warmupStatus = account.limitWarmupEnabled ? t("accounts.listItem.warmupOn") : t("accounts.listItem.warmupOff");
  const warmupToggleLabel = account.limitWarmupEnabled
    ? t("dashboard.accounts.disableWarmupFor", { account: title })
    : t("dashboard.accounts.enableWarmupFor", { account: title });
  const warmupDetail = account.limitWarmup
    ? `${formatSlug(account.limitWarmup.status)} | ${formatWarmupWindow(account.limitWarmup.window)} | ${formatSlug(account.limitWarmup.model)} | ${formatDateTimeInline(account.limitWarmup.completedAt ?? account.limitWarmup.attemptedAt, dateDisplayFormat)}`
    : t("accounts.listItem.noAttempts");
  const availableResetCredits = account.availableResetCredits ?? 0;
  const hasResetCredits = availableResetCredits > 0;
  const resetCreditDisabled =
    readOnly || status === "paused" || status === "reauth" || status === "deactivated";
  const resetCountdown = account.resetCreditNearestExpiresAt
    ? formatSingleUnitRemaining(account.resetCreditNearestExpiresAt)
    : null;
  const resetButtonTitle = resetCreditDisabled
    ? status === "paused"
      ? t("dashboard.accounts.resetCreditTitles.resumeRequired")
      : status === "reauth" || status === "deactivated"
        ? t("dashboard.accounts.resetCreditTitles.reauthRequired")
        : t("dashboard.accounts.resetCreditTitles.unavailable")
    : resetCountdown
      ? t("dashboard.accounts.resetCreditTitles.withCountdown", { count: availableResetCredits, countdown: resetCountdown.label })
      : t("dashboard.accounts.resetWithCount", { count: availableResetCredits });

  return (
    <div className="card-hover rounded-xl border bg-card p-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold leading-tight">
            {blurred
              ? <span className="privacy-blur">{title}</span>
              : title}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {planLabel}
            {!emailSubtitle ? idSuffix : ""}
          </p>
          {emailSubtitle ? (
            <p
              className="mt-0.5 truncate text-xs text-muted-foreground"
              title={showAccountId ? t("accounts.detail.accountIdTitle", { accountId: account.accountId }) : undefined}
            >
              <span className={blurred ? "privacy-blur" : undefined}>{emailSubtitle}</span>{showAccountId ? ` | ID ${compactId}` : ""}
            </p>
          ) : null}
        </div>
        <StatusBadge status={status} />
      </div>

      {/* Quota bars */}
      <div className={cn("mt-3.5 grid gap-3", showPrimary && showSecondary ? "grid-cols-2" : "grid-cols-1")}>
        {monthlyOnly ? (
          <QuotaBar
            label={t("common.time.monthly")}
            percent={monthlyRemaining}
            resetAt={account.resetAtMonthly}
            compactNow={compactNow}
            observationLabel={formatQuotaObservation(status, account.recordedAtMonthly, dateDisplayFormat)}
          />
        ) : (
          <>
            {showPrimary && (
              <QuotaBar
                label="5h"
                percent={primaryRemaining}
                resetAt={account.resetAtPrimary}
                compactNow={compactNow}
                observationLabel={formatQuotaObservation(
                  status, account.recordedAtPrimary, dateDisplayFormat, account.primaryWindowNotStarted,
                )}
              />
            )}
            {showSecondary && (
              <QuotaBar
                label={t("common.time.weekly")}
                percent={secondaryRemaining}
                resetAt={account.resetAtSecondary}
                compactNow={compactNow}
                observationLabel={formatQuotaObservation(status, account.recordedAtSecondary, dateDisplayFormat)}
              />
            )}
          </>
        )}
      </div>

      {compactNow !== undefined ? (
        compactAction ? <div className="mt-3 border-t pt-3">{compactAction}</div> : null
      ) : (
        <>
      <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-muted/40 px-2.5 py-2 text-xs">
        <div className="min-w-0">
          <p className="font-medium">{warmupStatus}</p>
          <p className="truncate text-[11px] text-muted-foreground">{warmupDetail}</p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className={cn(
            "h-7 gap-1.5 rounded-lg text-xs",
            account.limitWarmupEnabled
              ? "text-primary hover:bg-primary/10 hover:text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          aria-label={warmupToggleLabel}
          disabled={readOnly}
          onClick={() => onAction?.(account, "warmup-toggle")}
        >
          <Zap className="h-3 w-3" aria-hidden="true" />
          {account.limitWarmupEnabled ? t("common.states.on") : t("common.states.off")}
        </Button>
      </div>

      <div className="mt-3 grid gap-1 text-xs text-muted-foreground">
        <p>
          {t("dashboard.accounts.subscriptionCredits")}:{" "}
          <span className="font-medium tabular-nums text-foreground">
            {subscriptionCreditsLabel}
          </span>
        </p>
        <p>
          {t("dashboard.accounts.purchasedCredits")}:{" "}
          <span className="font-medium tabular-nums text-foreground">
            {purchasedCreditsLabel}
          </span>
        </p>
      </div>

      {/* Actions */}
      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t pt-3">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 gap-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground"
          onClick={() => onAction?.(account, "details")}
        >
          <ExternalLink className="h-3 w-3" />
          {t("common.actions.details")}
        </Button>
        {hasResetCredits ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="relative h-7 gap-1.5 rounded-lg pr-8 text-xs text-muted-foreground hover:text-foreground"
            title={resetButtonTitle}
            disabled={resetCreditDisabled}
            onClick={() => onAction?.(account, "reset-credit")}
          >
            <RotateCcw className="h-3 w-3" />
            {t("dashboard.accounts.resetWithCount", { count: availableResetCredits })}
            {resetCountdown ? (
              <span
                aria-hidden="true"
                className={cn(
                  "pointer-events-none absolute -top-1 right-1 text-[10px] tabular-nums",
                  resetCountdown.expiringSoon ? "text-destructive" : "text-muted-foreground",
                )}
              >
                {resetCountdown.label}
              </span>
            ) : null}
          </Button>
        ) : null}
        {(status === "paused" || status === "deactivated") && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-emerald-600 hover:bg-emerald-500/10 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300"
            disabled={readOnly}
            onClick={() => onAction?.(account, "resume")}
          >
            <Play className="h-3 w-3" />
            {t("common.actions.resume")}
          </Button>
        )}
        {(status === "reauth" || status === "deactivated") && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="h-7 gap-1.5 rounded-lg text-xs text-amber-600 hover:bg-amber-500/10 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
            disabled={readOnly}
            onClick={() => onAction?.(account, "reauth")}
          >
            <RotateCcw className="h-3 w-3" />
            {t("common.actions.reauthenticateShort")}
          </Button>
        )}
      </div>
        </>
      )}
    </div>
  );
}
