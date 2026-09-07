import json
import tempfile
import unittest
from pathlib import Path

from app.briefing_view import prepare_view, refresh_feedback
from app.trend_feed_data import save_refresh_status
from rag_finance.llm.company_relevance import classify_company_relevance, validation_reason
from rag_finance.profiles.company_profiles import load_all_company_profiles
from tests.test_company_relevance import _articles, _trends, _company_payload, _client_with_payloads, NOW


class RelevanceDiagnosticsTest(unittest.TestCase):
    def test_failed_attempts_explain_the_rule_without_echoing_model_values(self):
        profiles = load_all_company_profiles()
        ids = sorted(profiles)
        invalid = _company_payload(profiles, ids[0])
        invalid['evaluations'][0]['business_tags'] = ['SECRET-model-output']
        client, _ = _client_with_payloads(invalid, invalid, *[_company_payload(profiles, cid) for cid in ids[1:]])
        result = classify_company_relevance(_trends(), _articles(), profiles=profiles, client=client, sleep_fn=lambda _: None, now=NOW)
        self.assertEqual(result['status'], 'PARTIAL')
        failure = result['relevance_calls'][ids[0]]
        self.assertIn('업무 태그', failure['error_message'])
        self.assertIn('평가 항목 1', failure['error_message'])
        self.assertEqual(len(failure['attempt_details']), 2)
        self.assertNotIn('SECRET', json.dumps(result, ensure_ascii=False))
        self.assertEqual(len(result['evaluations']), 6)

    def test_recovered_company_keeps_attempt_history_but_no_terminal_error(self):
        profiles = load_all_company_profiles()
        ids = sorted(profiles)
        client, _ = _client_with_payloads({'evaluations': []}, *[_company_payload(profiles, cid) for cid in ids])
        result = classify_company_relevance(_trends(), _articles(), profiles=profiles, client=client, sleep_fn=lambda _: None, now=NOW)
        call = result['relevance_calls'][ids[0]]
        self.assertEqual(result['status'], 'CLASSIFIED')
        self.assertNotIn('error_message', call)
        self.assertEqual([a['outcome'] for a in call['attempt_details']], ['validation_error', 'success'])

    def test_safe_reasons_distinguish_empty_truncated_and_conditional_output(self):
        self.assertIn('빈 응답', validation_reason(ValueError('Model returned no content')))
        self.assertIn('토큰 한도', validation_reason(ValueError('Model returned no content'), finish_reason='length'))
        self.assertIn('조건부', validation_reason(ValueError('Evaluation #2 must describe company relevance conditionally when the company is absent from its evidence')))
        self.assertNotIn('SECRET', validation_reason(ValueError('SECRET unexpected private content')))

    def test_reasons_survive_save_reload_and_partial_wording_is_correct(self):
        report = {'outcome': 'partial', 'stage': 'relevance', 'relevance_status': 'PARTIAL',
                  'message': '관련성은 UNCLASSIFIED로 기록했습니다.',
                  'relevance_calls': {'hanwha_life': {'status': 'failed', 'error_message': '평가 항목 2 · 조건부 표현이 없습니다.'}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = save_refresh_status(report, live_dir=Path(tmp))
            saved = json.loads(path.read_text(encoding='utf-8'))
        immediate = refresh_feedback(report)['message']
        reloaded = prepare_view({'refresh': saved})['refresh_message']
        for message in (immediate, reloaded):
            self.assertIn('한화생명: 평가 항목 2', message)
            self.assertNotIn('UNCLASSIFIED', message)
            self.assertIn('일부 완료', message)
