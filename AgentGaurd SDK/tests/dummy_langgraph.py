import os
import operator
from typing import TypedDict, Annotated

# Import LangGraph components
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# Import our new SDK!
# Note: In a real project, this would be `from agentguard import AgentGuard`
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from AgentGaurd_SDK.client import AgentGuard

from langchain_core.language_models.fake_chat_models import FakeListChatModel

# Create a mock LLM that just repeats the same phrase over and over
fake_llm = FakeListChatModel(responses=["Are we stuck in a loop?"])

# 1. Define the Graph State
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]

# 2. Define the Agents (Nodes)
def agent_a(state: AgentState):
    # LAZY CODE: We do NOT pass `config=config` into the LLM! 
    # LangChain will drop the callback, but AgentGuard should catch it at the Node level anyway!
    response = fake_llm.invoke(state["messages"])
    print(f"Agent A: {response.content}")
    return {"messages": [AIMessage(content=response.content, name="Agent_A")]}

def agent_b(state: AgentState):
    # LAZY CODE
    response = fake_llm.invoke(state["messages"])
    print(f"Agent B: {response.content}")
    return {"messages": [AIMessage(content=response.content, name="Agent_B")]}

# 3. Build the Graph
builder = StateGraph(AgentState)
builder.add_node("Agent_A", agent_a)
builder.add_node("Agent_B", agent_b)

# Wire them to loop infinitely!
builder.set_entry_point("Agent_A")
builder.add_edge("Agent_A", "Agent_B")
builder.add_edge("Agent_B", "Agent_A")

graph = builder.compile()

# 4. Run the Test with AgentGuard
if __name__ == "__main__":
    # We initialize AgentGuard. 
    # We set loop_threshold to 6 so we don't have to wait long to see it trigger!
    guard = AgentGuard(
        loop_threshold=6,
        semantic_sensitivity=0.90
    )
    
    print("\n--- Starting Infinite Loop Test ---")
    try:
        # We start the graph and pass AgentGuard in as a callback!
        graph.invoke(
            {"messages": [HumanMessage(content="Are we stuck in a loop?")]},
            config={"callbacks": [guard.langgraph_callback()]}
        )
    except Exception as e:
        # If AgentGuard works, it will raise an Exception and land here!
        print(f"\n🛑 [AGENTGUARD INTERVENTION] {e}\n")
