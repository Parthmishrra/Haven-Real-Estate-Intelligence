"""Single-user, loopback-first FastAPI service and PCM WebSocket protocol."""
import asyncio
import io
import json
import os
import re
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader
from pydantic import BaseModel, Field

from .engine import Engine
from .store import Retriever, Store

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')


class PropertyInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=150)
    type: str = 'Apartment'
    beds: int = Field(ge=0, le=30)
    baths: int = Field(ge=0, le=30)
    area: int = Field(ge=1, le=1000000)
    rent: int = Field(ge=0, le=100000000)
    description: str = Field(default='', max_length=1000)


def create_app(data_dir=None):
    app = FastAPI(title='Haven API', version='1.0.0', docs_url='/api/docs', redoc_url=None)
    origins = [s.strip() for s in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:8000,http://localhost:8000').split(',') if s.strip()]
    token = os.getenv('HAVEN_API_TOKEN','')
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=['GET','POST','DELETE'], allow_headers=['Content-Type','Authorization'])
    store = Store(data_dir or os.getenv('DATA_DIR',str(ROOT / 'data')))
    fixture = json.loads((ROOT / 'dist/assets/sample-data.json').read_text())
    if os.getenv('SEED_SAMPLE_DATA','true').lower() == 'true':
        store.seed(fixture)
    retriever = Retriever(store, os.getenv('RETRIEVAL_MODE','semantic'), os.getenv('EMBEDDING_MODEL','sentence-transformers/all-MiniLM-L6-v2'), os.getenv('RERANK_ENABLED','false').lower()=='true')
    engine = Engine(store, retriever)
    app.state.store, app.state.engine = store, engine

    @app.middleware('http')
    async def guard(request: Request, call_next):
        from starlette.responses import JSONResponse
        if request.url.path.startswith('/api/') and request.method != 'OPTIONS':
            origin = request.headers.get('origin')
            if origin and origin not in origins:
                return JSONResponse({'detail':'Origin is not allowed.'}, status_code=403)
            if token and not secrets.compare_digest(request.headers.get('authorization',''), 'Bearer '+token):
                return JSONResponse({'detail':'A local API token is required.'}, status_code=401)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def validate_property(property_id):
        if property_id not in {p['id'] for p in store.properties()}:
            raise HTTPException(400, 'Select a known property.')

    @app.get('/api/health')
    async def health():
        return await engine.health()

    @app.get('/api/properties')
    def properties():
        return store.properties()

    @app.post('/api/properties')
    def add_property(prop: PropertyInput):
        return store.add_property(prop.model_dump())

    @app.get('/api/documents')
    def documents(property_id: str | None = None):
        return store.documents(property_id)

    @app.get('/api/documents/{doc_id}')
    def document(doc_id: str):
        doc = store.document(doc_id)
        if not doc:
            raise HTTPException(404, 'Document not found.')
        return doc

    @app.delete('/api/documents/{doc_id}')
    def delete_document(doc_id: str):
        if not store.delete(doc_id):
            raise HTTPException(404, 'Document not found.')
        return {'deleted':True}

    @app.post('/api/documents')
    async def upload(file: UploadFile = File(...), property_id: str = Form(...), kind: str = Form('Other')):
        validate_property(property_id)
        name = Path((file.filename or 'document').replace('\\','/')).name[:160]
        suffix = Path(name).suffix.lower()
        if suffix not in {'.pdf','.txt','.md'}:
            raise HTTPException(415,'Use PDF, TXT or Markdown.')
        raw = await file.read(10*1024*1024 + 1)
        await file.close()
        if len(raw) > 10*1024*1024:
            raise HTTPException(413,'The document limit is 10 MB.')

        def parse():
            if suffix == '.pdf':
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted:
                    raise ValueError('Remove password protection before uploading.')
                if len(reader.pages) > 200:
                    raise ValueError('Use PDFs of 200 pages or fewer.')
                return [page.extract_text() or '' for page in reader.pages]
            return [raw.decode('utf-8-sig')]
        try:
            pages = await asyncio.to_thread(parse)
        except Exception as exc:
            raise HTTPException(422, 'Could not read the file. Use a valid, unencrypted PDF or UTF-8 text file.') from exc
        if not any(p.strip() for p in pages):
            raise HTTPException(422,'No selectable text found. OCR scanned PDFs before uploading.')
        if sum(map(len,pages)) > 1_000_000:
            raise HTTPException(413,'Too much extracted text; split the document.')
        doc_id = await asyncio.to_thread(store.add_document, name, property_id, kind[:40], pages)
        return store.document(doc_id)

    @app.get('/api/traces')
    def traces():
        return store.traces()

    @app.delete('/api/sessions/{session}')
    def clear_session(session: str):
        engine.clear_session(session, [p['id'] for p in store.properties()])
        return {'cleared':True}

    @app.websocket('/ws')
    async def ws(socket: WebSocket):
        if socket.headers.get('origin') not in origins:
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            hello = await asyncio.wait_for(socket.receive_json(), 10)
            if token and not secrets.compare_digest(str(hello.get('token','')), token):
                await socket.close(code=1008)
                return
            session = str(hello.get('session',''))
            if not re.fullmatch(r'[A-Za-z0-9-]{8,80}', session):
                await socket.close(code=1008)
                return
        except Exception:
            await socket.close(code=1008)
            return
        send_lock = asyncio.Lock()
        task = None
        pcm = bytearray()
        recording = None

        async def send(event):
            async with send_lock:
                await socket.send_json(event)

        async def cancel():
            nonlocal task
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            task = None

        async def turn(question, property_id, voice, audio=None):
            try:
                if audio is not None:
                    await send({'type':'status','message':'Transcribing your voice…'})
                    question = await asyncio.to_thread(engine.transcribe, audio)
                    if not question:
                        await send({'type':'error','message':'No speech detected. Try again or type your question.'})
                        return
                    await send({'type':'transcript','text':question})
                answer = await engine.answer(question, property_id, session, send)
                if voice:
                    await engine.speak(answer, send)
            except asyncio.CancelledError:
                raise
            except Exception:
                await send({'type':'error','message':'This turn could not finish. Check the local model setup, or try typing your question.'})

        await send({'type':'ready'})
        try:
            while True:
                event = await socket.receive()
                if event['type'] == 'websocket.disconnect':
                    break
                if event.get('bytes') is not None:
                    data = event['bytes']
                    if recording is None:
                        continue
                    if len(data) % 2 or len(pcm)+len(data) > 16000*2*30:
                        recording = None
                        pcm.clear()
                        await send({'type':'error','message':'Audio must be 16 kHz mono PCM16, at most 30 seconds per turn.'})
                    else:
                        pcm.extend(data)
                    continue
                try:
                    if len(event.get('text','')) > 12_000:
                        raise ValueError('Message is too long.')
                    message = json.loads(event.get('text','{}'))
                    kind = message.get('type')
                    if kind in {'cancel','chat','audio_start'}:
                        await cancel()
                    if kind == 'cancel':
                        pcm.clear()
                        recording = None
                        await send({'type':'cancelled'})
                        continue
                    if kind in {'chat','audio_start'}:
                        validate_property(message.get('property_id'))
                        if kind == 'chat':
                            question = str(message.get('text','')).strip()
                            if not question or len(question)>4000:
                                raise ValueError('Enter a question of 1–4,000 characters.')
                            task = asyncio.create_task(turn(question, message['property_id'], bool(message.get('voice'))))
                        else:
                            if message.get('sample_rate') != 16000:
                                raise ValueError('Audio sample rate must be 16000.')
                            pcm.clear()
                            recording = message['property_id']
                            await send({'type':'recording'})
                    elif kind == 'audio_end':
                        if recording and len(pcm)>=3200:
                            task = asyncio.create_task(turn('', recording, True, bytes(pcm)))
                        else:
                            await send({'type':'error','message':'Recording was too short. Try again.'})
                        recording = None
                        pcm.clear()
                except (ValueError, HTTPException):
                    await send({'type':'error','message':'Invalid request. Select a property and enter a valid question.'})
        except WebSocketDisconnect:
            pass
        finally:
            await cancel()

    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
    return app


app = create_app()
