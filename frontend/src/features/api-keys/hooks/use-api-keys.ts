import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import {
  createApiKey,
  deleteApiKey,
  listApiKeys,
  regenerateApiKey,
  updateApiKey,
} from "@/features/api-keys/api";
import type {
  ApiKey,
  ApiKeyCreateRequest,
  ApiKeyUpdateRequest,
} from "@/features/api-keys/schemas";

export function useApiKeys() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data, error, isFetching, isLoading, isPending, isSuccess, refetch } = useQuery({
    queryKey: ["api-keys", "list"],
    queryFn: listApiKeys,
  });
  const apiKeysQuery = { data, error, isFetching, isLoading, isPending, isSuccess, refetch };

  const createMutation = useMutation({
    mutationFn: (payload: ApiKeyCreateRequest) => createApiKey(payload),
    onSuccess: () => {
      toast.success(t("apiKeys.toasts.created"));
      void queryClient.invalidateQueries({ queryKey: ["api-keys", "list"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("apiKeys.toasts.createFailed"));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ keyId, payload }: { keyId: string; payload: ApiKeyUpdateRequest }) =>
      updateApiKey(keyId, payload),
    onSuccess: (saved) => {
      queryClient.setQueryData<ApiKey[]>(["api-keys", "list"], (keys) =>
        keys?.map((key) => key.id === saved.id ? { ...key, ...saved } : key),
      );
      toast.success(t("apiKeys.toasts.updated"));
      void queryClient.invalidateQueries({ queryKey: ["api-keys", "list"] });
    },
    onError: (error: Error, { payload }) => {
      if (payload.accountScopeUpdate) {
        void queryClient.invalidateQueries({ queryKey: ["api-keys", "list"] });
      }
      toast.error(error.message || t("apiKeys.toasts.updateFailed"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (keyId: string) => deleteApiKey(keyId),
    onSuccess: () => {
      toast.success(t("apiKeys.toasts.deleted"));
      void queryClient.invalidateQueries({ queryKey: ["api-keys", "list"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("apiKeys.toasts.deleteFailed"));
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: (keyId: string) => regenerateApiKey(keyId),
    onSuccess: () => {
      toast.success(t("apiKeys.toasts.regenerated"));
      void queryClient.invalidateQueries({ queryKey: ["api-keys", "list"] });
    },
    onError: (error: Error) => {
      toast.error(error.message || t("apiKeys.toasts.regenerateFailed"));
    },
  });

  return {
    apiKeysQuery,
    createMutation,
    updateMutation,
    deleteMutation,
    regenerateMutation,
  };
}
