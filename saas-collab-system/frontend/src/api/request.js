import axios from 'axios';
import { pendingResponse } from '../mock';

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false';

const request = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  timeout: 10000
});

export function getMockResponse(mockHandler, moduleName) {
  if (typeof mockHandler === 'function') {
    return mockHandler();
  }
  return pendingResponse(moduleName);
}

export const getMockOrRequest = (moduleName) => pendingResponse(moduleName);

export default request;
