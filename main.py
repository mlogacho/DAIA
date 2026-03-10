import os
import re
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import Qdrant
from qdrant_client import QdrantClient
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain

load_dotenv()

app = FastAPI(title="DAIA - Datacom AI Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root_ui():
    return FileResponse("index.html")

@app.get("/chat")
def chat_ui():
    return FileResponse("index.html")

class QueryRequest(BaseModel):
    query: str

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
QDRANT_HOST    = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT    = int(os.getenv("QDRANT_PORT", "6333"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

CRM_BASE_URL   = os.getenv("CRM_BASE_URL", "http://localhost")
CRM_TOKEN      = os.getenv("CRM_TOKEN", "d22ad4f0656953b7075f930b65fa38c0750ac7b4")
CRM_HEADERS    = {"Authorization": f"Token {CRM_TOKEN}"}

if not OPENAI_API_KEY or OPENAI_API_KEY == "tu_clave_de_openai_aqui":
    print("ADVERTENCIA: API Key de OpenAI no configurada.")

# Catálogo de servicios (id → nombre) — se carga en runtime
_SERVICE_CATALOG: dict[int, str] = {}

def load_service_catalog():
    """Carga el catálogo de servicios para mapear IDs a nombres."""
    global _SERVICE_CATALOG
    if _SERVICE_CATALOG:
        return
    try:
        resp = requests.get(f"{CRM_BASE_URL}/api/services/catalog/?page_size=200", headers=CRM_HEADERS, timeout=8)
        for svc in resp.json().get("results", []):
            _SERVICE_CATALOG[svc["id"]] = svc.get("name", f"Servicio #{svc['id']}")
    except Exception as e:
        print(f"[CRM] No se pudo cargar catálogo de servicios: {e}")

# ─────────────────────────────────────────────
# PROMPTS
# ─────────────────────────────────────────────
SYSTEM_PROMPT = """Eres DAIA (Datacom AI Network Assistant), la asistente inteligente oficial de Datacom.
Tu propósito es facilitar información precisa y confidencial sobre clientes, servicios, contratos y procesos internos.

REGLAS ESTRICTAS:
1. Identidad: Eres DAIA. Usa un tono profesional, eficiente y colaborativo en español.
2. PRIORIDAD DE FUENTES (de mayor a menor):
   - PRIMERO: Usa los datos del CRM EN TIEMPO REAL (sección "DATOS EN TIEMPO REAL DEL CRM"). Si hay datos ahí, ÚSALOS.
   - SEGUNDO: Usa los documentos PDF si el CRM no tiene la información solicitada.
   - Solo si NINGUNA fuente tiene la información, responde: "Lo siento, no tengo acceso a esa información específica en los registros actuales de Datacom."
3. NUNCA respondas el fallback si hay datos del CRM disponibles. Si el CRM devolvió una tabla con información, úsala.
4. Formato de respuesta:
   - Para datos de servicios por cliente: muestra la tabla con Servicios Totales, Total Mensual (MRC) y Total Único (NRC).
   - Para listas: usa tablas Markdown bien formateadas.
   - Las cifras monetarias siempre con formato: $1,850.00
5. Privacidad: No menciones "API", "endpoint", "contexto" ni detalles de infraestructura.

--- DATOS EN TIEMPO REAL DEL CRM DE DATACOM (FUENTE PRINCIPAL) ---
{crm_data}

--- DOCUMENTOS PDF (contratos, facturas escaneadas) ---
{context}

--- LISTA DE DOCUMENTOS PDF ENCONTRADOS ---
{sources_list}

Pregunta del usuario: {question}
Respuesta experta de DAIA:"""

PROMPT = PromptTemplate(
    template=SYSTEM_PROMPT,
    input_variables=["context", "sources_list", "crm_data", "question"]
)

CLASSIFIER_SYSTEM_PROMPT = """Analiza la siguiente consulta del usuario y determina si requiere información INTERNA de Datacom o es una consulta EXTERNA general.

Categorías:
- INTERNAL: Preguntas sobre contratos, facturas, clientes, RUC, servicios contratados, tickets de soporte, IPs asignadas, precios MRC/NRC, account managers, representantes legales, procesos de Datacom, fechas, montos, o cualquier dato específico de la empresa.
- EXTERNAL: Saludos, preguntas de cultura general, programación, historia, consejos generales, o temas no relacionados con los datos privados de Datacom.

Responde ÚNICAMENTE con la palabra 'INTERNAL' o 'EXTERNAL'."""

CLASSIFIER_PROMPT = PromptTemplate(
    template="Contexto: {system_prompt}\n\nConsulta: {query}\n\nCategoría:",
    input_variables=["system_prompt", "query"]
)

# ─────────────────────────────────────────────
# HELPERS - RAG
# ─────────────────────────────────────────────
def get_vector_store():
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    embeddings = OpenAIEmbeddings(openai_api_key=OPENAI_API_KEY)
    return Qdrant(client=client, collection_name="daia_docs", embeddings=embeddings)

def search_documents(query: str) -> tuple[str, list]:
    try:
        vs = get_vector_store()
        docs = vs.similarity_search(query, k=20)
        unique_sources = set()
        context_parts = []
        for doc in docs:
            src = doc.metadata.get("source", "Desconocido")
            unique_sources.add(os.path.basename(src))
            context_parts.append(doc.page_content)
        return "\n---\n".join(context_parts), list(unique_sources)
    except Exception as e:
        print(f"[RAG] Error: {e}")
        return "", []

# ─────────────────────────────────────────────
# HELPERS - CRM API
# ─────────────────────────────────────────────
def crm_get(endpoint: str, params: dict = None):
    try:
        r = requests.get(f"{CRM_BASE_URL}{endpoint}", headers=CRM_HEADERS, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[CRM] Error GET {endpoint}: {e}")
        return None

def format_money(val) -> str:
    try:
        return f"${float(val):,.2f}"
    except:
        return str(val)

def extract_client_name_from_query(query: str) -> str | None:
    """Intenta extraer un nombre de cliente mencionado en la consulta."""
    # Patrones comunes: "de X", "tiene X", "el cliente X", "para X", "sobre X"
    patterns = [
        r"(?:de|tiene|tiene el cliente|para|del cliente|sobre|cliente)\s+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ0-9\s\-\.&]+?)(?:\s+tiene|\s+cuantos|\s+sus|\s+el|\s+los|\s*\?|$)",
        r"([A-ZÁÉÍÓÚÑ]{3,}(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-záéíóúñ]*)*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) >= 3 and candidate.upper() not in {"DATACOM", "EL", "LA", "LOS", "LAS", "DEL", "CRM"}:
                return candidate
    return None

def get_client_summary_table(clients_data: list) -> str:
    """Genera tabla resumen de clientes con servicios totales, MRC y NRC."""
    if not clients_data:
        return "Sin resultados de clientes."
    lines = []
    lines.append("| Cliente | Tax ID | Ciudad | Segmento | Servicios Totales | Total Mensual (MRC) | Total Único (NRC) | Estado | Account Manager |")
    lines.append("|---------|--------|--------|----------|:-----------------:|:-------------------:|:-----------------:|--------|-----------------|")
    for c in clients_data:
        estado = c.get("active_status") or c.get("prospect_status") or c.get("classification") or "-"
        lines.append(
            f"| **{c.get('name','-')}** | {c.get('tax_id','-')} | {c.get('city','-')} | {c.get('segment','-')} "
            f"| **{c.get('total_services_count', 0)}** | **{format_money(c.get('total_mrc', 0))}** "
            f"| **{format_money(c.get('total_nrc', 0))}** | {estado} | {c.get('account_manager','-')} |"
        )
    return "\n".join(lines)

def get_client_services_detail(client_id: int, client_name: str) -> str:
    """Obtiene el detalle línea a línea de servicios de un cliente específico."""
    load_service_catalog()
    data = crm_get(f"/api/services/client-services/", params={"client": client_id, "page_size": 200})
    if not data:
        return "Sin detalle de servicios disponible."
    results = data.get("results", [])
    if not results:
        return f"El cliente **{client_name}** no tiene servicios registrados."

    lines = [f"#### Detalle de {len(results)} servicios de **{client_name}**\n"]
    lines.append("| # | Servicio | Precio MRC | NRC | Estado | Ancho de Banda | Ubicación |")
    lines.append("|---|---------|:----------:|:---:|--------|----------------|-----------|")
    for i, s in enumerate(results, 1):
        svc_name = _SERVICE_CATALOG.get(s.get("service"), f"Servicio #{s.get('service')}")
        lines.append(
            f"| {i} | {svc_name} | {format_money(s.get('agreed_price',0))} "
            f"| {format_money(s.get('nrc',0))} | {s.get('status','-')} "
            f"| {s.get('bandwidth','-') or '-'} | {s.get('service_location','-') or '-'} |"
        )
    # Totales
    total_mrc = sum(float(s.get("agreed_price", 0) or 0) for s in results)
    total_nrc = sum(float(s.get("nrc", 0) or 0) for s in results)
    lines.append(f"\n**Total servicios: {len(results)} | MRC Total: {format_money(total_mrc)} | NRC Total: {format_money(total_nrc)}**")
    return "\n".join(lines)

def fetch_crm_data(query: str) -> str:
    """
    Motor de consulta inteligente al CRM.
    Detecta si la pregunta menciona un cliente específico o es una consulta general.
    """
    query_lower = query.lower()
    sections = []
    
    # ── Detectar keywords de módulos ────────────────────────────────────────
    needs_clients  = any(w in query_lower for w in [
        "cliente", "clientes", "empresa", "empresas", "cuantos", "listado",
        "ruc", "tax", "segmento", "account", "activos", "facturado", "billed"
    ])
    needs_services = any(w in query_lower for w in [
        "servicio", "servicios", "mrc", "nrc", "mensual", "único", "unico",
        "instalado", "internet", "bandwidth", "ip", "contratado", "housing",
        "precio", "total mensual", "total único"
    ])
    needs_invoices = any(w in query_lower for w in [
        "factura", "facturas", "facturación", "cobro", "pago", "pagado",
        "vencido", "billing", "monto"
    ])
    needs_tickets  = any(w in query_lower for w in [
        "ticket", "tickets", "soporte", "incidente", "problema", "falla"
    ])

    # Si no hay keyword específica, traer resumen de clientes por defecto
    if not any([needs_clients, needs_services, needs_invoices, needs_tickets]):
        needs_clients = True

    # ── Intentar detectar cliente específico ────────────────────────────────
    client_name_hint = extract_client_name_from_query(query)
    specific_client = None

    if client_name_hint:
        search_data = crm_get("/api/clients/clients/", params={"search": client_name_hint, "page_size": 200})
        if search_data and search_data.get("results"):
            # Tomar el más relevante (mejor match por nombre)
            results = search_data["results"]
            exact = [c for c in results if client_name_hint.upper() in c["name"].upper()]
            specific_client = exact[0] if exact else None

    # ── CASO 1: Cliente específico detectado ────────────────────────────────
    if specific_client:
        cid  = specific_client["id"]
        cname = specific_client["name"]

        # Siempre mostrar resumen del cliente
        summary = get_client_summary_table([specific_client])
        sections.append(f"### Resumen del cliente: {cname}\n\n{summary}")

        # Si se pregunta por servicios, mostrar detalle completo
        if needs_services or any(w in query_lower for w in ["cuantos", "cuántos", "cuales", "listar", "detalle", "todos"]):
            detail = get_client_services_detail(cid, cname)
            sections.append(detail)

        if needs_invoices:
            inv_data = crm_get("/api/billing/invoices/", params={"client": cid, "page_size": 50})
            if inv_data and inv_data.get("results"):
                inv_lines = [f"### Facturas de {cname}\n"]
                inv_lines.append("| N° Factura | Fecha Emisión | Vencimiento | Total | Estado |")
                inv_lines.append("|-----------|:------------:|:-----------:|:-----:|--------|")
                for inv in inv_data["results"]:
                    inv_lines.append(
                        f"| {inv.get('invoice_number','-')} | {inv.get('issue_date','-')} "
                        f"| {inv.get('due_date','-')} | {format_money(inv.get('total_amount',0))} "
                        f"| {inv.get('status','-')} |"
                    )
                sections.append("\n".join(inv_lines))

        if needs_tickets:
            ticket_data = crm_get("/api/support/tickets/", params={"client": cid, "page_size": 20})
            if ticket_data and ticket_data.get("results"):
                t_lines = [f"### Tickets de Soporte de {cname}\n"]
                t_lines.append("| # | Título | Prioridad | Estado | Fecha |")
                t_lines.append("|---|--------|:--------:|:------:|-------|")
                for t in ticket_data["results"]:
                    t_lines.append(
                        f"| {t.get('id','-')} | {t.get('title','-')} | {t.get('priority','-')} "
                        f"| {t.get('status','-')} | {str(t.get('created_at','-'))[:10]} |"
                    )
                sections.append("\n".join(t_lines))

        return "\n\n".join(sections) if sections else "No se encontró información para este cliente."

    # ── CASO 2: Consulta general (todos los clientes / vista resumen) ────────
    if needs_clients or needs_services:
        client_data = crm_get("/api/clients/clients/", params={"page_size": 200})
        if client_data:
            total = client_data.get("count", 0)
            results = client_data.get("results", [])
            
            # Filtrar solo activos si la pregunta lo sugiere
            if any(w in query_lower for w in ["activo", "activos", "instalado", "facturado"]):
                results = [c for c in results if c.get("active_status") or c.get("classification") == "ACTIVE"]

            table = get_client_summary_table(results)
            
            # Totales generales
            grand_mrc = sum(float(c.get("total_mrc", 0) or 0) for c in results)
            grand_nrc = sum(float(c.get("total_nrc", 0) or 0) for c in results)
            grand_svcs = sum(int(c.get("total_services_count", 0)) for c in results)

            sections.append(
                f"### Resumen General de Clientes del CRM de Datacom\n\n"
                f"**Total de clientes en sistema: {total}** | "
                f"**Total servicios activos: {grand_svcs}** | "
                f"**MRC Total: {format_money(grand_mrc)}** | "
                f"**NRC Total: {format_money(grand_nrc)}**\n\n"
                f"{table}"
            )

    if needs_invoices:
        inv_data = crm_get("/api/billing/invoices/", params={"page_size": 100})
        if inv_data and inv_data.get("results"):
            inv_lines = ["### Facturas Registradas en el CRM\n"]
            inv_lines.append("| N° Factura | Cliente | Fecha Emisión | Vencimiento | Total | Estado |")
            inv_lines.append("|-----------|---------|:------------:|:-----------:|:-----:|--------|")
            for inv in inv_data["results"]:
                client_name = str(inv.get("client", "-"))
                inv_lines.append(
                    f"| {inv.get('invoice_number','-')} | {client_name} "
                    f"| {inv.get('issue_date','-')} | {inv.get('due_date','-')} "
                    f"| {format_money(inv.get('total_amount',0))} | {inv.get('status','-')} |"
                )
            total = inv_data.get("count", len(inv_data["results"]))
            inv_lines.append(f"\n**Total facturas: {total}**")
            sections.append("\n".join(inv_lines))

    if needs_tickets:
        t_data = crm_get("/api/support/tickets/", params={"page_size": 50})
        if t_data and t_data.get("results"):
            t_lines = ["### Tickets de Soporte\n"]
            t_lines.append("| # | Cliente | Título | Prioridad | Estado | Fecha |")
            t_lines.append("|---|---------|--------|:--------:|:------:|-------|")
            for t in t_data["results"]:
                t_lines.append(
                    f"| {t.get('id','-')} | {t.get('client','-')} | {t.get('title','-')} "
                    f"| {t.get('priority','-')} | {t.get('status','-')} | {str(t.get('created_at','-'))[:10]} |"
                )
            t_lines.append(f"\n**Total tickets: {t_data.get('count', 0)}**")
            sections.append("\n".join(t_lines))

    return "\n\n".join(sections) if sections else "No se encontró información relevante en el CRM."

# ─────────────────────────────────────────────
# ENDPOINT PRINCIPAL
# ─────────────────────────────────────────────
@app.post("/chat")
def chat_with_daia(request: QueryRequest):
    if not OPENAI_API_KEY or OPENAI_API_KEY == "tu_clave_de_openai_aqui":
        raise HTTPException(status_code=500, detail="DAIA no está configurada. Falta API Key.")

    try:
        # ── PASO 1: DISPATCHER ────────────────────────────────────────────────
        classifier_llm   = ChatOpenAI(model="gpt-4o-mini", temperature=0.0, openai_api_key=OPENAI_API_KEY)
        classifier_chain = LLMChain(llm=classifier_llm, prompt=CLASSIFIER_PROMPT)
        classification   = classifier_chain.run(system_prompt=CLASSIFIER_SYSTEM_PROMPT, query=request.query).strip().upper()
        print(f"[Dispatcher] → {classification} | Query: {request.query[:80]}")

        # ── RUTA EXTERNA ──────────────────────────────────────────────────────
        if "EXTERNAL" in classification:
            ext_llm  = ChatOpenAI(model="gpt-4o-mini", temperature=0.7, openai_api_key=OPENAI_API_KEY)
            response = ext_llm.invoke(request.query)
            return {"answer": response.content, "sources": [], "routing": "EXTERNAL"}

        # ── RUTA INTERNA: RAG + CRM ───────────────────────────────────────────
        context_str, unique_sources = search_documents(request.query)
        sources_list_str = "\n".join(f"- {s}" for s in unique_sources) if unique_sources else "Ninguno"

        crm_data_str = fetch_crm_data(request.query)
        print(f"[CRM Data] Longitud del dato CRM: {len(crm_data_str)} chars")
        print(f"[CRM Data] Preview: {crm_data_str[:300]}")

        # Si ambas fuentes están vacías
        if not context_str and crm_data_str == "No se encontró información relevante en el CRM.":
            return {
                "answer": "Lo siento, no tengo acceso a esa información específica en los registros actuales de Datacom.",
                "sources": [], "routing": "INTERNAL"
            }

        # ── GPT-4o: sintetiza ambas fuentes ──────────────────────────────────
        llm   = ChatOpenAI(model="gpt-4o", temperature=0.0, openai_api_key=OPENAI_API_KEY)
        chain = LLMChain(llm=llm, prompt=PROMPT)
        result = chain.run(
            context=context_str or "Sin documentos PDF relevantes para esta consulta.",
            sources_list=sources_list_str,
            crm_data=crm_data_str,
            question=request.query
        )

        return {"answer": result, "sources": unique_sources, "routing": "INTERNAL"}

    except Exception as e:
        print(f"[Error] {str(e)}")
        raise HTTPException(status_code=500, detail="Ocurrió un error al procesar tu consulta.")

@app.get("/health")
def health_check():
    return {"status": "DAIA Online"}
