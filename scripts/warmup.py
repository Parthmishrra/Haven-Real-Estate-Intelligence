"""Run once online, before relying on offline operation."""
from dotenv import load_dotenv
load_dotenv()
import os
from sentence_transformers import SentenceTransformer
from faster_whisper import WhisperModel
print('Downloading/loading the local embedding model…')
SentenceTransformer(os.getenv('EMBEDDING_MODEL','sentence-transformers/all-MiniLM-L6-v2'))
print('Downloading/loading the speech model…')
WhisperModel(os.getenv('WHISPER_MODEL','base.en'), device=os.getenv('WHISPER_DEVICE','cpu'), compute_type=os.getenv('WHISPER_COMPUTE_TYPE','int8'))
if os.getenv('RERANK_ENABLED','false').lower()=='true':
    from flashrank import Ranker
    Ranker(model_name='ms-marco-MiniLM-L-12-v2', cache_dir=os.path.join(os.getenv('DATA_DIR','data'),'reranker'))
print('Models cached. Also run: ollama pull llama3.2:3b')
