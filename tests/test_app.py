import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.store import Retriever, Store, chunks


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv('RETRIEVAL_MODE','lexical')
    monkeypatch.setenv('SEED_SAMPLE_DATA','true')
    monkeypatch.delenv('HAVEN_API_TOKEN', raising=False)
    from backend.app import create_app
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def test_property_isolation_and_unknown(app):
    r=app.state.engine.retriever
    sources,_=r.search('rent security deposit','cedar')
    assert sources and all(s['property_id']=='cedar' for s in sources)
    assert any('32,000' in s['text'] for s in sources)
    assert all('48,000' not in s['text'] for s in sources)
    assert r.search('intergalactic spaceship flux capacitor','canopy')[0]==[]


def test_upload_read_delete_and_no_path_traversal(client,app):
    r=client.post('/api/documents',data={'property_id':'canopy','kind':'Lease'},files={'file':('../../escape.txt',b'The additional refundable bicycle deposit is 777 rupees.','text/plain')})
    assert r.status_code==200
    doc=r.json()
    assert doc['name']=='escape.txt'
    assert client.get('/api/documents/'+doc['id']).json()['excerpts'][0]['page']==1
    sources,_=app.state.engine.retriever.search('bicycle deposit','canopy')
    assert any(s['doc_id']==doc['id'] for s in sources)
    assert client.delete('/api/documents/'+doc['id']).status_code==200
    assert client.get('/api/documents/'+doc['id']).status_code==404
    assert all(s['doc_id']!=doc['id'] for s in app.state.engine.retriever.search('bicycle deposit','canopy')[0])


def test_invalid_uploads(client):
    assert client.post('/api/documents',data={'property_id':'canopy'},files={'file':('x.exe',b'bad')}).status_code==415
    assert client.post('/api/documents',data={'property_id':'canopy'},files={'file':('blank.txt',b'  ')}).status_code==422
    assert client.post('/api/documents',data={'property_id':'unknown'},files={'file':('ok.txt',b'hello')}).status_code==400
    assert client.post('/api/documents',data={'property_id':'canopy'},files={'file':('bad.pdf',b'not a pdf')}).status_code==422


def test_add_property(client):
    r=client.post('/api/properties',json={'name':'My flat','location':'Bengaluru','beds':2,'baths':2,'area':1200,'rent':40000})
    assert r.status_code==200 and not r.json()['sample']
    property_id=r.json()['id']
    assert any(p['id']==property_id for p in client.get('/api/properties').json())
    assert client.post('/api/documents',data={'property_id':property_id},files={'file':('info.txt',b'Rent is 40000 rupees.')}).status_code==200


def test_pdf_page_citations(client):
    # A minimal two-page PDF with real selectable text, no external fixture.
    import io
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer=PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    for phrase in ['Page one rent is 5000.', 'Page two parking includes two bays.']:
        page=writer.add_blank_page(width=400,height=400)
        stream=DecodedStreamObject();stream.set_data(f'BT /F1 12 Tf 20 300 Td ({phrase}) Tj ET'.encode())
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        page[NameObject('/Contents')]=writer._add_object(stream)
    output=io.BytesIO();writer.write(output)
    r=client.post('/api/documents',data={'property_id':'canopy'},files={'file':('two-pages.pdf',output.getvalue(),'application/pdf')})
    assert r.status_code==200
    assert [(s['page'],s['text']) for s in r.json()['excerpts']]==[(1,'Page one rent is 5000.'),(2,'Page two parking includes two bays.')]


def test_memory_scoped_by_session_and_property(app):
    s=app.state.store
    s.remember('session-one','canopy','user','private-canopy')
    s.remember('session-two','canopy','user','other-person')
    assert s.history('session-one','cedar')==[]
    assert s.history('session-one','canopy')==[{'role':'user','content':'private-canopy'}]


def open_ws(client):
    return client.websocket_connect('/ws',headers={'origin':'http://127.0.0.1:8000'})


