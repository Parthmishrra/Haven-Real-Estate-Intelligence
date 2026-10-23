"""SQLite source of truth. Never deserialize a client-supplied vector index."""
import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

STOP = set('a an the is are was were do does can could would should what which how much many tell me about for of to in on and or with it this that my please be have has i we you from at there your'.split())


def tokens(text):
    return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if t not in STOP]


def chunks(text, size=650, overlap=100):
    """Small character windows keep MiniLM inputs below its usual token limit."""
    text = re.sub(r'[ \t]+', ' ', text).strip()
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = max(text.rfind('\n', start + size // 2, end), text.rfind('. ', start + size // 2, end))
            if boundary > start:
                end = boundary + 1
        yield text[start:end].strip()
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


class Store:
    def __init__(self, directory):
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = self.path / 'haven.sqlite3'
        self.lock = threading.RLock()
        self.revision = 0
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT, property_id TEXT, kind TEXT, pages INTEGER, created REAL);
            CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, doc_id TEXT REFERENCES documents(id) ON DELETE CASCADE, page INTEGER, text TEXT);
            CREATE TABLE IF NOT EXISTS vectors(chunk_id TEXT, model TEXT, data BLOB, PRIMARY KEY(chunk_id,model), FOREIGN KEY(chunk_id) REFERENCES chunks(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS messages(session TEXT, property_id TEXT, role TEXT, content TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS traces(id TEXT PRIMARY KEY, session TEXT, property_id TEXT, provider TEXT, mode TEXT, latency_ms INTEGER, sources INTEGER, status TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS properties(id TEXT PRIMARY KEY,data TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        return db

    def seed(self, fixture):
        with self.connect() as db:
            for prop in fixture['properties']:
                db.execute('INSERT OR IGNORE INTO properties VALUES(?,?)', (prop['id'], json.dumps(prop)))
        with self.connect() as db:
            if db.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
                return
        for doc in fixture['documents']:
            self.add_document(doc['name'], doc['property_id'], doc['kind'], doc['pages'], doc['id'])
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('seeded','1')")

    def properties(self):
        with self.connect() as db:
            return [json.loads(r['data']) for r in db.execute('SELECT data FROM properties ORDER BY rowid')]

    def add_property(self, data):
        data = dict(data, id=uuid.uuid4().hex, sample=False, image='assets/canopy.jpg')
        with self.connect() as db:
            db.execute('INSERT INTO properties VALUES(?,?)', (data['id'], json.dumps(data)))
        return data

    def add_document(self, name, property_id, kind, pages, doc_id=None):
        doc_id = doc_id or uuid.uuid4().hex
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)', (doc_id, name, property_id, kind, len(pages), time.time()))
            for page, text in enumerate(pages, 1):
                for part in chunks(text):
                    if part:
                        db.execute('INSERT INTO chunks VALUES(?,?,?,?)', (uuid.uuid4().hex, doc_id, page, part))
            self.revision += 1
        return doc_id

    def documents(self, property_id=None):
        with self.connect() as db:
            query = 'SELECT d.*,COUNT(c.id) AS chunks FROM documents d LEFT JOIN chunks c ON c.doc_id=d.id'
            args = []
            if property_id:
                query += ' WHERE property_id=?'
                args.append(property_id)
            return [dict(row) for row in db.execute(query + ' GROUP BY d.id ORDER BY d.created DESC', args)]

    def document(self, doc_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not row:
                return None
            doc = dict(row)
            doc['excerpts'] = [dict(r) for r in db.execute('SELECT page,text FROM chunks WHERE doc_id=? ORDER BY rowid', (doc_id,))]
            return doc

    def delete(self, doc_id):
        with self.lock, self.connect() as db:
            count = db.execute('DELETE FROM documents WHERE id=?', (doc_id,)).rowcount
            self.revision += 1
            return count

    def all_chunks(self, property_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT c.*,d.name,d.kind,d.property_id FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE d.property_id=?', (property_id,))]

    def history(self, session, property_id):
        with self.connect() as db:
            rows = db.execute('SELECT role,content FROM messages WHERE session=? AND property_id=? ORDER BY created DESC LIMIT 12', (session, property_id)).fetchall()
            return [dict(row) for row in reversed(rows)]

    def remember(self, session, property_id, role, content):
        with self.connect() as db:
            db.execute('INSERT INTO messages VALUES(?,?,?,?,?)', (session, property_id, role, content, time.time()))

    def clear_session(self, session):
        with self.connect() as db:
            db.execute('DELETE FROM messages WHERE session=?', (session,))

    def trace(self, session, property_id, provider, mode, latency_ms, sources, status):
        row = dict(id=uuid.uuid4().hex[:12], session=session, property_id=property_id, provider=provider, mode=mode, latency_ms=latency_ms, sources=sources, status=status, created=time.time())
        with self.connect() as db:
            db.execute('INSERT INTO traces VALUES(:id,:session,:property_id,:provider,:mode,:latency_ms,:sources,:status,:created)', row)
        return row

    def traces(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM traces ORDER BY created DESC LIMIT 100')]


ALIASES = {
    'pet': 'pets dog cat animal policy', 'pets': 'pet dog cat animal policy',
    'deposit': 'security deposit refund deductions', 'rent': 'monthly rent payment due fee',
    'notice': 'termination vacate notice period lease', 'leave': 'terminate notice vacate move out',
    'parking': 'parking vehicle reserved bay', 'hoa': 'association maintenance community rules',
    'guest': 'visitors guests overnight stay', 'repair': 'maintenance repairs responsibility',
}


def expand_query(question):
    """Deterministic domain expansions avoid an extra LLM round-trip for voice."""
    extra = [ALIASES[t] for t in tokens(question) if t in ALIASES]
    return list(dict.fromkeys([question] + extra))[:4]


class Retriever:
    def __init__(self, store, mode='semantic', model='sentence-transformers/all-MiniLM-L6-v2', rerank=False):
        self.store, self.mode, self.model_name = store, mode, model
        self.embedder = None
        self.reranker = None
        self.rerank_enabled = rerank
        self.lock = threading.RLock()
        self.cache = {}
        self.status = 'not loaded' if mode == 'semantic' else 'lexical'

    def _index(self, property_id, rows):
        import numpy as np
        import faiss
        from sentence_transformers import SentenceTransformer
        key = (property_id, self.store.revision)
        if key in self.cache:
            return self.cache[key]
        if self.embedder is None:
            self.embedder = SentenceTransformer(self.model_name)
        with self.store.connect() as db:
            saved = {r['chunk_id']: r['data'] for r in db.execute('SELECT * FROM vectors WHERE model=?', (self.model_name,))}
        missing = [r for r in rows if r['id'] not in saved]
        if missing:
            vectors = self.embedder.encode([r['text'] for r in missing], normalize_embeddings=True, convert_to_numpy=True).astype('float32')
            with self.store.connect() as db:
                for row, vec in zip(missing, vectors):
                    saved[row['id']] = vec.tobytes()
                    db.execute('INSERT OR REPLACE INTO vectors VALUES(?,?,?)', (row['id'], self.model_name, vec.tobytes()))
        matrix = np.vstack([np.frombuffer(saved[r['id']], dtype='float32') for r in rows])
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        # Discard old revisions to avoid retaining deleted document embeddings.
        self.cache = {k:v for k,v in self.cache.items() if k[1] == self.store.revision}
        self.cache[key] = index
        return index

    def search(self, question, property_id, extra_queries=None, limit=4):
        with self.lock:
            rows = self.store.all_chunks(property_id)
            if not rows:
                return [], self.status
            queries = (expand_query(question) + (extra_queries or []))[:6]
            scores = {}
            for query in queries:
                terms = set(tokens(query))
                ranked = sorted(((len(terms & set(tokens(r['text']))), i) for i,r in enumerate(rows)), reverse=True)
                for rank, (score, i) in enumerate(ranked[:12]):
                    if score:
                        scores[i] = scores.get(i, 0) + 1/(60 + rank)
            self.status = 'lexical'
            if self.mode == 'semantic':
                try:
                    import numpy as np
                    index = self._index(property_id, rows)
                    vectors = self.embedder.encode(queries, normalize_embeddings=True, convert_to_numpy=True).astype('float32')
                    distances, indices = index.search(vectors, min(12, len(rows)))
                    for ds, ids in zip(distances, indices):
                        for rank, (distance, i) in enumerate(zip(ds, ids)):
                            if distance >= 0.28:
                                scores[int(i)] = scores.get(int(i), 0) + 1/(60 + rank)
                    self.status = 'hybrid · MiniLM + FAISS'
                except Exception:
                    self.status = 'lexical fallback · embedding model unavailable'
            ranked = sorted(scores, key=scores.get, reverse=True)[:12]
            if self.rerank_enabled and ranked:
                try:
                    from flashrank import Ranker, RerankRequest
                    if self.reranker is None:
                        self.reranker = Ranker(model_name='ms-marco-MiniLM-L-12-v2', cache_dir=str(self.store.path / 'reranker'))
                    rr = self.reranker.rerank(RerankRequest(query=question, passages=[{'id':i,'text':rows[i]['text']} for i in ranked]))
                    ranked = [int(r['id']) for r in rr]
                    self.status += ' · FlashRank'
                except Exception:
                    self.status += ' · reranker unavailable'
            result = []
            for i in ranked[:limit]:
                row = dict(rows[i])
                row['label'] = f'S{len(result)+1}'
                result.append(row)
            return result, self.status
