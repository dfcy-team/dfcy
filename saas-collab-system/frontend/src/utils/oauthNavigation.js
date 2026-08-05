export const navigateToOAuthAuthorization = (authorizationUrl) => {
  if (typeof authorizationUrl !== 'string' || !authorizationUrl.startsWith('https://synthetic.invalid/')) {
    throw new Error('OAuth authorization URL is not an approved synthetic URL.');
  }
  window.location.assign(authorizationUrl);
};
