"""Host-side container lifecycle for the agent runtime.

Imported by the harness (`harness.byo_agent.run_agent`) and the workflows
to bring up the kali container, install the CA, inject env, and mount
the codebase.  Both the in-process custom agent and the BYO external
agents share this layer.
"""
