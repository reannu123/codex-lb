import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { AlertMessage } from "@/components/alert-message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { clearModelPrice, getModelPrices, saveModelPrice } from "@/features/settings/api";
import type { ModelPrice } from "@/features/settings/schemas";
import { getErrorMessageOrNull } from "@/utils/errors";

const queryKey = ["settings", "model-prices"] as const;
const fields = ["inputPer1M", "cachedInputPer1M", "outputPer1M"] as const;
const decimalRate = /^[0-9]+(?:\.[0-9]{1,6})?$/;

export function ModelPricesSettings({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation();
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const [modelId, setModelId] = useState("");
  const prices = useQuery({ queryKey, queryFn: getModelPrices, enabled: expanded });
  const model = prices.data?.models.find((entry) => entry.modelId === modelId);
  return (
    <section className="rounded-xl border bg-card p-4">
      <h3>
        <Button
          variant="ghost"
          className="justify-start px-0 text-base font-semibold"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={() => setExpanded(!expanded)}
        >
          {t("settings.modelPrices.title")}
        </Button>
      </h3>
      {expanded ? (
        <div className="mt-3 space-y-3" id={panelId}>
          <p className="text-sm text-muted-foreground">{t("settings.modelPrices.description")}</p>
          {prices.isPending ? <p role="status">{t("settings.modelPrices.loading")}</p> : null}
          {prices.isError ? (
            <div className="space-y-2">
              <AlertMessage variant="error">{t("settings.modelPrices.loadFailed")}</AlertMessage>
              <Button variant="outline" onClick={() => void prices.refetch()}>{t("common.actions.retry")}</Button>
            </div>
          ) : null}
          {prices.data ? (
            <label className="block max-w-md space-y-1 text-sm font-medium">
              <span>{t("settings.modelPrices.model")}</span>
              <select
                className="block w-full rounded-md border bg-background p-2"
                value={modelId}
                onChange={(event) => setModelId(event.target.value)}
              >
                <option value="">{t("settings.modelPrices.select")}</option>
                {prices.data.models.map((entry) => (
                  <option key={entry.modelId} value={entry.modelId}>{entry.modelId}</option>
                ))}
              </select>
            </label>
          ) : null}
          {model ? (
            <ModelPriceDetails
              key={model.modelId}
              model={model}
              canWrite={canWrite}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ModelPriceDetails({ model, canWrite }: { model: ModelPrice; canWrite: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [rates, setRates] = useState({ inputPer1M: "", cachedInputPer1M: "", outputPer1M: "" });
  function startEditing() {
    setRates({
      inputPer1M: model.effective?.inputPer1M.toString() ?? "",
      cachedInputPer1M: model.effective?.cachedInputPer1M.toString() ?? "",
      outputPer1M: model.effective?.outputPer1M.toString() ?? "",
    });
    setEditing(true);
  }
  const mutation = useMutation({
    mutationFn: (action: "save" | "clear") =>
      action === "save" ? saveModelPrice(model.modelId, rates) : clearModelPrice(model.modelId),
    onSuccess: (data) => {
      client.setQueryData(queryKey, data);
      setEditing(false);
    },
  });
  const valid = fields.every((field) => decimalRate.test(rates[field]) && Number(rates[field]) <= 1_000_000);
  const error = getErrorMessageOrNull(mutation.error);
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {t(`settings.modelPrices.sources.${model.source}`)}
        {model.catalogModelId && model.catalogModelId !== model.modelId ? ` · ${model.catalogModelId}` : null}
      </p>
      <dl className="grid gap-2 text-sm sm:grid-cols-3">
        {fields.map((field) => (
          <div key={field}>
            <dt className="text-muted-foreground">{t(`settings.modelPrices.fields.${field}`)}</dt>
            <dd className="font-mono">{model.effective?.[field] ?? "—"}</dd>
            {model.source === "local_override" && model.inherited ? (
              <dd className="text-muted-foreground">
                {t("settings.modelPrices.inherited", { rate: model.inherited[field] })}
              </dd>
            ) : null}
          </div>
        ))}
      </dl>
      {model.cachedInputInheritsInput ? <p className="text-sm">{t("settings.modelPrices.cacheInheritance")}</p> : null}
      {model.hasCatalogTiers ? <p className="text-sm">{t("settings.modelPrices.tiers")}</p> : null}
      {error ? <AlertMessage variant="error">{error}</AlertMessage> : null}
      {canWrite && editing ? (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) mutation.mutate("save");
          }}
        >
          <div className="grid gap-2 sm:grid-cols-3">
            {fields.map((field) => (
              <label className="space-y-1 text-sm" key={field}>
                <span>{t(`settings.modelPrices.fields.${field}`)}</span>
                <Input
                  inputMode="decimal"
                  required
                  value={rates[field]}
                  onChange={(event) => setRates({ ...rates, [field]: event.target.value })}
                />
              </label>
            ))}
          </div>
          <p className="text-sm text-muted-foreground">{t("settings.modelPrices.rateHelp")}</p>
          <div className="flex gap-2">
            <Button type="submit" disabled={!valid || mutation.isPending}>{t("common.actions.save")}</Button>
            <Button type="button" variant="outline" onClick={() => setEditing(false)} disabled={mutation.isPending}>
              {t("common.cancel")}
            </Button>
          </div>
        </form>
      ) : null}
      {canWrite && !editing ? (
        <div className="flex gap-2">
          <Button variant="outline" onClick={startEditing} disabled={mutation.isPending}>
            {t("settings.modelPrices.edit")}
          </Button>
          {model.source === "local_override" ? (
            <Button variant="outline" onClick={() => mutation.mutate("clear")} disabled={mutation.isPending}>
              {t("settings.modelPrices.clear")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
