const DAY=86400000;
const date=value=>new Date(value+'T00:00:00Z');
const iso=value=>value.toISOString().slice(0,10);
export function shiftMonth(month,offset){const d=date(month+'-01');return iso(new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth()+offset,1))).slice(0,7);}
export function periodRange(type,value){
 const d=date(value.length===7?value+'-01':value);
 if(type==='week'){const from=new Date(+d-((d.getUTCDay()+6)%7)*DAY);return{from:iso(from),to:iso(new Date(+from+6*DAY))};}
 const year=d.getUTCFullYear(),month=d.getUTCMonth(),half=type==='half_month';
 const from=new Date(Date.UTC(year,month,half&&d.getUTCDate()>15?16:1));
 return{from:iso(from),to:iso(new Date(Date.UTC(year,month,half&&from.getUTCDate()===1?15:new Date(Date.UTC(year,month+1,0)).getUTCDate())))};
}
export function calendarDays(month){const from=periodRange('week',month+'-01').from;return Array.from({length:42},(_,i)=>iso(new Date(+date(from)+i*DAY)));}
export function periodText(value){
 if(value.period_type==='month')return value.month?value.month.replace('-','年')+'月':'全部账期';
 if(value.period==='undated')return '待归期（无可靠日期）';
 if(!value.period)return '请选择区间';
 const range=periodRange(value.period_type,value.period);
 return range.from+' — '+range.to;
}
