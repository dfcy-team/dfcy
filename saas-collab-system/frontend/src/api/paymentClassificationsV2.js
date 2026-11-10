import {requestApi} from './request';
export {createIdempotencyKey} from './supplyChainV2';
const path=(kind,id,type,entryId)=>`/api/internal/supply-chain/v2/costs/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/classifications/${encodeURIComponent(type)}/${encodeURIComponent(entryId)}/`;
export const fetchClassification=(kind,id,type,entryId)=>requestApi({method:'get',url:path(kind,id,type,entryId)});
export const saveClassification=(kind,id,type,entryId,data,key)=>requestApi({method:'put',url:path(kind,id,type,entryId),data,headers:{'Idempotency-Key':key}});
