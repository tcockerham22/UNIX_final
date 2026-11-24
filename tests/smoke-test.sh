#!/usr/bin/env bash
# Smoke test for the deployed system. Run it from outside the VPC (laptop or
# Cloud Shell), otherwise the blocked-port check doesn't mean anything:
#
#   LB_URL=http://<load-balancer-ip> ./tests/smoke-test.sh
#
# Settings (env vars):
#   LB_URL          required
#   ASK_PATH        RAG endpoint (default /api/ask)
#   ASK_FIELD       JSON field for the question (default question)
#   KNOWN_QUESTION  question with a known answer
#   EXPECTED        text the answer must contain (default lvcreate)
#   BLOCKED_PORTS   ports that must be unreachable (default 5432 11434)
#
# Assumes the endpoint takes {"question": "..."} and returns JSON that has a
# "sources" field. Change this once the real format is decided.

set -uo pipefail

: "${LB_URL:?set LB_URL, e.g. http://34.1.2.3}"
ASK_PATH="${ASK_PATH:-/api/ask}"
ASK_FIELD="${ASK_FIELD:-question}"
KNOWN_QUESTION="${KNOWN_QUESTION:-Which command creates a logical volume in LVM?}"
EXPECTED="${EXPECTED:-lvcreate}"
BLOCKED_PORTS="${BLOCKED_PORTS:-5432 11434}"

mkdir -p tests/results
LOG="tests/results/smoke-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

FAILED=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; FAILED=1; }

HOST="${LB_URL#*://}"
HOST="${HOST%%[:/]*}"

echo "=== Smoke test ==="
echo "date: $(date -Is)   target: $LB_URL"
echo "script written with AI assistance (Claude); reviewed by the team"
echo

echo "--- 1. Front end reachable through the load balancer ---"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$LB_URL/" || echo 000)"
[[ "$code" == "200" ]] && pass "GET / returned 200" || fail "GET / returned $code"

echo "--- 2. RAG answer with sources ---"
body="$(printf '{"%s": "%s"}' "$ASK_FIELD" "$KNOWN_QUESTION")"
ok=0
for attempt in 1 2 3; do
    resp="$(curl -s --max-time 180 -H 'Content-Type: application/json' -d "$body" "$LB_URL$ASK_PATH" || true)"
    if echo "$resp" | grep -qi -- "$EXPECTED"; then ok=1; break; fi
    echo "attempt $attempt did not contain '$EXPECTED'; retrying (LLM output varies)"
done
echo "response (first 500 chars): ${resp:0:500}"
[[ $ok -eq 1 ]] && pass "answer contains '$EXPECTED'" || fail "answer never contained '$EXPECTED'"
echo "$resp" | grep -qi "source" && pass "response includes sources" || fail "response has no sources field"

echo "--- 3. Internal ports are blocked from outside ---"
for port in $BLOCKED_PORTS; do
    if timeout 4 bash -c "exec 3<>/dev/tcp/$HOST/$port" 2>/dev/null; then
        fail "port $port is reachable from here (it must be blocked)"
    else
        pass "port $port is not reachable"
    fi
done

echo
[[ $FAILED -eq 0 ]] && echo "RESULT: PASS" || echo "RESULT: FAIL"
exit $FAILED
