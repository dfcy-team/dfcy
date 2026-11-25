import json
import re
import unittest

from apps.finance.summary_database_document import compact_tools_inputs


class FinanceToolsDocumentTests(unittest.TestCase):
    def test_duplicate_cost_quotes_are_losslessly_interned_and_restored_before_calculation(self):
        quote = {'rate': '2.125', 'input_id': 42, 'source': {'date': '2026-10-01', 'basis': 'approved'}}
        facts = [{'kind': 'product_cost', 'amount': '-21.25', 'cost_conversion': {'quote': quote, 'local_amount': '-21.25', 'to': 'PHP'}} for _ in range(3)]
        snapshot = {'database': {'facts': facts, 'raw_flows': [], 'rates': {}, 'shares': {}},
                    'allocations': {}, 'local_expenses': {'facts': []}}
        source = '<script id="snapshot">'+json.dumps(snapshot)+'</script><script>const SNAPSHOT = typeof document === \'undefined\' ? globalThis.TEST_SNAPSHOT : JSON.parse(document.getElementById(\'snapshot\').textContent);\n</script>// SAAS_DATABASE_ENTRIES'
        result = compact_tools_inputs(source)
        data = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', result)[1])['database']
        self.assertEqual(data['settings_quotes'], [quote])
        for fact in data['facts']:
            self.assertEqual(fact['cost_conversion']['quote'], {'settings_quote': 0})
            self.assertEqual(fact['cost_conversion']['local_amount'], '-21.25')
        self.assertLess(result.index('c.quote=SNAPSHOT.database.settings_quotes'), result.index('// SAAS_DATABASE_ENTRIES'))

    def test_settings_drop_only_raw_detail_arrays(self):
        facts = [{'kind': 'advertising', 'amount': '-105.00'}, {'kind': 'sales', 'amount': '800.00'}, {'kind': 'product_cost', 'amount': '-20.00', 'cost_calculation': {'state': 'ready', 'version': 3, 'components': [{'evidence': 'detail-only'}]}}]
        database = {'facts': facts, 'shares': {'order': []}, 'rates': {'monthly': {}},
                    'raw_flows': [{'source_id': 'raw:1'}], 'cost_flows': [{'source_id': 'cost:1'}]}
        source = '<script id="snapshot">' + json.dumps({'database': database}) + '</script>// SAAS_DATABASE_ENTRIES'
        result = compact_tools_inputs(source)
        data = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', result)[1])['database']
        self.assertEqual(data['facts'][:2], facts[:2])
        self.assertEqual(data['facts'][2]['amount'], '-20.00')
        self.assertEqual(data['facts'][2]['cost_calculation'], {'state': 'ready', 'version': 3})
        self.assertIn('components', facts[2]['cost_calculation'])
        self.assertEqual(data['rates'], database['rates'])
        self.assertEqual(data['shares'], database['shares'])
        self.assertNotIn('raw_flows', data)
        self.assertNotIn('cost_flows', data)
        self.assertIn('raw_flows', source)

    def test_legacy_document_is_unchanged(self):
        source = '<script id="snapshot">{"legacy":true}</script>'
        self.assertEqual(compact_tools_inputs(source), source)


class PackedToolsDocumentTests(unittest.TestCase):
    def test_snapshot_round_trip_preserves_values_and_key_order(self):
        import subprocess
        from apps.finance.summary_database_document import pack_tools_document
        value = {'facts': [{'amount': '-0.000001', 'empty': [], 'null': None, 'enabled': False},
                           {'amount': 0, '__proto__': {'safe': True}, 'empty': {}}], 'unicode': '账务'}
        reader = "JSON.parse(document.getElementById('snapshot').textContent)"
        source = '<script id="snapshot" type="application/json">' + json.dumps(value) + '</script><script>const SNAPSHOT=' + reader + ';console.log(JSON.stringify(SNAPSHOT));</script>'
        result = pack_tools_document(source)
        payload = re.search(r'id="snapshot"[^>]*>(.*?)</script>', result)[1]
        script = re.findall(r'<script>(.*?)</script>', result)[0]
        output = subprocess.check_output(['node', '-e', 'const document={getElementById:()=>({textContent:' + json.dumps(payload) + '})};' + script], text=True, encoding='utf-8')
        self.assertEqual(json.loads(output), value)
        self.assertEqual(list(json.loads(output)['facts'][1]), list(value['facts'][1]))


class ScopedToolsDocumentTests(unittest.TestCase):
    def test_selected_store_keeps_all_months_rates_and_global_settings(self):
        from apps.finance.summary_database_document import scope_tools_inputs
        facts = [{'store_id':1,'store_code':'A','date':'2026-09-01','amount':'-1'}, {'store_id':1,'date':'2026-10-01','amount':'-2'}, {'store_id':2,'store_code':'B','amount':'-3'}]
        snapshot = {'database':{'facts':facts,'shares':{'order':facts},'rates':{'complete':True},'participation_sources':facts},'local_expenses':{'facts':facts}}
        source = '<script id="snapshot">'+json.dumps(snapshot)+'</script>// SAAS_DATABASE_ENTRIES'
        result=scope_tools_inputs(source,1)
        value=json.loads(re.search(r'id="snapshot">(.*?)</script>',result)[1])
        self.assertEqual(value['database']['facts'],facts[:2])
        self.assertEqual(value['database']['shares']['order'],facts[:2])
        self.assertEqual(value['database']['rates'],{'complete':True})
        self.assertEqual(value['database']['settings_store'],1)
        self.assertEqual({row['store_id'] for row in value['database']['settings_shops']},{1,2})
        self.assertEqual(value['local_expenses']['facts'],[])


