import objc
from Cocoa import *
from ApplicationServices import (
    AXObserverCreate,
    AXObserverAddNotification,
    AXUIElementCreateApplication,
    AXObserverGetRunLoopSource,
    AXIsProcessTrustedWithOptions,
    AXUIElementCopyAttributeValue
)
from CoreFoundation import CFRunLoopAddSource, CFRunLoopGetCurrent, kCFRunLoopDefaultMode
import threading
import time
import sqlite3
from collections import defaultdict

def check_accessibility_permissions():
    options = {"AXTrustedCheckOptionPrompt": True}
    return AXIsProcessTrustedWithOptions(options)

# Setup Observer for Application Events
def setup_accessibility_notifications(pid, callback):
    ax_app = AXUIElementCreateApplication(pid)
    observer_ref, err = AXObserverCreate(pid, callback, None)
    if err != 0:
        raise RuntimeError(f"AXObserverCreate failed with error: {err}")

    notifications = [
        "AXValueChanged", "AXTitleChanged", "AXFocusedUIElementChanged",
        "AXFocusedWindowChanged", "AXMainWindowChanged", "AXSelectedTextChanged",
        "AXLayoutChanged"
    ]

    for notification in notifications:
        AXObserverAddNotification(observer_ref, ax_app, notification, None)

    CFRunLoopAddSource(
        CFRunLoopGetCurrent(),
        AXObserverGetRunLoopSource(observer_ref),
        kCFRunLoopDefaultMode
    )

# UI Element Traversal
def traverse_element(element, depth=0, visited=None):
    if visited is None:
        visited = set()

    if depth > 100 or element in visited:
        return None

    visited.add(element)

    attributes_to_check = ["AXDescription", "AXValue", "AXLabel", "AXRoleDescription", "AXHelp"]
    unwanted_values = {"0", "", "\u200E", "3", "\u200F"}

    element_attributes = {}

    for attr in attributes_to_check:
        value_ptr, _ = AXUIElementCopyAttributeValue(element, attr, None)
        if value_ptr:
            value_str = str(value_ptr)
            if value_str and value_str not in unwanted_values:
                element_attributes[attr] = value_str

    # Get children and traverse recursively
    children_ptr, _ = AXUIElementCopyAttributeValue(element, "AXChildren", None)
    children_data = []

    if children_ptr:
        for child in children_ptr:
            child_data = traverse_element(child, depth + 1, visited)
            if child_data:
                children_data.append(child_data)

    return {
        'attributes': element_attributes,
        'children': children_data,
        'depth': depth
    }

# Event Callback with Debouncing
class DebounceHandler:
    def __init__(self, interval=0.2):
        self.interval = interval
        self.pending = []
        self.lock = threading.Lock()
        self.timer = None

    def handle_event(self, element):
        with self.lock:
            self.pending.append(element)
            if self.timer:
                self.timer.cancel()
            self.timer = threading.Timer(self.interval, self.process_events)
            self.timer.start()

    def process_events(self):
        with self.lock:
            elements = self.pending
            self.pending = []

        for element in elements:
            element_data = traverse_element(element)
            if element_data:
                print("Processed UI Element:", element_data)

if __name__ == '__main__':
    if not check_accessibility_permissions():
        print("Accessibility permissions not granted.")
        exit(1)

    pid = NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
    debounce_handler = DebounceHandler()

    def observer_callback(observer, element, notification, refcon):
        debounce_handler.handle_event(element)

    setup_accessibility_notifications(pid, observer_callback)

    print("Monitoring started.")
    CFRunLoopRun()

