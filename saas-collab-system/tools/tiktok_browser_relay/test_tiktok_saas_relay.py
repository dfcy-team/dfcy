"""Synthetic Flask tests; imports Main's protocol by absolute path only."""
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

PROTOCOL = Path(__file__).resolve().parents[2] / 'backend/apps/integrations/tiktok_bridge_protocol.py'
spec = importlib.util.spec_from_file_location('tiktok_bridge_protocol', PROTOCOL)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)
import tiktok_saas_relay as relay
from flask import Flask


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = b'synthetic-placeholder-key-only-0000000000'
        keyfile = Path(self.temp.name) / 'placeholder.key'
        keyfile.write_bytes(self.key)
        self.env = patch.dict(os.environ, TIKTOK_BROWSER_BRIDGE_KEY_FILE=str(keyfile))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = Flask(__name__)
        self.app.testing = True
        @self.app.before_request
        def gate():
            return 'legacy-gate', 418
        relay.install(self.app)
        relay.install(self.app)
        self.client = self.app.test_client()
        self.flow = dict(session_id=1, actor_id=2, tenant_id=3, store_id=4, config_id=5,
                         platform_store_id='FAKE_SHOP_ID',
                         state='s' * 32, app_key='placeholder', region='TH',
                         callback_uri=protocol.CALLBACK_URI, return_uri=protocol.RETURN_URI,
                         authorization_url='https://services.tiktokshop.com/open/authorize?'
                         + urlencode(dict(service_id='placeholder', state='s' * 32)))

    def token(self, **kw):
        return protocol.sign_token(self.flow, self.key, 'start', **kw)

    def start(self, ticket=None, path='/saas-tk/start'):
        return self.client.post(path, json={'ticket': ticket or self.token()}, base_url='https://localhost',
                                headers={'Origin': 'https://dingfengchuangyu.com'})

    def callback(self, pairs=None):
        return self.client.get('/callback/?' + urlencode(pairs or {'app_key': 'placeholder', 'code': 'secret-code', 'shop_region': 'TH'}),
                               base_url='https://localhost')

    def test_start_page_and_headers(self):
        r = self.client.get('/saas-tk/start')
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertNotIn('never-display', body)
        self.assertLess(body.index('history.replaceState'), body.index('fetch('))
        for word in ['localStorage', 'analytics', 'https://', 'location.search']:
            self.assertNotIn(word, body)
        self.assertEqual(r.headers['Cache-Control'], 'no-store')
        self.assertEqual(r.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(r.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r.headers['X-Frame-Options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", r.headers['Content-Security-Policy'])

    def test_start_cookie_and_idempotence(self):
        ticket = self.token()
        r = self.start(ticket)
        self.assertEqual(r.json, {'next': self.flow['authorization_url']})
        for flag in ['HttpOnly', 'Secure', 'SameSite=Lax', 'Path=/', 'Max-Age=600']:
            self.assertIn(flag, r.headers['Set-Cookie'])
        self.assertEqual(self.start(ticket).status_code, 200)
        self.assertEqual(self.start(path='/saas-tk/start?ticket=forbidden').status_code, 400)

    def test_invalid_tickets_and_addresses(self):
        for ticket in [self.token(now=int(time.time()) - 601), self.token() + 'x',
                       protocol.sign_token(self.flow, self.key, 'callback')]:
            self.assertEqual(self.start(ticket).status_code, 400)
        for field, value in [('return_uri', 'https://evil.invalid'),
                             ('callback_uri', 'https://evil.invalid/callback'),
                             ('authorization_url', 'https://evil.invalid/open/authorize')]:
            flow = {**self.flow, field: value}
            self.assertEqual(self.start(protocol.sign_token(flow, self.key, 'start')).status_code, 400)

    def test_multi_flow_and_expired_cookie(self):
        old = self.token()
        self.start(old)
        for field, value in [('session_id', 99), ('state', 'x' * 32)]:
            flow = {**self.flow, field: value}
            if field == 'state':
                flow['authorization_url'] = self.flow['authorization_url'].replace('s' * 32, value)
            r = self.start(protocol.sign_token(flow, self.key, 'start'))
            self.assertEqual(r.status_code, 409)
            self.assertNotIn('Set-Cookie', r.headers)
        self.client.set_cookie(relay.COOKIE, self.token(now=int(time.time()) - 601))
        self.assertEqual(self.start().status_code, 200)

    def test_callback_missing_and_correct_state_receipts_and_consumption(self):
        for state in [None, self.flow['state']]:
            self.start()
            params = dict(app_key='placeholder', code='secret-code', shop_region='TH')
            if state is not None:
                params['state'] = state
            r = self.callback(params)
            self.assertEqual(r.status_code, 303)
            location = urlsplit(r.headers['Location'])
            self.assertEqual(location._replace(fragment='').geturl(), protocol.RETURN_URI)
            receipt = parse_qs(location.fragment)['receipt'][0]
            claims = protocol.verify_token(receipt, self.key, 'callback')
            self.assertEqual(claims['callback_params'], params)
            self.assertLessEqual(claims['exp'] - claims['iat'], 120)
            self.assertEqual(self.callback(params).status_code, 418)

    def test_callback_rejections_do_not_leak(self):
        self.start()
        base = [('app_key', 'placeholder'), ('code', 'secret-code'), ('shop_region', 'TH')]
        for extra in [[('state', '')], [('state', 'wrong-secret-state')],
                      [('state', self.flow['state']), ('state', self.flow['state'])],
                      [('state', 'ads_secret'), ('state', self.flow['state'])],
                      [('shop_region', 'PH')], [('unknown', 'x')], [('code', 'duplicate')],
                      [('locale', str(i)) for i in range(41)]]:
            r = self.callback(base + extra)
            self.assertEqual(r.status_code, 400)
            self.assertNotIn('secret', r.get_data(as_text=True))
            self.assertNotIn('Location', r.headers)
        self.assertEqual(self.callback(dict(app_key='wrong', code='secret-code')).status_code, 400)
        self.assertEqual(self.callback(dict(app_key='placeholder', code='')).status_code, 400)
        self.assertEqual(self.callback(dict(app_key='placeholder', error='denied', shop_region='TH')).status_code, 303)

    def test_other_routes_and_callbacks_passthrough(self):
        self.assertEqual(self.callback().status_code, 418)
        self.start()
        for params in [dict(auth_code='ads', app_key='placeholder', code='x'),
                       dict(state='ads_123', app_key='placeholder', code='x'),
                       dict(scopes='content', code='x'), dict(code='legacy')]:
            self.assertEqual(self.callback(params).status_code, 418)
        for path in ['/shopee/callback', '/lazada/callback', '/ads', '/content/callback',
                     '/saas-tk/start/extra', '/callback/extra']:
            self.assertEqual(self.client.get(path).status_code, 418)

    def test_missing_key_and_no_logs(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        self.start('secret-ticket')
        self.start()
        self.callback(dict(app_key='placeholder', code='secret-code', state='secret-state'))
        self.assertEqual(stream.getvalue(), '')
        for keyvalue in ['', str(Path(self.temp.name) / 'missing')]:
            with patch.dict(os.environ, TIKTOK_BROWSER_BRIDGE_KEY_FILE=keyvalue):
                self.assertEqual(self.start().status_code, 503)
                self.assertEqual(self.client.get('/saas-tk/start').status_code, 503)

    def test_short_remaining_flow_and_wrong_key(self):
        ticket = self.token(now=int(time.time()) - 550)
        self.start(ticket)
        r = self.callback()
        receipt = parse_qs(urlsplit(r.headers['Location']).fragment)['receipt'][0]
        claims = protocol.verify_token(receipt, self.key, 'callback')
        self.assertLessEqual(claims['exp'] - claims['iat'], 50)
        self.assertEqual(self.start(protocol.sign_token(self.flow, b'x' * 32, 'start')).status_code, 400)

    def test_bad_callback_cookies_and_unavailable_key(self):
        for ticket in [self.token(now=int(time.time()) - 601), self.token() + 'x',
                       protocol.sign_token(self.flow, self.key, 'callback')]:
            self.client.set_cookie(relay.COOKIE, ticket)
            r = self.callback()
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.headers['Cache-Control'], 'no-store')
            self.assertEqual(r.headers['Referrer-Policy'], 'no-referrer')
            self.assertEqual(r.headers['X-Frame-Options'], 'DENY')
            self.assertNotIn('secret-code', r.get_data(as_text=True))
        self.client.set_cookie(relay.COOKIE, self.token())
        shortfile = Path(self.temp.name) / 'short-placeholder.key'
        shortfile.write_bytes(b'placeholder')
        with patch.dict(os.environ, TIKTOK_BROWSER_BRIDGE_KEY_FILE=str(shortfile)):
            self.assertEqual(self.callback().status_code, 503)
            self.assertEqual(self.start().status_code, 503)

    def test_post_origin_media_body_and_duplicate_json(self):
        valid = json.dumps({'ticket': self.token()})
        cases = [({}, 'application/json', valid),
                 ({'Origin': 'null'}, 'application/json', valid),
                 ({'Origin': 'https://dingfengchuangyu.com.evil.invalid'}, 'application/json', valid),
                 ({'Origin': 'https://dingfengchuangyu.com/'}, 'application/json', valid),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'text/plain', valid),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'application/problem+json', valid),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'application/json',
                  '{"ticket":"secret-first","ticket":"secret-last"}'),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'application/json', valid + ' ' * 30000),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'application/json', '{"secret":'),
                 ({'Origin': 'https://dingfengchuangyu.com'}, 'application/json', '[' * 2000)]
        for headers, media, body in cases:
            with self.subTest(headers=headers, media=media, length=len(body)):
                r = self.client.post('/saas-tk/start', data=body, content_type=media, headers=headers)
                self.assertEqual(r.status_code, 400)
                self.assertNotIn('secret', r.get_data(as_text=True))
                self.assertNotIn('Set-Cookie', r.headers)

    def test_exact_start_path_and_query_rejection(self):
        self.assertEqual(self.client.get('/saas-tk/start/').status_code, 418)
        self.assertEqual(self.start(path='/saas-tk/start/').status_code, 418)
        for query in ['ticket=secret-ticket', 'code=secret-code', 'anything=']:
            r = self.client.get('/saas-tk/start?' + query)
            self.assertEqual(r.status_code, 400)
            self.assertNotIn('secret', r.get_data(as_text=True))

    def test_ticket_size_and_key_strip(self):
        flow = {**self.flow, 'authorization_url': self.flow['authorization_url'] + 'x' * 2400}
        oversized = protocol.sign_token(flow, self.key, 'start')
        self.assertGreater(len(oversized), 3000)
        r = self.start(oversized)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('Set-Cookie', r.headers)
        keyfile = Path(os.environ['TIKTOK_BROWSER_BRIDGE_KEY_FILE'])
        keyfile.write_bytes(b' \r\n' + self.key + b'\r\n ')
        self.assertEqual(self.start().status_code, 200)

    def test_callback_limits_controls_and_region(self):
        self.start()
        base = dict(app_key='placeholder', code='secret-code', shop_region='TH')
        bad = [{k: v for k, v in base.items() if k != 'shop_region'},
               {**base, 'shop_region': ''}, {**base, 'shop_region': ' TH'},
               {**base, 'code': 'x' * 8193},
               {**base, 'code': 'x' * 8100, 'locale': 'y' * 8100}]
        for char in ['\x00', '\n', '\r', '\t', '\x1f', '\x7f']:
            bad.append({**base, 'code': 'secret' + char})
            bad.append({**base, 'locale': char})
        for params in bad:
            r = self.callback(params)
            self.assertEqual(r.status_code, 400)
            self.assertNotIn('secret', r.get_data(as_text=True))
        self.assertEqual(self.callback({**base, 'shop_region': 'th'}).status_code, 303)

    def test_no_key_other_platforms_and_invalid_cookies(self):
        for cookie in [None, 'invalid-cookie', self.token()]:
            if cookie:
                self.client.set_cookie(relay.COOKIE, cookie)
            else:
                self.client.delete_cookie(relay.COOKIE)
            with patch.dict(os.environ, TIKTOK_BROWSER_BRIDGE_KEY_FILE=''):
                for params in [dict(auth_code='secret', code='x', app_key='placeholder'),
                               dict(state='ads_123', code='x', app_key='placeholder'),
                               dict(scopes='content', code='x')]:
                    self.assertEqual(self.callback(params).status_code, 418)
                self.assertEqual(self.callback().status_code, 503 if cookie else 418)

    def test_fragment_script_validation(self):
        # Execute the actual inline script with a synthetic browser surface, no network.
        harness = r'''
const script=SCRIPT;
(async()=>{
for(const [hash,valid] of [
 ['#ticket=abc.def',true], ['#ticket=abc.def&ticket=ghi.jkl',false],
 ['#other=x&ticket=abc.def',false], ['#ticket=',false],
 ['#ticket=abc%2Edef',false], ['#ticket=abc.def&',false],
 ['#ticket='+ 'a'.repeat(3000)+'.b',false], ['#ticket=abc.def\n',false],
 ['#ticket=abc.def'+String.fromCharCode(10),false]]){
let cleared=false,calls=0;
global.location={hash,pathname:'/saas-tk/start',assign:()=>{}};
global.history={replaceState:()=>{cleared=true;location.hash='';}};
global.document={body:{textContent:''}};
global.fetch=async(path,options)=>{
 if(!cleared||path!='/saas-tk/start'||options.method!=='POST')throw Error('unsafe');
 calls++;return {ok:true,json:async()=>({next:'verified'})};};
await eval(script);
if(!cleared||calls!==(valid?1:0))throw Error('fragment accepted incorrectly');
}
})();
'''.replace('SCRIPT', json.dumps(relay.SCRIPT))
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_install_key_path_without_environment_and_config_priority(self):
        configured = os.environ['TIKTOK_BROWSER_BRIDGE_KEY_FILE']
        handlers = list(self.app.before_request_funcs[None])
        relay.install(self.app, key_file=configured)
        self.assertEqual(self.app.config['TIKTOK_BROWSER_BRIDGE_KEY_FILE'], configured)
        self.assertEqual(self.app.before_request_funcs[None], handlers)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.start().status_code, 200)
            self.assertEqual(self.callback().status_code, 303)
        with patch.dict(os.environ, TIKTOK_BROWSER_BRIDGE_KEY_FILE='missing-placeholder'):
            self.assertEqual(self.start().status_code, 200)
        relay.install(self.app, key_file=str(Path(self.temp.name) / 'missing-configured-key'))
        self.assertEqual(self.start().status_code, 503)

    def test_only_relay_responses_scrub_request_environment(self):
        captured = []
        @self.app.after_request
        def capture(response):
            from flask import request
            captured.append({name: request.environ.get(name) for name in
                             ('QUERY_STRING', 'RAW_URI', 'REQUEST_URI')})
            return response

        def get(path, query):
            return self.client.get(path + '?' + query, base_url='https://localhost',
                                   environ_overrides={'RAW_URI': path + '?' + query,
                                                      'REQUEST_URI': path + '?' + query})

        query = 'ticket=secret-ticket'
        self.assertEqual(get('/saas-tk/start', query).status_code, 400)
        self.assertEqual(captured[-1], dict(QUERY_STRING='', RAW_URI='/saas-tk/start',
                                           REQUEST_URI='/saas-tk/start'))
        self.start()
        query = 'app_key=placeholder&code=secret-code&shop_region=TH'
        self.assertEqual(get('/callback', query).status_code, 303)
        self.assertEqual(captured[-1], dict(QUERY_STRING='', RAW_URI='/callback', REQUEST_URI='/callback'))
        # Cookie was consumed: the old callback and other platforms retain raw environ.
        self.assertEqual(get('/callback', query).status_code, 418)
        self.assertEqual(captured[-1], dict(QUERY_STRING=query, RAW_URI='/callback?' + query,
                                           REQUEST_URI='/callback?' + query))
        self.start()
        query = 'auth_code=secret-ads-code&state=ads_123'
        self.assertEqual(get('/callback/', query).status_code, 418)
        self.assertEqual(captured[-1], dict(QUERY_STRING=query, RAW_URI='/callback/?' + query,
                                           REQUEST_URI='/callback/?' + query))


if __name__ == '__main__':
    unittest.main()
