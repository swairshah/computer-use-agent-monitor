"""
Event class for macOS UI Monitoring.
This module provides the UIEvent class for representing UI events.
"""

class UIEvent:
    """Represents a UI event like a click, key press, or focus change."""
    
    def __init__(self, event_type: str, timestamp: float, **kwargs):
        self.event_type = event_type  # click, key_press, focus_change, etc.
        self.timestamp = timestamp    # When the event occurred
        self.details = kwargs         # Additional event-specific details
    
    def __str__(self):
        details_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
        return f"UIEvent({self.event_type}, {self.timestamp:.2f}, {details_str})"
    
    def to_dict(self):
        """Convert event to a serializable dictionary."""
        return {
            "type": self.event_type,
            "timestamp": self.timestamp,
            **self.details
        }