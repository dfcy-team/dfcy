import { requestApi } from './request';
const base = '/api/internal/supply-chain/v2/count-difference-choices/';
export const fetchCountDifferenceChoices = () => requestApi({url:base,method:'get'});
export const saveCountDifferenceChoice = (data, requestKey) => requestApi({url:base,method:'post',data,headers:{'Idempotency-Key':requestKey}});
