import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

load_dotenv()

DATA_PATH = os.getenv("DAIA_DATA_PATH", "./data")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY or OPENAI_API_KEY == "tu_clave_de_openai_aqui":
    print("Error: Configura tu OPENAI_API_KEY en el archivo .env primero.")
    exit(1)

def ingest_documents():
    print(f"Buscando PDFs en: {DATA_PATH}")
    if not os.path.exists(DATA_PATH):
        os.makedirs(DATA_PATH)
        print(f"Directorio creado. Por favor, coloca los PDFs de Datacom en {DATA_PATH} y vuelve a ejecutar.")
        return

    loader = PyPDFDirectoryLoader(DATA_PATH)
    docs = loader.load()
    
    if not docs:
        print("No se encontraron documentos PDF. Asegúrate de que estén en la carpeta data.")
        return
        
    print(f"Cargados {len(docs)} páginas de documentos.")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len
    )
    texts = text_splitter.split_documents(docs)
    print(f"Documentos divididos en {len(texts)} chunks para vectorización.")

    # Conectar a Qdrant y crear la colección si no existe
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)

    try:
        client.get_collection("daia_docs")
        print("La colección 'daia_docs' ya existe. Agregando nuevos vectores...")
    except Exception:
        print("La colección no existe, procediendo a crearla...")
        client.create_collection(
            collection_name="daia_docs",
            vectors_config=models.VectorParams(size=1536, distance=models.Distance.COSINE)
        )

    # Ingestar los textos a Qdrant (Langchain VectorStore facilita esto pero al sobreescribir usamos Qdrant de LC)
    from langchain_community.vectorstores import Qdrant
    qdrant = Qdrant(client=client, collection_name="daia_docs", embeddings=embeddings)
    
    qdrant.add_documents(texts)
    print("¡Ingesta de documentos exitosa! DAIA ya puede consultar esta información confidencial.")

if __name__ == "__main__":
    ingest_documents()
