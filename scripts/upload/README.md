# Upload script

`upload_corpus.py` — the one-time local seed that pushes `DocumentCorpus/` into the
private Supabase Storage bucket. Storage only: it never writes the `documents`
registry, because the ingestion job owns that and reconciles against the bucket.

```
uv run scripts/upload/upload_corpus.py
```

Credentials come from the environment or from `ingestion/.env`. The script creates the
bucket private if it does not exist, and uploads with upsert, so re-running leaves the
bucket in the same state.

Run this before the ingestion job. After it, the bucket — not this repo — is the
source of truth for what the corpus contains.
