import { successResponse } from './index';

export const mockFinanceImports = () => successResponse({
  status: 'mock',
  module: 'finance.imports',
  items: [
    {
      import_no: 'MOCK-FINANCE-IMPORT-001',
      status: 'pending',
      authorization: 'backend-required'
    }
  ]
});
