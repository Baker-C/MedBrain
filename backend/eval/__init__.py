"""The eval harness: authored cases, scoring, and the report.

Runs in-process — it imports the same retrieval and chat core the query operation
composes, so it measures the path users get without needing a running server. Kept
out of the deployed image; see DESIGN.md's eval-harness section.
"""
