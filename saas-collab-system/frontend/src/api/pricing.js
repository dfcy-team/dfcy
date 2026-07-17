import { requestPendingOrMock } from './request';
import { mockPrices } from '../mock/pricing';

export const fetchPrices = () =>
  requestPendingOrMock(mockPrices, 'pricing.prices');

export const fetchPriceDetail = (id = 1) =>
  requestPendingOrMock(mockPrices, `pricing.prices.detail:${id}`);
