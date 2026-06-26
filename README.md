# DAIA — Datacom AI Assistant

Asistente de inteligencia artificial interno para **Datacom**, desarrollado sobre FastAPI, LangChain y Qdrant. DAIA responde consultas en lenguaje natural sobre clientes, contratos, servicios, facturación y soporte, combinando tres fuentes de conocimiento en tiempo real.

---

## Arquitectura

```
Usuario (Browser)
       │
       ▼
  index.html  ◄──── FastAPI (main.py)  :8010
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    CRM Datacom    Qdrant (Docker)   datacom.ec
   (API REST)      :6333 (RAG)      (Web scraping)
                         │
                   OpenAI GPT-4o
```

| Componente | Tecnología | Función |
|---|---|---|
| Backend API | FastAPI + Uvicorn | Servicio REST, sirve la UI |
| Frontend | HTML + Tailwind CSS | Chat UI estilo ChatGPT |
| Vector DB | Qdrant (Docker) | Almacena embeddings de PDFs |
| LLM principal | GPT-4o | Síntesis de respuestas internas |
| LLM dispatcher | GPT-4o-mini | Clasifica INTERNAL / EXTERNAL |
| Embeddings | OpenAI text-embedding-ada-002 | Vectorización de documentos |
| Web scraping | BeautifulSoup + lxml | Contenido público de datacom.ec |

---

## Funcionalidades

### 1. Dispatcher Inteligente (INTERNAL / EXTERNAL)

Cada consulta pasa primero por un clasificador LLM (`gpt-4o-mini`) que decide la ruta:

- **INTERNAL** → Consulta sobre Datacom (clientes, servicios, contratos, facturación, soporte, productos y planes del sitio web).
- **EXTERNAL** → Saludos, cultura general, programación u otros temas ajenos a Datacom.

Las consultas externas se resuelven directamente con `gpt-4o-mini` (ruta ligera y económica).

### 2. RAG sobre Documentos PDF

- Los PDFs de la carpeta `CONTRATOS/` (y cualquier carpeta configurada en `DAIA_DATA_PATH`) se procesan con `ingest.py`.
- Se fragmentan en chunks de 1 000 caracteres (overlap de 200) y se vectorizan con `OpenAIEmbeddings`.
- Los vectores se almacenan en la colección `daia_docs` de Qdrant.
- En cada consulta interna se recuperan los 20 chunks más relevantes por similitud coseno.

### 3. Integración CRM en Tiempo Real

Motor de consulta inteligente que detecta si la pregunta menciona un cliente específico o es una consulta general:

| Módulo CRM | Endpoint | Datos disponibles |
|---|---|---|
| Clientes | `/api/clients/clients/` | Nombre, RUC, ciudad, segmento, estado, Account Manager |
| Catálogo de servicios | `/api/services/catalog/` | IDs → nombres de servicios |
| Servicios por cliente | `/api/services/client-services/` | MRC, NRC, estado, bandwidth, ubicación |
| Facturas | `/api/billing/invoices/` | N° factura, fechas, total, estado |
| Tickets de soporte | `/api/support/tickets/` | ID, título, prioridad, estado, fecha |

La detección de cliente usa extracción por regex sobre la consulta en lenguaje natural. El resumen de todos los clientes incluye totales de MRC, NRC y cantidad de servicios.

### 4. Scraping del Sitio Web Público

- Descarga y cachea 5 páginas de `datacom.ec` cada hora (TTL = 3 600 s).
- Páginas: `/`, `/servicios`, `/soluciones`, `/nosotros`, `/contacto`.
- Se limpia el HTML (scripts, estilos, nav, footer) y se trunca a 2 500 caracteres por página.
- Se usa como fuente de conocimiento para preguntas sobre productos y planes comerciales.

### 5. Prioridad de Fuentes

```
1. CRM (tiempo real)  ◄── SIEMPRE se consulta primero
2. Sitio web datacom.ec (caché 1 h)
3. Documentos PDF en Qdrant
```

Si ninguna fuente tiene la información, DAIA responde con un mensaje estándar de datos no disponibles.

### 6. Frontend Chat

