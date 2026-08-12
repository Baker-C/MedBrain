"""Pure scoring over saved traces: rank metrics, grounding, behavioral checks.

Everything here is hermetic — no network, no clock — and runs in CI. The judge is
the one answer scorer that costs a model call, and it lives outside this package.
"""
