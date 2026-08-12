from typing import Optional
from .core.memory import MemoryStore, LocalMemory
from .integrations.langgraph import AgentGuardCallback

class AgentGuard:
    """
    The main SDK entry point for AgentGuard.
    Acts as a facade to automatically configure guardrails and memory for multi-agent systems.
    """
    def __init__(
        self,
        budget_ceiling: float = 10.0,
        loop_threshold: int = 15,
        semantic_sensitivity: float = 0.90,
        engine_url: Optional[str] = None
    ):
        self.budget_ceiling = budget_ceiling
        self.loop_threshold = loop_threshold
        self.semantic_sensitivity = semantic_sensitivity
        self.engine_url = engine_url
        
        # Initialize the state store based on the engine_url
        if self.engine_url is None:
            # Fallback to in-memory dictionary for local testing/MVP
            self._memory: MemoryStore = LocalMemory()
        else:
            # Future expansion (Phase 4): Connect to Redis/Postgres
            raise NotImplementedError("Remote engine (Redis) support is coming in Phase 4.")

    def langgraph_callback(self, workflow_id: str = "default") -> AgentGuardCallback:
        """
        Generates a LangChain BaseCallbackHandler pre-configured with the agent's memory and settings.
        Pass this directly into your LangGraph `config={"callbacks": [...]}`.
        """
        return AgentGuardCallback(
            memory=self._memory,
            workflow_id=workflow_id,
            budget_ceiling=self.budget_ceiling,
            loop_threshold=self.loop_threshold,
            semantic_sensitivity=self.semantic_sensitivity
        )
