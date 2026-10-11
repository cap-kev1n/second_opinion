"""Version-controlled synthetic evaluation dataset for Second Opinion Phase 5.

Contains 20 curated synthetic fixtures covering all required evaluation categories:
1. Direct support
2. Direct contradiction
3. Partial support of compound claims
4. Irrelevant evidence (topic mismatch)
5. Conflicting sources
6. Paraphrased evidence with low lexical overlap
7. Numeric claims and unit differences
8. Dates, populations, and conditions changing meaning
9. Missing qualifiers or overgeneralization
10. Compound claims where only one proposition is supported
11. Evidence split across paragraph or chunk boundaries
12. No relevant evidence in supplied sources (negative fixture)
13. Relevant and irrelevant passages mixed together
14. Multiple sources with distinct titles and locations
15. Reconciled conditions versus genuine conflict
"""

from typing import List, Optional
from pydantic import BaseModel, Field

DATASET_VERSION = "1.0.0"


class SourceFixture(BaseModel):
    """Synthetic reference source for evaluation."""
    id: str
    title: str
    content: str


class EvaluationFixture(BaseModel):
    """An evaluation test fixture containing sources, claim, expected retrieval and verdict."""
    id: str
    category: str
    sources: List[SourceFixture]
    claim_text: str
    normalized_text: str
    expected_verdict: str  # supported, contradicted, insufficiently_supported, ambiguous
    expected_evidence_substrings: List[str] = Field(
        default_factory=list,
        description="Key substrings in sources that indicate relevant evidence was successfully retrieved."
    )
    expected_relationship: str  # supports, contradicts, partially_supports, irrelevant, conflicting
    explanation: str
    notes: Optional[str] = None


