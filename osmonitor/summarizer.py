from __future__ import annotations

import os
import json
import asyncio
import base64
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, BinaryContent

try: 
    import logfire 
    logfire.configure()
    logfire.instrument_pydantic_ai()
except ImportError:
    print("Logfire not found. Skipping instrumentation.")
    pass

class TimelineEvent(BaseModel):
    timestamp: float
    event_type: str
    app_info: Dict[str, str]
    position: Dict[str, Any]
    screenshot_path: Optional[str] = None
    element_title: Optional[str] = ""
    element_role: Optional[str] = ""
    character: Optional[str] = None
    current_buffer: Optional[str] = None
    scroll_dx: Optional[int] = None
    scroll_dy: Optional[int] = None

class TimelineStats(BaseModel):
    total_events: int
    event_types: Dict[str, int]
    apps_used: Dict[str, int]
    time_spent: Dict[str, float]
    session_duration: float
    start_time: str
    end_time: str
    
class AppUsage(BaseModel):
    app_name: str
    window_titles: List[str]
    click_count: int
    keystroke_count: int
    scroll_count: int
    time_spent_seconds: float
    percentage_of_session: float
    
class ImageAnalysisResult(BaseModel):
    image_path: str
    content_description: str
    ui_elements: List[str]
    activity_type: str
    
class ActivitySummary(BaseModel):
    session_overview: str
    detailed_timeline: str
    application_usage: str
    interaction_patterns: str
    content_engagement: str
    visual_evidence: str
    conclusions: str

@dataclass
class SummarizerDeps:
    timeline_path: str = "./timeline.json"
    screenshots_dir: str = "./screenshots"

with open("prompts/summarizer_prompt.md", "r") as f:
    system_prompt = f.read()

with open("prompts/image_analyzer_prompt.md","r") as f:
    image_analyzer_prompt = f.read()


vision_agent = Agent(
    'anthropic:claude-3-5-sonnet-latest',
    system_prompt=image_analyzer_prompt
)

summarizer_agent = Agent(
    'anthropic:claude-3-5-sonnet-latest',
    system_prompt=system_prompt,
    deps_type=SummarizerDeps
)

