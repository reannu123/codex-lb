import i18n from "@/i18n";
import { sameAccountScope } from "@/features/api-keys/account-scope";
import { del, get, patch, post } from "@/lib/api-client";

import {
  ApiKeyCreateRequestSchema,
  ApiKeyCreateResponseSchema,
  ApiKeyListSchema,
  ApiKeySchema,
  ApiKeyUpdateRequestSchema,
  ModelsResponseSchema,
} from "@/features/api-keys/schemas";

export const API_KEYS_BASE_PATH = "/api/api-keys";
const MODELS_PATH = "/api/models";

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
  const saved = await patch(`${API_KEYS_BASE_PATH}/${encodeURIComponent(keyId)}`, ApiKeySchema, {
    body: validated,
  });
  if (validated.accountScopeUpdate && !sameAccountScope(validated.accountScopeUpdate, saved)) {
    throw new Error(i18n.t("apiKeys.accountScope.unconfirmed"));
  }
  return saved;
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
