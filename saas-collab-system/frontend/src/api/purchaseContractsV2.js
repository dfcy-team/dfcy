import {requestApi,downloadApiFile} from './request';
import {createIdempotencyKey} from './supplyChainV2';
export {createIdempotencyKey};
const path=id=>`/api/internal/supply-chain/v2/supplier-shipments/${encodeURIComponent(id)}/purchase-contract/`;
export const fetchContract=id=>requestApi({method:'get',url:path(id)});
export const saveContract=(id,data,key)=>requestApi({method:'put',url:path(id),data,headers:{'Idempotency-Key':key}});
export const issueContract=(id,data,key)=>requestApi({method:'post',url:`${path(id)}issue/`,data,headers:{'Idempotency-Key':key}});
export const downloadContract=(id,number)=>downloadApiFile(`${path(id)}download/`,`${number||'采购合同'}.xlsx`);