- Interfaz dark mode estilo ChatGPT.
- Renderizado de Markdown con tablas, negritas y listas.
- **Badge de enrutamiento** en cada respuesta: `Conocimiento Interno` (GPT-4o + CRM + RAG) o `ChatGPT Free` (GPT-4o-mini).
- Avatar DAIA personalizado (PNG embebido en base64).
- URL relativa `/chat` para portabilidad sin cambios en producción.

---

## Estructura del Proyecto

```
DAIA/
├── main.py              # Aplicación FastAPI principal
├── ingest.py            # Script de ingesta de PDFs a Qdrant
├── index.html           # Frontend chat (single-page)
├── docker-compose.yml   # Servicio Qdrant
├── requirements.txt     # Dependencias Python
├── .env.template        # Plantilla de variables de entorno
├── .gitignore
├── CONTRATOS/           # PDFs de contratos (no incluidos en repo)
└── qdrant_storage/      # Volumen de Qdrant (no incluido en repo)
```

---

## Requisitos

- Python 3.10+
- Docker y Docker Compose
- Cuenta OpenAI con acceso a `gpt-4o`, `gpt-4o-mini` y `text-embedding-ada-002`
- Acceso a la API del CRM de Datacom

---

## Instalación y Despliegue

### 1. Clonar el repositorio

```bash
git clone https://github.com/mlogacho/DAIA.git
cd DAIA
```

### 2. Configurar variables de entorno

```bash
cp .env.template .env
```

Editar `.env`:

```env
OPENAI_API_KEY=sk-...
QDRANT_HOST=localhost
QDRANT_PORT=6333
DAIA_DATA_PATH=./CONTRATOS
CRM_BASE_URL=http://<ip-crm>
CRM_TOKEN=<token-api-crm>
```

### 3. Levantar Qdrant

```bash
docker compose up -d
```

### 4. Instalar dependencias Python

```bash
pip install -r requirements.txt
```

### 5. Ingestar documentos PDF

```bash
python ingest.py
```

Coloca los PDFs en la carpeta definida en `DAIA_DATA_PATH` antes de ejecutar. Si la colección `daia_docs` ya existe, los nuevos documentos se agregan sin borrar los anteriores.

### 6. Iniciar el servidor

```bash
uvicorn main:app --host 127.0.0.1 --port 8010
```

En producción se recomienda dejar FastAPI en `127.0.0.1:8010` detrás de un proxy Nginx en `/api`.

---

## Endpoints API

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/` | Sirve la UI de chat |
| `GET` | `/chat` | Alias de la UI de chat |
| `POST` | `/chat` | Enviar consulta a DAIA |
| `GET` | `/health` | Health check |

### POST /chat

**Request:**
```json
{ "query": "¿Cuántos servicios tiene el cliente ACME?" }
```

**Response:**
```json
{
  "answer": "...",
  "sources": ["contrato_acme.pdf"],
  "routing": "INTERNAL"
}
```

`routing` puede ser `"INTERNAL"` o `"EXTERNAL"`.

---

## Variables de Entorno

| Variable | Descripción | Default |
|---|---|---|
| `OPENAI_API_KEY` | API Key de OpenAI | — (requerida) |
| `QDRANT_HOST` | Host de Qdrant | `localhost` |
| `QDRANT_PORT` | Puerto de Qdrant | `6333` |
| `DAIA_DATA_PATH` | Ruta a los PDFs a ingestar | `./data` |
| `CRM_BASE_URL` | URL base del CRM de Datacom | `http://localhost` |
| `CRM_TOKEN` | Token de autenticación del CRM | — |

---

## Dependencias

```
fastapi==0.110.0
uvicorn==0.29.0
langchain==0.1.13
langchain-openai==0.1.1
qdrant-client==1.8.0
langchain-community==0.0.29
pypdf==4.1.0
python-dotenv==1.0.1
requests>=2.31.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
```

---

## Seguridad y Privacidad

- Las API keys y tokens se cargan exclusivamente desde `.env` (nunca hardcodeados).
- `.env`, `qdrant_storage/` y la carpeta `CONTRATOS/` están excluidos del repositorio via `.gitignore`.
- DAIA nunca expone detalles de infraestructura, endpoints ni tokens en sus respuestas.
- CORS configurado con `allow_origins=["*"]`; ajustar a dominios específicos en producción.
