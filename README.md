# Production-Ready RAG AI Agent in Python using PDF RAG with Inngest

Ask questions about your own PDFs. Upload a file through a Streamlit page, and it
gets chunked, embedded, and stored in Qdrant. Ask a question and it retrieves the
closest chunks and hands them to an LLM to answer from.

The backend is a FastAPI service and the vector database runs in Docker, so the
whole thing comes up locally with a few commands and no cloud dependencies beyond
the OpenAI API.

The part worth paying attention to is that ingestion and querying aren't plain
functions. They're Inngest workflows, so each step is durable: if the embedding
call fails halfway through, the retry picks up from the failed step instead of
re-reading the PDF and re-embedding everything you already paid for. Throttling
and rate limits are declared on the function rather than hand-rolled with a
semaphore somewhere.

## Stack

| Piece | Choice |
| --- | --- |
| Workflow engine | Inngest (durable steps, throttling, rate limiting) |
| API host | FastAPI — serves the Inngest functions |
| UI | Streamlit |
| PDF parsing + chunking | LlamaIndex `PDFReader` + `SentenceSplitter` |
| Embeddings | OpenAI `text-embedding-3-large`, 3072 dims |
| Answer model | `gpt-4o-mini` via Inngest's `step.ai.infer` |
| Vector store | Qdrant, running in Docker |
| Packaging | uv |

## FastAPI and Docker

FastAPI isn't here to expose REST endpoints you'd call by hand. Inngest needs an
HTTP endpoint it can reach to invoke registered functions, and
`inngest.fast_api.serve(app, inngest_client, [...])` in `main.py` mounts both
workflows under `/api/inngest`. The Inngest dev server discovers them by hitting
that URL. So FastAPI is the host process the workflow engine talks to — adding a
normal `@app.post("/query")` route alongside it would work fine if you wanted
direct HTTP access later.

Qdrant runs as a Docker container rather than an embedded or in-memory store. It
needs to survive restarts (re-embedding a large PDF costs real money), and the
container maps `qdrant_storage/` on the host into `/qdrant/storage` inside it so
the collection persists. The container also exposes Qdrant's own dashboard on
6333, which is useful for confirming that points actually landed after an
ingestion run.

## How the two workflows work

**`rag/ingest_pdf`** — two steps. `load-and-chunk` reads the PDF and splits it
(1000 tokens, 200 overlap). `embed-and-upsert` embeds the chunks and writes them
to Qdrant. Point IDs are `uuid5` over `{source_id}:{index}`, which makes
re-ingesting the same PDF overwrite the old points instead of duplicating them.
Throttled to 2 runs/minute, and rate-limited to one run per `source_id` every 4
hours so an accidental double-upload doesn't burn embedding credits.

**`rag/query_pdf_ai`** — embeds the question, pulls the top-k chunks from Qdrant,
pastes them into a prompt, and calls the model through `step.ai.infer`, which means
the LLM call itself is a durable step with its own retry. The system prompt
restricts it to answering from the supplied context. Returns the answer, the set of
source filenames, and how many chunks were used.

Streamlit doesn't call these directly. It sends an event, gets back an event ID,
then polls the local Inngest dev API (`/v1/events/{id}/runs`) until the run
reports Completed and reads the output off the run. That's why the dev server has
to be running for the UI to show answers.

## Files

```
main.py            FastAPI app + both Inngest functions
data_loader.py     PDF loading, chunking, OpenAI embeddings
vector_db.py       QdrantStorage — collection setup, upsert, search
custom_types.py    Pydantic models for step inputs/outputs
streamlit_app.py   upload form, question form, run polling
qdrant_storage/    Qdrant's on-disk data (mounted into the container)
```

Step return values are Pydantic models rather than dicts because Inngest
serializes step output between retries — the client is configured with
`PydanticSerializer()` and each `step.run` declares its `output_type`. Return a
bare dict and you lose the typing across the step boundary.

## Running it

Needs Python 3.12+, uv, Docker, and an OpenAI API key.

```bash
uv sync
echo "OPENAI_API_KEY=sk-..." > .env
```

Four processes. Separate terminals:

```bash
# 1. Qdrant (Docker)
docker run -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/qdrant_storage:/qdrant/storage" qdrant/qdrant

# 2. FastAPI, serving the Inngest functions
uv run uvicorn main:app --reload

# 3. Inngest dev server, pointed at the FastAPI app
npx inngest-cli@latest dev -u http://127.0.0.1:8000/api/inngest

# 4. Streamlit
uv run streamlit run streamlit_app.py
```

Streamlit comes up on 8501, the Inngest dashboard on 8288, Qdrant's own dashboard
on 6333. The Inngest one is the useful one while developing — you can see each
step, its output, and replay a run that failed.

Order matters a little: start the Docker container and FastAPI before the Inngest
dev server, otherwise it has nothing to register against and you'll have to
re-sync.

Upload a PDF, wait for the ingest run to go green in the dashboard, then ask a
question.

## Notes from building this

The rate limit on ingest is keyed on `source_id`, and `source_id` defaults to the
filename. Two different PDFs both named `report.pdf` will collide, and the second
one gets silently skipped for 4 hours. Hashing the file contents instead would fix
it.

`client.search()` on the Qdrant client is deprecated in favour of `query_points()`.
It still works but warns.

Uploaded PDFs are written to `uploads/` and the workflow receives an absolute path,
so the FastAPI process and the Streamlit process have to share a filesystem. Split
them across containers and ingestion breaks — you'd need to pass bytes or an object
storage key instead of a path.

Retrieval is dense-only, top-k, no reranking and no filtering by score. Ask
something the PDFs don't cover and it still retrieves five chunks and tries to
answer from them.

## Not built

- No delete or list operation — nothing removes a document once ingested.
- No conversation history; every question is standalone.
- Sources are filenames only, no page numbers, so answers can't be traced to a
  location in the document.
- The query polling loop times out at 120s and has no cancellation.
- Only Qdrant is containerised. FastAPI and Streamlit run on the host, so there's
  no `docker compose` file yet.

## Important

The `.env` file does not contain an OpenAI API key. Add your own before running:

```
OPENAI_API_KEY=sk-...
```