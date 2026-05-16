"""Custom agent: in-process Python loop (Phase 1 dispatch path).

The custom dispatch path runs as Python in the runner process and executes
tools via ``docker exec`` into the kali container. Phase 2 (design §10)
containerizes this under the BYO contract, at which point ``agent/custom/``
will gain its own ``Dockerfile`` + ``run-agent.sh``.
"""
