import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { createElement, type PropsWithChildren } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import { useApiKeys } from "@/features/api-keys/hooks/use-api-keys";
import { createApiKey } from "@/test/mocks/factories";
import { server } from "@/test/mocks/server";

function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });
}

function createWrapper(queryClient: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useApiKeys", () => {
  it.each([
    { accountAssignmentScopeEnabled: true, assignedAccountIds: ["account-a"] },
    { assignedAccountIds: [] },
    { accountAssignmentScopeEnabled: false },
  ])("rejects an HTTP 200 that cannot confirm scope (%j)", async (responseScope) => {
    const queryClient = createTestQueryClient();
    const existingKey = createApiKey({ accountAssignmentScopeEnabled: true, assignedAccountIds: ["account-a"] });
    const { accountAssignmentScopeEnabled, assignedAccountIds, ...keyWithoutScope } = existingKey;
    const list = vi.fn(() => HttpResponse.json([existingKey]));
    const successToast = vi.spyOn(toast, "success").mockImplementation(() => "");
    const errorToast = vi.spyOn(toast, "error").mockImplementation(() => "");
    server.use(
      http.get("/api/api-keys/", list),
      http.patch("/api/api-keys/:keyId", () => HttpResponse.json({ ...keyWithoutScope, ...responseScope })),
    );

    try {
      const { result } = renderHook(() => useApiKeys(), { wrapper: createWrapper(queryClient) });
      await waitFor(() => expect(result.current.apiKeysQuery.isSuccess).toBe(true));

      const error = "The server did not confirm the requested account scope.";
      await expect(result.current.updateMutation.mutateAsync({
        keyId: existingKey.id,
        payload: {
          accountScopeUpdate: {
            accountAssignmentScopeEnabled: false,
            assignedAccountIds: [],
            expected: { accountAssignmentScopeEnabled, assignedAccountIds },
          },
        },
      })).rejects.toThrow(error);

      expect(errorToast).toHaveBeenCalledWith(error);
      expect(successToast).not.toHaveBeenCalled();
      await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
      expect(result.current.apiKeysQuery.data).toEqual([existingKey]);
    } finally {
      successToast.mockRestore();
      errorToast.mockRestore();
    }
  });

  it("runs CRUD mutations and returns plain key on create", async () => {
    const queryClient = createTestQueryClient();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useApiKeys(), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(result.current.apiKeysQuery.isSuccess).toBe(true));
    const existingKeyId = result.current.apiKeysQuery.data?.[0]?.id;
    expect(existingKeyId).toBeTruthy();
    if (!existingKeyId) throw new Error("Expected at least one API key in test data");

    const created = await result.current.createMutation.mutateAsync({
      name: "Test Key",
      allowedModels: ["gpt-5.1"],
      applyToCodexModel: true,
      weeklyTokenLimit: 1000,
      expiresAt: null,
    });
    expect(created.key).toContain("sk-test");

    await result.current.updateMutation.mutateAsync({
      keyId: existingKeyId,
      payload: {
        name: "Updated Name",
      },
    });

    await result.current.regenerateMutation.mutateAsync(existingKeyId);
    await result.current.deleteMutation.mutateAsync(created.id);

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["api-keys", "list"] });
    });
  });
});
