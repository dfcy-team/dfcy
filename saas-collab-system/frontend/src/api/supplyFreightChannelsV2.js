import { requestApi } from './request';
const BASE='/api/internal/supply-chain/v2/freight-channels/';
export const fetchFreightChannels=params=>requestApi({method:'get',url:BASE,params});
export const createFreightChannel=(data,key)=>requestApi({method:'post',url:BASE,data,headers:{'Idempotency-Key':key}});
export const updateFreightChannel=(id,data,key)=>requestApi({method:'patch',url:`${BASE}${encodeURIComponent(id)}/`,data,headers:{'Idempotency-Key':key}});
export const fetchFreightQuotes=(id,params)=>requestApi({method:'get',url:`${BASE}${encodeURIComponent(id)}/quotes/`,params});
export const publishFreightQuote=(id,data,key)=>requestApi({method:'post',url:`${BASE}${encodeURIComponent(id)}/quotes/`,data,headers:{'Idempotency-Key':key}});
