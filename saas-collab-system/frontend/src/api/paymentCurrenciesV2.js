import {requestApi} from './request';
export {createIdempotencyKey} from './supplyChainV2';
const path=(kind,id,type,entry)=>`/api/internal/supply-chain/v2/costs/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/payment-currencies/${encodeURIComponent(type)}/${encodeURIComponent(entry)}/`;
export const fetchCurrency=(kind,id,type,entry)=>requestApi({method:'get',url:path(kind,id,type,entry)});
export const saveCurrency=(kind,id,type,entry,data,key)=>requestApi({method:'put',url:path(kind,id,type,entry),data,headers:{'Idempotency-Key':key}});
