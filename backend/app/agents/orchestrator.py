"""Central LangGraph traffic controller."""

from langgraph.graph import END, START, StateGraph

from app.agents.geospatial_agent import geospatial_geofencing_agent
from app.agents.intent_agent import intent_translation_agent
from app.agents.ocean_agent import ocean_analytics_agent
from app.agents.reporting_agent import reporting_agent
from app.agents.route_agent import route_optimization_agent
from app.agents.state import AgentState
from app.agents.synthesis_agent import synthesizing_agent
from app.agents.weather_agent import weather_safety_agent

AGENT_NODES = ("ocean", "weather", "geofence", "route", "reporting")


def route_sub_tasks(state: AgentState) -> list[str]:
    selected = []
    for task in state.get("sub_tasks", []):
        for name in task.get("agents", []):
            if name in AGENT_NODES and name not in selected:
                selected.append(name)
    return selected or ["synthesizer"]


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("intent", intent_translation_agent)
    workflow.add_node("ocean", ocean_analytics_agent)
    workflow.add_node("weather", weather_safety_agent)
    workflow.add_node("geofence", geospatial_geofencing_agent)
    workflow.add_node("route", route_optimization_agent)
    workflow.add_node("reporting", reporting_agent)
    workflow.add_node("synthesizer", synthesizing_agent)
    workflow.add_edge(START, "intent")
    workflow.add_conditional_edges("intent", route_sub_tasks, {**{name: name for name in AGENT_NODES}, "synthesizer": "synthesizer"})
    for name in AGENT_NODES:
        workflow.add_edge(name, "synthesizer")
    workflow.add_edge("synthesizer", END)
    return workflow.compile()


graph = build_graph()
