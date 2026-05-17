"""Host-side container lifecycle for the agent runtime. Brings up the kali
container, installs the CA, injects env, and mounts the codebase.

Both the in-process custom agent and the BYO external agents run inside the
container provisioned here.
"""
