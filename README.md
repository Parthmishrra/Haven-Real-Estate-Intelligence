# Haven Real Estate Intelligence

Haven is a local-first workspace for exploring properties and asking grounded questions about real-estate documents. It combines a responsive browser interface with a FastAPI backend, local document retrieval, Ollama chat, and optional microphone input.

The application is designed for a single user working with leases, property details, community rules, and related notes. Answers are based on retrieved document excerpts and include source labels that can be opened and reviewed.

## What the application does

### Property workspace

- Browse properties with bedroom filters and property search.
- View property details such as location, bedrooms, bathrooms, area, rent, and description.
- Add custom properties from the interface.
- Mark properties as favorites.
- Keep each conversation and document search scoped to the selected property.

### Knowledge base

- Upload PDF, TXT, and Markdown documents in the local application.
- Assign every upload to a property and a document type such as Lease, Community rules, Property details, or Other.
- Inspect document text and page-level excerpts.
- Remove documents from the searchable knowledge base.
- Search selectable PDF text and UTF-8 text files. Scanned PDFs require OCR before upload; encrypted/password-protected PDFs are not supported.

### Document-grounded assistant

- Ask questions about rent, deposits, pets, parking, guests, repairs, notice periods, and other property-specific topics.
- Retrieve relevant excerpts using lexical search plus MiniLM embeddings and FAISS similarity search.
- Expand common real-estate terms to improve recall.
- Stream local Ollama responses over a WebSocket connection.
- Open citations to compare the answer with the exact retrieved source text.
- Fall back to labelled excerpts when the local model is unavailable or returns unusable citations.
- Abstain when the selected property has no relevant evidence instead of inventing an answer.

### Voice interaction

- Record microphone audio in the browser.
- Stream mono PCM16 audio at 16 kHz to the local backend.
- Transcribe completed utterances with faster-whisper on the machine.
- Send the transcript through the same property-scoped retrieval and chat workflow.
- Read answers aloud with an installed local browser/system voice.
- Optionally use Edge TTS when explicitly enabled; this sends response text to Microsoft's online service.

Voice is utterance-based: recording stops after a short pause or at the UI time limit. It is not a phone system, full-duplex call, or partial-transcript streaming service.

### Workspace and diagnostics

- Store properties, documents, chunks, embeddings, conversations, and traces in SQLite under `data/`.
- Show backend, model, retrieval, speech, memory, and tracing readiness in Settings.
- Export the current conversation as a text file.
- Optionally add Redis as a conversation cache and Phoenix as a local tracing backend.

## Demo mode and local mode

The static frontend can run as a browser-only preview. Demo mode stores fictional sample properties and TXT/Markdown documents in browser storage and performs extractive document search. It does not run Ollama, FAISS, Whisper, Redis, or Phoenix.

The complete local application is served by FastAPI. Local mode adds PDF ingestion, MiniLM/FAISS retrieval, Ollama answer generation, SQLite persistence, microphone transcription, and the backend API. Open `http://127.0.0.1:8000` to use this mode automatically.

Sample properties and documents are fictional demonstrations. They are not listings, offers, leases, or legal advice.

## Requirements

- Windows 10/11 or macOS/Linux.
- Python 3.11 or 3.12. Python 3.12 is recommended for the current dependency set.
- Ollama for local chat generation.
- Approximately 8 GB of free disk space for the Python packages and default local models.
- A modern browser for the interface and microphone features.

Node.js is only needed for the browser retrieval test. Docker is optional.

## Windows quick start

1. Install Python 3.12 and Ollama.
2. Start Ollama and download the default chat model:

   ```powershell
   ollama pull llama3.2:3b
   ```

3. From the project directory, run:

   ```powershell
   .\start-windows.cmd
   ```

   The script creates `.venv`, installs dependencies, creates `.env` from `.env.example` when needed, and starts FastAPI on loopback.

4. Open `http://127.0.0.1:8000`.

For manual setup:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\warmup.py
.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Keep Ollama running while using the local assistant. Stop FastAPI with Ctrl+C.

## macOS and Linux quick start

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
ollama pull llama3.2:3b
.venv/bin/python scripts/warmup.py
.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

The included `start-macos.sh` script provides the same setup flow for macOS.

## Model warmup

Run the warmup script before using the application offline:

```powershell
.venv\Scripts\python.exe scripts\warmup.py
```

It caches:

- Ollama's configured chat model, which must be pulled separately with `ollama pull`.
- `sentence-transformers/all-MiniLM-L6-v2` for semantic document retrieval.
- `Systran/faster-whisper-base.en` for English speech recognition.

The default Whisper configuration uses CPU and int8 computation, so CUDA is not required. Change `WHISPER_MODEL=base` for multilingual speech or use `tiny.en` on lower-memory machines.

