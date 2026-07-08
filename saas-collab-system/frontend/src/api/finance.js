import { getMockResponse } from './request';
import { mockFinanceImports } from '../mock/finance';

export const fetchFinanceImports = () => getMockResponse(mockFinanceImports, 'finance.imports');
