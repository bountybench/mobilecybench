"""Custom agent: in-process Python loop.

Runs in the runner process and executes tools via ``docker exec`` into the
kali container. A future phase containerizes this under the BYO contract.
"""
