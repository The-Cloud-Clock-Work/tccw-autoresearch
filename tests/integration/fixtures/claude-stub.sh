#!/usr/bin/env bash
set -euo pipefail

# Fake claude CLI for integration testing.
# Parses --add-dir to find the worktree, fixes one ruff error in main.py,
# and outputs valid stream-json to stdout.

ADD_DIR=""
prev=""
for arg in "$@"; do
    if [[ "$prev" == "--add-dir" ]]; then
        ADD_DIR="$arg"
    fi
    prev="$arg"
done

# Fix one ruff error: replace "x=1" with "x = 1"
if [[ -n "$ADD_DIR" && -f "$ADD_DIR/main.py" ]]; then
    sed -i 's/^x=1/x = 1/' "$ADD_DIR/main.py"
fi

# Output valid stream-json
cat <<'JSONL'
{"type":"system","subtype":"init","session_id":"stub-session-001","model":"stub","permissionMode":"bypassPermissions","tools":["Edit","Read"]}
{"type":"assistant","message":{"content":[{"type":"text","text":"Fixed one ruff whitespace error in main.py"}],"usage":{"input_tokens":100,"output_tokens":50,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}
{"type":"result","subtype":"success","total_cost_usd":0.001,"duration_ms":1000,"duration_api_ms":500,"num_turns":1,"stop_reason":"end_turn","is_error":false,"result":"Fixed whitespace formatting in main.py: changed x=1 to x = 1","permission_denials":[]}
JSONL
