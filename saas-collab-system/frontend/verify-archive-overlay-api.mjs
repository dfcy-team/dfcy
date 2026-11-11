import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

// Execute the captured live API module with a recording transport, never HTTP.
const snapshot = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let source = Buffer.from(snapshot['assets/influencers-DRFnSV9F.js'], 'base64').toString();
source = source.replace(/^import[^;]+;/, 'const p=x=>x,c=x=>x,i=x=>x;');
source = source.replace(/export\{([^}]+)\};?/, (_, bindings) =>
  'globalThis.exports={' + bindings.split(',').map(binding => {
    const [local, exported] = binding.trim().split(' as ');
    return `${exported || local}:${local}`;
  }).join(',') + '};');
const context = vm.createContext({});
vm.runInContext(source, context);
const builder = fs.readFileSync(new URL('./build-archive-overlay.mjs', import.meta.url), 'utf8');
const mapping = vm.runInNewContext('(' + builder.match(/const api=(\{[^;]+\});/)[1] + ')');
const contracts = {
  fetchInfluencers: ['get', '/', [{}]],
  fetchInfluencer: ['get', '/17/', [17]],
  fetchInfluencerForm: ['get', '/17/', [17]],
  fetchRelatedInfluencerArchives: ['get', '/17/related-archives/', [17]],
  createRelatedInfluencerArchive: ['post', '/17/related-archives/', [17, {}, 'v1']],
  fetchInfluencerBlacklistHistory: ['get', '/17/blacklist-history/', [17]],
  fetchInfluencerContacts: ['get', '/17/contacts/', [17]],
  saveInfluencerForm: ['patch', '/17/', [17, {}, 'v1']],
  fetchTikTokCreatorSnapshots: ['get', '/17/tiktok-creator/', [17]],
  queryTikTokCreator: ['post', '/17/tiktok-creator/', [17, 2]],
  updateInfluencerBlacklist: ['post', '/17/blacklist/', [17, {}, 'v1']],
  updateInfluencerStatus: ['post', '/17/status/', [{id:17,updated_at:'v1'}, 'inactive']],
};
const built = fs.readFileSync(process.argv[3], 'utf8');
for (const [name, [method, suffix, args]] of Object.entries(contracts)) {
  const config = context.exports[mapping[name]](...args);
  assert.equal(config.method, method, name);
  assert.equal(config.url, '/api/internal/influencers' + suffix, name);
  assert.ok(new RegExp(`(?:\\{|,)${mapping[name]} as \\w+`).test(built), name + ' built import');
}
assert.equal(context.exports[mapping.INFLUENCER_CONTACT_CHANNEL_LABELS].email, '\u90ae\u7bb1');
assert.equal(context.exports[mapping.INFLUENCER_COOPERATION_STATUS_LABELS].prospect, '\u5f85\u63a5\u6d3d');
console.log('PASS: 12 live API method/URL contracts and 2 label mappings; no network requests');
