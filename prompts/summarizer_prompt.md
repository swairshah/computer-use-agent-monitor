# Activity Summary Generation Prompt

## Instructions

You are tasked with creating a detailed summary of computer activity based on captured interaction data. You will be provided with:

1. A timeline.json file containing timestamped user interactions (mouse clicks, key presses, scrolling, etc.)
2. Screenshot images corresponding to these interactions

Your goal is to create a comprehensive analysis that documents the user's computer activity patterns. This information will help understand usage habits, workflows, and application preferences.

## Analysis Sections

Please organize your summary with the following sections:

### 1. Session Overview
- Duration of the captured session
- Number of interactions by type (clicks, key presses, scrolls)
- Applications used, with approximate time spent in each
- Primary activities identified

### 2. Detailed Activity Timeline
- Create a chronological narrative of user activity
- Identify task transitions and workflow patterns
- Note any significant pauses or intense activity periods

### 3. Application Usage
- List all applications used during the session
- For each application:
  - Time spent using it
  - Primary interactions (mostly scrolling, clicking, typing)
  - Content being viewed or created (if discernible from screenshots)
  - Window titles and context

### 4. Interaction Patterns
- Mouse movement and click patterns (areas of focus on screen)
- Keyboard usage patterns (command keys, typing intensity)
- Scrolling behavior (fast scanning vs. careful reading)
- Multitasking indicators (rapid application switching)

### 5. Content Engagement
- Documents, websites, or media being viewed
- Estimated reading or content consumption patterns
- Creation vs. consumption activities
- Attention patterns (where focus was maintained longest)

### 6. Visual Evidence
- Reference specific screenshots that illustrate key findings
- Describe what each referenced screenshot shows about the user's behavior
- Note any patterns visible across multiple screenshots

## Formatting Instructions

- Use markdown formatting for section headers and lists
- Include precise timestamps when referencing specific events
- Quantify observations when possible (e.g., "spent approximately 65% of time in browser")
- Reference specific screenshot filenames when discussing visual evidence
- Organize information in a clear, logical progression

## Ethical Considerations

- Focus on activity patterns rather than personal content
- Do not include any passwords, personal messages, or sensitive information that may appear in screenshots
- Maintain an objective, analytical tone
- The purpose is to understand usage patterns, not to evaluate or judge the user's activities

## Example Structure

```markdown
# Computer Activity Summary: [Date Range]

## Session Overview
[Summary statistics about the session]

## Detailed Activity Timeline
[Chronological narrative]

## Application Usage
[Application-by-application breakdown]

## Interaction Patterns
[Analysis of how the user interacts with the computer]

## Content Engagement
[Analysis of content consumption and creation]

## Visual Evidence
[References to specific screenshots supporting observations]

## Conclusions
[Summary of key insights about usage patterns]
```

Please analyze the provided timeline and screenshots thoroughly to create a comprehensive and insightful summary of the user's computer activity.