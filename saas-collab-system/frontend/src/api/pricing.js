import { getMockResponse } from './request';
import { mockPrices } from '../mock/pricing';

export const fetchPrices = () => getMockResponse(mockPrices, 'pricing.prices');
