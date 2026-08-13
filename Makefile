# Root entrypoint for the eval harness. The harness is a backend package and owns
# all of the work; this target only spares the reader from knowing that.
#
# A full run drives 18 cases x 4 retrieval configurations through the real pipeline
# and judges every answer, so it needs backend/.env and an ingested corpus. Traces
# and the report land in backend/eval/runs/; the report also prints here.
#
# To re-score a saved run without touching the pipeline:
#   cd backend && uv run python -m eval --score-only eval/runs/<stamp>.json

.PHONY: eval

eval:
	cd backend && uv run python -m eval