def test_websocket_stream_and_citations(client,app,monkeypatch):
    async def tokens(messages):
        assert 'UNTRUSTED SOURCE EXCERPTS' in messages[-1]['content']
        yield 'The sample rent is ₹48,000 '
        yield '[S1].'
    monkeypatch.setattr(app.state.engine,'llm_tokens',tokens)
    with open_ws(client) as socket:
        socket.send_json({'session':'test-session-123'})
        assert socket.receive_json()['type']=='ready'
        socket.send_json({'type':'chat','property_id':'canopy','text':'What is the rent?'})
        events=[]
        for _ in range(20):
            event=socket.receive_json();events.append(event)
            if event['type']=='done':break
        assert events[-1]['type']=='done'
        assert events[-1]['mode']=='generated'
        assert events[-1]['sources']
        assert any(e['type']=='token' for e in events)
        assert client.get('/api/traces').json()[0]['sources']>0


@pytest.mark.parametrize('fault',['unavailable','invalid_citation'])
def test_model_failure_returns_honest_excerpts(client,app,monkeypatch,fault):
    async def failing(messages):
        if fault=='unavailable':
            raise RuntimeError('Offline')
        yield 'Made-up claim [S999].'
    monkeypatch.setattr(app.state.engine,'llm_tokens',failing)
    with open_ws(client) as socket:
        socket.send_json({'session':'test-fallback-123'});socket.receive_json()
        socket.send_json({'type':'chat','property_id':'canopy','text':'What is the deposit?'})
        while True:
            event=socket.receive_json()
            if event['type']=='done':break
        assert event['mode']=='extractive'
        assert '[S999]' not in event['text']
        assert 'unavailable or returned unusable citations' in event['text']


def test_voice_pcm_protocol(client,app,monkeypatch):
    monkeypatch.setattr(app.state.engine,'transcribe',lambda raw:'What is the rent?' if len(raw)==32000 else '')
    async def tokens(messages):yield 'The rent is ₹48,000 [S1].'
    monkeypatch.setattr(app.state.engine,'llm_tokens',tokens)
    with open_ws(client) as socket:
        socket.send_json({'session':'test-voice-session'});socket.receive_json()
        socket.send_json({'type':'audio_start','property_id':'canopy','sample_rate':16000})
        assert socket.receive_json()['type']=='recording'
        for _ in range(10):socket.send_bytes(b'\x00\x00'*1600)
        socket.send_json({'type':'audio_end'})
        events=[]
        for _ in range(20):
            event=socket.receive_json();events.append(event)
            if event['type']=='speak':break
        assert any(e['type']=='transcript' for e in events)
        assert any(e['type']=='done' for e in events)
        assert events[-1]['type']=='speak'


def test_cancellation(client,app,monkeypatch):
    async def slow(messages):
        yield 'Starting '
        await asyncio.sleep(60)
        yield 'unwanted late response [S1]'
    monkeypatch.setattr(app.state.engine,'llm_tokens',slow)
    with open_ws(client) as socket:
        socket.send_json({'session':'test-cancel-123'});socket.receive_json()
        socket.send_json({'type':'chat','property_id':'canopy','text':'rent'})
        while socket.receive_json()['type']!='token':pass
        socket.send_json({'type':'cancel'})
        assert socket.receive_json()['type']=='cancelled'
    assert app.state.store.traces()==[]


def test_origin_and_token_controls(tmp_path,monkeypatch):
    monkeypatch.setenv('HAVEN_API_TOKEN','test-secret')
    from backend.app import create_app
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/properties').status_code==401
        assert c.get('/api/properties',headers={'Authorization':'Bearer test-secret'}).status_code==200
        assert c.get('/api/properties',headers={'Authorization':'Bearer test-secret','Origin':'https://untrusted.example'}).status_code==403
        with pytest.raises(Exception):
            with c.websocket_connect('/ws',headers={'origin':'https://untrusted.example'}) as socket:
                socket.send_json({'session':'test-session','token':'test-secret'})


def test_chunker_preserves_tail():
    text='important clause. '*100+'FINAL-CLAUSE'
    result=list(chunks(text))
    assert len(result)>1 and result[-1].endswith('FINAL-CLAUSE')
    assert all(len(p)<=650 for p in result)
