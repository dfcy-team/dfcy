import { mockCurrentUser, mockLogin } from '../mock/auth';

export function login() {
  return mockLogin();
}

export function getCurrentUser() {
  return mockCurrentUser();
}
