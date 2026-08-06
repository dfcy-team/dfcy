// Marketplace OAuth capability mapping (contract a2-sandbox-v1 status rule).
// Progression is fail closed: only exact backend-provided values promote the label.
// `connected` additionally requires real requests, negative permission checks and
// field validation per the contract; the frontend never promotes it on its own.

export const OAUTH_CAPABILITY_LEVELS = ['mock', 'sandbox_verified', 'connected'];

const CAPABILITY_META = {
  mock: {
    label: 'Synthetic (mock)',
    tagType: 'info',
    description: 'Synthetic mode is active; no real platform request is sent.'
  },
  sandbox_verified: {
    label: 'Sandbox verified',
    tagType: 'warning',
    description: 'Sandbox integration verified; real contract values registered in the evidence registry.'
  },
  connected: {
    label: 'Connected',
    tagType: 'success',
    description: 'Real platform connection verified by real requests, negative permission checks and field validation.'
  }
};

export function normalizeOAuthCapability(apiStatus) {
  return OAUTH_CAPABILITY_LEVELS.includes(apiStatus) ? apiStatus : 'mock';
}

export function oauthCapabilityLabel(apiStatus) {
  return CAPABILITY_META[normalizeOAuthCapability(apiStatus)].label;
}

export function oauthCapabilityTagType(apiStatus) {
  return CAPABILITY_META[normalizeOAuthCapability(apiStatus)].tagType;
}

export function oauthCapabilityDescription(apiStatus) {
  return CAPABILITY_META[normalizeOAuthCapability(apiStatus)].description;
}
