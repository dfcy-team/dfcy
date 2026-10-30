import { requestApi } from './request';
import { createIdempotencyKey } from './supplyChainV2';

const BASE='/api/internal/supply-chain/v2/';
const enc=(v)=>encodeURIComponent(v);
function write(method,url,data,key=createIdempotencyKey()){return requestApi({method,url,data,headers:{'Idempotency-Key':key}});}
export {createIdempotencyKey};
export const fetchCostTargets=(params={})=>requestApi({method:'get',url:`${BASE}cost-targets/`,params});
export const fetchSupplyProductCosts=(params={})=>requestApi({method:'get',url:`${BASE}product-cost-ledger/`,params});
export const fetchSupplyCostOptions=(params={})=>requestApi({method:'get',url:`${BASE}product-cost-ledger/options/`,params});
export const fetchCostContext=(kind,id)=>requestApi({method:'get',url:`${BASE}costs/${enc(kind)}/${enc(id)}/`});
export const fetchCostVersion=(kind,id,sequence)=>requestApi({method:'get',url:`${BASE}costs/${enc(kind)}/${enc(id)}/versions/${enc(sequence)}/`});
export const saveFee=(kind,id,data,key)=>write('put',`${BASE}costs/${enc(kind)}/${enc(id)}/fee/`,data,key);
export const calculateCost=(kind,id,data,key)=>write('post',`${BASE}costs/${enc(kind)}/${enc(id)}/calculate/`,data,key);
export const recordSettlement=(kind,id,data,key)=>write('post',`${BASE}costs/${enc(kind)}/${enc(id)}/settlement/`,data,key);

export const fetchPayeeAccounts=(kind,id)=>requestApi({method:'get',url:`${BASE}costs/${enc(kind)}/${enc(id)}/payee-accounts/`});
export const createPayeeAccount=(kind,id,data,key)=>write('post',`${BASE}costs/${enc(kind)}/${enc(id)}/payee-accounts/`,data,key);
export const updatePayeeAccount=(kind,id,accountId,data,key)=>write('put',`${BASE}costs/${enc(kind)}/${enc(id)}/payee-accounts/${enc(accountId)}/`,data,key);

const paymentsPath=(kind,id)=>`${BASE}costs/${enc(kind)}/${enc(id)}/payments/`;
export const fetchPayments=(kind,id)=>requestApi({method:'get',url:paymentsPath(kind,id)});
export const createPayment=(kind,id,data,key)=>write('post',paymentsPath(kind,id),data,key);
export const applyPrepayment=(id,data,key)=>write('post',`${BASE}costs/shipment/${enc(id)}/prepayment-applications/`,data,key);
export const uploadPaymentVoucher=(kind,id,paymentId,file,key)=>{const data=new FormData();data.append('file',file);return write('post',`${paymentsPath(kind,id)}${enc(paymentId)}/vouchers/`,data,key);};
export const paymentVoucherUrl=(kind,id,paymentId,voucherId)=>`${paymentsPath(kind,id)}${enc(paymentId)}/vouchers/${enc(voucherId)}/download/`;

export const reversePayment=(kind,id,entryId,data,key)=>write('post',`${paymentsPath(kind,id)}${enc(entryId)}/reverse/`,data,key);
export const reversePrepayment=(id,entryId,data,key)=>write('post',`${BASE}costs/shipment/${enc(id)}/prepayment-applications/${enc(entryId)}/reverse/`,data,key);
