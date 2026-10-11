"""Deterministic evaluation fixture suite for claim/evidence verification archetypes.

Documented Invariant:
Offline mock tests verify system behavior, lifecycle integrity, and schema compliance,
but do not prove real-world factual accuracy of external models.
"""

import pytest
from typing import Dict, Any, List
from models.schemas import Verdict, EvidenceRelationship
from services.claim_assessor import validate_model_assessment


BENCHMARK_CASES: List[Dict[str, Any]] = [
    {
        "name": "directly_supported",
        "description": "Passage directly and sufficiently supports the material substance of the claim.",
        "claim": "Mercury orbits the Sun in approximately 88 Earth days.",
        "evidence": [
            {
                "id": "ev-mercury-1",
                "excerpt": "Mercury is the fastest planet in our solar system, completing one orbit around the Sun in about 87.97 Earth days.",
            }
        ],
        "expected_verdict": Verdict.SUPPORTED.value,
        "expected_relationship": EvidenceRelationship.SUPPORTS.value,
    },
    {
        "name": "directly_contradicted",
        "description": "Passage explicitly contradicts the material factual assertion of the claim.",
        "claim": "Mount Everest is located entirely within Switzerland.",
        "evidence": [
            {
                "id": "ev-everest-1",
                "excerpt": "Mount Everest is situated in the Himalayas, straddling the border between Nepal and China.",
            }
        ],
        "expected_verdict": Verdict.CONTRADICTED.value,
        "expected_relationship": EvidenceRelationship.CONTRADICTS.value,
    },
    {
        "name": "topic_match_unestablished",
        "description": "Passage discusses the topic (Nobel Prize, Curie) but does not establish the specific assertion.",
        "claim": "Marie Curie won the Nobel Prize in Physics for discovering polonium in 1903.",
        "evidence": [
            {
                "id": "ev-curie-1",
                "excerpt": "Marie Curie won the 1903 Nobel Prize in Physics for research on radiation phenomena.",
            }
        ],
        "expected_verdict": Verdict.INSUFFICIENTLY_SUPPORTED.value,
        "expected_relationship": EvidenceRelationship.IRRELEVANT.value,
    },
    {
        "name": "silent_source",
        "description": "Passage is completely silent on the claim proposition.",
        "claim": "The speed of light in vacuum is approximately 300,000 km/s.",
        "evidence": [
            {
                "id": "ev-sound-1",
                "excerpt": "The speed of sound in dry air at 20°C is approximately 343 meters per second.",
            }
        ],
        "expected_verdict": Verdict.INSUFFICIENTLY_SUPPORTED.value,
        "expected_relationship": EvidenceRelationship.IRRELEVANT.value,
    },
    {
        "name": "conflicting_sources",
        "description": "Two supplied reference passages conflict on the factual value.",
        "claim": "The Battle of Hastings commenced in the morning at 9:00 AM.",
        "evidence": [
            {
                "id": "ev-hastings-1",
                "excerpt": "William of Poitiers writes that the battle commenced at 9:00 AM.",
            },
            {
                "id": "ev-hastings-2",
                "excerpt": "Alternative chronicles assert that combat did not commence until after midday.",
            },
        ],
        "expected_verdict": Verdict.AMBIGUOUS.value,
        "expected_relationship": EvidenceRelationship.CONFLICTING.value,
    },
    {
        "name": "compound_partial_support",
        "description": "Passage supports one part of a compound claim while refuting another part.",
        "claim": "Mars has two moons and possesses vast oceans of liquid surface water.",
        "evidence": [
            {
                "id": "ev-mars-1",
                "excerpt": "Mars has two moons, Phobos and Deimos. The surface is completely arid with no liquid surface water.",
            }
        ],
        "expected_verdict": Verdict.INSUFFICIENTLY_SUPPORTED.value,
        "expected_relationship": EvidenceRelationship.PARTIALLY_SUPPORTS.value,
    },
]


@pytest.mark.parametrize("case", BENCHMARK_CASES, ids=lambda c: c["name"])
def test_evaluation_benchmark_fixture(case):
    """Verify that structured outputs for each benchmark archetype validate against system rules."""
    valid_ids = {ev["id"] for ev in case["evidence"]}

    assessments = [
        {
            "evidence_id": ev["id"],
            "relationship": case["expected_relationship"],
            "explanation": f"Evaluation of {ev['id']} in archetype {case['name']}",
        }
        for ev in case["evidence"]
    ]

    simulated_result = {
        "verdict": case["expected_verdict"],
        "reasoning": f"Structured benchmark reasoning for {case['name']}.",
        "evidence_assessments": assessments,
        "limitations": ["Archetype evaluation note."],
    }

    validated = validate_model_assessment(simulated_result, valid_ids)
    assert validated["verdict"] == case["expected_verdict"]
    assert len(validated["evidence_assessments"]) == len(case["evidence"])
    for a in validated["evidence_assessments"]:
        assert a["relationship"] == case["expected_relationship"]
