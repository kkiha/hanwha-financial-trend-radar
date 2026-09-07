from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from app.evidence_labels import label_event_reports
from app.briefing_view import prepare_view
from rag_finance.llm.trend_clusterer import validate_trend_payload, build_trend_response_format, build_cluster_messages
from tests.test_trend_clusterer import _articles, _payload


class DisplayMetadataTest(unittest.TestCase):
    def articles(self):
        return [dict(title=t, published_at='2026-09-07T09:00:00+00:00', source=str(i))
                for i, t in enumerate([
                    "한화투자증권 '중개형 ISA 투자 시작' 이벤트 실시",
                    '한화투자증권, 중개형 ISA 이벤트…신규 개설·이전 고객 최대 100만원',
                    '다른증권, 중개형 ISA 이벤트 실시',
                ])]

    def test_same_event_hint_without_removing_articles(self):
        articles = self.articles()
        label_event_reports(articles)
        self.assertEqual(articles[0]['event_label'], articles[1]['event_label'])
        self.assertNotIn('event_label', articles[2])
        self.assertEqual(len(articles), 3)

    def test_separate_dates_and_conflicting_amounts_not_grouped(self):
        for mode in ('date', 'amount'):
            articles = self.articles()[:2]
            if mode == 'date':
                articles[1]['published_at'] = '2026-09-01T09:00:00+00:00'
            else:
                articles[0]['title'] += ' 200만원'
            label_event_reports(articles)
            self.assertTrue(all('event_label' not in a for a in articles))

    def test_view_annotations_do_not_mutate_metrics_or_original(self):
        original = {'trends': [{'articles': self.articles(), 'source_count': 3}],
                    'company_intelligence': {'companies': []}}
        before = deepcopy(original)
        view = prepare_view(original)
        self.assertEqual(original, before)
        self.assertEqual(view['trends'][0]['source_count'], 3)
        self.assertIn('event_label', view['trends'][0]['articles'][0])

    def test_model_timestamp_ignored_and_removed_from_contract(self):
        articles = _articles()
        now = datetime(2026, 9, 8, 1, 2, 3, tzinfo=timezone.utc)
        for supplied in ('1900-01-01T00:00:00Z', '2099-01-01T00:00:00Z', None):
            payload = _payload(articles)
            payload['generated_at'] = supplied
            with patch('rag_finance.llm.trend_clusterer.datetime') as clock:
                clock.now.return_value = now
                result = validate_trend_payload(payload, articles)
            self.assertEqual(result['generated_at'], now.isoformat())
        schema = build_trend_response_format(articles)['json_schema']['schema']
        self.assertNotIn('generated_at', schema['properties'])
        self.assertNotIn('generated_at', schema['required'])
        self.assertNotIn('generated_at', build_cluster_messages(articles, window_days=7)[1]['content'])