## Configuration

Copy `.env.example` to `.env`. The important defaults are:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2:3b
ENABLE_CLOUD_LLM=false
RETRIEVAL_MODE=semantic
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
WHISPER_MODEL=base.en
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
TTS_PROVIDER=browser
DATA_DIR=data
```

The default configuration does not require an API key and does not enable paid cloud inference.

Optional settings include:

- `RETRIEVAL_MODE=lexical` for a lightweight search-only mode.
- `RERANK_ENABLED=true` to enable local FlashRank reranking. Its model downloads on first use.
- `MULTIQUERY_LLM=true` to generate additional search queries with the configured LLM.
- `REDIS_URL=redis://127.0.0.1:6379/0` to add Redis conversation caching.
- `PHOENIX_ENDPOINT=http://127.0.0.1:6006/v1/traces` to export local trace metadata.
- `HAVEN_API_TOKEN` to protect local API/WebSocket access with a bearer token.
- `ALLOWED_ORIGINS` to restrict browser origins. Keep the default loopback origins for local use.

Cloud LLM and online TTS are opt-in only. To use Groq, set `LLM_PROVIDER=groq`, `ENABLE_CLOUD_LLM=true`, `GROQ_API_KEY`, and `GROQ_MODEL`. To use Edge TTS, set `TTS_PROVIDER=edge` and optionally choose `EDGE_VOICE`. These options send data outside the computer and may incur limits or charges.

## Typical workflow

1. Select a property from the Assistant view.
2. Open Knowledge base and upload its lease, property information, or community rules.
3. Return to Assistant and ask a specific question.
4. Review the source labels beneath the answer.
5. Open a citation to inspect the retrieved page excerpt.
6. Export the conversation if you need a text record.

For a new property, add the property card first and then upload documents for that property. A property card by itself does not create lease or availability evidence.

## API and WebSocket interface

FastAPI exposes interactive documentation at `/api/docs`.

HTTP endpoints:

- `GET /api/health` — backend, model, retrieval, speech, memory, and tracing readiness.
- `GET /api/properties` — list properties.
- `POST /api/properties` — create a property.
- `GET /api/documents?property_id=...` — list documents, optionally scoped to a property.
- `POST /api/documents` — upload one PDF, TXT, or Markdown document.
- `GET /api/documents/{id}` — inspect a document and its excerpts.
- `DELETE /api/documents/{id}` — remove a document.
- `GET /api/traces` — list recent local activity traces.
- `DELETE /api/sessions/{session}` — clear persisted conversation memory.

The `/ws` WebSocket accepts a session hello message followed by chat or audio messages. Chat messages include `property_id` and question text. Audio messages use 16 kHz mono PCM16 frames between `audio_start` and `audio_end` events.

## Verification

Run the backend tests with lightweight lexical retrieval:

```powershell
$env:RETRIEVAL_MODE = 'lexical'
.venv\Scripts\python.exe -m pytest tests -q
```

Run the browser retrieval tests:

```powershell
node --test tests/browser-retrieval.test.mjs
```

Run the retrieval evaluation:

```powershell
.venv\Scripts\python.exe scripts\evaluate.py
.venv\Scripts\python.exe scripts\evaluate.py --semantic
```

The automated tests cover property isolation, abstention, citations, uploads, deletion, property creation, session isolation, WebSocket streaming, invalid-citation fallback, audio protocol validation, cancellation, and origin/token checks. They mock model output and speech recognition; hardware microphone quality and inference performance still depend on the computer.

## Security and scope

Haven is a single-user local application, not a production multi-tenant service. Keep it bound to `127.0.0.1` unless authentication, TLS, rate limiting, tenant isolation, upload controls, and backups have been added.

Uploaded documents are treated as untrusted evidence. The assistant explains document wording; it does not establish legal enforceability, verify availability, contact owners, book viewings, process payments, or perform transactions. Always review the cited document before making a lease, financial, or legal decision.

## Project structure

```text
backend/app.py          FastAPI routes, uploads, static hosting, and WebSocket protocol
backend/engine.py       Ollama/Groq adapters, retrieval orchestration, memory, speech, and tracing
backend/store.py        SQLite persistence, chunking, lexical search, embeddings, and FAISS retrieval
dist/                   Browser frontend and sample data
scripts/warmup.py       Cache the embedding and Whisper models
scripts/evaluate.py     Retrieval regression evaluation
tests/                  Python backend and browser retrieval tests
.env.example            Local configuration template
start-windows.cmd       Windows setup and startup script
start-macos.sh          macOS setup and startup script
docker-compose.yml      Optional Redis and Phoenix services
```