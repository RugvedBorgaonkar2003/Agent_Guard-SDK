import hashlib
import difflib
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from ..core.memory import MemoryStore


class AgentGuardException(Exception):
    """Raised when an agent violates a guardrail (Loop, Budget, or Lock)."""
    pass


class AgentGuardCallback(BaseCallbackHandler):
    """
    Hooks into LangGraph/LangChain execution to enforce guardrails automatically.
    """
    
    def __init__(
        self, 
        memory: MemoryStore, 
        workflow_id: str = "default", 
        budget_ceiling: float = 10.0,
        loop_threshold: int = 15,
        semantic_sensitivity: float = 0.90
    ):
        self.memory = memory
        self.workflow_id = workflow_id
        self.budget_ceiling = budget_ceiling
        self.loop_threshold = loop_threshold
        self.semantic_sensitivity = semantic_sensitivity
        self.raise_error = True  # Forces LangChain to crash the graph instead of swallowing the exception!
        
        self.current_node = "unknown_agent"
        self.active_locks: Dict[UUID, str] = {}  # Maps run_id -> resource_id

    def _get_active_workflow_id(self, kwargs: Dict[str, Any]) -> str:
        """Dynamically gets the root execution ID if no explicit workflow_id was provided."""
        if self.workflow_id != "default":
            return self.workflow_id
            
        # Fallback to the unique parent run_id LangChain generates for the execution tree
        run_id = kwargs.get("parent_run_id") or kwargs.get("run_id")
        return str(run_id) if run_id else "default"

    def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any
    ) -> Any:
        """1 & 2. Interception and Filter: Ignore system nodes, target real agents."""
        metadata = kwargs.get("metadata", {})
        node = metadata.get("langgraph_node")
        
        # Filter out LangGraph's internal background nodes
        if node and node not in ["__start__", "__end__"]:
            self.current_node = node
            
            # 3. Extraction & Hash
            messages = inputs.get("messages", [])
            if not messages:
                return
                
            last_message = messages[-1]
            # Safely handle LangChain BaseMessage objects or raw dictionaries
            content = getattr(last_message, 'content', str(last_message))
            prompt_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
            
            # 4. The Sliding Window (First-In, First-Out)
            active_workflow_id = self._get_active_workflow_id(kwargs)
            event_data = {
                "agent_name": self.current_node,
                "prompt_hash": prompt_hash,
                "prompt_text": content
            }
            self.memory.add_event(active_workflow_id, event_data)
            
            # 5 & 6. Suspicion Check & Semantic Matcher (The Verdict)
            events = self.memory.get_events(active_workflow_id, limit=self.loop_threshold)
            if len(events) == self.loop_threshold:
                agents = [e["agent_name"] for e in events]
                
                # If only 1 or 2 agents are dominating the sliding window, it's highly suspicious (ping-pong)
                if len(set(agents)) <= 2:
                    recent_prompts = [e["prompt_text"] for e in events[-3:]]
                    
                    # Check for semantic looping on the most recent prompts
                    similarity_ratio = difflib.SequenceMatcher(None, recent_prompts[0], recent_prompts[-1]).ratio()
                    if similarity_ratio > self.semantic_sensitivity:
                        raise AgentGuardException(f"Infinite Semantic Loop Detected (Similarity: {similarity_ratio:.2f}). Execution halted.")

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> Any:
        """2. Loop & Budget Check before the API call."""
        
        active_workflow_id = self._get_active_workflow_id(kwargs)
        
        # A. Budget Hard Ceiling
        current_spend = self.memory.get_spend(active_workflow_id)
        if current_spend >= self.budget_ceiling:
            raise AgentGuardException(f"Budget Exceeded! Total spent: ${current_spend:.4f}. Ceiling: ${self.budget_ceiling:.4f}")
        
        # (All Loop Detection logic is now safely inside on_chain_start)

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> Any:
        """3. The Cash Register. Update budget based on actual token usage."""
        active_workflow_id = self._get_active_workflow_id(kwargs)
        
        if response.llm_output and "token_usage" in response.llm_output:
            usage = response.llm_output["token_usage"]
            total_tokens = usage.get("total_tokens", 0)
            
            # MVP Cost Estimation: $0.001 per 1000 tokens
            cost = (total_tokens / 1000) * 0.001
            self.memory.increment_spend(active_workflow_id, cost)

    def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs: Any
    ) -> Any:
        """4. Database Locks. Prevent simultaneous overwrites."""
        tool_name = serialized.get("name", "unknown_tool")
        run_id = kwargs.get("run_id")
        
        # For MVP, we treat the tool name itself as the resource being locked.
        resource_id = f"tool_lock_{tool_name}"
        
        if self.memory.acquire_lock(resource_id, self.current_node):
            if run_id:
                self.active_locks[run_id] = resource_id
        else:
            raise AgentGuardException(f"Resource Lock Error: '{tool_name}' is currently locked by another agent.")

    def on_tool_end(self, output: Any, **kwargs: Any) -> Any:
        """Release the lock when the tool finishes."""
        run_id = kwargs.get("run_id")
        if run_id and run_id in self.active_locks:
            resource_id = self.active_locks.pop(run_id)
            self.memory.release_lock(resource_id, self.current_node)
