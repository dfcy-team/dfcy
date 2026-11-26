const {test}=require('node:test');
const assert=require('node:assert/strict');
const {prepareSource}=require('../apps/finance/summary_engine.cjs');
const ids=['unified-finance-ui','sku-summary-ui','finance-fee-checkboxes','html2-sp6th-fees-data','html2-sp6th-fees','html2-lazada-cycles-data','html2-lazada-finance','html2-ledger-fees','html2-profit-rules','html2-store-hierarchy','html2-shopee-recharge-data','html2-shopee-recharge','html2-advertising-columns','html2-product-links','html2-fee-rates'];
function fixture(compact){
 const snapshot={raw:[],shopee_income:[],database:{facts:[]},local_expenses:{facts:[]},label:'中文😀'};
 return '<html><script id="snapshot">'+JSON.stringify(snapshot)+'</script><script>\n const FACTS=SNAPSHOT.database.facts;'+(compact?'// SAAS_DATABASE_ENTRIES':'')+'\n</script>'+ids.map(id=>'<script id="'+id+'">/* '+id+' 中文 */</script>').join('')+'</html>';
}
for(const compact of [false,true])for(const retainJSON of [false,true])for(const native of [false,true]){
 test(`Buffer and text keep identical financial inputs compact=${compact} retain=${retainJSON} native=${native}`,()=>{
  const html=fixture(compact),text=prepareSource(html,native,{retainJSON}),buffer=prepareSource(Buffer.from(html),native,{retainJSON});
  assert.deepEqual(buffer,text);
  if(!retainJSON){assert.equal(buffer.snapshotJSON,null);assert.equal(buffer.dataJSON,null);}
 });
}
test('buffer parser rejects incomplete source',()=>{
 assert.throws(()=>prepareSource(Buffer.from('<html>'),true,{retainJSON:false}));
});
test('one-shot VM produces identical data with source retention disabled',()=>{
 const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto'),vm=require('node:vm');
 const {createEngine}=require('../apps/finance/summary_engine.cjs');
 const directory=fs.mkdtempSync(path.join(os.tmpdir(),'finance-oom-synthetic-'));
 try{
  const html=fixture(false).replace('const FACTS=SNAPSHOT.database.facts;','const SNAPSHOT=TEST_SNAPSHOT;const localFact=x=>x;globalThis.PREVIEW_TEST={};');
  const file=path.join(directory,'source.html.gz');fs.writeFileSync(file,zlib.gzipSync(html));
  const input={sourceHash:crypto.createHash('sha256').update(html).digest('hex'),state:{}};
  const before=createEngine(file,input),after=createEngine(file,input,{retainSource:false});
  assert.equal(JSON.stringify(vm.runInContext('SNAPSHOT',before.c)),JSON.stringify(vm.runInContext('SNAPSHOT',after.c)));
  assert.deepEqual(after.writes,before.writes);
  assert.throws(()=>createEngine(file,{...input,sourceHash:'incorrect'},{retainSource:false}));
 }finally{fs.rmSync(directory,{recursive:true,force:true});}
});

test('bundled attributed snapshot template opens in native query',()=>{
 const path=require('node:path'),{spawnSync}=require('node:child_process');
 const source=path.resolve(__dirname,'../apps/finance/templates/database-v1.html.gz');
 const request={key:'template-smoke',path:source,input:{action:'history',state:{}}};
 const child=spawnSync(process.execPath,[path.resolve(__dirname,'../apps/finance/summary_native.cjs')],{input:JSON.stringify(request)+'\n',encoding:'utf8',timeout:20000});
 assert.equal(child.status,0,child.stderr);const result=JSON.parse(child.stdout);assert.equal(result.ok,true,JSON.stringify(result));assert.ok(Array.isArray(result.result.rows));
});

test('ignores unrelated optional script attributes as the accepted engine did',()=>{
 const html=fixture(false)+'<script id="optional" src=\'optional.js\'></script>';
 const parsed=prepareSource(Buffer.from(html),false,{retainJSON:false});
 assert.equal(parsed.snapshot.label,'中文😀');assert.equal(Object.keys(parsed.scripts).length,15);
});
