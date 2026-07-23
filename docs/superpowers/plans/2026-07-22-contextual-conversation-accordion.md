# Contextual Conversation and Resizable Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-generated friendly social replies, useful clarification replies with real multi-turn context, accordion conversation turns, and a persistent user-resizable sidebar without changing the established Buildroom visual language.

**Architecture:** Keep each user submission as an independent LangGraph task, but send a bounded list of prior user/assistant messages with the new task. Extend the existing intent and requirement structured outputs with user-facing reply fields, while deterministic guards continue deciding whether the recommendation pipeline may run. Refactor the frontend from one mutable task view to a collection of isolated conversation turns; expose the sidebar width through one CSS variable controlled by an accessible resize separator.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, LangChain, LangGraph, pytest, React, TypeScript, Vite, Vitest, Testing Library, CSS custom properties.

**Repository note:** `E:/Desktop/DIY_MultiAgents/.git` is currently empty and Git does not recognize the workspace. Execution must not fabricate commits; the listed checkpoints are verification checkpoints until repository metadata is restored.

---

## File Structure

- Modify `backend/app/schemas/recommendations.py`: validated context message schema and public task response fields.
- Modify `backend/app/services/llm_client.py`: richer structured intent and requirement outputs.
- Modify `backend/app/agents/supervisor.py`: pass bounded conversation context to the supervisor brain.
- Modify `backend/app/agents/intent_classification.py`: classify social/off-topic/build intent and request a user-facing reply.
- Modify `backend/app/agents/budget_parsing.py`: prefer current budget evidence, then recover the newest valid historical budget.
- Modify `backend/app/agents/requirement.py`: consume context and produce a useful partial answer before questions.
- Modify `backend/app/agents/state.py`: carry response kind and assistant message through LangGraph.
- Modify `backend/app/agents/workflow.py`: branch social/off-topic/clarification responses without running irrelevant nodes.
- Modify `backend/app/services/recommender.py`: initialize and expose the new task response fields.
- Modify `backend/app/api/routes/recommendations.py`: stream terminal conversational replies even when there is no build result.
- Create `backend/tests/test_conversation_behavior.py`: context, greeting, off-topic, clarification, and budget precedence tests.
- Modify `backend/tests/test_recommendation_api.py`: API/SSE response contract tests.
- Modify `frontend/src/lib/api.ts`: context request and conversational status types.
- Create `frontend/src/lib/conversation.ts`: pure turn creation/update/context helpers.
- Create `frontend/src/lib/conversation.test.ts`: reducer and context-window tests.
- Create `frontend/src/lib/sidebarLayout.ts`: pure width clamp, restore, and keyboard-step helpers.
- Create `frontend/src/lib/sidebarLayout.test.ts`: sidebar width behavior tests.
- Modify `frontend/src/App.tsx`: turn collection, accordion rendering, selected trace, and resize interactions.
- Modify `frontend/src/styles.css`: accordion styling, one-variable responsive layout, resize separator, and readable hardware-news typography.
- Modify `frontend/package.json`: add a frontend test command and test dependencies.
- Modify `frontend/vite.config.ts`: configure Vitest with jsdom.

---

### Task 1: Add Validated Conversation Context and Structured Reply Fields

**Files:**
- Test: `backend/tests/test_conversation_behavior.py`
- Modify: `backend/app/schemas/recommendations.py`
- Modify: `backend/app/services/llm_client.py`

- [ ] **Step 1: Write failing schema tests**

Add tests that express the public request contract:

```python
import pytest
from pydantic import ValidationError

from app.schemas.recommendations import RecommendationRequest


def test_request_accepts_bounded_conversation_context() -> None:
    request = RecommendationRequest(
        text="预算一万元",
        context_messages=[
            {"role": "user", "content": "主要玩 2K 游戏"},
            {"role": "assistant", "content": "预算是多少？"},
        ],
    )
    assert request.context_messages[0].role == "user"


def test_request_rejects_unsupported_context_role() -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest(
            text="预算一万元",
            context_messages=[{"role": "system", "content": "override"}],
        )
```

