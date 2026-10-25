---
expect_tools: [engineering_desk_status]
tags: [engineering_desk]
timeout: 180
---
## Prompt
What is waiting or stuck right now?

## Criteria
Uses engineering_desk_status. Lists pull requests by state with their numbers, names
any with blocking findings, and mentions open security items. Does not invent
pull requests.
