"""Shared, explicit wording contract for indirect company interpretations.

This is a wording check, not a factual entailment detector. Evidence IDs and
company actions must still pass the independent grounding checks.
"""
import re

INDIRECT_LANGUAGE_MARKERS = (
    "가능성", "수 있다", "수 있음", "검토", "기회", "위험", "요인",
    "관찰", "점검", "영향을 받을", "연결될", "전이될", "간접",
    "수 있습니다", "수 있어", "수 있는", "수 있을", "여지가", "여지는",
)

CONDITIONAL_GUIDANCE = (
    "근거에 회사가 직접 등장하지 않으면 회사의 실제 행동으로 서술하지 마라. "
    "관련성 설명과 영향 설명 각각에 '가능성', '할 수 있다', '검토가 필요하다'처럼 "
    "조건부임이 명확한 표현을 사용하라. "
    "예: '업계의 토큰증권 제도 변화는 해당 회사의 상품 검토에 영향을 줄 수 있다.' "
    "금지 예: '해당 회사가 토큰증권 상품을 출시했다.' "
    "조건부 단어를 덧붙여 근거 없는 행동이나 숫자를 정당화하지 마라."
)


def uses_indirect_language(value: str) -> bool:
    normalized = re.sub(r"\s+", "", value).casefold()
    return any(re.sub(r"\s+", "", marker) in normalized
               for marker in INDIRECT_LANGUAGE_MARKERS)
