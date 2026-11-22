import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ModelPricesSettings } from "@/features/settings/components/model-prices-settings";

function renderPrices(canWrite: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ModelPricesSettings canWrite={canWrite} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("Model prices settings", () => {
  it("saves a complete override with a zero rate and clears back to missing", async () => {
    const user = renderPrices(true);
    await user.click(screen.getByRole("button", { name: "Model prices" }));
    await user.selectOptions(await screen.findByRole("combobox"), "gpt-6.2-sol");
    expect(screen.getByText("Missing price")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Edit base rates" }));
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Input" }), "2");
    await user.type(screen.getByRole("textbox", { name: "Cached input" }), "0");
    await user.type(screen.getByRole("textbox", { name: "Output" }), "8");
    await user.click(save);
    expect(await screen.findByText("Local override")).toBeVisible();
    expect(screen.getByText("0")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Clear override" }));
    expect(await screen.findByText("Missing price")).toBeVisible();
  });

  it("allows read-only users to inspect missing prices", async () => {
    const user = renderPrices(false);
    await user.click(screen.getByRole("button", { name: "Model prices" }));
    await user.selectOptions(await screen.findByRole("combobox"), "gpt-6.2-sol");
    expect(screen.getByText("Missing price")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Edit base rates" })).not.toBeInTheDocument();
  });
});
