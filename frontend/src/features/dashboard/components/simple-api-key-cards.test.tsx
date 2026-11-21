import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";

import { SimpleApiKeyCards } from "@/features/dashboard/components/simple-api-key-cards";
import { createAccountSummary, createApiKey } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";
import { renderWithProviders } from "@/test/utils";

it("shows the committed accounts after a conflicting save with the same assignment count", async () => {
  const accounts = ["A", "B", "C"].map((name) => createAccountSummary({
    accountId: name,
    displayName: `Account ${name}`,
  }));
  let key = createApiKey({ accountAssignmentScopeEnabled: true, assignedAccountIds: ["A"] });
  server.use(
    http.get("/api/api-keys/", () => HttpResponse.json([key])),
    http.patch("/api/api-keys/:keyId", () => {
      key = { ...key, assignedAccountIds: ["B"] };
      return HttpResponse.json({
        error: { code: "api_key_account_scope_conflict", message: "Account scope changed." },
      }, { status: 409 });
    }),
  );

  const user = userEvent.setup();
  renderWithProviders(<SimpleApiKeyCards accounts={accounts} canEdit canEditAccounts />);
  const card = within(await screen.findByRole("article"));
  const accountA = card.getByRole("switch", { name: "Account A" });
  const accountB = card.getByRole("switch", { name: "Account B" });
  const accountC = card.getByRole("switch", { name: "Account C" });
  expect(accountA).toBeChecked();
  await user.click(accountA);
  await user.click(accountC);
  expect(accountC).toBeChecked();
  const save = card.getByRole("button", { name: "Save account scope" });
  await user.click(save);

  const review = await card.findByRole("button", { name: "Review saved state" });
  expect(save).toBeDisabled();
  expect(accountA).not.toBeChecked();
  expect(accountB).toBeChecked();
  expect(accountC).not.toBeChecked();
  expect(accountB).toBeDisabled();
  await user.click(review);
  expect(accountB).toBeChecked();
  expect(accountB).toBeEnabled();
});
