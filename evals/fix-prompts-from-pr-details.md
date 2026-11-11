---
expect_tools: [pr_details]
tags: [engineering_desk]
# The tools answer signed-in people only: admin@localhost holds the engineering_desk grant (README).
run_as: admin@localhost
timeout: 180
---
## Prompt
How do I fix the Engineering Desk findings on kestrel-oak/storefront PR 101?

## Criteria
Reads pr_details and gives the open findings with their fix prompts, or says
the pull request has not been reviewed yet. Explains that the developer's own
coding agent does the fixing and pushing. Does not offer to dismiss findings.