class DocumentByteCacheTests(unittest.TestCase):
    def test_lru_budget_and_version_store_isolation(self):
        from unittest.mock import patch
        from apps.finance import summary_views as views
        with patch.object(views, '_document_cache', __import__('collections').OrderedDict()), patch.object(views, '_document_cache_bytes', 0), patch.object(views, '_document_cache_limit', 10), patch.object(views, 'build_prepared_document', return_value=b'1234') as build:
            def get(store, version=1):
                return views.prepared_document('test', 'hash', (version,), (1,), True, store)
            get(1);get(2);get(1);get(3)
            self.assertEqual(build.call_count,3)
            get(1)
            self.assertEqual(build.call_count,3)
            get(2)
            self.assertEqual(build.call_count,4)
            get(2,2)
            self.assertEqual(build.call_count,5)
            self.assertLessEqual(views._document_cache_bytes,10)
            build.return_value=b'X'*11
            get(4);get(4)
            self.assertEqual(build.call_count,7)
            self.assertLessEqual(views._document_cache_bytes,10)


class DocumentConcurrentBuildTests(unittest.TestCase):
    def test_shared_build_and_failure_retry(self):
        from concurrent.futures import Future, ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from collections import OrderedDict
        from apps.finance import summary_views as views
        for fail in [False, True]:
            waiting, release = Event(), Event()
            class ObservedFuture(Future):
                def result(self, *args, **kwargs):
                    waiting.set()
                    return super().result(*args, **kwargs)
            def build(*args):
                assert release.wait(5)
                if fail:
                    raise ValueError('synthetic build failure')
                return b'1234'
            with patch.object(views, '_document_cache', OrderedDict()), patch.object(views, '_document_builds', {}), patch.object(views, '_document_cache_bytes', 0), patch.object(views, 'Future', ObservedFuture), patch.object(views, 'build_prepared_document', side_effect=build) as builder:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    one=pool.submit(views.prepared_document,'test','hash',(1,),(1,),True,1)
                    two=pool.submit(views.prepared_document,'test','hash',(1,),(1,),True,1)
                    try:
                        self.assertTrue(waiting.wait(5))
                    finally:
                        release.set()
                    for result in (one,two):
                        if fail:
                            with self.assertRaises(ValueError):result.result(timeout=5)
                        else:self.assertEqual(result.result(timeout=5),b'1234')
                self.assertEqual(builder.call_count,1)
                self.assertEqual(views._document_builds,{})
                builder.side_effect=None;builder.return_value=b'retry'
                self.assertEqual(views.prepared_document('test','hash',(1,),(1,),True,1), b'retry' if fail else b'1234')


class SinglePassToolsTests(unittest.TestCase):
    def test_scope_precedes_compaction_and_preserves_cross_month_inputs(self):
        from unittest.mock import patch
        from apps.finance import summary_database_document as doc
        quote={'rate':'2.00','input_id':42}
        facts=[{'source_id':'a','store_id':1,'store_code':'A','kind':'product_cost','date':'2026-09-01','amount':'-10','cost_conversion':{'quote':quote}},
               {'source_id':'b','store_id':1,'store_code':'A','kind':'advertising','date':'2026-10-01','amount':'-20'},
               {'source_id':'c','store_id':2,'store_code':'B','kind':'order_fee','amount':'-30'}]
        data={'database':{'facts':facts,'shares':{'order':[]},'rates':{'all_months':True},'raw_flows':[]},'allocations':{'unallocated':{}},'local_expenses':{'facts':[]}}
        source='<script id="snapshot">'+json.dumps(data)+'</script><script>const SNAPSHOT = typeof document === \'undefined\' ? globalThis.TEST_SNAPSHOT : JSON.parse(document.getElementById(\'snapshot\').textContent);\nfunction shops(){return [];}const FACTS=SNAPSHOT.database.facts;</script>// SAAS_DATABASE_ENTRIES'
        compact=doc.compact_tools_snapshot
        def check_scope(snapshot):
            self.assertEqual([f['store_id'] for f in snapshot['database']['facts']],[1,1])
            return compact(snapshot)
        with patch.object(doc,'compact_tools_snapshot',side_effect=check_scope):
            template,snapshot=doc.prepare_tools_document(source,1)
        self.assertEqual([f['date'] for f in snapshot['database']['facts']],['2026-09-01','2026-10-01'])
        self.assertEqual(snapshot['database']['rates'],{'all_months':True})
        self.assertEqual({row['store_id'] for row in snapshot['database']['settings_shops']},{1,2})
        self.assertNotIn('"amount"',template)
        self.assertIn('c.quote=SNAPSHOT.database.settings_quotes',template)
        self.assertIn('"schemas"',doc.pack_tools_document(template,snapshot))

    def test_legacy_snapshot_uses_existing_fallback(self):
        from apps.finance.summary_database_document import prepare_tools_document
        self.assertIsNone(prepare_tools_document('<script id="snapshot">{"legacy":true}</script>',1))


    def test_unknown_reader_keeps_fallback_and_cannot_emit_empty_snapshot(self):
        from apps.finance.summary_database_document import prepare_tools_document,pack_tools_document
        source='<script id="snapshot">{"database":{"facts":[]}}</script>// SAAS_DATABASE_ENTRIES'
        self.assertIsNone(prepare_tools_document(source,1))
        with self.assertRaises(ValueError):pack_tools_document(source,{'database':{'facts':[]}})
