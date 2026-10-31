import {requestApi,downloadApiFile} from './request';
import {createIdempotencyKey} from './supplyChainV2';
export {createIdempotencyKey};
const path=id=>`/api/internal/supply-chain/v2/supplier-shipments/${encodeURIComponent(id)}/purchase-contract/`;
export const fetchContract=id=>requestApi({method:'get',url:path(id)});
export const saveContract=(id,data,key)=>requestApi({method:'put',url:path(id),data,headers:{'Idempotency-Key':key}});
export const issueContract=(id,data,key)=>requestApi({method:'post',url:`${path(id)}issue/`,data,headers:{'Idempotency-Key':key}});
export const downloadContract=(id,number)=>downloadApiFile(`${path(id)}download/`,`${number||'采购合同'}.xlsx`);

export const voidContract=(id,data,key)=>requestApi({method:'post',url:`${path(id)}void/`,data,headers:{'Idempotency-Key':key}});
export const reissueContract=(id,data,key)=>requestApi({method:'post',url:`${path(id)}reissue/`,data,headers:{'Idempotency-Key':key}});
export const fetchContractHistory=(id,offset=0)=>requestApi({method:'get',url:`${path(id)}history/`,params:{offset}});
export const downloadContractHistory=(id,historyId,number)=>downloadApiFile(`${path(id)}history/${historyId}/download/`,`${number}-历史合同.xlsx`);
export const downloadHistoricalSignature=(url,name)=>downloadApiFile(url,name);
