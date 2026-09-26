"""Invariant #7 guard for the Phase-3 Dify DAG template
(dify_workflows/analyze_oa.workflow.json): when security_level is anything but
"public", every LLM node the run can reach must be local (provider=ollama).

Walks the graph edges from Start, following only the TRUE branch of every
confidential if-else gate (the branch a confidential run takes)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

WF = Path(__file__).resolve().parents[2] / "dify_workflows" / "analyze_oa.workflow.json"


@pytest.fixture(scope="module")
def wf() -> dict:
    return json.loads(WF.read_text(encoding="utf-8"))


def _all_nodes(wf: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for n in wf["workflow"]["graph"]["nodes"]:
        out[n["id"]] = n
        for c in n["data"].get("children", []) or []:
            out[c["id"]] = c
    return out


def _reachable(wf: dict, *, confidential: bool) -> set[str]:
    nodes = _all_nodes(wf)
    edges = wf["workflow"]["graph"]["edges"]
    take = "true" if confidential else "false"
    seen, stack = set(), ["node-start"]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        is_gate = nodes[cur]["data"].get("type") == "if-else"
        for e in edges:
            if e["source"] != cur:
                continue
            if is_gate and e.get("sourceHandle") not in (take,):
                continue
            stack.append(e["target"])
    return seen


def _llm_nodes(wf: dict, ids: set[str]) -> list[dict]:
    nodes = _all_nodes(wf)
    return [nodes[i] for i in ids if nodes[i]["data"].get("type") == "llm"]


def test_edges_reference_existing_nodes(wf):
    nodes = _all_nodes(wf)
    for e in wf["workflow"]["graph"]["edges"]:
        assert e["source"] in nodes, e
        assert e["target"] in nodes, e


def test_confidential_path_reaches_only_local_llms(wf):
    reach = _reachable(wf, confidential=True)
    llms = _llm_nodes(wf, reach)
    # parse + draft + verify all present on the confidential path
    assert len(llms) >= 3
    for n in llms:
        assert n["data"]["model"]["provider"] == "ollama", n["id"]
    assert "node-end" in reach


def test_public_path_uses_current_cloud_models(wf):
    llms = _llm_nodes(wf, _reachable(wf, confidential=False))
    names = {n["data"]["model"]["name"] for n in llms}
    assert names <= {"claude-sonnet-5", "claude-haiku-4-5"}, names
    for n in llms:
        # Claude 5-family models reject non-default sampling params.
        assert "temperature" not in n["data"]["model"].get("completion_params", {})


def test_gates_fail_closed_on_unknown_level(wf):
    nodes = _all_nodes(wf)
    gates = [n for n in nodes.values() if n["data"].get("type") == "if-else"]
    assert len(gates) >= 3  # parse gate, draft gate, verify gate
    for g in gates:
        conds = g["data"]["conditions"][0]["conditions"]
        assert any(
            c["comparison_operator"] == "is not" and c["value"] == "public" for c in conds
        ), g["id"]
