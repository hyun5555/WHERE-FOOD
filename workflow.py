"""Bounded, request-local LangGraph: clarify, recommend, or explain no results."""
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

import recommendation as rec
from explanations import explain_recommendations


class MealState(TypedDict, total=False):
    constraints: rec.MealConstraints
    payload: rec.ConfirmedRecommendInput
    database_path: str
    weather_provider: Callable
    origin: dict | None
    result: dict
    steps: list[str]


def resolve(state):
    c = state["constraints"]
    result = rec.new_response(c)
    origin = None
    if c.unknown_terms:
        result.update(status="clarification_required",
                      message="다음 조건을 수정하거나 이번 검색에서 제외할지 확인해주세요: " + ", ".join(c.unknown_terms))
    else:
        origin, options = rec.resolve_origin(c, state["payload"])
        if origin is None:
            result.update(status="clarification_required", location_options=options,
                          message="검색 기준 장소를 선택해주세요." if options else "위치를 허용하거나 확인 화면에 구체적인 장소를 적어주세요.")
    return {"origin": origin, "result": result, "steps": ["RESOLVE"]}


def search(state):
    result = rec.recommend(state["constraints"], state["origin"], state["database_path"], state["weather_provider"])
    return {"result": result, "steps": [*state["steps"], "SEARCH_FILTER_RANK"]}


def clarify(state):
    result = {**state["result"], "next_action": "review_constraints"}
    return {"result": result, "steps": [*state["steps"], "CLARIFY"]}


def no_results(state):
    result = {**state["result"], "status": "no_results", "next_action": "review_constraints"}
    counts = result["diagnostics"].get("category_counts", {})
    summary = " · ".join(f"{label} {counts[key]}건" for key, label in rec.CATEGORY_LABELS.items() if counts.get(key))
    result["message"] = ("확보한 자료로 모든 필수 조건을 확인한 추천을 만들지 못했습니다. " + summary + "."
                         if summary else "현재 검색 범위에서 장소 후보를 조회하지 못했습니다. 주변에 식당이 없다는 뜻은 아닙니다.")
    return {"result": result, "steps": [*state["steps"], "NO_RESULTS"]}


def respond(state):
    count = len(state["result"]["recommendations"])
    result = {**state["result"], "status": "ok" if count == 3 else "partial", "next_action": "choose_restaurant",
              "message": f"확인한 조건을 만족하는 식당 {count}곳입니다. 미확인 선호는 각 카드에 표시했습니다."}
    return {"result": result, "steps": [*state["steps"], "RESPOND"]}


def explain(state):
    result = state["result"]
    explain_recommendations(result, state["constraints"])
    return {"result": result, "steps": [*state["steps"], "EXPLAIN"]}


builder = StateGraph(MealState)
for name, fn in (("RESOLVE", resolve), ("SEARCH_FILTER_RANK", search), ("CLARIFY", clarify),
                 ("NO_RESULTS", no_results), ("EXPLAIN", explain), ("RESPOND", respond)):
    builder.add_node(name, fn)
builder.add_edge(START, "RESOLVE")
builder.add_conditional_edges("RESOLVE", lambda s: "CLARIFY" if s["origin"] is None else "SEARCH_FILTER_RANK",
                              ["CLARIFY", "SEARCH_FILTER_RANK"])
builder.add_conditional_edges("SEARCH_FILTER_RANK", lambda s: "EXPLAIN" if s["result"]["recommendations"] else "NO_RESULTS",
                              ["EXPLAIN", "NO_RESULTS"])
builder.add_conditional_edges("EXPLAIN", lambda s: "RESPOND" if s["result"]["recommendations"] else "NO_RESULTS",
                              ["RESPOND", "NO_RESULTS"])
for name in ("CLARIFY", "NO_RESULTS", "RESPOND"):
    builder.add_edge(name, END)
# No checkpoint, remote runtime, tracing export, retry loop, or automatic relaxation.
meal_graph = builder.compile()


def run_recommendation(constraints, payload, database_path, weather_provider):
    with tracing_context(enabled=False):
        state = meal_graph.invoke({"constraints": constraints, "payload": payload,
                                   "database_path": database_path, "weather_provider": weather_provider},
                                  config={"callbacks": [], "recursion_limit": 8})
    result = state["result"]
    result["workflow"] = {"engine": "langgraph", "version": "meal-v2", "steps": state["steps"]}
    return result
