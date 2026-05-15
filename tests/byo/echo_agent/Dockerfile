# Echo agent: minimal BYO-contract stub for the contract self-test.
#
# Reads /app/task.json, writes a known exploit.sh + conversation.jsonl +
# result.json, exits. Used in tests/byo/test_contract_self.py to exercise
# harness.byo_agent.run_agent end-to-end without depending on a real LLM CLI.
#
# Tests typically MOCK rather than build this image (faster, no daemon),
# but it ships as a reference for labs and as an option for integration runs
# (docker build -t cybench/mobilecybench-echo:test tests/byo/echo_agent/).

FROM alpine:3.20

RUN apk add --no-cache bash jq

COPY run-agent.sh /run-agent.sh
RUN chmod +x /run-agent.sh

# Explicit ENTRYPOINT [] in case alpine ever ships one.
ENTRYPOINT []
