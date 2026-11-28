import {describe,it,expect} from 'vitest';
import fs from 'node:fs';
import {parse as parseVue} from '@vue/compiler-sfc';
import {parse as parseJs} from '@babel/parser';

const source=fs.readFileSync('src/components/supply-chain/SettlementOverviewV2.vue','utf8');
const script=parseVue(source).descriptor.scriptSetup.content;
const ast=parseJs(script,{sourceType:'module'});
const names=['currencyDescription','currencyBreakdown','currencyEvidence','goPay'];
const functions=ast.program.body.filter(n=>n.type==='FunctionDeclaration'&&names.includes(n.id.name)).map(n=>script.slice(n.start,n.end)).join('\n');
const money=ast.program.body.find(n=>n.type==='VariableDeclaration'&&n.declarations.some(d=>d.id.name==='money'));
const moneyCode=script.slice(money.start,money.end);
const pushes=[];
const api=new Function('props','router',moneyCode+'\n'+functions+'\nreturn {currencyDescription,currencyBreakdown,currencyEvidence,goPay,money};')({overview:true},{push:x=>pushes.push(x)});

describe('domestic original-unit presentation',()=>{
 it('keeps mixed and unknown totals visibly unresolved',()=>{
   expect(api.money(null)).toBe('待核对');
   expect(api.currencyDescription({mixed_currency:true})).toContain('不同币种');
   expect(api.currencyDescription({unresolved_currency_nonzero:true})).toContain('币种待核对');
   const text=api.currencyBreakdown({totals_by_currency:{CNY:{amount:'10'},PHP:{amount:'10'}}},'amount');
   expect(text).toContain('CNY 10');expect(text).toContain('PHP 10');expect(text).not.toContain('20');
 });
 it('shows original due and differently posted cash without inventing a balance',()=>{
   const text=api.currencyEvidence({original_due:{currency:'CNY',amount:'6'},payment_totals_by_currency:{PHP:{paid_amount:'4'}}});
   expect(text).toContain('CNY 6');expect(text).toContain('PHP 4');expect(text).toContain('余额待核对');
 });
 it('distinguishes a historical display confirmation from an original posting and avoids false zero wording',()=>{
   const text=api.currencyEvidence({original_due:{currency:'PHP',amount:'6'},payment_totals_by_currency:{CNY:{paid_amount:'4'}},payment_currency_evidence_sources:['legacy_confirmation']});
   expect(text).toContain('付款币种（含历史确认）');expect(text).not.toContain('入账原币');
   expect(source).toContain('v-if="row.monetary_currency_conflict"');
   expect(source).toContain('付款币种待核对');
 });
 it('preserves supplier versus carrier for identical party IDs through both entry points',()=>{
   api.goPay('domestic',7,'Same numeric ID','supplier');
   api.goPay('domestic',7,'Same numeric ID','carrier');
   expect(pushes.map(x=>x.query.party_kind)).toEqual(['supplier','freight_company']);
   expect(source).toContain('goPay(queue,partyId,partyName,monthlyPartyType)');
   expect(source).toContain('openGroup(queue,{party_id:row.party_id,name:row.party_name,party_type:row.party_type})');
 });
 it('does not display missing legacy currency as CNY or enable a blocked replacement',()=>{
   const legacy=fs.readFileSync('src/components/supply-chain/ShipmentDomesticExpenses.vue','utf8');
   expect(legacy).not.toContain("legacyFee.currency || 'CNY'");
   expect(legacy).toContain("legacyFee.currency || '币种待核对'");
   expect(legacy).toContain(':disabled="!legacyFee.can_replace"');
 });
});
