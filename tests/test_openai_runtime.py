import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from openai import OpenAI

from rag_finance.llm.openai_runtime import (
    create_client, resolve_api_key, completion_options, DEFAULT_MODEL,
)
from rag_finance.llm.grounding import uses_indirect_language
from rag_finance.llm.trend_clusterer import cluster_trends, TrendClusteringError
from rag_finance.llm.company_relevance import classify_company_relevance
from rag_finance.llm.company_brief import generate_company_briefs
from rag_finance.profiles.company_profiles import load_all_company_profiles
from tests.test_trend_clusterer import _articles as trend_articles, _payload as trend_payload
from tests.test_company_relevance import (
    _articles, _trends, _company_payload, NOW,
)
from tests.test_company_brief import (
    _prepared, _model_payload, _relevance, _articles as brief_articles,
    _trends as brief_trends,
)


class OpenAIRuntimeTest(unittest.TestCase):
    def test_environment_model_and_reasoning_override_and_cli_priority(self):
        from scripts.refresh_trend_feed import _effective_llm_settings
        with patch.dict(os.environ, {'OPENAI_MODEL': 'gpt-5.5', 'OPENAI_REASONING_EFFORT': 'low'}):
            settings = _effective_llm_settings('missing-config.json')
            self.assertEqual(settings['model'], 'gpt-5.5')
            self.assertEqual(settings['reasoning_effort'], 'low')
            self.assertEqual(settings['relevance_reasoning_effort'], 'low')
            self.assertEqual(_effective_llm_settings('missing-config.json', 'gpt-5.4-mini')['model'], 'gpt-5.4-mini')
        with patch.dict(os.environ, {'OPENAI_REASONING_EFFORT': 'invalid'}):
            with self.assertRaises(ValueError):
                _effective_llm_settings('missing-config.json')

    def test_call_records_are_isolated_and_include_usage(self):
        from rag_finance.llm.openai_runtime import complete, isolated_run, run_calls
        from types import SimpleNamespace
        response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15))
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: response)))
        @isolated_run
        def run():
            self.assertEqual(run_calls(), [])
            complete(client, stage='briefs', model='gpt-5.5', reasoning_effort='none', max_completion_tokens=4000)
            return run_calls()
        for _ in range(2):
            records = run()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['usage']['total_tokens'], 15)
            self.assertGreaterEqual(records[0]['elapsed_seconds'], 0)
        self.assertEqual(run_calls(), [])

    def client(self, handler):
        client = OpenAI(api_key="test-key", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(client.close)
        return client

    def response(self, payload, finish="stop"):
        return httpx.Response(200, json={"id": "test-completion", "object": "chat.completion",
            "created": 1, "model": DEFAULT_MODEL,
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": json.dumps(payload)}}]})

    def test_real_sdk_sends_openai_contract_and_parses_trends(self):
        sent = []
        articles = trend_articles()
        def handle(request):
            self.assertEqual(str(request.url), "https://api.openai.com/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer test-key")
            body = json.loads(request.content)
            sent.append(body)
            self.assertNotIn("max_tokens", body)
            self.assertEqual(body["reasoning_effort"], "none")
            self.assertFalse(body["store"])
            self.assertTrue(body["response_format"]["json_schema"]["strict"])
            return self.response(trend_payload(articles))
        result = cluster_trends(articles, client=self.client(handle))
        self.assertEqual(result["model"], DEFAULT_MODEL)
        self.assertEqual(len(sent), 1)

    def test_real_sdk_relevance_and_brief_preserve_expected_output(self):
        profiles = load_all_company_profiles()
        calls = []
        def relevance_handler(request):
            body = json.loads(request.content)
            cid = body['response_format']['json_schema']['schema']['properties']['evaluations']['items']['properties']['company_id']['enum'][0]
            calls.append(cid)
            payload = _company_payload(profiles, cid)
            # A legitimate polite modal previously rejected by the keyword rule.
            for i, item in enumerate(payload['evaluations']):
                item['reason_ko'] = f'{cid}의 사업 {i}에 영향을 줄 수 있습니다.'
                item['transmission_path_ko'] = '제도 변화 → 상품 구성에 영향을 줄 수 있습니다.'
            return self.response(payload)
        result = classify_company_relevance(_trends(), _articles(), profiles=profiles,
            client=self.client(relevance_handler), now=NOW)
        self.assertEqual(result['status'], 'CLASSIFIED')
        self.assertEqual(len(calls), 3)
        cid = sorted(profiles)[0]
        settings = {('trend_01', cid): ('high', 'strong')}
        _, _, _, context, selected, monitoring = _prepared(profiles, settings)
        payload = _model_payload(selected, profiles)
        result = generate_company_briefs(brief_trends(), _relevance(profiles, settings),
            brief_articles(), profiles=profiles, now=NOW,
            client=self.client(lambda request: self.response(payload)))
        self.assertEqual(result['status'], 'GENERATED')

    def test_auth_and_quota_do_not_retry_or_expose_api_body(self):
        for status, code, expected in [(401, 'invalid_api_key', '인증'),
                                       (429, 'insufficient_quota', '잔액')]:
            calls = []
            def handle(request):
                calls.append(request)
                return httpx.Response(status, json={'error': {
                    'message': 'secret-response-do-not-log', 'type': code, 'code': code}})
            with self.subTest(status=status), self.assertRaises(TrendClusteringError) as caught:
                cluster_trends(trend_articles(), client=self.client(handle), sleep_fn=lambda _: None)
            self.assertEqual(len(calls), 1)
            self.assertIn(expected, str(caught.exception))
            self.assertNotIn('secret-response', json.dumps(caught.exception.diagnostics))

    def test_truncated_trends_get_more_output_budget(self):
        calls = []
        def handle(request):
            calls.append(json.loads(request.content))
            return self.response(trend_payload(trend_articles()), 'length' if len(calls) == 1 else 'stop')
        cluster_trends(trend_articles(), client=self.client(handle))
        self.assertEqual([c['max_completion_tokens'] for c in calls], [2600, 5200])

    def test_client_disables_sdk_retries_and_uses_official_endpoint(self):
        client = create_client('test-key')
        self.addCleanup(client.close)
        self.assertEqual(client.max_retries, 0)
        self.assertEqual(client.timeout, 45.0)
        self.assertEqual(str(client.base_url), 'https://api.openai.com/v1/')

    def test_credentials_env_precedes_server_secrets(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ' env-key '}), \
             patch('streamlit.runtime.exists', return_value=True), \
             patch('streamlit.secrets', {'OPENAI_API_KEY': 'secret-key'}):
            self.assertEqual(resolve_api_key(), 'env-key')
            self.assertEqual(resolve_api_key(' explicit '), 'explicit')
            self.assertEqual(resolve_api_key(''), '')

    def test_streamlit_secrets_only_works(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), \
             patch('streamlit.runtime.exists', return_value=True), \
             patch('streamlit.secrets', {'OPENAI_API_KEY': 'secret-key'}):
            self.assertEqual(resolve_api_key(), 'secret-key')

    def test_dotenv_load_preserves_server_key(self):
        from scripts.refresh_trend_feed import load_env_file
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'.env'
            path.write_text('OPENAI_API_KEY=local-key\n', encoding='utf-8')
            with patch.dict(os.environ, {}, clear=True):
                load_env_file(path)
                self.assertEqual(resolve_api_key(), 'local-key')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'server-key'}):
                load_env_file(path)
                self.assertEqual(resolve_api_key(), 'server-key')

    def test_reasoning_runs_omit_sampling_options(self):
        options = completion_options(model=DEFAULT_MODEL, max_tokens=2000,
                                     reasoning_effort='low', temperature=0.1)
        self.assertNotIn('temperature', options)
        self.assertEqual(options['reasoning_effort'], 'low')

    def test_modal_variants_pass_but_bare_company_actions_do_not(self):
        for text in ['영향을 줄 수 있습니다.', '영향을 줄수있습니다.',
                     '검토할 여지가 있다.', '영향을 줄 수 있는 변화다.']:
            self.assertTrue(uses_indirect_language(text), text)
        for text in ['한화생명이 상품을 출시했다.', '매출이 확정적으로 증가한다.']:
            self.assertFalse(uses_indirect_language(text), text)
