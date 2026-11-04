// Calendar arithmetic is UTC civil-date arithmetic; source dates are already localized.
const DAY=86400000;
function date(value){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return null;
 const d=new Date(value+'T00:00:00Z');return Number.isFinite(+d)&&d.toISOString().slice(0,10)===value?d:null;
}
const iso=d=>d.toISOString().slice(0,10);
function anchor(type,value){
 const d=date(value);if(!d)return null;
 if(type==='week')return iso(new Date(+d-((d.getUTCDay()+6)%7)*DAY));
 if(type==='half_month')return value.slice(0,7)+(d.getUTCDate()<16?'-01':'-16');
 if(type==='month')return value.slice(0,7)+'-01';
 throw Error('统计维度无效。');
}
function periodRange(type,value){
 const d=date(value);if(!d||anchor(type,value)!==value)throw Error('统计区间无效。');
 const end=type==='week'?new Date(+d+6*DAY):type==='half_month'&&d.getUTCDate()===1?new Date(+d+14*DAY):new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+1,0));
 return{from:value,to:iso(end)};
}
function periodOptions(month,dates=[]){
 const start=date(month+'-01');if(!start)return{week:[],half_month:[]};
 const days=[];for(let d=start;iso(d).startsWith(month);d=new Date(+d+DAY))days.push(iso(d));
 return Object.fromEntries(['week','half_month'].map(type=>[type,[...new Set(days.concat(dates).map(d=>anchor(type,d)).filter(Boolean))].sort().reverse().map(value=>{const range=periodRange(type,value);return{value,label:range.from+' — '+range.to,...range};})]));
}
function datedFact(f,first){
 let value=Object.hasOwn(f,'statistics_date')?f.statistics_date:f.date,basis=f.statistics_date_basis||'原财务流水日期';
 if(f.hierarchy_allocation&&!Object.hasOwn(f,'statistics_date')){value=first.get([f.store_id,f.external_order_id,f.currency].join('|'))||null;basis='关联订单本账期首次有效销售结算日（分摊归期）';}
 else if(/^hierarchy-(ad|reclassification):/.test(f.source_id||'')){value=null;basis='月度控制额，无实际日依据';}
 return{...f,period_date:date(value)?value:null,period_date_basis:basis};
}
function inPeriod(f,type,value){
 if(type==='month'||!type)return true;
 if(value==='undated')return !date(f.period_date);
 if(!value)return true;
 const r=periodRange(type,value);return !!date(f.period_date)&&f.period_date>=r.from&&f.period_date<=r.to;
}
module.exports={DAY,date,iso,anchor,periodRange,periodOptions,datedFact,inPeriod};
