import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/confirm-dialog";

type ManualWarmupConfirmDialogProps = Pick<
  ComponentProps<typeof ConfirmDialog>,
  "open" | "onOpenChange" | "onConfirm"
>;

export function ManualWarmupConfirmDialog(props: ManualWarmupConfirmDialogProps) {
  const { t } = useTranslation();
  return (
    <ConfirmDialog
      {...props}
      title={t("accounts.manualWarmupDialog.title")}
      description={t("accounts.manualWarmupDialog.description")}
      confirmLabel={t("accounts.actions.manualWarmup")}
      cancelLabel={t("common.cancel")}
    />
  );
}
