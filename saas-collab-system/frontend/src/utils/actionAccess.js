function requiredPermissions(action) {
  if (Array.isArray(action.permissions)) return action.permissions;
  return action.permission ? [action.permission] : [];
}

export function getActionAccess(auth, action) {
  const permissions = requiredPermissions(action);
  const userTypeAllowed = !action.userTypes?.length || action.userTypes.includes(auth.currentUser?.user_type);
  const permissionAllowed = !permissions.length || auth.hasPermission(...permissions);
  const allowed = userTypeAllowed && permissionAllowed;

  return {
    allowed,
    visible: allowed || action.unauthorizedBehavior === 'disable',
    disabled: Boolean(action.disabled) || !allowed,
    reason: allowed ? '' : (action.deniedReason || `缺少操作权限：${permissions.join(' / ') || '角色不匹配'}`)
  };
}
