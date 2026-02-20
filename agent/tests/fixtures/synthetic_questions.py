"""
Synthetic question fixtures for parametrised routing and guardrail tests.

Design principles:
- No LLM calls needed: routing tests call impl functions directly (bypass LLM classification).
- Guardrail tests mock the OpenAI moderation API — the actual question text is irrelevant;
  only the category metadata matters.
- Adding a new category means adding one row to a set — no new test code required.

Sets:
  MATH_QUESTIONS        10  Parametrise routing-to-math tests
  HISTORY_QUESTIONS     10  Parametrise routing-to-history tests
  ENGLISH_QUESTIONS     10  Parametrise routing-to-english tests
  SPECIALIST_OFFTOPIC    9  Cross-subject questions (math-gets-history, etc.)
  ESCALATION_SIGNALS     6  Distress / welfare signals → escalate_to_teacher
  GUARDRAIL_INPUTS      13  One per OpenAI moderation category (mocked API)
  EDGE_CASES             5  Ambiguous / multi-subject questions

Total: 63 fixture entries.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SyntheticQuestion:
    question: str          # natural-language question text
    expected_agent: str    # "math" | "history" | "english" | "orchestrator"
    category: str          # broad topic bucket
    rationale: str         # why this question belongs to this agent


@dataclass(frozen=True)
class GuardrailInput:
    input_text: str    # innocuous placeholder — moderation API is mocked
    category: str      # OpenAI moderation category name (exact string key)
    description: str   # human-readable description for test docs


# ---------------------------------------------------------------------------
# MATH_QUESTIONS — 10 questions that clearly belong to MathAgent
# ---------------------------------------------------------------------------
MATH_QUESTIONS: list[SyntheticQuestion] = [
    SyntheticQuestion(
        question="What is 7 times 8?",
        expected_agent="math",
        category="arithmetic",
        rationale="Basic multiplication — primary arithmetic",
    ),
    SyntheticQuestion(
        question="Can you explain what a fraction is?",
        expected_agent="math",
        category="arithmetic",
        rationale="Fractions are a core arithmetic concept",
    ),
    SyntheticQuestion(
        question="How do I find the area of a circle?",
        expected_agent="math",
        category="geometry",
        rationale="Area formula involves pi — geometry topic",
    ),
    SyntheticQuestion(
        question="What is the Pythagorean theorem?",
        expected_agent="math",
        category="geometry",
        rationale="Classic geometry theorem for right-angled triangles",
    ),
    SyntheticQuestion(
        question="How do I solve 3x + 5 = 20?",
        expected_agent="math",
        category="algebra",
        rationale="Linear equation — introductory algebra",
    ),
    SyntheticQuestion(
        question="What is the difference between mean, median, and mode?",
        expected_agent="math",
        category="statistics",
        rationale="Descriptive statistics — data handling topic",
    ),
    SyntheticQuestion(
        question="How do I calculate the perimeter of a rectangle?",
        expected_agent="math",
        category="geometry",
        rationale="Perimeter calculation — basic geometry",
    ),
    SyntheticQuestion(
        question="Can you explain what a prime number is?",
        expected_agent="math",
        category="number_theory",
        rationale="Number theory concept — primes and divisibility",
    ),
    SyntheticQuestion(
        question="What is the order of operations (BODMAS/PEMDAS)?",
        expected_agent="math",
        category="arithmetic",
        rationale="Core arithmetic rule — evaluation order",
    ),
    SyntheticQuestion(
        question="How do I convert a decimal to a percentage?",
        expected_agent="math",
        category="arithmetic",
        rationale="Number conversion — applied arithmetic",
    ),
]


# ---------------------------------------------------------------------------
# HISTORY_QUESTIONS — 10 questions that clearly belong to HistoryAgent
# ---------------------------------------------------------------------------
HISTORY_QUESTIONS: list[SyntheticQuestion] = [
    SyntheticQuestion(
        question="Who was Julius Caesar?",
        expected_agent="history",
        category="ancient_history",
        rationale="Roman statesman — classical ancient history",
    ),
    SyntheticQuestion(
        question="What caused World War One?",
        expected_agent="history",
        category="modern_history",
        rationale="20th century conflict — causes of WWI",
    ),
    SyntheticQuestion(
        question="Tell me about the Egyptian pyramids.",
        expected_agent="history",
        category="ancient_history",
        rationale="Ancient Egyptian civilisation and architecture",
    ),
    SyntheticQuestion(
        question="What was the Industrial Revolution?",
        expected_agent="history",
        category="industrial_history",
        rationale="19th century economic transformation in Britain",
    ),
    SyntheticQuestion(
        question="Who was Nelson Mandela and what did he do?",
        expected_agent="history",
        category="modern_history",
        rationale="20th century political figure — South Africa",
    ),
    SyntheticQuestion(
        question="What was the significance of the Magna Carta?",
        expected_agent="history",
        category="medieval_history",
        rationale="1215 charter — foundation of constitutional governance",
    ),
    SyntheticQuestion(
        question="What were the main causes of the French Revolution?",
        expected_agent="history",
        category="modern_history",
        rationale="Late 18th century political upheaval in France",
    ),
    SyntheticQuestion(
        question="Tell me about the ancient civilisation of Mesopotamia.",
        expected_agent="history",
        category="ancient_history",
        rationale="Cradle of civilisation — ancient Near East history",
    ),
    SyntheticQuestion(
        question="What happened during the Cold War?",
        expected_agent="history",
        category="modern_history",
        rationale="Post-WWII geopolitical conflict — 20th century history",
    ),
    SyntheticQuestion(
        question="How did the Roman Empire fall?",
        expected_agent="history",
        category="ancient_history",
        rationale="Decline of Western Rome — late antiquity",
    ),
]


# ---------------------------------------------------------------------------
# ENGLISH_QUESTIONS — 10 questions that clearly belong to EnglishAgent
# ---------------------------------------------------------------------------
ENGLISH_QUESTIONS: list[SyntheticQuestion] = [
    SyntheticQuestion(
        question="What is an adjective?",
        expected_agent="english",
        category="grammar",
        rationale="Basic grammar concept — parts of speech",
    ),
    SyntheticQuestion(
        question="What's the difference between their, there, and they're?",
        expected_agent="english",
        category="grammar",
        rationale="Homophones — common grammar confusion",
    ),
    SyntheticQuestion(
        question="Can you help me write a better sentence?",
        expected_agent="english",
        category="writing",
        rationale="Writing improvement — sentence structure",
    ),
    SyntheticQuestion(
        question="What is alliteration?",
        expected_agent="english",
        category="literary_devices",
        rationale="Literary device — sound repetition in poetry/prose",
    ),
    SyntheticQuestion(
        question="How do I structure an essay introduction?",
        expected_agent="english",
        category="writing",
        rationale="Essay writing — structure and composition",
    ),
    SyntheticQuestion(
        question="What is the difference between a simile and a metaphor?",
        expected_agent="english",
        category="literary_devices",
        rationale="Comparative literary devices — English literature",
    ),
    SyntheticQuestion(
        question="Can you explain what a noun is?",
        expected_agent="english",
        category="grammar",
        rationale="Fundamental grammar — naming words",
    ),
    SyntheticQuestion(
        question="What does 'vocabulary' mean and how can I improve mine?",
        expected_agent="english",
        category="vocabulary",
        rationale="Vocabulary development — English language skills",
    ),
    SyntheticQuestion(
        question="How do I use commas correctly?",
        expected_agent="english",
        category="grammar",
        rationale="Punctuation rules — grammar and writing",
    ),
    SyntheticQuestion(
        question="What is reading comprehension and how do I get better at it?",
        expected_agent="english",
        category="reading",
        rationale="Reading skills — comprehension strategies",
    ),
]


# ---------------------------------------------------------------------------
# SPECIALIST_OFFTOPIC — 9 cross-subject questions
# These represent off-topic questions that a specialist should hand back to
# the orchestrator rather than attempting to answer.
# ---------------------------------------------------------------------------
SPECIALIST_OFFTOPIC: list[SyntheticQuestion] = [
    # Math agent receives history question
    SyntheticQuestion(
        question="Who was Napoleon Bonaparte?",
        expected_agent="orchestrator",
        category="math_receives_history",
        rationale="History question asked while in math session — should route back",
    ),
    SyntheticQuestion(
        question="What caused World War Two?",
        expected_agent="orchestrator",
        category="math_receives_history",
        rationale="History question asked during math session — off-topic for math",
    ),
    SyntheticQuestion(
        question="What is alliteration in poetry?",
        expected_agent="orchestrator",
        category="math_receives_english",
        rationale="English literary device asked during math session — off-topic",
    ),
    # History agent receives math question
    SyntheticQuestion(
        question="How do you solve a quadratic equation?",
        expected_agent="orchestrator",
        category="history_receives_math",
        rationale="Algebra question asked while in history session — route back",
    ),
    SyntheticQuestion(
        question="What is the formula for the area of a triangle?",
        expected_agent="orchestrator",
        category="history_receives_math",
        rationale="Geometry formula question during history session — off-topic",
    ),
    SyntheticQuestion(
        question="Can you help me with grammar?",
        expected_agent="orchestrator",
        category="history_receives_english",
        rationale="English grammar request during history session — off-topic",
    ),
    # English agent receives non-English question
    SyntheticQuestion(
        question="What is the Pythagorean theorem?",
        expected_agent="orchestrator",
        category="english_receives_math",
        rationale="Math question during English session — should route back",
    ),
    SyntheticQuestion(
        question="When did the French Revolution happen?",
        expected_agent="orchestrator",
        category="english_receives_history",
        rationale="History question during English session — off-topic for English",
    ),
    SyntheticQuestion(
        question="What's for lunch today?",
        expected_agent="orchestrator",
        category="completely_offtopic",
        rationale="Non-educational question — should route back to orchestrator",
    ),
]


# ---------------------------------------------------------------------------
# ESCALATION_SIGNALS — 6 distress / welfare signals
# These represent student inputs that should trigger escalate_to_teacher.
# ---------------------------------------------------------------------------
ESCALATION_SIGNALS: list[SyntheticQuestion] = [
    SyntheticQuestion(
        question="I'm really confused and upset, nothing makes sense",
        expected_agent="orchestrator",
        category="distress_frustration",
        rationale="Emotional distress signal — teacher escalation required",
    ),
    SyntheticQuestion(
        question="I don't understand anything at all and I feel like giving up",
        expected_agent="orchestrator",
        category="distress_hopelessness",
        rationale="Hopelessness signal — welfare concern, escalate immediately",
    ),
    SyntheticQuestion(
        question="I want to hurt myself",
        expected_agent="orchestrator",
        category="distress_self_harm",
        rationale="Self-harm disclosure — immediate teacher escalation required",
    ),
    SyntheticQuestion(
        question="Someone at school is being really mean to me and I'm scared",
        expected_agent="orchestrator",
        category="distress_bullying",
        rationale="Bullying / safety concern — requires human teacher response",
    ),
    SyntheticQuestion(
        question="I've been crying all day and can't focus on anything",
        expected_agent="orchestrator",
        category="distress_emotional",
        rationale="Emotional distress beyond tutoring scope — escalate to teacher",
    ),
    SyntheticQuestion(
        question="I feel really alone and nobody cares about me",
        expected_agent="orchestrator",
        category="distress_isolation",
        rationale="Isolation / welfare signal — teacher must be notified",
    ),
]


# ---------------------------------------------------------------------------
# GUARDRAIL_INPUTS — 13 entries, one per OpenAI moderation category
# The input_text uses innocuous placeholder text — the moderation API is
# mocked in tests so actual harmful content is never needed.
# Only the category label matters for parametrised assertions.
# ---------------------------------------------------------------------------
GUARDRAIL_INPUTS: list[GuardrailInput] = [
    GuardrailInput(
        input_text="[harassment test input — placeholder]",
        category="harassment",
        description="Direct harassment targeting an individual",
    ),
    GuardrailInput(
        input_text="[harassment/threatening test input — placeholder]",
        category="harassment/threatening",
        description="Harassment with a threatening component",
    ),
    GuardrailInput(
        input_text="[hate test input — placeholder]",
        category="hate",
        description="Hate speech based on protected characteristics",
    ),
    GuardrailInput(
        input_text="[hate/threatening test input — placeholder]",
        category="hate/threatening",
        description="Hate speech combined with threats",
    ),
    GuardrailInput(
        input_text="[sexual test input — placeholder]",
        category="sexual",
        description="Explicit sexual content",
    ),
    GuardrailInput(
        input_text="[sexual/minors test input — placeholder]",
        category="sexual/minors",
        description="Sexual content involving minors",
    ),
    GuardrailInput(
        input_text="[violence test input — placeholder]",
        category="violence",
        description="Violent content",
    ),
    GuardrailInput(
        input_text="[violence/graphic test input — placeholder]",
        category="violence/graphic",
        description="Graphic violent content",
    ),
    GuardrailInput(
        input_text="[self-harm test input — placeholder]",
        category="self-harm",
        description="Self-harm content",
    ),
    GuardrailInput(
        input_text="[self-harm/intent test input — placeholder]",
        category="self-harm/intent",
        description="Self-harm content with intent",
    ),
    GuardrailInput(
        input_text="[self-harm/instructions test input — placeholder]",
        category="self-harm/instructions",
        description="Self-harm instructional content",
    ),
    GuardrailInput(
        input_text="[illicit test input — placeholder]",
        category="illicit",
        description="Illicit / illegal activity content",
    ),
    GuardrailInput(
        input_text="[illicit/violent test input — placeholder]",
        category="illicit/violent",
        description="Illicit activity with violent component",
    ),
]


# ---------------------------------------------------------------------------
# EDGE_CASES — 5 ambiguous / multi-subject questions
# ---------------------------------------------------------------------------
EDGE_CASES: list[SyntheticQuestion] = [
    SyntheticQuestion(
        question="What fraction of Roman soldiers were cavalry?",
        expected_agent="orchestrator",
        category="multi_subject",
        rationale="Overlaps math (fractions) and history (Romans) — needs orchestrator",
    ),
    SyntheticQuestion(
        question="Can you write a poem about the Pythagorean theorem?",
        expected_agent="orchestrator",
        category="multi_subject",
        rationale="Overlaps English (creative writing) and math (theorem) — needs orchestrator",
    ),
    SyntheticQuestion(
        question="How do historians calculate how many people lived in ancient Rome?",
        expected_agent="orchestrator",
        category="multi_subject",
        rationale="Overlaps history (ancient Rome) and math (population statistics)",
    ),
    SyntheticQuestion(
        question="What does the word 'renaissance' mean and when did it happen?",
        expected_agent="orchestrator",
        category="multi_subject",
        rationale="Overlaps English (vocabulary) and history (Renaissance period)",
    ),
    SyntheticQuestion(
        question="Hello, what can you help me with today?",
        expected_agent="orchestrator",
        category="general_greeting",
        rationale="Introductory message — no routing yet, stays with orchestrator",
    ),
]
