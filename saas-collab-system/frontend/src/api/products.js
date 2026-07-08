import { getMockResponse } from './request';
import { mockProductMasterList, mockResearchList } from '../mock/products';

export const fetchResearchList = () => getMockResponse(mockResearchList, 'products.research');
export const fetchProductMasterList = () => getMockResponse(mockProductMasterList, 'products.master');
