# Take-Home Assignment

**Time budget:** We expect this to take 6–10 focused hours. Do not spend more than 24 total hours on it. We value scoping discipline — a smaller, polished, well-reasoned submission beats a sprawling, half-finished one.

**AI tooling policy:** You are encouraged to use LLMs, coding assistants (Copilot, Cursor, Claude Code, etc.), and any other tools you'd use on the job. We are *not* testing whether you can write code without help. We *are* testing the judgment, taste, and rigor you bring that the tools don't supply on their own. Full disclosure requirements are below.

---

## 1\. The Task

Build **"MedBrain"** — a small web application that lets a clinical operations professional (e.g., a practice administrator, clinical research coordinator, or nurse educator) ask natural-language questions over a document knowledge base and get **grounded, cited answers**.

### Corpus

Use publicly available documents in the medical/healthcare domain. Assemble a corpus of **15–30 documents** (PDF and/or HTML), for example:

- CDC clinical guidelines (e.g., immunization schedules, infection-control guidance)  
- FDA drug labels / prescribing information from DailyMed  
- USPSTF screening recommendations  
- WHO or NIH clinical guidance documents  
- CMS billing/coding or compliance guidance

You choose the exact documents — your choices and how you handle their quirks (tables, scanned pages, nested sections) are part of the evaluation. Include the corpus (or a download script) in the repo.

### Core requirements (all required)

1. **Ingestion pipeline.** A repeatable, idempotent pipeline that parses, chunks, embeds, and indexes the corpus into a vector store of your choice (pgvector, Qdrant, Weaviate, Pinecone, Chroma, etc.). Re-running it should not duplicate data.  
     
2. **Retrieval \+ generation.** A chat or Q\&A interface where answers are:  
     
   - **Grounded** — generated only from retrieved context, with inline **citations** that link to the source document and section/page.  
   - **Honest** — when the corpus doesn't contain the answer, the app must say so rather than hallucinate. (We will test this deliberately.)  
   - **Responsibly scoped** — the app should present itself as a document-lookup tool for professionals, not a source of medical advice. A persistent disclaimer plus a refusal path for personal-medical-advice questions ("should I stop taking my medication?") is expected. How you handle this boundary is part of the evaluation.  
   - **Streamed** — token streaming to the UI, with sensible loading/error states.

   

3. **Evaluation harness.** This is the heart of the assignment. Build a small, runnable eval suite:  
     
   - A test set of **at least 15 question/expected-answer pairs** you author yourself, including at least 3 questions that are *unanswerable* from the corpus, at least 2 that require synthesizing across multiple documents, and at least 2 personal-medical-advice questions the app should decline.  
   - Automated scoring of retrieval quality (e.g., hit rate / MRR on expected sources) and answer quality (LLM-as-judge, string/fact matching, or another defensible approach).  
   - A single command (e.g., `make eval`) that runs it and prints a report.  
   - A short **failure analysis** in your design doc: which questions fail, why, and what you'd change.

   

4. **Web application.** A functional frontend (framework of your choice) and API backend. It doesn't need to be beautiful, but it should be usable: conversation history within a session, visible citations, graceful error handling.  
     
5. **Deployment.** Deployed and live-testable at a public URL (Vercel, Fly.io, Railway, Render, a cheap VPS — your call). Include the URL in your README. Keep API keys server-side.

### Stretch goals (pick at most one — depth over breadth)

- **Hybrid retrieval:** combine dense vectors with BM25/keyword search and rerank; show eval deltas before/after.  
- **Query decomposition:** detect and handle multi-hop questions by breaking them into sub-queries.  
- **Structured extraction:** a side endpoint that extracts a structured summary (JSON schema) from any single document, with schema validation.  
- **Observability:** tracing of each request (retrieved chunks, prompts, token counts, latency, cost) viewable per-conversation — via Langfuse, OpenTelemetry, or a simple homegrown view.

---

## 2\. Deliverables

1. **GitHub repository** (private; invite `<reviewer-github-handles>`), containing:  
     
   - Source code with a clear structure and a README covering: what it does, how to run it locally (one or two commands — Docker Compose or equivalent preferred), how to run ingestion, and how to run evals.  
   - CI that runs on push: linting, type checks, and at least a handful of meaningful unit/integration tests (not exhaustive coverage — the *right* tests).  
   - Sensible commit history. We read it. A single "initial commit" dump of 5,000 lines tells us nothing; a sequence of coherent commits tells us how you work.

   

2. **Live deployment URL.**  
     
3. **`DESIGN.md`** (1–2 pages, the most heavily weighted deliverable). Cover:  
     
   - Key architectural decisions and the **tradeoffs you rejected** (chunking strategy and size, embedding model, vector store, retrieval approach, prompt structure) — and *why*, given this corpus and use case.  
   - Failure analysis from your eval suite.  
   - What you would do next with another week: scaling to 10,000 documents, multi-tenancy, cost controls, latency budgets.  
   - Known shortcuts and technical debt you consciously took given the time box.

   

4. **`AI_USAGE.md`** (half a page). Which AI tools you used, for what, and — most importantly — **at least three concrete examples of where you overrode, corrected, or rejected AI-generated output and why.** "I accepted everything Cursor suggested" is a legitimate answer only if it's true, but it will show in the follow-up interview.

---

## 3\. How we evaluate

We share our rubric because we want you to spend time on what matters:

| Area | Weight | What we look for |
| :---- | :---- | :---- |
| AI/RAG engineering judgment | 30% | Chunking/retrieval choices fit the corpus; grounding, unanswerable-question handling, and medical-advice refusal actually work; citations are real, not decorative |
| Evaluation rigor | 25% | Eval suite is honest and runnable; failure analysis shows real understanding, not marketing |
| Design reasoning (`DESIGN.md`) | 20% | Tradeoffs articulated with specifics; scaling answers are credible |
| Software craft | 15% | Code structure, typing, tests, CI, secret handling, idempotent pipeline, commit history |
| Product sense & UX | 10% | The app is usable by the target persona; errors and latency are handled gracefully |

**What we are *not* grading:** visual polish, exhaustive test coverage, exotic model choices, or feature count. Do not gold-plate.

**Follow-up session:** If your submission advances, we'll do a 60-minute live session where you walk us through your code, we probe your decisions, and we ask you to make a small live modification (e.g., "add a relevance threshold below which the app declines to answer"). This is where AI-generated code without understanding becomes visible — make sure you can defend every significant line in your repo.

---

## 4\. Practical notes

- **Model access:** Use any provider. If API costs are a concern, tell us — we can provide a capped API key. Small/cheap models are fine; we're grading engineering, not model spend.  
- **Questions:** Email us anytime during the week. Asking good clarifying questions is a positive signal, not a negative one.  
- **Scope discipline:** If you're running over time, cut a stretch goal or simplify the UI — never cut the eval harness or the design doc.  
- **Your code stays yours.** We will not use your submission in our product, and we'll delete our copies after the process concludes.

Good luck — we're looking forward to seeing how you think.  
