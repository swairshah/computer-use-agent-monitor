"""
Element classes for macOS UI Monitoring.
This module provides the ElementInfo class for representing UI elements.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field

from osmonitor.utils.accessibility import clean_accessibility_value
from macos_accessibility import ThreadSafeAXUIElement, MacOSUIElement

logger = logging.getLogger(__name__)

@dataclass
class ElementAttributes:
    """Represents a UI element with attributes and hierarchy information."""
    element_ref: Any  # Reference to the accessibility element (may be None)
    path: str  # Path to the element in the UI hierarchy
    attributes: Dict[str, Any]  # Element attributes
    depth: int  # Depth in the UI hierarchy
    x: float  # X coordinate
    y: float  # Y coordinate
    width: float  # Width
    height: float  # Height
    children: List[str] = field(default_factory=list)  # List of child element identifiers
    
    def __post_init__(self):
        # Generate a unique identifier for this element
        self.identifier = str(uuid.uuid4())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to a serializable dictionary."""
        return {
            "id": self.identifier,
            "path": self.path,
            "attributes": self.attributes,
            "depth": self.depth,
            "position": {"x": self.x, "y": self.y},
            "size": {"width": self.width, "height": self.height},
            "children": self.children
        }

@dataclass
class WindowState:
    """Represents the state of a window with its UI elements."""
    elements: Dict[str, ElementAttributes] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    initial_traversal_at: Optional[datetime] = None
    text_output: str = ""

@dataclass
class WindowIdentifier:
    """Identifies a window uniquely."""
    app: str
    window: str
    
    def __hash__(self):
        return hash((self.app, self.window))
    
    def __eq__(self, other):
        if not isinstance(other, WindowIdentifier):
            return False
        return self.app == other.app and self.window == other.window

@dataclass
class UIFrame:
    """Represents a UI frame for sending through a pipe."""
    window: str
    app: str
    text_output: str
    initial_traversal_at: str

