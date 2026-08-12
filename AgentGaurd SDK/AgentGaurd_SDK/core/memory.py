from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import deque

class MemoryStore(ABC):
    """
    Abstract blueprint for AgentGuard memory. 
    This ensures that whether we use local dicts or remote Redis, the methods are identical.
    """
    
    @abstractmethod
    def acquire_lock(self, resource_id: str, agent_id: str) -> bool:
        pass

    @abstractmethod
    def release_lock(self, resource_id: str, agent_id: str) -> None:
        pass

    @abstractmethod
    def add_event(self, workflow_id: str, event_data: dict) -> None:
        pass

    @abstractmethod
    def get_events(self, workflow_id: str, limit: int = 10) -> List[dict]:
        pass
        
    @abstractmethod
    def increment_spend(self, entity_id: str, amount: float) -> float:
        pass
        
    @abstractmethod
    def get_spend(self, entity_id: str) -> float:
        pass


class LocalMemory(MemoryStore):
    """
    A lightweight, in-memory hashmap storage for Phase 1.
    No database required. Perfect for single-machine testing.
    """
    def __init__(self, max_events_per_workflow: int = 100):
        # Database Concurrency Control
        self._locks: Dict[str, str] = {}  # {resource_id: agent_id}
        
        # Loop Detection History (using deque for O(1) performance and memory capping)
        self.max_events = max_events_per_workflow
        self._events: Dict[str, deque] = {}  # {workflow_id: deque of event_dicts}
        
        # Budget Hard Ceilings
        self._budgets: Dict[str, float] = {}  # {entity_id: total_spend}

    def acquire_lock(self, resource_id: str, agent_id: str) -> bool:
        """Attempts to grab a lock on a resource. Returns True if successful."""
        if resource_id in self._locks and self._locks[resource_id] != agent_id:
            return False # Someone else holds the lock
        self._locks[resource_id] = agent_id
        return True

    def release_lock(self, resource_id: str, agent_id: str) -> None:
        """Releases a lock if the agent actually holds it."""
        if self._locks.get(resource_id) == agent_id:
            del self._locks[resource_id]

    def add_event(self, workflow_id: str, event_data: dict) -> None:
        """Stores an event (like a message sent) to help detect loops."""
        if workflow_id not in self._events:
            self._events[workflow_id] = deque(maxlen=self.max_events)
        
        # Add timestamp if not present
        if "timestamp" not in event_data:
            event_data["timestamp"] = datetime.now().isoformat()
            
        self._events[workflow_id].append(event_data)

    def get_events(self, workflow_id: str, limit: int = 10) -> List[dict]:
        """Gets the most recent events for loop analysis."""
        events = self._events.get(workflow_id, [])
        # Convert the fast deque back to a list for easy slicing by the client
        return list(events)[-limit:]
        
    def increment_spend(self, entity_id: str, amount: float) -> float:
        """Adds to the budget counter and returns the new total."""
        current = self._budgets.get(entity_id, 0.0)
        self._budgets[entity_id] = current + amount
        return self._budgets[entity_id]
        
    def get_spend(self, entity_id: str) -> float:
        """Gets the current total spend for an entity."""
        return self._budgets.get(entity_id, 0.0)