@summarizer_agent.tool
async def load_timeline_data(ctx: RunContext, limit: Optional[int] = None) -> Dict:
    """
    Load and parse the timeline.json file containing user interaction data.
    
    Args:
        limit: Optional maximum number of events to load
        
    Returns:
        Dictionary with timeline events and basic statistics
    """
    try:
        timeline_path = os.environ.get("TIMELINE_PATH", "./timeline.json")
        events = []
        
        with open(timeline_path, "r") as f:
            for i, line in enumerate(f):
                if limit and i >= limit:
                    break
                if line.strip():
                    try:
                        event = json.loads(line)
                        events.append(event)
                    except json.JSONDecodeError:
                        continue
        
        # Calculate basic statistics
        event_types = {}
        apps_used = {}
        
        for event in events:
            # Count event types
            event_type = event.get("event_type", "unknown")
            event_types[event_type] = event_types.get(event_type, 0) + 1
            
            # Count app usage
            app_name = event.get("app_info", {}).get("app_name", "unknown")
            apps_used[app_name] = apps_used.get(app_name, 0) + 1
        
        # Calculate session duration
        if events:
            start_time = events[0].get("timestamp", 0)
            end_time = events[-1].get("timestamp", 0)
            session_duration = end_time - start_time
            
            # Format times for display
            start_time_str = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S")
            end_time_str = datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S")
        else:
            session_duration = 0
            start_time_str = "unknown"
            end_time_str = "unknown"
        
        return {
            "success": True,
            "events": events[:limit] if limit else events,
            "stats": {
                "total_events": len(events),
                "event_types": event_types,
                "apps_used": apps_used,
                "session_duration": session_duration,
                "start_time": start_time_str,
                "end_time": end_time_str
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@summarizer_agent.tool
async def analyze_app_usage(ctx: RunContext, events: List[Dict]) -> Dict:
    """
    Analyze application usage patterns from the timeline events.
    
    Args:
        events: List of timeline events
        
    Returns:
        Dictionary with application usage metrics
    """
    try:
        app_windows = {}
        app_events = {}
        app_time = {}
        current_app = None
        last_timestamp = None
        
        # Process events chronologically
        for event in events:
            timestamp = event.get("timestamp", 0)
            app_info = event.get("app_info", {})
            app_name = app_info.get("app_name", "unknown")
            window_title = app_info.get("window_title", "unknown")
            event_type = event.get("event_type", "unknown")
            
            # Track window titles for each app
            if app_name not in app_windows:
                app_windows[app_name] = set()
            app_windows[app_name].add(window_title)
            
            # Count events by type for each app
            if app_name not in app_events:
                app_events[app_name] = {"click": 0, "key_press": 0, "scroll": 0, "text_entry": 0, "other": 0}
            
            if event_type == "mouse_click":
                app_events[app_name]["click"] += 1
            elif event_type == "key_press":
                app_events[app_name]["key_press"] += 1
            elif event_type == "scroll":
                app_events[app_name]["scroll"] += 1
            elif event_type == "text_entry":
                app_events[app_name]["text_entry"] += 1
            else:
                app_events[app_name]["other"] += 1
            
            # Calculate time spent in each app
            if current_app and last_timestamp and current_app == app_name:
                time_diff = timestamp - last_timestamp
                app_time[current_app] = app_time.get(current_app, 0) + time_diff
            
            current_app = app_name
            last_timestamp = timestamp
        
        # Calculate total session time
        if events:
            total_time = events[-1].get("timestamp", 0) - events[0].get("timestamp", 0)
        else:
            total_time = 0
        
        # Format results
        app_usage = []
        for app_name in app_events.keys():
            time_spent = app_time.get(app_name, 0)
            percentage = (time_spent / total_time * 100) if total_time > 0 else 0
            
            app_usage.append({
                "app_name": app_name,
                "window_titles": list(app_windows.get(app_name, [])),
                "click_count": app_events[app_name]["click"],
                "keystroke_count": app_events[app_name]["key_press"] + app_events[app_name]["text_entry"],
                "scroll_count": app_events[app_name]["scroll"],
                "time_spent_seconds": time_spent,
                "percentage_of_session": percentage
            })
        
        # Sort by time spent
        app_usage.sort(key=lambda x: x["time_spent_seconds"], reverse=True)
        
        return {
            "success": True,
            "app_usage": app_usage,
            "total_session_time": total_time
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# Tool for the vision agent
@vision_agent.tool
async def get_image_content(ctx: RunContext, image_data: bytes) -> str:
    """
    This tool is for the vision agent to process the image.
    The agent will automatically use its vision capabilities to analyze the image.
    
    Args:
        image_data: Raw binary image data
        
    Returns:
        Analysis of the image content
    """
    # The vision agent will use its capabilities to analyze the image
    # No implementation needed here as the agent will handle it
    return "Image analysis results will be provided by the agent"

# Tool for the main agent to analyze screenshots
@summarizer_agent.tool
async def analyze_screenshot(ctx: RunContext, image_path: str) -> Dict:
    """
    Analyze a screenshot using Claude Vision to extract relevant information.
    
    Args:
        image_path: Path to the screenshot image
        
    Returns:
        Dictionary with analysis results including UI elements and content description
    """
    try:
        screenshots_dir = os.environ.get("SCREENSHOTS_DIR", "./screenshots")
        full_path = os.path.join(screenshots_dir, os.path.basename(image_path))
        if not os.path.exists(full_path):
            full_path = image_path  # Try using the path directly if not found
            
        if not os.path.exists(full_path):
            return {
                "success": False,
                "error": f"Image not found: {image_path}"
            }
            
        # Open and process the image
        with open(full_path, "rb") as img_file:
            image_data = img_file.read()
        
        # Use vision_agent to analyze the image - declarative approach
        # The image is passed as a BinaryContent input
        result = await vision_agent.run(
            prompt="Analyze this screenshot and provide insight on the visible content, UI elements, and activity type.",
            input=[BinaryContent(content=image_data, media_type="image/png")]
        )
        
        # Extract text response from the result
        response = result.data
        
        # Parse the response 
        sections = response.split("\n\n")
        
        content_description = sections[0] if len(sections) > 0 else "No description available"
        
        ui_elements = []
        activity_type = "Unknown"
        
        for section in sections:
            if "UI elements:" in section or "visible UI elements:" in section.lower():
                elements_text = section.split(":", 1)[1].strip()
                ui_elements = [elem.strip() for elem in elements_text.split("\n") if elem.strip()]
            elif "activity:" in section.lower() or "type of activity:" in section.lower():
                activity_text = section.split(":", 1)[1].strip()
                activity_type = activity_text.split("\n")[0].strip()
        
        return {
            "success": True,
            "image_path": image_path,
            "content_description": content_description,
            "ui_elements": ui_elements,
            "activity_type": activity_type,
            "full_analysis": response
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@summarizer_agent.tool
async def generate_activity_summary(ctx: RunContext,
                                   timeline_stats: Dict,
                                   app_usage: List[Dict],
                                   analyzed_screenshots: List[Dict]) -> Dict:
    """
    Generate a comprehensive activity summary based on all analyzed data.
    
    Args:
        timeline_stats: Statistics about the timeline events
        app_usage: Application usage metrics
        analyzed_screenshots: Results from screenshot analysis
        
    Returns:
        Dictionary with the formatted activity summary
    """
    try:
        # Create a detailed prompt for the agent to generate the summary
        prompt = f"""
        # Activity Summary Data

        ## Session Overview Stats
        - Duration: {timeline_stats.get('session_duration', 0)/60:.2f} minutes
        - Total Events: {timeline_stats.get('total_events', 0)}
        - Start Time: {timeline_stats.get('start_time', 'unknown')}
        - End Time: {timeline_stats.get('end_time', 'unknown')}
        - Event Types: {timeline_stats.get('event_types', {})}

        ## Application Usage
        {json.dumps(app_usage, indent=2)}

        ## Analyzed Screenshots (sample of {len(analyzed_screenshots)} screenshots)
        {json.dumps(analyzed_screenshots[:5] if len(analyzed_screenshots) > 5 else analyzed_screenshots, indent=2)}
        
        Based on this data, generate a comprehensive activity summary following the format in the system prompt.
        Focus on identifying patterns, workflows, and user behavior from the data.
        """
        
        # Instead of using Anthropic client directly, we'll use the agent declaratively
        # Create a summary agent with our system prompt
        summary_agent = Agent(
            'anthropic:claude-3-5-sonnet-latest',
            system_prompt=system_prompt
        )
        
        # Run the summary agent with the provided data
        result = await summary_agent.run(prompt=prompt)
        
        # Get the text response
        summary = result.data
        
        # Parse the summary into sections
        sections = {}
        current_section = None
        current_content = []
        
        for line in summary.split('\n'):
            if line.startswith('# '):
                continue  # Skip the title
            elif line.startswith('## '):
                if current_section and current_content:
                    sections[current_section] = '\n'.join(current_content)
                current_section = line[3:].strip().lower().replace(' ', '_')
                current_content = []
            else:
                if current_section:
                    current_content.append(line)
        
        # Add the last section
        if current_section and current_content:
            sections[current_section] = '\n'.join(current_content)
        
        return {
            "success": True,
            "summary": summary,
            "sections": sections
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

async def analyze_computer_activity(timeline_path="./timeline.json", 
                                   screenshots_dir="./screenshots", 
                                   output_file="activity_summary.md",
                                   sample_size=50):
    """
    Main function to analyze computer activity and generate a summary.
    
    Args:
        timeline_path: Path to the timeline.json file
        screenshots_dir: Directory containing screenshots
        output_file: File to save the summary to
        sample_size: Maximum number of events to analyze (for performance)
    """
    # Set environment variables for the tools
    os.environ["TIMELINE_PATH"] = timeline_path
    os.environ["SCREENSHOTS_DIR"] = screenshots_dir
    
    result = await summarizer_agent.run("analyze the timeline for me please")
    print(result.data)
    
async def test():
    result = await summarizer_agent.run("hi")
    print(result.data)

if __name__ == "__main__":
    # asyncio.run(test())
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate activity summaries from computer use monitoring data")
    parser.add_argument("--timeline", default="./timeline.json", help="Path to timeline.json file")
    parser.add_argument("--screenshots", default="./screenshots", help="Directory containing screenshots")
    parser.add_argument("--output", default="activity_summary.md", help="Output file for the summary")
    parser.add_argument("--sample", type=int, default=100, help="Number of events to analyze (default: 100)")
    
    args = parser.parse_args()
    
    asyncio.run(analyze_computer_activity(
        timeline_path=args.timeline,
        screenshots_dir=args.screenshots,
        output_file=args.output,
        sample_size=args.sample
    ))