class ElementInfo:
    """Information about a UI element."""
    
    # Known accessibility attributes that often contain useful information
    IMPORTANT_ATTRIBUTES = [
        "AXRole", "AXTitle", "AXDescription", "AXValue", "AXHelp", 
        "AXLabel", "AXRoleDescription", "AXSubrole", "AXIdentifier",
        "AXPlaceholderValue", "AXSelectedText", "AXText", "AXDisplayedText",
        "AXPath", "AXName", "AXMenuItemCmdChar", "AXMenuItemCmdModifiers", 
        "AXMenuItemCmdVirtualKey", "AXMenuItemMarkChar", "AXTitleUIElement", 
        "AXParent", "AXChildren", "AXWindow", "AXTopLevelUIElement", "AXEnabled",
        "AXFocused", "AXVisible", "AXSelected", "AXExpanded", "AXRequired"
    ]
    
    def __init__(self, element: MacOSUIElement):
        """Initialize with a MacOSUIElement."""
        self.element = element
        self.id = element.id()
        self.raw_attributes = {}  # Store all raw attributes
        
        # Get role with better error handling
        try:
            raw_role = element.role()
            self.role = clean_accessibility_value(raw_role) or "Unknown"
            if not self.role:  # If empty after cleaning
                self.role = "Unknown"
        except Exception as e:
            self.role = f"Unknown ({str(e)[:30]})"
        
        # Get position with default fallback
        try:
            raw_pos = element.element.get_position()
            # For position, we need to handle it specially since we need the numeric values
            if isinstance(raw_pos, tuple) and len(raw_pos) == 2:
                self.position = raw_pos
            else:
                self.position = (0, 0)
        except Exception:
            self.position = (0, 0)
        
        # Get size with default fallback
        try:
            raw_size = element.element.get_size()
            # For size, we need to handle it specially since we need the numeric values
            if isinstance(raw_size, tuple) and len(raw_size) == 2:
                self.size = raw_size
            else:
                self.size = (0, 0)
        except Exception:
            self.size = (0, 0)
            
        # Store direct parent element's role (useful for context)
        try:
            parent_element = element.element.get_attribute("AXParent")
            if parent_element:
                parent = MacOSUIElement(ThreadSafeAXUIElement(parent_element))
                self.parent_role = clean_accessibility_value(parent.role())
            else:
                self.parent_role = ""
        except Exception:
            self.parent_role = ""
            
        # Get all attributes and store them
        try:
            # Get all available attributes 
            attrs = element.attributes() or {}
            self.raw_attributes = attrs
            
            # Set basic attributes with empty defaults
            self.title = ""
            self.value = ""
            self.description = ""
            self.help = ""
            self.identifier = ""
            self.label = ""
            self.subrole = ""
            self.placeholder = ""
            self.selected_text = ""
            self.text = ""
            self.displayed_text = ""
            self.name = ""
            self.path = ""
            self.url = ""
            self.role_description = ""
            
            # Status attributes
            self.enabled = True
            self.focused = False
            self.visible = True
            self.selected = False
            self.expanded = False
            self.required = False
            
            # Process direct attribute mapping
            direct_mapping = {
                "value": "AXValue",
                "description": "AXDescription",
                "help": "AXHelp",
                "identifier": "AXIdentifier",
                "label": "AXLabel",
                "subrole": "AXSubrole",
                "placeholder": "AXPlaceholderValue",
                "selected_text": "AXSelectedText",
                "text": "AXText",
                "displayed_text": "AXDisplayedText",
                "name": "AXName", 
                "path": "AXPath",
                "url": "AXURL",
                "role_description": "AXRoleDescription",
                "enabled": "AXEnabled",
                "focused": "AXFocused",
                "visible": "AXVisible",
                "selected": "AXSelected", 
                "expanded": "AXExpanded",
                "required": "AXRequired"
            }
            
            # Set attributes from mapping
            for attr_name, ax_name in direct_mapping.items():
                if ax_name in attrs:
                    raw_value = attrs.get(ax_name)
                    if attr_name in ["enabled", "focused", "visible", "selected", "expanded", "required"]:
                        # For boolean attributes, convert but keep as boolean
                        if raw_value is not None:
                            setattr(self, attr_name, bool(raw_value))
                    else:
                        # For text attributes, clean the value
                        setattr(self, attr_name, clean_accessibility_value(raw_value))
            
            # Try specific approach for title - sometimes needs special handling
            try:
                raw_title = element.element.get_title()
                self.title = clean_accessibility_value(raw_title)
            except Exception:
                # If direct method fails, try to get from attributes
                self.title = clean_accessibility_value(attrs.get("AXTitle", ""))
            
            # If we have a TitleUIElement, try to get its value
            if not self.title and "AXTitleUIElement" in attrs:
                try:
                    title_elem = attrs.get("AXTitleUIElement")
                    if title_elem:
                        title_ui = MacOSUIElement(ThreadSafeAXUIElement(title_elem))
                        title_value = title_ui.element.get_title() or title_ui.element.get_attribute("AXValue")
                        if title_value:
                            self.title = clean_accessibility_value(title_value)
                except Exception:
                    pass
             
            # Get additional attributes that might help identify menu items
            if self.role == "AXMenuItem" or self.subrole == "AXMenuItem":
                self.menu_cmd_char = clean_accessibility_value(attrs.get("AXMenuItemCmdChar", ""))
                self.menu_mark_char = clean_accessibility_value(attrs.get("AXMenuItemMarkChar", ""))
            
            # Get child count
            try:
                children = attrs.get("AXChildren", [])
                self.child_count = len(children) if children else 0
            except Exception:
                self.child_count = 0
            
            # If title is STILL empty, try alternative attributes as fallbacks
            if not self.title:
                for attr in [self.label, self.value, self.name, self.description, 
                            self.text, self.displayed_text, self.selected_text, 
                            self.placeholder, self.menu_cmd_char, self.menu_mark_char]:
                    if attr:
                        self.title = clean_accessibility_value(attr)
                        break
                        
            # Last resort: try using role description if we have no title
            if not self.title and self.role_description:
                self.title = f"[{self.role_description}]"
                
            # Try to get frame geometry for better positioning
            try:
                frame = attrs.get("AXFrame", None)
                if frame and isinstance(frame, dict):
                    origin = frame.get("origin", {})
                    size = frame.get("size", {})
                    x = origin.get("x", self.position[0])
                    y = origin.get("y", self.position[1])
                    width = size.get("width", self.size[0])
                    height = size.get("height", self.size[1])
                    self.position = (x, y)
                    self.size = (width, height)
            except Exception:
                # Keep existing position/size if this fails
                pass
                
        except Exception as e:
            logger.debug(f"Error getting element attributes: {e}")
            # Keep the defaults set earlier
    
    def __str__(self):
        title_str = f'"{self.title}"' if self.title else "No title"
        context = []
        
        # Add most relevant context attributes
        if self.role_description:
            context.append(self.role_description)
        elif self.role:
            context.append(self.role)
        
        if self.subrole:
            context.append(f"subrole:{self.subrole}")
            
        if self.parent_role:
            context.append(f"in:{self.parent_role}")
            
        if self.child_count > 0:
            context.append(f"children:{self.child_count}")
            
        # Add enabled/selected status if not the default
        if not self.enabled:
            context.append("disabled")
        if self.selected:
            context.append("selected")
        if self.focused:
            context.append("focused")
            
        context_str = ", ".join(context)
        
        return f"{title_str} ({context_str})"
    
    def to_dict(self):
        """Convert element info to a serializable dictionary."""
        # Base attributes always included
        result = {
            "id": self.id,
            "role": self.role,
            "title": self.title,
            "position": {"x": self.position[0], "y": self.position[1]},
            "size": {"width": self.size[0], "height": self.size[1]}
        }
        
        # Include status attributes
        status = {}
        for attr_name in ["enabled", "focused", "visible", "selected", "expanded", "required"]:
            value = getattr(self, attr_name, None)
            if value is not None:  # Include all booleans, even False
                status[attr_name] = value
                
        if status:
            result["status"] = status
            
        # Add parent information if available
        if self.parent_role:
            result["parent_role"] = self.parent_role
            
        # Add child count if available
        if hasattr(self, 'child_count') and self.child_count > 0:
            result["child_count"] = self.child_count
        
        # Add additional text attributes if they have values
        text_attrs = [
            "value", "description", "label", "identifier", "help",
            "subrole", "placeholder", "selected_text", "text", 
            "displayed_text", "name", "path", "url", "role_description"
        ]
        
        for attr_name in text_attrs:
            value = getattr(self, attr_name, "")
            if value:  # Only include non-empty values
                result[attr_name] = value
        
        # Add menu item specific attributes if present
        if hasattr(self, 'menu_cmd_char') and self.menu_cmd_char:
            result["menu_cmd_char"] = self.menu_cmd_char
            
        if hasattr(self, 'menu_mark_char') and self.menu_mark_char:
            result["menu_mark_char"] = self.menu_mark_char
                
        return result