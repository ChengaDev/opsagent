# Is OpsAgent right for you?

OpsAgent works best for **teams** — where CI failures need to be triaged quickly, root causes aren't always obvious, and the investigation result needs to reach multiple people (Slack, webhooks).

## Good fit

- Multiple contributors pushing to the same repo
- CI failures that block the team and need fast triage
- Slack or on-call integration to route the RCA to the right person
- Complex dependency graphs where the root cause isn't immediately visible in the log

## Less useful for

- Solo projects where you read the Actions log directly
- Simple repos where failures are always obvious
- Repos with very infrequent CI failures

## What OpsAgent is not

- It is not a log aggregator or observability platform
- It does not run continuously — it runs once per failure, as a pipeline step
- It does not replace your existing monitoring (Datadog, Grafana, etc.) — it complements it by explaining failures in plain language
