import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { AccountSummary } from "@/features/accounts/schemas";
import { usePrivacyStore } from "@/hooks/use-privacy";
import { formatCompactAccountId } from "@/utils/account-identifiers";
import { isSingleAccountRoutingSelectable } from "@/utils/account-status";

function accountLabel(account: AccountSummary): string {
  const name = account.alias?.trim() || account.displayName?.trim() || account.email?.trim() || account.accountId;
  const compactId = formatCompactAccountId(account.accountId, 6, 4);
  return `${name} (${compactId})`;
}

type SingleAccountRoutingSelectProps = {
  accounts: AccountSummary[];
  accountId?: string | null;
  busy: boolean;
  loading?: boolean;
  onChange: (accountId: string) => void;
};

export function SingleAccountRoutingSelect({
  accounts, accountId, busy, loading = false, onChange,
}: SingleAccountRoutingSelectProps) {
  const { t } = useTranslation();
  const blurred = usePrivacyStore((state) => state.blurred);
  const selectable = accounts.filter((account) => isSingleAccountRoutingSelectable(account.status));
  const blockedSelected = accounts.find(
    (account) => account.accountId === accountId && !isSingleAccountRoutingSelectable(account.status),
  );
  const visible = blockedSelected ? [blockedSelected, ...selectable] : selectable;

  return (
    <Select value={accountId ?? ""} onValueChange={onChange}>
      <SelectTrigger
        aria-label={t("settings.routing.singleAccount.label")}
        className="h-8 w-full text-xs sm:w-64"
        disabled={busy || loading || selectable.length === 0}
      >
        <SelectValue placeholder={t(loading ? "settings.routing.singleAccount.loading" : "settings.routing.singleAccount.placeholder")} />
      </SelectTrigger>
      <SelectContent align="end">
        {visible.map((account) => (
          <SelectItem key={account.accountId} value={account.accountId} disabled={account === blockedSelected}>
            <span className={blurred && !account.alias &&
              (!account.displayName || account.displayName === account.email) ? "privacy-blur" : undefined}>
              {accountLabel(account)}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
