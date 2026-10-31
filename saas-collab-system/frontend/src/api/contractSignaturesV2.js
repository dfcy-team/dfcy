import {requestApi,downloadApiFile,fetchApiFile} from './request';
export {createIdempotencyKey} from './supplyChainV2';
const path=id=>`/api/internal/supply-chain/v2/supplier-shipments/${encodeURIComponent(id)}/purchase-contract/signatures/`;
export const fetchSignatures=id=>requestApi({method:'get',url:path(id)});
export const uploadSignature=(id,file,key)=>{const data=new FormData();data.append('file',file);return requestApi({method:'post',url:path(id),data,timeout:60000,headers:{'Idempotency-Key':key}});};
export const saveSignatureStatus=(id,data,key)=>requestApi({method:'post',url:`${path(id)}status/`,data,headers:{'Idempotency-Key':key}});
export const previewSignature=(id,attachment)=>fetchApiFile(`${path(id)}${encodeURIComponent(attachment.id)}/download/`);
export const downloadSignature=(id,attachment)=>downloadApiFile(`${path(id)}${encodeURIComponent(attachment.id)}/download/`,attachment.file_name);
