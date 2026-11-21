.PHONY: test quality-live

# Offline: no paid model requests or production MCP calls.
test:
	.venv/bin/python -m unittest discover -s tests -v

# Explicit opt-in only. Default: one case; at most three per invocation.
quality-live:
	.venv/bin/python -m x68k_knowledge.mcp_evaluation --live $(ARGS)
