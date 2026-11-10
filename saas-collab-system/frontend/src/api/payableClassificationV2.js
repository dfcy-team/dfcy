import {requestApi} from './request';
export {createIdempotencyKey} from './supplyChainV2';
const path=(kind,id)=>`/api/internal/supply-chain/v2/costs/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/payable-classification/`;
export const fetchPayableClassification=(kind,id)=>requestApi({method:'get',url:path(kind,id)});
export const savePayableClassification=(kind,id,data,key)=>requestApi({method:'post',url:path(kind,id),data,headers:{'Idempotency-Key':key}});
