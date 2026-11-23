import fs from 'node:fs';
import assert from 'node:assert/strict';
const plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
for (const item of plan.filter(x => /List-dates-/.test(x.path))) {
  const text = Buffer.from(item.data, 'base64').toString();
  const task = item.path.includes('Outreach');
  const [create, message, change, button, reset] = task ? ['n','k','W','f','Xl'] : ['t','h','ae','m','Vl'];
  const start = text.indexOf(`${create}("label",{style:"display:inline-flex`);
  const end = text.indexOf(`u(${button},{type:"primary",onClick:${change}}`, start);
  assert(start > 0 && end > start);
  const T = {created_from:'',created_to:''};
  let calls=0;
  const node=(tag,props,children)=>({tag,props,children});
  const labels = new Function('T',create,message,change,`return [${text.slice(start,end)}]`)(T,node,x=>x,()=>calls++);
  assert.equal(labels.length,2);
  for (const [index,field] of ['created_from','created_to'].entries()) {
    const input=labels[index].children[1];
    assert.equal(input.tag,'input');
    assert.equal(input.props.type,'date');
    input.props.onChange({target:{value:'2026-11-05'}});
    assert.equal(T[field],'2026-11-05');
  }
  assert.equal(calls,2);
  const marker='T.created_from&&(l.created_from=T.created_from);T.created_to&&(l.created_to=T.created_to);';
  assert(text.includes(marker));
  const params={store:23};
  new Function('T','l',marker)(T,params);
  assert.deepEqual(params,{store:23,created_from:'2026-11-05',created_to:'2026-11-05'});
  const body=text.match(new RegExp(`function ${reset}\\(\\)\\{([^}]+}\\),[^}]+)}`))[1];
  new Function('T',change,body)(T,()=>calls++);
  assert.equal(T.created_from,'');assert.equal(T.created_to,'');assert.equal(calls,3);
  const empty={};new Function('T','l',marker)(T,empty);assert.deepEqual(empty,{});
  console.log(item.path+': render/change/query/reset passed');
}
