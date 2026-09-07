from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.briefing_view import company_summary, refresh_feedback
from app.trend_feed_data import (save_company_briefs, build_company_intelligence,
                                 attach_previous_briefs, preserve_previous_briefs)
from rag_finance.llm.company_brief import generate_company_briefs
from rag_finance.profiles.company_profiles import load_all_company_profiles
from tests.test_company_brief import (_prepared, _model_payload, _client_with_payloads,
                                     _trends, _articles, _relevance, NOW)


class BriefResilienceTest(unittest.TestCase):
    def setUp(self):
        self.profiles = load_all_company_profiles()
        self.cid, self.other = sorted(self.profiles)[:2]
        self.settings = {('trend_01', self.cid): ('high', 'strong'),
                         ('trend_02', self.cid): ('high', 'strong'),
                         ('trend_03', self.cid): ('medium', 'limited'),
                         ('trend_01', self.other): ('high', 'strong')}
        *_, selected, _ = _prepared(self.profiles, self.settings)
        self.good = _model_payload(selected, self.profiles)

    def run_payloads(self, *payloads):
        client, calls = _client_with_payloads(*payloads)
        result = generate_company_briefs(_trends(), _relevance(self.profiles, self.settings),
                                         _articles(), profiles=self.profiles, client=client,
                                         sleep_fn=lambda _: None, now=NOW)
        return result, calls

    def test_bad_item_does_not_discard_sibling_company_brief_or_monitoring(self):
        bad = deepcopy(self.good)
        bad['companies'][0]['briefs'][1]['headline_ko'] = '길' * 50
        result, calls = self.run_payloads(bad, bad)
        self.assertEqual(len(calls.calls), 2)
        self.assertEqual(result['status'], 'PARTIAL')
        company = next(c for c in result['companies'] if c['company_id'] == self.cid)
        self.assertEqual([b['trend_id'] for b in company['briefs']], ['trend_01'])
        self.assertEqual(len(company['monitoring_items']), 1)
        self.assertEqual(len(next(c for c in result['companies'] if c['company_id'] == self.other)['briefs']), 1)
        # Retry schema scopes exactly one company and one failed trend.
        schema = json.dumps(calls.calls[1]['response_format'], ensure_ascii=False)
        self.assertIn('trend_02', schema)
        self.assertNotIn('trend_01', schema)
        self.assertNotIn(self.other, schema)
        call = result['brief_calls'][self.cid+'__trend_02']
        self.assertEqual(call['attempts'][-1]['error_code'], 'length_limit')
        self.assertIn('headline_ko', call['error_message'])

    def test_repair_only_failed_item_and_restore_complete_result(self):
        bad = deepcopy(self.good)
        bad['companies'][0]['briefs'][1]['watch_next'] = ['하나만 있음']
        result, calls = self.run_payloads(bad, self.good)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual(len(calls.calls), 2)
        self.assertEqual(len(result['brief_calls'][self.other+'__trend_01']['attempts']), 1)
        self.assertEqual(len(result['brief_calls'][self.cid+'__trend_02']['attempts']), 2)

    def test_content_violation_is_not_silently_rewritten(self):
        bad = deepcopy(self.good)
        bad['companies'][0]['briefs'][0]['company_relevance_ko'] = '매출이 확정적으로 증가한다.'
        result, _ = self.run_payloads(bad, bad)
        call = result['brief_calls'][self.cid+'__trend_01']
        self.assertEqual(call['status'], 'failed')
        self.assertEqual(call['attempts'][-1]['error_code'], 'unsupported_assertion')
        self.assertNotIn('매출이 확정적으로', json.dumps(result, ensure_ascii=False))

    def test_output_truncation_increases_only_retry_budget(self):
        responses = iter(['length', 'stop', 'stop', 'stop'])
        calls = []
        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=next(responses),
                message=SimpleNamespace(content=json.dumps(self.good, ensure_ascii=False)))])
        result = generate_company_briefs(_trends(), _relevance(self.profiles, self.settings),
            _articles(), profiles=self.profiles,
            client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
            sleep_fn=lambda _: None, now=NOW)
        self.assertEqual(result['status'], 'GENERATED')
        self.assertEqual([c['max_completion_tokens'] for c in calls], [4000, 8000, 8000, 8000])

    def test_previous_evidence_is_self_contained_and_not_added_to_current_counts(self):
        success, _ = self.run_payloads(self.good)
        failure = deepcopy(success)
        failure['status'] = 'PARTIAL'
        failure['generated_at'] = (NOW + timedelta(hours=1)).isoformat()
        target = next(c for c in failure['companies'] if c['company_id'] == self.cid)
        target.update(briefs=[], generation_status='PARTIAL', failed_briefs=['trend_01', 'trend_02'])
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            save_company_briefs(success, live_dir=directory, articles=_articles())
            save_company_briefs(failure, live_dir=directory, articles=[])
            view = build_company_intelligence(failure, [], trends_generated_at=failure['source_trends_generated_at'])
            attach_previous_briefs(view, directory)
        company = next(c for c in view['companies'] if c['company_id'] == self.cid)
        self.assertEqual(company['briefs'], [])
        self.assertEqual(len(company['monitoring_items']), 1)
        old = company['previous_success']
        self.assertEqual(old['generated_at'], success['generated_at'])
        self.assertTrue(old['company']['briefs'][0]['evidence_articles'])
        self.assertIn('생성 미완료', company_summary(company))

    def test_successful_empty_company_clears_stale_fallback(self):
        result, _ = self.run_payloads(self.good)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            save_company_briefs(result, live_dir=directory, articles=_articles())
            view=build_company_intelligence(result, _articles(), trends_generated_at=result['source_trends_generated_at'])
            attach_previous_briefs(view, directory)
        self.assertTrue(all('previous_success' not in c for c in view['companies']))

    def test_missing_key_still_returns_monitoring(self):
        with patch.dict('os.environ', {}, clear=True):
            result = generate_company_briefs(_trends(), _relevance(self.profiles, self.settings),
                _articles(), profiles=self.profiles, now=NOW)
        self.assertEqual(result['status'], 'PARTIAL')
        company = next(c for c in result['companies'] if c['company_id'] == self.cid)
        self.assertEqual(len(company['monitoring_items']), 1)
        self.assertEqual(company['briefs'], [])

    def test_refresh_persists_partial_items_diagnostics_and_reload(self):
        from scripts import refresh_trend_feed as runner
        from app.trend_feed_data import load_trend_feed
        from tests.test_refresh_trend_feed import _debug
        bad = deepcopy(self.good)
        bad['companies'][0]['briefs'][1]['headline_ko'] = '길' * 50
        partial, _ = self.run_payloads(bad, bad)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict('os.environ', {'OPENAI_API_KEY': 'test-key'}), \
             patch.object(runner, 'load_env_file'), \
             patch.object(runner, 'collect_articles', return_value=(_articles(), _debug())), \
             patch.object(runner, 'cluster_trends', return_value=_trends()), \
             patch.object(runner, 'classify_company_relevance', return_value=_relevance(self.profiles, self.settings)), \
             patch.object(runner, 'generate_company_briefs', return_value=partial):
            directory = Path(tmp)
            report = runner.refresh(live_dir=directory)
            saved = json.loads((directory/'latest_refresh.json').read_text(encoding='utf-8'))
            loaded = load_trend_feed(live_path=directory/'latest_trends.json')
        self.assertEqual(report['outcome'], 'partial')
        self.assertEqual(saved['brief_status'], 'PARTIAL')
        self.assertEqual(saved['main_briefs'], 2)
        self.assertEqual(saved['monitoring_items'], 1)
        self.assertIn('headline_ko', refresh_feedback(saved)['message'])
        company = next(c for c in loaded['company_intelligence']['companies'] if c['company_id'] == self.cid)
        self.assertEqual(len(company['briefs']), 1)
        self.assertEqual(company['generation_status'], 'PARTIAL')

    def test_existing_success_is_archived_before_new_collection(self):
        result, _ = self.run_payloads(self.good)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/'latest_company_briefs.json').write_text(json.dumps(result), encoding='utf-8')
            trends={**_trends(), 'articles': _articles()}
            (directory/'latest_trends.json').write_text(json.dumps(trends), encoding='utf-8')
            preserve_previous_briefs(directory)
            cache=json.loads((directory/'latest_company_briefs_success.json').read_text(encoding='utf-8'))
        snapshot=cache['companies'][self.cid][0]
        self.assertTrue(snapshot['company']['briefs'][0]['evidence_articles'])
