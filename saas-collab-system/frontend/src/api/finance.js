import { requestWithMockFallback } from './request';
import { mockFinanceImports } from '../mock/finance';

export const fetchFinanceImports = () =>
  requestWithMockFallback({ method: 'get', url: '/api/finance/imports/' }, mockFinanceImports, 'finance.imports');