EVALUATION_DATASET: List[EvaluationFixture] = [
    # 1. Direct support
    EvaluationFixture(
        id="fx-01-direct-support",
        category="direct_support",
        sources=[
            SourceFixture(
                id="src-01",
                title="Spaceflight Chronicle",
                content=(
                    "The James Webb Space Telescope was successfully launched on December 25, 2021, "
                    "from the Guiana Space Centre aboard an Ariane 5 rocket. The mission is an international "
                    "collaboration between NASA, ESA, and CSA."
                ),
            )
        ],
        claim_text="The James Webb Space Telescope was launched on December 25, 2021 aboard an Ariane 5 rocket.",
        normalized_text="The James Webb Space Telescope launched on December 25, 2021 on an Ariane 5 rocket.",
        expected_verdict="supported",
        expected_evidence_substrings=["launched on December 25, 2021", "Ariane 5 rocket"],
        expected_relationship="supports",
        explanation="The source text directly and explicitly confirms the launch date and launch vehicle.",
    ),

    # 2. Direct contradiction
    EvaluationFixture(
        id="fx-02-direct-contradiction",
        category="direct_contradiction",
        sources=[
            SourceFixture(
                id="src-02",
                title="Planetary Astronomy Handbook",
                content=(
                    "Mars has only two natural satellites, Phobos and Deimos, both discovered by American "
                    "astronomer Asaph Hall in August 1877. Both are irregularly shaped rocky bodies with low masses."
                ),
            )
        ],
        claim_text="Mars has four natural satellites discovered in 1877.",
        normalized_text="Mars possesses four natural moons discovered in 1877.",
        expected_verdict="contradicted",
        expected_evidence_substrings=["Mars has only two natural satellites"],
        expected_relationship="contradicts",
        explanation="The source explicitly states that Mars has only two natural satellites, directly contradicting four.",
    ),

    # 3. Partial support of compound claim
    EvaluationFixture(
        id="fx-03-partial-support",
        category="partial_support",
        sources=[
            SourceFixture(
                id="src-03",
                title="History of Medicine",
                content=(
                    "Alexander Fleming observed antibacterial properties in penicillium mold at St Mary's Hospital "
                    "in London in 1928. However, Fleming did not have the chemical resources to isolate or mass-produce "
                    "the substance himself."
                ),
            )
        ],
        claim_text="Alexander Fleming discovered penicillin in 1928 and established industrial manufacturing plants.",
        normalized_text="Alexander Fleming discovered penicillin in 1928 and built industrial production facilities.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=["Alexander Fleming observed antibacterial properties in penicillium mold", "1928"],
        expected_relationship="partially_supports",
        explanation="The source confirms the discovery in 1928, but explicitly disconfirms industrial manufacturing by Fleming.",
        notes="Evaluates handling of compound claim where only the initial proposition is supported.",
    ),

    # 4. Irrelevant evidence (topic match but unestablished)
    EvaluationFixture(
        id="fx-04-irrelevant-evidence",
        category="irrelevant_evidence",
        sources=[
            SourceFixture(
                id="src-04",
                title="Geographical Survey of Oceans",
                content=(
                    "The Pacific Ocean is the largest and deepest of Earth's oceanic divisions, encompassing "
                    "an area of over 165 million square kilometers and containing the Mariana Trench."
                ),
            )
        ],
        claim_text="Mount Everest reaches an elevation of 8,848.86 meters above sea level.",
        normalized_text="Mount Everest has an elevation of 8,848.86 meters.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=[],
        expected_relationship="irrelevant",
        explanation="The reference material describes oceans; it contains no information regarding Mount Everest.",
        notes="Evaluates correct abstention when candidate evidence is completely unrelated.",
    ),

    # 5. Conflicting sources
    EvaluationFixture(
        id="fx-05-conflicting-sources",
        category="conflicting_sources",
        sources=[
            SourceFixture(
                id="src-05a",
                title="Archaeological Field Report A",
                content="Carbon dating of timber recovered from the northern tower establishes construction in 1340 CE.",
            ),
            SourceFixture(
                id="src-05b",
                title="Municipal Archive Records B",
                content="Official charter logs indicate municipal construction of the northern tower commenced in 1415 CE.",
            ),
        ],
        claim_text="The northern tower was constructed in 1340 CE.",
        normalized_text="The northern tower was built in 1340 CE.",
        expected_verdict="ambiguous",
        expected_evidence_substrings=["construction in 1340 CE", "commenced in 1415 CE"],
        expected_relationship="conflicting",
        explanation="Source A specifies 1340 CE while Source B specifies 1415 CE. The genuine conflict cannot be resolved from supplied text.",
        notes="Genuine source conflict requires ambiguous verdict.",
    ),

    # 6. Paraphrased evidence with low lexical overlap
    EvaluationFixture(
        id="fx-06-paraphrased-low-overlap",
        category="paraphrased_evidence_low_lexical_overlap",
        sources=[
            SourceFixture(
                id="src-06",
                title="Solar Terrestrial Physics",
                content=(
                    "Intense geomagnetic disturbances from coronal mass ejections precipitated voltage collapse "
                    "and prolonged blackouts across high-latitude electrical transmission networks."
                ),
            )
        ],
        claim_text="Space weather provoked electrical grid infrastructure disruptions.",
        normalized_text="Space weather caused power grid failures.",
        expected_verdict="supported",
        expected_evidence_substrings=["geomagnetic disturbances", "prolonged blackouts"],
        expected_relationship="supports",
        explanation="The source text conceptually confirms power failures from space weather, but uses non-identical terminology ('coronal mass ejections' vs 'space weather').",
        notes="Stress-tests lexical retrieval limits versus semantic verification.",
    ),

    # 7. Numeric claims and unit differences
    EvaluationFixture(
        id="fx-07-numeric-unit-difference",
        category="numeric_claims_and_units",
        sources=[
            SourceFixture(
                id="src-07",
                title="Civil Engineering Survey",
                content="The suspension span across the estuary measures exactly 1,500 meters in total deck length.",
            )
        ],
        claim_text="The bridge suspension span measures 1,500 miles in total length.",
        normalized_text="The suspension span measures 1500 miles.",
        expected_verdict="contradicted",
        expected_evidence_substrings=["measures exactly 1,500 meters"],
        expected_relationship="contradicts",
        explanation="The source specifies 1,500 meters, which contradicts the claim's unit of 1,500 miles.",
        notes="Unit mismatches must not be treated as supported merely because numeric token 1500 matches.",
    ),

    # 8. Dates, populations, and conditions changing meaning
    EvaluationFixture(
        id="fx-08-condition-population-difference",
        category="dates_populations_conditions",
        sources=[
            SourceFixture(
                id="src-08",
                title="Clinical Pharmacology Bulletin",
                content=(
                    "In a multicenter trial of pediatric asthma patients under 12 years of age, the inhaled formulation "
                    "demonstrated an 88 percent reduction in acute exacerbations during the 2022 testing window."
                ),
            )
        ],
        claim_text="The drug demonstrates an 88 percent reduction in acute asthma exacerbations across all patient demographics.",
        normalized_text="The drug achieves an 88 percent reduction in asthma exacerbations across all populations.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=["pediatric asthma patients under 12 years of age", "88 percent reduction"],
        expected_relationship="partially_supports",
        explanation="The source proves efficacy only for pediatric patients under 12, not across all demographics.",
        notes="Evaluates qualifier preservation: pediatric cohort != universal population.",
    ),

    # 9. Missing qualifiers or overgeneralization
    EvaluationFixture(
        id="fx-09-missing-qualifiers",
        category="missing_qualifiers_overgeneralization",
        sources=[
            SourceFixture(
                id="src-09",
                title="Nutritional Science Journal",
                content=(
                    "Under laboratory conditions, moderate daily dietary polyphenol intake may sometimes contribute "
                    "to modest improvements in arterial elasticity in certain adult cohorts."
                ),
            )
        ],
        claim_text="Polyphenol intake always cures arterial disease in all humans.",
        normalized_text="Polyphenols invariably cure arterial disease.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=["may sometimes contribute to modest improvements"],
        expected_relationship="partially_supports",
        explanation="The source uses cautious qualifiers ('may sometimes contribute', 'modest improvements'), which disallows the unconditional claim 'always cures'.",
    ),

    # 10. Compound claims with one supported proposition
    EvaluationFixture(
        id="fx-10-compound-one-supported",
        category="compound_claims",
        sources=[
            SourceFixture(
                id="src-10",
                title="Apollo Program Archives",
                content=(
                    "Apollo 11 astronaut Neil Armstrong stepped onto the lunar surface at 02:56 UTC on July 21, 1969, "
                    "becoming the first human to walk on the Moon."
                ),
            )
        ],
        claim_text="Neil Armstrong walked on the Moon in July 1969 and also piloted the first mission to Mars in 1975.",
        normalized_text="Neil Armstrong walked on the Moon in July 1969 and piloted a Mars mission in 1975.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=["Neil Armstrong stepped onto the lunar surface", "July 21, 1969"],
        expected_relationship="partially_supports",
        explanation="The moon landing is confirmed, but the claim's second assertion (Mars piloting) is unmentioned and unsubstantiated.",
    ),

    # 11. Evidence split across chunk/paragraph boundary
    EvaluationFixture(
        id="fx-11-split-across-boundary",
        category="evidence_split_across_boundary",
        sources=[
            SourceFixture(
                id="src-11",
                title="Polar Atmospheric Research Memo",
                content=(
                    "Project Borealis deployed high-altitude balloon telemetry packages from Kiruna, Sweden throughout October 2023.\n\n"
                    "The onboard spectrophotometer telemetry confirmed a localized stratospheric ozone recovery of 7.2 percent."
                ),
            )
        ],
        claim_text="Project Borealis measured a 7.2 percent stratospheric ozone recovery over Kiruna.",
        normalized_text="Project Borealis recorded a 7.2 percent ozone recovery in Kiruna.",
        expected_verdict="supported",
        expected_evidence_substrings=["Project Borealis", "7.2 percent"],
        expected_relationship="supports",
        explanation="The context is split across two distinct paragraphs, requiring cohesive lexical retrieval across the boundary.",
    ),

    # 12. No relevant evidence in supplied sources (negative test)
    EvaluationFixture(
        id="fx-12-no-relevant-evidence",
        category="no_relevant_evidence",
        sources=[
            SourceFixture(
                id="src-12",
                title="Baking Artisan Bread",
                content=(
                    "To achieve an open crumb in sourdough bread, maintain hydration between 75 and 80 percent, "
                    "perform gentle coil folds every thirty minutes, and bake in a preheated Dutch oven at 230 degrees Celsius."
                ),
            )
        ],
        claim_text="Quantum computers utilize superconducting transmon qubits cooled to millikelvin temperatures.",
        normalized_text="Quantum computers use superconducting qubits at millikelvin temperatures.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=[],
        expected_relationship="irrelevant",
        explanation="No passage relates to quantum computing. Must cleanly return 0 passages and insufficiently_supported without LLM call.",
    ),

    # 13. Relevant and irrelevant passages mixed together
    EvaluationFixture(
        id="fx-13-mixed-relevant-irrelevant",
        category="mixed_passages",
        sources=[
            SourceFixture(
                id="src-13",
                title="Global Industry Review 2021",
                content=(
                    "Section 1: Commercial aviation passenger volumes contracted significantly in early 2020.\n\n"
                    "Section 2: The global automotive sector suffered an estimated production shortfall of 4.5 million vehicles "
                    "in 2021 due to acute semiconductor microchip supply chain bottlenecks.\n\n"
                    "Section 3: Commercial real estate occupancy rates exhibited regional divergence throughout Europe."
                ),
            )
        ],
        claim_text="The automotive sector experienced production shortfalls of 4.5 million vehicles in 2021 due to semiconductor shortages.",
        normalized_text="Automotive production lost 4.5 million vehicles in 2021 from microchip shortages.",
        expected_verdict="supported",
        expected_evidence_substrings=["shortfall of 4.5 million vehicles in 2021 due to acute semiconductor"],
        expected_relationship="supports",
        explanation="The retriever must successfully isolate Section 2 from the distractor sections 1 and 3.",
    ),

    # 14. Multiple sources with distinct titles and locations
    EvaluationFixture(
        id="fx-14-multiple-sources",
        category="multiple_sources",
        sources=[
            SourceFixture(
                id="src-14a",
                title="Aviation Metallurgy Journal",
                content="Titanium-aluminide alloys are selected for low-pressure turbine blades due to high specific strength at 700C.",
            ),
            SourceFixture(
                id="src-14b",
                title="Turbine Propulsion Systems",
                content="Single-crystal nickel superalloys remain standard for high-pressure turbine combustor liners.",
            ),
        ],
        claim_text="Titanium-aluminide alloys are utilized in low-pressure turbine blades.",
        normalized_text="Titanium-aluminide alloys are used in low-pressure turbine blades.",
        expected_verdict="supported",
        expected_evidence_substrings=["Titanium-aluminide alloys are selected for low-pressure turbine blades"],
        expected_relationship="supports",
        explanation="The system must attribute the passage to Aviation Metallurgy Journal, not Turbine Propulsion Systems.",
    ),

    # 15. Reconciled conditions versus genuine source conflict
    EvaluationFixture(
        id="fx-15-reconciled-conditions",
        category="reconciled_conditions_not_conflicting",
        sources=[
            SourceFixture(
                id="src-15a",
                title="Solar Facility Summer Operational Report",
                content="During the clear summer peak in July, the photovoltaic array produced a daily average of 420 megawatt-hours.",
            ),
            SourceFixture(
                id="src-15b",
                title="Solar Facility Winter Operational Report",
                content="During December overcast conditions, the photovoltaic array produced a daily average of 110 megawatt-hours.",
            ),
        ],
        claim_text="The photovoltaic array produced an average of 420 megawatt-hours during summer peak operations in July.",
        normalized_text="The solar array generated 420 MWh daily during July summer peaks.",
        expected_verdict="supported",
        expected_evidence_substrings=["clear summer peak in July", "daily average of 420 megawatt-hours"],
        expected_relationship="supports",
        explanation="Source A and Source B report differing figures for different seasons (summer vs winter). This is NOT a conflict for the July claim.",
        notes="Demonstrates distinguishing contextual condition differences from genuine factual contradiction.",
    ),

    # 16. Multiple supporting passages independently validating claim
    EvaluationFixture(
        id="fx-16-multiple-supporting-passages",
        category="direct_support",
        sources=[
            SourceFixture(
                id="src-16",
                title="Seismological Survey Records",
                content=(
                    "The Valdivia earthquake struck southern Chile on May 22, 1960. It registered a moment magnitude of 9.5, "
                    "making it the most powerful earthquake ever instrumentally recorded. Tsunami waves crossed the Pacific Basin."
                ),
            )
        ],
        claim_text="The 1960 Valdivia earthquake registered a moment magnitude of 9.5.",
        normalized_text="The 1960 Valdivia earthquake had a moment magnitude of 9.5.",
        expected_verdict="supported",
        expected_evidence_substrings=["Valdivia earthquake", "magnitude of 9.5"],
        expected_relationship="supports",
        explanation="The source directly confirms the date, location, and 9.5 moment magnitude.",
    ),

    # 17. Direct contradiction with explicit disconfirmation
    EvaluationFixture(
        id="fx-17-contradiction-explicit",
        category="direct_contradiction",
        sources=[
            SourceFixture(
                id="src-17",
                title="Geological Society Monograph",
                content="Diamond is composed purely of carbon atoms arranged in a crystal lattice; it contains no silica.",
            )
        ],
        claim_text="Diamonds are formed primarily from silicon dioxide crystals.",
        normalized_text="Diamonds are composed of silicon dioxide.",
        expected_verdict="contradicted",
        expected_evidence_substrings=["Diamond is composed purely of carbon atoms", "contains no silica"],
        expected_relationship="contradicts",
        explanation="The source explicitly disconfirms silicon dioxide by stating diamond is purely carbon and contains no silica.",
    ),

    # 18. Boundary test: claim mentions date outside source scope
    EvaluationFixture(
        id="fx-18-date-mismatch-unsupported",
        category="dates_populations_conditions",
        sources=[
            SourceFixture(
                id="src-18",
                title="Metropolitan Transit Authority Report",
                content="The automated subway signaling system operated without unscheduled interruptions throughout the calendar year 2018.",
            )
        ],
        claim_text="The automated subway signaling system operated without interruption in 2024.",
        normalized_text="The subway signaling system had zero interruptions in 2024.",
        expected_verdict="insufficiently_supported",
        expected_evidence_substrings=["operated without unscheduled interruptions throughout the calendar year 2018"],
        expected_relationship="partially_supports",
        explanation="The source only documents performance in 2018, providing no evidence for the year 2024.",
    ),

    # 19. Irrelevant distractor passages in distinct documents
    EvaluationFixture(
        id="fx-19-distinct-distractor-documents",
        category="mixed_passages",
        sources=[
            SourceFixture(
                id="src-19a",
                title="Botanical Taxonomy",
                content="Quercus robur, the English oak, is native to most of Europe west of the Caucasus mountains.",
            ),
            SourceFixture(
                id="src-19b",
                title="Semiconductor Physics",
                content="Silicon carbide power MOSFETs operate with lower conduction losses and higher thermal conductivity than silicon.",
            ),
        ],
        claim_text="Silicon carbide power MOSFETs achieve lower conduction losses compared to silicon devices.",
        normalized_text="Silicon carbide MOSFETs have lower conduction losses than silicon.",
        expected_verdict="supported",
        expected_evidence_substrings=["Silicon carbide power MOSFETs operate with lower conduction losses"],
        expected_relationship="supports",
        explanation="Retrieval must isolate Source B and discard botanical Source A.",
    ),

    # 20. Paraphrase with partial synonym overlap
    EvaluationFixture(
        id="fx-20-paraphrase-synonym-overlap",
        category="paraphrased_evidence_low_lexical_overlap",
        sources=[
            SourceFixture(
                id="src-20",
                title="Atmospheric Chemistry Letters",
                content="Chlorofluorocarbons release active chlorine radicals upon photolysis, catalytically degrading stratospheric ozone molecules.",
            )
        ],
        claim_text="CFC emissions cause the destruction of the ozone layer.",
        normalized_text="CFC emissions destroy stratospheric ozone.",
        expected_verdict="supported",
        expected_evidence_substrings=["Chlorofluorocarbons release active chlorine radicals", "degrading stratospheric ozone"],
        expected_relationship="supports",
        explanation="CFCs are defined as Chlorofluorocarbons; 'catalytically degrading' maps to 'destroy'. Tests lexical match on 'ozone'.",
    ),
]
