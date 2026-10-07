export function authorizationPreviewSignature({ userIds = [], roleCodes = [], operation = '', replaceSource = '', reason = '' } = {}) {
  return JSON.stringify({
    user_ids: [...userIds].map(String).sort(),
    role_codes: [...roleCodes].map(String).sort(),
    operation,
    replace_source: replaceSource,
    reason: String(reason).trim(),
  });
}

export function canApplyAuthorizationPreview(preview, previewSignature, currentSignature, authorizationStale = false) {
  return !authorizationStale && Boolean(preview?.preview_token) && previewSignature === currentSignature;
}

export function splitResourcePolicies(definitions = [], policies = []) {
  const knownResources = new Set(definitions.map((definition) => definition.resource_code));
  const wildcardByResource = {};
  for (const definition of definitions) {
    wildcardByResource[definition.resource_code] = policies.find((policy) => (
      policy.resource_code === definition.resource_code && policy.permission_code === '*'
    )) || null;
  }
  return {
    wildcardByResource,
    operationPolicies: policies.filter((policy) => policy.permission_code !== '*' || !knownResources.has(policy.resource_code)),
  };
}

export function buildResourcePoliciesForSave(definitions, enabled, policyMap, operationPolicies = []) {
  return [
    ...operationPolicies,
    ...definitions.filter((definition) => enabled[definition.resource_code]).map((definition) => {
      const row = policyMap[definition.resource_code];
      const config = row.scope_type === 'custom'
        ? Object.fromEntries(Object.entries(row.config || {}).filter(([, values]) => !Array.isArray(values) || values.length > 0))
        : {};
      return { resource_code: definition.resource_code, permission_code: '*', scope_type: row.scope_type, config };
    }),
  ];
}
