#!/bin/bash

docker cp $(dirname "$0")/ghidra_example.sh ghidra-mcp-test:/tmp/ghidra_example.sh
docker exec ghidra-mcp-test chmod +x /tmp/ghidra_example.sh

if docker exec -it ghidra-mcp-test /tmp/ghidra_example.sh; then
  echo "Ghidra test passed"
else
  echo "Ghidra test failed"
  exit 1
fi