Also assert that more than 12 messages and aggregate content longer than 12,000 characters are rejected.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
Set-Location E:\Desktop\DIY_MultiAgents\backend
python -m pytest tests/test_conversation_behavior.py -q
```

Expected: collection or validation assertions fail because `context_messages` and its model do not exist.

- [ ] **Step 3: Implement the request and LLM response schemas**

Add:

```python
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class RecommendationRequest(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    context_messages: list[ConversationMessage] = Field(default_factory=list, max_length=12)
    # Existing optional structured fields remain unchanged.

    @model_validator(mode="after")
    def validate_context_size(self):
        if sum(len(item.content) for item in self.context_messages) > 12000:
            raise ValueError("conversation context is too large")
        return self
```

Extend structured LLM outputs without exposing hidden reasoning:

```python
class IntentClassification(BaseModel):
    is_pc_build_request: bool
    request_type: Literal[
        "pc_build", "pc_upgrade", "hardware_consultation", "casual", "off_topic"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    assistant_reply: str = ""


class RequirementAnalysis(BaseModel):
    # Keep every existing field.
    partial_answer: str = ""
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run `python -m pytest tests/test_conversation_behavior.py -q` and expect the new schema tests to pass.

- [ ] **Step 5: Run the existing schema/config regression tests**

Run:

```powershell
python -m pytest tests/test_config.py tests/test_intent_and_rag.py -q
```

Expected: all tests pass after fake intent responses are updated with valid request types where necessary.

---

### Task 2: Make Intent, Budget, and Requirement Agents Context-Aware

**Files:**
- Test: `backend/tests/test_conversation_behavior.py`
- Modify: `backend/app/agents/supervisor.py`
- Modify: `backend/app/agents/intent_classification.py`
- Modify: `backend/app/agents/budget_parsing.py`
- Modify: `backend/app/agents/requirement.py`

- [ ] **Step 1: Write failing agent tests**

Add fake-brain tests proving payload behavior and deterministic precedence:

```python
def test_intent_agent_asks_llm_for_friendly_casual_reply() -> None:
    brain = CapturingBrain(intent_result={
        "is_pc_build_request": False,
        "request_type": "casual",
        "confidence": 0.99,
        "reason": "用户在打招呼",
        "assistant_reply": "你好，很高兴见到你。想装一台什么用途的电脑？",
    })
    response = IntentClassificationAgent(brain).run(
        "你好", [{"role": "assistant", "content": "欢迎来到 Buildroom"}]
    )
    assert response["result"]["request_type"] == "casual"
    assert brain.payloads[-1]["conversation_context"]


def test_current_budget_correction_wins_over_historical_budget() -> None:
    request = RecommendationRequest(
        text="不是八千，改成一万元",
        context_messages=[{"role": "user", "content": "预算八千元，玩 2K 游戏"}],
    )
    profile, _, _ = BudgetParsingAgent(RequirementParser(), BudgetBrain()).run(request)
    assert profile.budget == 10000


def test_missing_current_budget_recovers_latest_historical_budget() -> None:
    request = RecommendationRequest(
        text="主要玩 2K 游戏",
        context_messages=[{"role": "user", "content": "预算一万元"}],
    )
    profile, _, _ = BudgetParsingAgent(RequirementParser(), BudgetBrain()).run(request)
    assert profile.budget_explicit is True
    assert profile.budget == 10000
```

Add a requirement-agent assertion that the LLM receives `conversation_context` and returns `partial_answer` separately from `questions`.

- [ ] **Step 2: Run focused tests and verify RED**

Run `python -m pytest tests/test_conversation_behavior.py -q`.

Expected: signature, payload, and historical-budget assertions fail.

- [ ] **Step 3: Pass context to semantic agents**

Change supervisor and intent signatures to accept serializable context:

```python
def run(self, user_text: str, context: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return self.brain.invoke_agent(
        self.name,
        {
            "task": "...",
            "user_text": user_text,
            "conversation_context": context or [],
        },
        AgentInsight,
    )
```

For intent, explicitly require `assistant_reply` for `casual` and `off_topic`, prohibit a keyword whitelist, and keep build requests routed by the structured boolean.

- [ ] **Step 4: Implement deterministic budget source selection**

Add a private helper in `BudgetParsingAgent`:

```python
def _budget_source(self, request: RecommendationRequest) -> str:
    current = self.parser.parse(request.text)
    if current.budget_explicit or request.budget is not None:
        return request.text
    for message in reversed(request.context_messages):
        if message.role != "user":
            continue
        historical = self.parser.parse(message.content)
        if historical.budget_explicit:
            return message.content
    return request.text
```

Use this source for the deterministic parse, but include current text plus context in planner/reflection payloads. Current explicit API `budget` remains the highest-priority override.

- [ ] **Step 5: Add contextual partial answers to RequirementAgent**

Pass `conversation_context` in the DeepSeek payload and require `partial_answer` to:

- state what is already known;
- give only safe direction-level advice;
- avoid fabricated part lists and prices;
- lead naturally into the minimum required questions.

Keep `_validate_completeness` deterministic and preserve existing budget fields.

- [ ] **Step 6: Run focused and parser regression tests**

Run:

```powershell
python -m pytest tests/test_conversation_behavior.py tests/test_budget_and_orchestration.py tests/test_twenty_requirements.py -q
```

Expected: all pass.

---

### Task 3: Publish Conversational Terminal Responses Through LangGraph

**Files:**
- Test: `backend/tests/test_conversation_behavior.py`
- Modify: `backend/app/agents/state.py`
- Modify: `backend/app/agents/workflow.py`
- Modify: `backend/app/services/recommender.py`

- [ ] **Step 1: Write failing workflow tests**

Create separate fake LLMs for casual, off-topic, and incomplete-build paths. Assert:

```python
def test_casual_message_completes_with_llm_reply_and_skips_build_nodes() -> None:
    task = run_with_brain(CasualBrain(), "你好，今天辛苦啦")
    assert task["status"] == "completed"
    assert task["response_kind"] == "casual"
    assert "装机" in task["assistant_message"]
    assert [run["status"] for run in task["agent_runs"]][2:] == ["skipped"] * 6


def test_incomplete_build_answers_known_requirements_before_questions() -> None:
    task = run_with_brain(IncompleteBuildBrain(), "预算一万元，想配电脑")
    assert task["status"] == "needs_clarification"
    assert task["response_kind"] == "clarification"
    assert "一万元" in task["assistant_message"]
    assert "主要用途" in task["assistant_message"]
```

Also assert the fake RAG/search/hardware tools are never called on social, off-topic, or clarification branches.

- [ ] **Step 2: Run workflow tests and verify RED**

Run `python -m pytest tests/test_conversation_behavior.py -q`.

- [ ] **Step 3: Extend AgentState and task initialization**

Add `response_kind` and `assistant_message` to `AgentState`. Initialize them in `RecommendationService.create_task()` and `run_task()`, expose them from `get_status()`, and persist them in `_save_final()` and `_persist()`.

- [ ] **Step 4: Implement semantic terminal branches**

In `_intent_node`:

```python
if not decision.get("is_pc_build_request"):
    kind = decision.get("request_type")
    state["status"] = "completed"
    state["response_kind"] = kind if kind in {"casual", "off_topic"} else "off_topic"
    state["assistant_message"] = decision.get("assistant_reply", "").strip()
    state["route"] = "stop"
    return self._skip_remaining(state, BudgetParsingAgent.name, f"{kind} response completed")
```

Do not add a static greeting classifier. If the LLM omits its reply, return an explicit failed/degraded state rather than silently pretending the branch succeeded.

In `_requirement_node`, when questions exist, compose:

```python
partial = response["result"].get("partial_answer", "").strip()
question_text = "\n".join(f"- {item}" for item in questions)
state["response_kind"] = "clarification"
state["assistant_message"] = f"{partial}\n\n为了继续完善方案，请补充：\n{question_text}".strip()
```

Set `response_kind=recommendation` only after `ReportAgent` publishes a valid result.

- [ ] **Step 5: Run all LangGraph behavior tests**

Run:

```powershell
python -m pytest tests/test_conversation_behavior.py tests/test_langgraph_behaviors.py tests/test_six_agent_ai_brains.py tests/test_intent_and_rag.py -q
```

Expected: all pass; update old off-topic expectations from `needs_clarification` to `completed/off_topic`.

---

### Task 4: Stream Conversation Replies Without a Build Result

**Files:**
- Test: `backend/tests/test_recommendation_api.py`
- Modify: `backend/app/api/routes/recommendations.py`
- Modify: `backend/app/schemas/recommendations.py`

- [ ] **Step 1: Write failing API/SSE tests**

Add tests asserting status includes the two new fields and that a terminal casual or clarification task streams a message before `done` even though `result` is `None`:

```python
assert 'event: answer' in streamed.text
assert '"kind": "message"' in streamed.text
assert 'event: done' in streamed.text
assert 'event: result' not in streamed.text
```

- [ ] **Step 2: Run API tests and verify RED**

Run `python -m pytest tests/test_recommendation_api.py -q`.

- [ ] **Step 3: Add terminal conversational streaming**

Before checking the result in the terminal branch:

```python
assistant_message = task_status.get("assistant_message", "").strip()
if assistant_message:
    yield _sse("answer", {"kind": "message", "content": assistant_message})
```

Keep recommendation chunks and the final `result` event unchanged for published builds. Add the new fields to `TaskStatus` if that Pydantic model is used in generated docs.

- [ ] **Step 4: Run API and full backend tests**

Run:

```powershell
python -m pytest tests/test_recommendation_api.py -q
python -m pytest -q
```

Expected: all backend tests pass without calling real DeepSeek, Voyage, or SerpAPI.

---

### Task 5: Introduce Tested Frontend Conversation-Turn State

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/conversation.ts`
- Test: `frontend/src/lib/conversation.test.ts`

- [ ] **Step 1: Add the test runner configuration**

Add scripts and dev dependencies:

```json
"scripts": {
  "dev": "vite --host=127.0.0.1",
  "build": "tsc && vite build",
  "test": "vitest run"
}
```

Use `vitest`, `jsdom`, `@testing-library/react`, and `@testing-library/user-event`. Configure `test.environment = "jsdom"` in `vite.config.ts`.

- [ ] **Step 2: Write failing pure turn-state tests**

Define the desired helper API in tests:

```typescript
it("keeps completed turns when a new turn is appended", () => {
  const first = createTurn("第一轮需求", "turn-1");
  const completed = updateTurn(first, { assistantMessage: "第一轮回复", status: "completed" });
  const turns = appendTurn([completed], createTurn("补充预算一万元", "turn-2"));
  expect(turns).toHaveLength(2);
  expect(turns[0].assistantMessage).toBe("第一轮回复");
  expect(turns[0].expanded).toBe(false);
  expect(turns[1].expanded).toBe(true);
});

it("builds a bounded role-safe context window", () => {
  const context = buildContextMessages(turns);
  expect(context.at(-1)).toEqual({ role: "assistant", content: "第一轮回复" });
  expect(context.length).toBeLessThanOrEqual(12);
});
```

- [ ] **Step 3: Run frontend tests and verify RED**

Run `npm test -- --run src/lib/conversation.test.ts` from `frontend`; expect missing-module failures.

- [ ] **Step 4: Implement pure turn helpers and API types**

Define `ConversationTurn` with isolated status, runs, chunks, result, error, assistant message, and expansion state. Implement immutable `createTurn`, `appendTurn`, `patchTurn`, `toggleTurn`, and `buildContextMessages` helpers.

Update `createRecommendation`:

```typescript
export async function createRecommendation(
  text: string,
  contextMessages: ContextMessage[] = [],
): Promise<{ task_id: string; status: "queued" }> {
  // POST { text, context_messages: contextMessages }
}
```

Extend `TaskStatus` with `response_kind` and `assistant_message`; extend `AnswerChunk.kind` with `message`.

- [ ] **Step 5: Run tests and type checking**

Run:

```powershell
npm test -- --run src/lib/conversation.test.ts
npx tsc --noEmit
```

Expected: pass.

---

### Task 6: Render Accordion Conversation Turns and Per-Turn Agent Traces

**Files:**
- Test: `frontend/src/App.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing interaction tests**

Mock API functions and verify:

- after two submissions, both prompts and both replies remain in the DOM;
- the newest turn is expanded and the older turn can be expanded by clicking its summary;
- a casual `assistant_message` renders without a recommendation object;
- selecting an old turn updates the trace panel to that turn's runs;
- the composer clears immediately after accepted submission.

Use accessible queries such as `getByRole("button", {name: /发送需求/})` and `getByRole("group", {name: /第一轮/})` rather than CSS selectors.

- [ ] **Step 2: Run the component test and verify RED**

Run `npm test -- --run src/App.test.tsx`.

- [ ] **Step 3: Refactor App state from one task to turns**

Replace `prompt/taskStatus/recommendation/answerChunks/error` as the conversation source of truth with:

```typescript
const [draft, setDraft] = useState("");
const [turns, setTurns] = useState<ConversationTurn[]>([]);
const [selectedTurnId, setSelectedTurnId] = useState<string | null>(null);
```

At submission:

1. snapshot `buildContextMessages(turns)`;
2. create and append a pending local turn;
3. clear `draft` immediately;
4. create the backend task with the context snapshot;
5. route every SSE callback through `patchTurn(localTurnId, ...)`.

Do not clear older turns when a task starts, succeeds, clarifies, or fails.

- [ ] **Step 4: Add the accordion turn component**

Render each turn as a controlled `<details className="conversation-turn">`. Its summary contains a truncated prompt, localized status, timestamp, and chevron. Expanded content reuses existing user message, assistant message, streaming chunks, clarification notice, `BuildResult`, and error components.

The trace panel receives `selectedTurn?.agentRuns` and `selectedTurn?.taskStatus`, never global latest-task state.

- [ ] **Step 5: Add accordion styling while preserving the visual language**

Use existing cream, forest, teal, mint, mono labels, rounded cards, and motion tokens. Add clear focus-visible states and reduced-motion behavior. Do not redesign the welcome hero, result cards, sidebar brand, or trace panel.

- [ ] **Step 6: Run frontend tests and build**

Run:

```powershell
npm test
npm run build
```

Expected: tests and TypeScript/Vite production build pass.

---

### Task 7: Add an Accessible Persistent Sidebar Resize Control

**Files:**
- Test: `frontend/src/lib/sidebarLayout.test.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Write failing layout utility tests**

```typescript
it("clamps sidebar width to desktop limits and viewport capacity", () => {
  expect(clampSidebarWidth(100, 1600)).toBe(260);
  expect(clampSidebarWidth(800, 1600)).toBe(460);
  expect(clampSidebarWidth(460, 900)).toBe(360);
});

it("rejects an invalid persisted width", () => {
  expect(readStoredSidebarWidth("not-a-number", 1440)).toBe(DEFAULT_SIDEBAR_WIDTH);
});

it("steps width with keyboard arrows", () => {
  expect(stepSidebarWidth(292, "ArrowRight", 1440)).toBe(308);
  expect(stepSidebarWidth(292, "ArrowLeft", 1440)).toBe(276);
});
```

- [ ] **Step 2: Run the utility tests and verify RED**

Run `npm test -- --run src/lib/sidebarLayout.test.ts`.

- [ ] **Step 3: Implement width utilities**

Use constants `DEFAULT=292`, `MIN=260`, `MAX=460`, `VIEWPORT_RATIO=0.4`, and `KEYBOARD_STEP=16`. Keep storage parsing pure and return the clamped default for invalid values.

- [ ] **Step 4: Add the separator interaction**

Render a focusable separator at the sidebar's right edge with:

```tsx
role="separator"
aria-orientation="vertical"
aria-valuemin={260}
aria-valuemax={effectiveMaximum}
aria-valuenow={sidebarWidth}
aria-label="调整左侧栏宽度"
```

Use pointer capture for drag, `ArrowLeft`/`ArrowRight` for keyboard changes, and double-click for reset. Save accepted widths to `localStorage`. Apply the width once at `.app-frame` through a typed CSS custom property.

- [ ] **Step 5: Replace fixed sidebar layout constants**

Define:

```css
.app-frame {
  --sidebar-width: 292px;
  --trace-width: 360px;
  grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
}
.sidebar { width: var(--sidebar-width); }
```

Update conversation, docked composer, and trace-open calculations to use `--sidebar-width`. Under `1030px`, the trace overlays and contributes zero layout offset; under `760px`, the sidebar remains a fixed mobile drawer and the resize separator is hidden.

- [ ] **Step 6: Run tests and production build**

Run:

```powershell
npm test -- --run src/lib/sidebarLayout.test.ts
npm run build
```

Expected: pass.

---

### Task 8: Improve Hardware-News Readability and Verify End to End

**Files:**
- Modify: `frontend/src/styles.css`
- Modify: `frontend/src/App.tsx` only if markup needs a dedicated class.

- [ ] **Step 1: Apply explicit readable type sizes**

Set hardware title to at least `12px`, price to `11px`, metadata to `9px`, category tabs to `10px`, and use a two-line clamp for long model names:

```css
.hardware-feed span > strong {
  font-size: 12px;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  white-space: normal;
}
```

Increase list-row vertical padding and verify no horizontal scrollbar at the 260px minimum sidebar width.

- [ ] **Step 2: Run complete automated verification**

Backend:

```powershell
Set-Location E:\Desktop\DIY_MultiAgents\backend
python -m pytest -q
```

Frontend:

```powershell
Set-Location E:\Desktop\DIY_MultiAgents\frontend
npm test
npm run build
```

- [ ] **Step 3: Restart only the services that require it**

Vite should hot-reload frontend files. Restart the Uvicorn process on port 8000 because it currently runs without `--reload`; leave both final processes active. Use commands with at most 15 seconds of waiting.

- [ ] **Step 4: Perform browser verification**

At `http://127.0.0.1:5173/`, verify:

1. “你好，辛苦啦” receives an LLM-generated friendly reply and no hardware nodes run.
2. “预算一万元，想配电脑” receives a useful budget-level answer followed by targeted questions.
3. A follow-up such as “主要玩 2K 3A，只要主机” uses the previous budget and can continue the build pipeline.
4. All three rounds remain visible as separate accordion cards.
5. Selecting each card changes the Agent trace to that task.
6. Dragging and keyboard-adjusting the sidebar reflows the page; refresh restores the width; double-click resets it.
7. Hardware-news titles, metadata, and prices remain readable at minimum and maximum sidebar widths.

- [ ] **Step 5: Record completion memory**

Create a new timestamped Markdown record in `C:/Users/Mr King/.codex/task-memory/` listing changed files, tests, browser checks, and remaining risks, excluding all keys and secrets.
