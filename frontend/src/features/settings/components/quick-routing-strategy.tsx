import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { AccountSummary } from "@/features/accounts/schemas";
import { useSettings } from "@/features/settings/hooks/use-settings";
import type { DashboardSettings } from "@/features/settings/schemas";
import { isSingleAccountRoutingSelectable } from "@/utils/account-status";
import { STRATEGY_GUIDE_VALUES } from "./routing-strategies";
import { SingleAccountRoutingSelect } from "./single-account-routing-select";

type RoutingDraft = {
  version: DashboardSettings["version"];
  strategy: DashboardSettings["routingStrategy"];
  accountId: string | null;
};

export function QuickRoutingStrategy({ accounts, canWrite }: { accounts: AccountSummary[]; canWrite: boolean }) {
  const { t } = useTranslation();
  const { settingsQuery, updateSettingsMutation } = useSettings();
  const [draft, setDraft] = useState<RoutingDraft | null>(null);
  const settings = settingsQuery.data;
  const candidates = accounts.filter((account) => isSingleAccountRoutingSelectable(account.status));
  const strategy = draft?.strategy ?? settings?.routingStrategy;
  const accountId = draft ? draft.accountId : settings?.singleAccountId;
  const stale = draft !== null && settings !== undefined && draft.version !== settings.version;

  return (
    <section className="space-y-3" aria-labelledby="simple-routing">
      <h2 id="simple-routing" className="text-lg font-semibold">{t("settings.routing.strategy.label")}</h2>
      {settingsQuery.error ? <AlertMessage variant="error">{settingsQuery.error.message}</AlertMessage> : null}
      {settings && strategy ? (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={strategy}
            disabled={!canWrite || updateSettingsMutation.isPending || stale}
            onValueChange={(value) => setDraft({
              version: settings.version,
              strategy: Object.values(STRATEGY_GUIDE_VALUES).find((strategy) => strategy === value) ?? settings.routingStrategy,
              accountId: candidates.find((account) => account.accountId === accountId)?.accountId ?? null,
            })}
          >
            <SelectTrigger aria-label={t("settings.routing.strategy.label")} className="w-64 max-w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(STRATEGY_GUIDE_VALUES).map(([label, value]) => (
                <SelectItem key={value} value={value} disabled={value === "single_account" && candidates.length === 0}>
                  {t(`settings.routing.strategy.${label}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {strategy === "single_account" && candidates.length > 0 ? (
            <SingleAccountRoutingSelect
              accounts={accounts}
              accountId={accountId}
              busy={!canWrite || stale || updateSettingsMutation.isPending}
              onChange={(value) => setDraft({ version: draft?.version ?? settings.version, strategy, accountId: value })}
            />
          ) : null}
          {canWrite && draft ? (
            <>
              <Button
                type="button"
                size="sm"
                disabled={stale || updateSettingsMutation.isPending || (strategy === "single_account" &&
                  !candidates.some((account) => account.accountId === accountId))}
                onClick={() => updateSettingsMutation.mutate({
                  expectedVersion: draft.version,
                  routingStrategy: draft.strategy,
                  ...(draft.strategy === "single_account" ? { singleAccountId: draft.accountId } : {}),
                }, { onSuccess: () => setDraft(null) })}
              >
                {t("common.actions.save")}
              </Button>
              <Button type="button" size="sm" variant="ghost" disabled={updateSettingsMutation.isPending} onClick={() => {
                setDraft(null);
                updateSettingsMutation.reset();
              }}>
                {t(stale ? "apiKeys.accountScope.review" : "common.cancel")}
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
      {updateSettingsMutation.error ? (
        <AlertMessage variant="error">{updateSettingsMutation.error.message}</AlertMessage>
      ) : null}
    </section>
  );
}
