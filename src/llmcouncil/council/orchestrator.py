"""Council orchestrator — LangGraph state machine for the fixed deliberation protocol.

Fixed protocol: Propose → Critique → (check termination) → [Revise]* → Vote → Synthesize
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, TypedDict
import operator

from langgraph.graph import StateGraph, END

from llmcouncil.config import AppConfig
from llmcouncil.council.llm_adapter import LLMResponse, call_seat
from llmcouncil.council.synthesizer import render_verdict
from llmcouncil.council.voting import VotePayload, simple_majority, straw_poll_unanimous


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class CouncilState(TypedDict):
    session_id: str
    query: str
    seats: list[dict[str, Any]]      # serialized SeatConfigs
    max_rounds: int
    include_minority: bool
    voting_mechanism: str
    # Annotated[list, operator.add] → nodes return partial lists; LangGraph appends them.
    drafts: Annotated[list[str], operator.add]
    critiques: Annotated[list[list[str]], operator.add]   # one list of texts per round
    transcript: Annotated[list[dict[str, Any]], operator.add]
    votes: Annotated[list[dict[str, Any]], operator.add]
    verdict_text: str
    minority_text: str | None
    terminated_by: str
    error: str | None
    route_decision: str              # "continue" | "vote" — read by the conditional edge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seat(seats: list[dict[str, Any]], role: str) -> dict[str, Any]:
    return next(s for s in seats if s["role"] == role)


def _seats_by_role(seats: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    return [s for s in seats if s["role"] == role]


def _draft_label(idx: int) -> str:
    return f"draft_{idx}"


def _parse_vote(text: str, valid_labels: list[str]) -> dict[str, Any]:
    m = re.search(r"\{[^}]+\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group())
            choice = obj.get("choice", valid_labels[-1])
            if choice not in valid_labels:
                choice = valid_labels[-1]
            return {
                "choice": choice,
                "confidence": float(obj.get("confidence", 0.7)),
                "rationale": str(obj.get("rationale", "")),
                "concerns": list(obj.get("concerns", [])),
            }
        except (json.JSONDecodeError, ValueError):
            pass
    # Fallback: pick the first label mentioned in the text.
    for label in reversed(valid_labels):
        if label in text:
            return {"choice": label, "confidence": 0.7, "rationale": text[:200], "concerns": []}
    return {"choice": valid_labels[-1], "confidence": 0.5, "rationale": "parse error", "concerns": []}


def _make_entry(
    session_id: str,
    round_: int,
    seat_id: int,
    kind: str,
    content: str,
    resp: LLMResponse | None = None,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "round": round_,
        "seat_id": seat_id,
        "kind": kind,
        "content_json": json.dumps({"text": content}),
        "tokens_in": resp.tokens_in if resp else 0,
        "tokens_out": resp.tokens_out if resp else 0,
        "usd": resp.usd if resp else 0.0,
        "latency_ms": resp.latency_ms if resp else 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

async def propose_node(state: CouncilState) -> dict[str, Any]:
    seat = _seat(state["seats"], "proposer")
    round_idx = len(state["drafts"])  # 0 = initial draft; 1+ = revision

    if round_idx == 0:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are the Proposer in an LLM Council deliberation. "
                    "Draft a comprehensive answer to the user's query. "
                    "End your response with exactly:\nCONFIDENCE: 0.XX\nRATIONALE: <one sentence>"
                ),
            },
            {"role": "user", "content": state["query"]},
        ]
    else:
        prev_draft = state["drafts"][-1]
        last_critiques = state["critiques"][-1] if state["critiques"] else []
        critiques_text = "\n\n".join(
            f"Critic {i + 1}:\n{c}" for i, c in enumerate(last_critiques)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the Proposer in an LLM Council deliberation. "
                    "Revise your answer, citing which critiques you accepted or rejected. "
                    "End your response with exactly:\nCONFIDENCE: 0.XX\nRATIONALE: <one sentence>"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original query: {state['query']}\n\n"
                    f"Your previous draft (draft_{round_idx - 1}):\n{prev_draft}\n\n"
                    f"Critiques received:\n{critiques_text}\n\n"
                    "Please revise your draft."
                ),
            },
        ]

    resp = await call_seat(seat["provider"], seat["model"], messages)
    entry = _make_entry(state["session_id"], round_idx, seat["seat_id"], "draft", resp.text, resp)
    return {"drafts": [resp.text], "transcript": [entry]}


async def critique_node(state: CouncilState) -> dict[str, Any]:
    critics = _seats_by_role(state["seats"], "critic")
    draft = state["drafts"][-1]
    draft_label = _draft_label(len(state["drafts"]) - 1)
    round_idx = len(state["drafts"]) - 1

    async def critique_one(seat: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are a Critic in an LLM Council deliberation. "
                    "Rigorously critique the Proposer's draft. "
                    "Identify factual errors, missing context, and logical flaws."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Query: {state['query']}\n\n"
                    f"Proposer's draft ({draft_label}):\n{draft}"
                ),
            },
        ]
        resp = await call_seat(seat["provider"], seat["model"], messages)
        entry = _make_entry(
            state["session_id"], round_idx, seat["seat_id"], "critique", resp.text, resp
        )
        return resp.text, entry

    results = await asyncio.gather(*[critique_one(s) for s in critics])
    round_critiques = [r[0] for r in results]
    entries = [r[1] for r in results]
    return {"critiques": [round_critiques], "transcript": entries}


async def check_termination_node(state: CouncilState) -> dict[str, Any]:
    # Round cap is checked first — no LLM calls needed.
    round_cap = len(state["drafts"]) >= state["max_rounds"]
    if round_cap:
        return {"route_decision": "vote", "terminated_by": "round_cap"}

    # Straw poll only makes sense after at least one revision (len >= 2),
    # otherwise the only draft is trivially the unanimous choice.
    if len(state["drafts"]) < 2:
        return {"route_decision": "continue"}

    non_proposers = [s for s in state["seats"] if s["role"] != "proposer"]
    draft_labels = [_draft_label(i) for i in range(len(state["drafts"]))]
    labels_str = ", ".join(draft_labels)

    async def straw_one(seat: dict[str, Any]) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": "Answer with exactly one draft label, nothing else."},
            {
                "role": "user",
                "content": (
                    f"Which draft would you currently back? Options: {labels_str}\n"
                    "Reply with exactly one label, e.g. draft_0"
                ),
            },
        ]
        resp = await call_seat(seat["provider"], seat["model"], messages, max_tokens=20)
        for label in reversed(draft_labels):
            if label in resp.text:
                return label
        return draft_labels[-1]

    straw_choices = list(await asyncio.gather(*[straw_one(s) for s in non_proposers]))
    unanimous = straw_poll_unanimous(straw_choices)

    if unanimous:
        return {"route_decision": "vote", "terminated_by": "unanimous"}
    return {"route_decision": "continue"}


async def vote_node(state: CouncilState) -> dict[str, Any]:
    draft_labels = [_draft_label(i) for i in range(len(state["drafts"]))]
    drafts_text = "\n\n".join(
        f"**{_draft_label(i)}**:\n{d}" for i, d in enumerate(state["drafts"])
    )

    async def vote_one(seat: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "You are voting on the best answer to a query. "
                    'Respond in JSON: {"choice": "draft_N", "confidence": 0.XX, '
                    '"rationale": "...", "concerns": ["..."]}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Query: {state['query']}\n\nDrafts:\n{drafts_text}\n\n"
                    f"Vote for the best draft. Valid choices: {', '.join(draft_labels)}"
                ),
            },
        ]
        resp = await call_seat(seat["provider"], seat["model"], messages)
        parsed = _parse_vote(resp.text, draft_labels)
        vote_dict = {"seat_id": seat["seat_id"], **parsed}
        entry = _make_entry(
            state["session_id"],
            len(state["drafts"]),
            seat["seat_id"],
            "vote",
            resp.text,
            resp,
        )
        return vote_dict, entry

    results = await asyncio.gather(*[vote_one(s) for s in state["seats"]])
    vote_dicts = [r[0] for r in results]
    entries = [r[1] for r in results]
    return {"votes": vote_dicts, "transcript": entries}


async def synthesize_node(state: CouncilState) -> dict[str, Any]:
    votes = [VotePayload(**v) for v in state["votes"]]
    winning_choice, _is_tie = simple_majority(votes)

    draft_idx_str = winning_choice.split("_")[-1]
    draft_idx = int(draft_idx_str) if draft_idx_str.isdigit() else len(state["drafts"]) - 1
    draft_idx = min(draft_idx, len(state["drafts"]) - 1)
    winning_text = state["drafts"][draft_idx]

    winning_votes = sum(1 for v in votes if v.choice == winning_choice)
    total_votes = len(votes)

    minority_concerns: list[str] = []
    for v in votes:
        if v.choice != winning_choice:
            minority_concerns.extend(v.concerns)
            if v.rationale:
                minority_concerns.append(f"Dissent (seat {v.seat_id}): {v.rationale[:200]}")

    verdict_text, minority_text = render_verdict(
        winning_draft_text=winning_text,
        mechanism=state["voting_mechanism"],
        winning_votes=winning_votes,
        total_votes=total_votes,
        votes=votes,
        include_minority=state["include_minority"],
        minority_concerns=minority_concerns,
    )

    judge_seat = _seat(state["seats"], "judge")
    entry = _make_entry(
        state["session_id"],
        len(state["drafts"]),
        judge_seat["seat_id"],
        "verdict",
        verdict_text,
    )

    return {
        "verdict_text": verdict_text,
        "minority_text": minority_text,
        "transcript": [entry],
    }


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def _route(state: CouncilState) -> Literal["continue", "vote"]:
    decision = state.get("route_decision", "continue")
    return "vote" if decision == "vote" else "continue"


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_council_graph() -> Any:
    workflow: StateGraph = StateGraph(CouncilState)  # type: ignore[type-arg]

    workflow.add_node("propose", propose_node)
    workflow.add_node("critique", critique_node)
    workflow.add_node("check_termination", check_termination_node)
    workflow.add_node("vote", vote_node)
    workflow.add_node("synthesize", synthesize_node)

    workflow.set_entry_point("propose")
    workflow.add_edge("propose", "critique")
    workflow.add_edge("critique", "check_termination")
    workflow.add_conditional_edges(
        "check_termination",
        _route,
        {"continue": "propose", "vote": "vote"},
    )
    workflow.add_edge("vote", "synthesize")
    workflow.add_edge("synthesize", END)

    return workflow.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_council(query: str, cfg: AppConfig) -> dict[str, Any]:
    """Convene a council session and return the final graph state."""
    session_id = str(uuid.uuid4())
    seats = [s.model_dump() for s in cfg.council.seats]

    initial: CouncilState = {
        "session_id": session_id,
        "query": query,
        "seats": seats,
        "max_rounds": cfg.council.max_rounds,
        "include_minority": cfg.council.include_minority,
        "voting_mechanism": cfg.voting.mechanism,
        "drafts": [],
        "critiques": [],
        "transcript": [],
        "votes": [],
        "verdict_text": "",
        "minority_text": None,
        "terminated_by": "",
        "error": None,
        "route_decision": "continue",
    }

    graph = build_council_graph()
    result: dict[str, Any] = await graph.ainvoke(initial)
    return result
