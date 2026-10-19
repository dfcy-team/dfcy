"""Synthetic Ads relay tests; never import the real portal or call TikTok."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "tiktok_ads_bridge_protocol.py"
if not PROTOCOL.exists():
    PROTOCOL = HERE.parents[1] / "affiliate-daily-ingestion-20261012/candidate/backend/apps/integrations/tiktok_ads_bridge_protocol.py"
spec = importlib.util.spec_from_file_location("tiktok_ads_bridge_protocol", PROTOCOL)
protocol = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = protocol
spec.loader.exec_module(protocol)
import tiktok_saas_ads_relay as relay
from flask import Flask


class AdsRelayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = b"synthetic-placeholder-ads-relay-key-0000000000"
        keyfile = Path(self.temp.name) / "placeholder.key"
        keyfile.write_bytes(self.key)
        keyfile.chmod(0o600)
        self.directory = Path(self.temp.name) / "receipts"
        self.app = Flask(__name__)
        self.app.testing = True
        @self.app.before_request
        def legacy():
            return "legacy-handler", 418
        relay.install(self.app, str(keyfile), str(self.directory))
        relay.install(self.app, str(keyfile), str(self.directory))
        self.client = self.app.test_client()
        self.flow = dict(session_id=str(uuid4()), state="saas_ads_" + "s" * 43,
            actor_id=2, tenant_id=3, store_id=4, config_id=5, app_id="1234567890",
            callback_uri=protocol.CALLBACK_URI, return_uri=protocol.RETURN_URI)
        self.flow["authorization_url"] = "https://business-api.tiktok.com/portal/auth?" + urlencode({
            "app_id": self.flow["app_id"], "state": self.flow["state"], "redirect_uri": protocol.CALLBACK_URI})

    def request(self, method, path, **kwargs):
        return self.client.open(path, method=method, base_url="https://dingfengchuangyu.com", **kwargs)

    def start(self, ticket=None, origin="https://dingfengchuangyu.com"):
        ticket = ticket or protocol.sign_token(self.flow, self.key, "start")
        return self.request("POST", "/saas-tk-ads/start", json={"ticket": ticket}, headers={"Origin": origin})

    def callback(self, **overrides):
        params = {"auth_code": "synthetic-code-never-browser", "state": self.flow["state"], **overrides}
        return self.request("GET", "/callback?" + urlencode(params))

    def receipt(self):
        self.assertEqual(self.start().status_code, 200)
        response = self.callback()
        self.assertEqual(response.status_code, 303)
        return parse_qs(urlsplit(response.headers["Location"]).fragment)["receipt_id"][0]

    def fetch(self, receipt, **overrides):
        claims = {name: self.flow[name] for name in ("session_id", "actor_id", "tenant_id", "store_id", "config_id")}
        claims.update(receipt_id=receipt, **overrides)
        ticket = protocol.sign_token(claims, self.key, "fetch")
        return self.request("POST", "/saas-tk-ads/receipt", json={"ticket": ticket})

    def test_start_and_security_headers(self):
        response = self.request("GET", "/saas-tk-ads/start")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
        body = response.get_data(as_text=True)
        self.assertLess(body.index("history.replaceState"), body.index("fetch("))
        self.assertNotIn("localStorage", body)
        self.assertEqual(self.start().json["next"], self.flow["authorization_url"])

    def test_invalid_origin_and_signature(self):
        self.assertEqual(self.start(origin="https://attacker.invalid").status_code, 400)
        self.assertEqual(self.start(ticket="invalid.invalid").status_code, 400)

    def test_expired_start(self):
        ticket = protocol.sign_token(self.flow, self.key, "start", now=int(time.time()) - 700)
        self.assertEqual(self.start(ticket=ticket).status_code, 400)

    def test_cookie_flags_and_same_context_restart_without_waiting(self):
        response = self.start()
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax", "Path=/"):
            self.assertIn(flag, cookie)
        other = {**self.flow, "session_id": str(uuid4()), "state": "saas_ads_" + "t" * 43}
        other["authorization_url"] = "https://business-api.tiktok.com/portal/auth?" + urlencode({
            "app_id": other["app_id"], "state": other["state"], "redirect_uri": protocol.CALLBACK_URI})
        self.assertEqual(self.start(protocol.sign_token(other, self.key, "start")).status_code, 200)
        self.assertEqual(self.callback().status_code, 400)
        self.assertEqual(self.callback(state=other['state']).status_code, 303)

    def test_other_owner_or_store_cannot_replace_active_browser_flow(self):
        self.start()
        for field in ('actor_id','tenant_id','store_id','config_id','app_id'):
            other={**self.flow,'session_id':str(uuid4())}
            other[field]='9876543210' if field=='app_id' else other[field]+1
            other['authorization_url']='https://business-api.tiktok.com/portal/auth?'+urlencode({
                'app_id':other['app_id'],'state':other['state'],'redirect_uri':protocol.CALLBACK_URI})
            self.assertEqual(self.start(protocol.sign_token(other,self.key,'start')).status_code,409)
        self.assertEqual(self.callback().status_code,303)

    def test_restart_does_not_extend_ticket_lifetime_or_expose_credentials(self):
        self.start()
        expired=protocol.sign_token(self.flow,self.key,'start',now=int(time.time())-700)
        self.assertEqual(self.start(expired).status_code,400)
        page=self.request('GET','/saas-tk-ads/start').get_data(as_text=True)
        self.assertNotIn('等待十分钟',page)
        self.assertNotIn('localStorage',page)
        self.assertIn('返回 SaaS 重新发起授权',page)

    def test_callback_only_returns_opaque_identifiers(self):
        self.start()
        response = self.callback()
        self.assertEqual(response.status_code, 303)
        location = response.headers["Location"]
        self.assertNotIn("synthetic-code", location)
        self.assertNotIn("auth_code", location)
        self.assertNotIn(self.flow["state"], location)
        params = parse_qs(urlsplit(location).fragment)
        self.assertEqual(set(params), {"session_id", "receipt_id"})
        self.assertEqual(params["session_id"], [self.flow["session_id"]])
        self.assertRegex(params["receipt_id"][0], r"^[0-9a-f]{64}$")

    def test_receipt_is_encrypted_at_rest(self):
        receipt = self.receipt()
        stored = (self.directory / (receipt + ".receipt")).read_bytes()
        self.assertNotIn(b"synthetic-code", stored)
        self.assertNotIn(self.flow["state"].encode(), stored)
        if os.name != "nt":
            self.assertEqual((self.directory.stat().st_mode & 0o777), 0o700)
            self.assertEqual(((self.directory / (receipt + ".receipt")).stat().st_mode & 0o777), 0o600)

    def test_shop_content_and_legacy_ads_untouched(self):
        self.start()
        for params in [dict(code="synthetic", app_key="shop", shop_region="PH"),
                       dict(code="synthetic", scopes="user.info.basic"),
                       dict(state="ads_legacy", error="access_denied"), {}]:
            self.assertEqual(self.request("GET", "/callback?" + urlencode(params)).status_code, 418)
        self.assertEqual(self.request("GET", "/privacy").status_code, 418)

    def test_missing_cookie_never_falls_into_legacy_exchange(self):
        self.assertEqual(self.callback().status_code, 400)

    def test_duplicate_callback_fields_rejected(self):
        self.start()
        pairs = [("state", self.flow["state"]), ("auth_code", "synthetic"), ("auth_code", "other")]
        self.assertEqual(self.request("GET", "/callback?" + urlencode(pairs)).status_code, 400)

    def test_wrong_application_or_extra_params_rejected(self):
        self.start()
        self.assertEqual(self.callback(id="999999").status_code, 400)
        self.assertEqual(self.callback(next="https://attacker.invalid").status_code, 400)

    def test_wrong_methods_duplicate_json_and_fetch_without_signature(self):
        self.assertEqual(self.request("GET", "/saas-tk-ads/receipt").status_code, 405)
        self.assertEqual(self.request("POST", "/saas-tk-ads/receipt", json={"ticket": "bad"}).status_code, 400)
        self.assertEqual(self.request("POST", "/saas-tk-ads/start", data='{"ticket":"a","ticket":"b"}',
            content_type="application/json", headers={"Origin":"https://dingfengchuangyu.com"}).status_code, 400)

    @unittest.skipIf(os.name == "nt", "POSIX file-lock acceptance runs separately on Linux")
    def test_fetch_is_context_bound_and_single_use(self):
        receipt = self.receipt()
        self.assertEqual(self.fetch(receipt, tenant_id=999).status_code, 400)
        response = self.fetch(receipt)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["session_id"], self.flow["session_id"])
        self.assertEqual(response.json["callback_params"]["auth_code"], "synthetic-code-never-browser")
        self.assertEqual(self.fetch(receipt).status_code, 400)
        self.assertFalse((self.directory / (receipt + ".receipt")).exists())

    @unittest.skipIf(os.name == "nt", "POSIX file-lock acceptance runs separately on Linux")
    def test_more_than_one_thousand_consumptions_do_not_exhaust_capacity(self):
        claims = {**self.flow, "exp": int(time.time()) + 600}
        with self.app.app_context():
            for _ in range(1002):
                receipt = relay._save_receipt(claims, {"state":self.flow["state"], "auth_code":"synthetic"}, self.key)
                fetch = {**self.flow, "receipt_id":receipt}
                self.assertEqual(relay._take_receipt(fetch, self.key)["callback_params"]["auth_code"], "synthetic")
            self.assertEqual(list(self.directory.glob("*.receipt")), [])

    @unittest.skipIf(os.name == "nt", "POSIX file-lock acceptance runs separately on Linux")
    def test_expired_and_consumed_reclamation_preserves_valid_receipts(self):
        valid = self.receipt()
        expired = {"flow": self.flow, "callback_params":{"state":self.flow["state"]}, "exp":int(time.time())-1}
        for name, body in [("a"*64, relay._fernet(self.key).encrypt(json.dumps(expired).encode())), ("b"*64,b"USED")]:
            path = self.directory / (name + ".receipt")
            path.write_bytes(body)
            path.chmod(0o600)
        with self.app.app_context():
            self.assertEqual(relay._reap_receipts(self.directory,self.key),2)
        self.assertTrue((self.directory/(valid+".receipt")).exists())

    @unittest.skipIf(os.name == "nt", "POSIX file-lock acceptance runs separately on Linux")
    def test_concurrent_fetch_has_exactly_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        receipt = self.receipt()
        claims = {**self.flow, "receipt_id": receipt}
        def take():
            with self.app.app_context():
                try:
                    relay._take_receipt(claims,self.key)
                    return True
                except (OSError,ValueError,relay.InvalidToken):
                    return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(lambda _:take(),range(2))),1)

    @unittest.skipIf(os.name == "nt", "POSIX file-lock acceptance runs separately on Linux")
    def test_denial_has_no_authorization_code(self):
        self.start()
        response = self.callback(error="user_cancel", error_description="untrusted details")
        receipt = parse_qs(urlsplit(response.headers["Location"]).fragment)["receipt_id"][0]
        data = self.fetch(receipt).json["callback_params"]
        self.assertEqual(data, {"state": self.flow["state"], "error": "authorization_denied"})

    def test_protocol_rejects_arbitrary_redirect_and_cross_purpose(self):
        for field, value in [("return_uri", "https://attacker.invalid"), ("callback_uri", "https://attacker.invalid"),
                             ("session_id", "not-uuid"), ("actor_id", True)]:
            with self.assertRaises(ValueError):
                protocol.validate_flow({**self.flow, field: value})
        with self.assertRaises(ValueError):
            protocol.verify_token(protocol.sign_token(self.flow, self.key, "start"), self.key, "fetch")
        with self.assertRaises(ValueError):
            protocol.verify_token(protocol.sign_token(self.flow, self.key, "start"), b"different-placeholder-key-000000000", "start")


if __name__ == "__main__":
    unittest.main()
