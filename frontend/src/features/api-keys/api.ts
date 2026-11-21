import i18n from "@/i18n";
import { sameAccountScope } from "@/features/api-keys/account-scope";
import { del, get, patch, post } from "@/lib/api-client";

import {
  ApiKeyAccountScopeSchema,
  ApiKeyCreateRequestSchema,
  ApiKeyCreateResponseSchema,
  ApiKeyListSchema,
  ApiKeySchema,
  ApiKeyUpdateRequestSchema,
  ModelsResponseSchema,
} from "@/features/api-keys/schemas";

export const API_KEYS_BASE_PATH = "/api/api-keys";
const MODELS_PATH = "/api/models";
const ScopeUpdateResponseSchema = ApiKeySchema.extend(ApiKeyAccountScopeSchema.partial().shape);

export function listApiKeys() {
  return get(`${API_KEYS_BASE_PATH}/`, ApiKeyListSchema);
}

export function createApiKey(payload: unknown) {
  const validated = ApiKeyCreateRequestSchema.parse(payload);
  return post(`${API_KEYS_BASE_PATH}/`, ApiKeyCreateResponseSchema, {
    body: validated,
  });
}

export async function updateApiKey(keyId: string, payload: unknown) {
  const validated = ApiKeyUpdateRequestSchema.parse(payload);
  const path = `${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}`;
  const options = { body: validated };
  const requestedScope = validated.accountScopeUpdate;
  if (!requestedScope) {
    return patch(path, ApiKeySchema, options);
  }

  const saved = await patch(path, ScopeUpdateResponseSchema, options);
  const scope = ApiKeyAccountScopeSchema.safeParse(saved);
  if (!scope.success || !sameAccountScope(requestedScope, scope.data)) {
    throw new Error(i18n.t("apiKeys.accountScope.unconfirmed"));
  }
  return { ...saved, ...scope.data };
}

export function deleteApiKey(keyId: string) {
  return del(`${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}`);
}

export function regenerateApiKey(keyId: string) {
  return post(
    `${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}/regenerate`,
    ApiKeyCreateResponseSchema,
  );
}

export function listModels() {
  return get(MODELS_PATH, ModelsResponseSchema);
}
