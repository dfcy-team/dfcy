import {requestApi,downloadApiFile,fetchApiFile} from './request';
export {createIdempotencyKey} from './supplyChainV2';
const base='/api/internal/supply-chain/v2/payment-batches/';
export const candidates=params=>requestApi({method:'get',url:base+'candidates/',params});
export const list=params=>requestApi({method:'get',url:base,params});
export const detail=id=>requestApi({method:'get',url:`${base}${id}/`});
export const create=(data,key)=>requestApi({method:'post',url:base,data,headers:{'Idempotency-Key':key}});
export const action=(id,action,data,key)=>requestApi({method:'post',url:`${base}${id}/${action}/`,data,headers:{'Idempotency-Key':key}});
export const upload=(row,file,key)=>{const data=new FormData();data.append('file',file);data.append('expected_version',row.version);return requestApi({method:'post',url:`${base}${row.id}/vouchers/`,data,timeout:60000,headers:{'Idempotency-Key':key}});};
export const voucherPath=(id,file)=>`${base}${id}/vouchers/${file.id}/download/`;
export const preview=(id,file)=>fetchApiFile(voucherPath(id,file));
export const download=(id,file)=>downloadApiFile(voucherPath(id,file),file.file_name);

export const removeVoucher=(id,file,version,key)=>requestApi({method:'post',url:`${base}${id}/vouchers/${file.id}/remove/`,data:{expected_version:version},headers:{'Idempotency-Key':key}});
