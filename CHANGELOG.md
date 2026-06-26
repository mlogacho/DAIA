# Changelog

Todos los cambios notables de este proyecto se documentan en este archivo.  
Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

---

## [Unreleased]

---

## [1.2.0] — 2026-05-29

### Changed
- Actualización del nombre y tono del asistente en el prompt del sistema y en la interfaz de usuario: el asistente se presenta siempre como **DAIA (Datacom AI Assistant)** con identidad, tono y nomenclatura consistentes en todas las interacciones.

---

## [1.1.0] — 2026-03-10

### Added
- **Scraping del sitio web de Datacom** (`datacom.ec`) como nueva fuente de conocimiento:
  - Se descargan y procesan 5 páginas públicas: `/`, `/servicios`, `/soluciones`, `/nosotros`, `/contacto`.
  - Caché en memoria con TTL de 1 hora para minimizar peticiones externas.
  - Limpieza de HTML con BeautifulSoup + lxml (se eliminan scripts, estilos, nav, footer e iframes).
  - Truncado a 2 500 caracteres por página para respetar el límite de contexto del LLM.
- Nueva dependencia: `beautifulsoup4>=4.12.0`, `lxml>=5.0.0`, `requests>=2.31.0`.
- El prompt del sistema incluye ahora una sección `SITIO WEB PÚBLICO DE DATACOM` entre CRM y PDFs.
- El clasificador INTERNAL/EXTERNAL reconoce explícitamente preguntas sobre productos, planes y cobertura como consultas internas.

### Changed
- Orden de prioridad de fuentes actualizado: **CRM → Web → PDFs**.
- `requirements.txt` ampliado con las nuevas dependencias de scraping.

---

## [1.0.0] — 2026-03-10

### Added
- **Primera versión funcional de DAIA**.
- **Backend FastAPI** (`main.py`) con los endpoints:
  - `GET /` y `GET /chat` — sirven la interfaz de chat.
  - `POST /chat` — procesa consultas con LLM + RAG + CRM.
  - `GET /health` — health check.
- **Dispatcher Inteligente** con `gpt-4o-mini`:
  - Clasifica cada consulta como `INTERNAL` o `EXTERNAL`.
  - Consultas externas se resuelven directamente con `gpt-4o-mini` (ruta ligera).
  - Consultas internas pasan por la pipeline completa RAG + CRM + GPT-4o.
- **Pipeline RAG** sobre documentos PDF:
  - Script `ingest.py` para carga, fragmentación (chunk 1 000 / overlap 200) y vectorización de PDFs.
  - Almacenamiento en Qdrant (`daia_docs`, 1 536 dimensiones, distancia coseno).
  - Recuperación de los 20 chunks más relevantes por consulta.
- **Integración CRM en tiempo real** con detección inteligente de módulos según keywords de la consulta:
  - Clientes: listado, segmento, ciudad, estado, Account Manager.
  - Servicios: detalle por cliente con MRC, NRC, bandwidth y ubicación.
  - Catálogo de servicios: mapeo ID → nombre.
  - Facturas: número, fechas, monto y estado.
  - Tickets de soporte: ID, título, prioridad, estado y fecha.
- **Detección de cliente por nombre** desde lenguaje natural (regex multipatrón).
- **Tablas Markdown** en todas las respuestas de datos estructurados (clientes, servicios, facturas, tickets) con totales MRC/NRC.
- **Frontend chat** (`index.html`):
  - Dark mode estilo ChatGPT con Tailwind CSS.
  - Renderizado de Markdown con tablas y negritas.
  - Badge de enrutamiento: `Conocimiento Interno` / `ChatGPT Free`.
  - Avatar DAIA con logo embebido en base64.
  - URL relativa `/chat` para portabilidad en producción.
- **Docker Compose** (`docker-compose.yml`) con servicio Qdrant en red bridge `daia_network`.
- **CORS** habilitado para permitir peticiones desde cualquier origen.
- Configuración por variables de entorno: `OPENAI_API_KEY`, `QDRANT_HOST`, `QDRANT_PORT`, `DAIA_DATA_PATH`, `CRM_BASE_URL`, `CRM_TOKEN`.
- Plantilla `.env.template` y `.gitignore` con exclusiones de secretos, vectores y contratos.

[Unreleased]: https://github.com/mlogacho/DAIA/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/mlogacho/DAIA/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mlogacho/DAIA/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/mlogacho/DAIA/releases/tag/v1.0.0
