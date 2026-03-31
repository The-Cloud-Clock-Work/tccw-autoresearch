---
description: Run the metric harness and report the result
allowed-tools: [Bash, Read]
---

Run the metric harness command from the marker config to check current progress.

1. Read `.autoresearch/config.yaml` to find the metric command
2. Run the metric command
3. Extract the metric value using the extract regex
4. Report: current value, baseline, direction, and whether it improved
