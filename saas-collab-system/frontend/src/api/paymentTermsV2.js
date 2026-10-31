import {requestApi} from './request';
import {createIdempotencyKey} from './supplyChainV2';
export {createIdempotencyKey};
const base='/api/internal/supply-chain/v2/';
const path=(kind,id)=>`${base}costs/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/payment-terms/`;
export const fetchPaymentTerms=(kind,id)=>requestApi({method:'get',url:path(kind,id)});
export const savePaymentTerms=(kind,id,data,key)=>requestApi({method:'put',url:path(kind,id),data,headers:{'Idempotency-Key':key}});
export const fetchPaymentReminders=(params)=>requestApi({method:'get',url:`${base}payment-reminders/`,params});
