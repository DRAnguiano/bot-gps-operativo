"""Indexación RAG y clientes LLM.

Dos responsabilidades:

1. **Construcción del índice** (`build_index`): lee fuentes en ``DATA_DIR``
   (PDF/txt/md), las trocea (`_split_text`) y las persiste como embeddings
   `BAAI/bge-m3` en la colección ChromaDB. El volumen ``.cache/`` (~2.4 GB con
   el modelo) NO se borra; ver constraint 7 en ``openspec/project.md``.
2. **Recuperación y generación**: `retrieve_context_for_guardrail` (recupera
   para el guardrail) y la generación LLM vía Gemini (`call_llm` →
   `call_gemini_llm`; proveedor único — Groq/Cohere retirados 2026-07-07).

Nota: la recuperación acotada por fuente autorizada (fail-closed de pago) vive
en `app/knowledge/context_builder.py`, que reutiliza los helpers privados de
este módulo (`_embed_texts`, `_get_collection`). El RAG responde políticas/HR;
nunca decide facts del candidato.
"""
import os
import re
from pathlib import Path
from typing import Any

import chromadb
import httpx
from chromadb.config import Settings as ChromaSettings
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

from . import settings


# =========================
# Configuración con defaults
# =========================

DATA_DIR = getattr(settings, "DATA_DIR", os.getenv("DATA_DIR", "/app/data"))

CHROMA_DB_DIR = getattr(
    settings,
    "CHROMA_DB_DIR",
    getattr(settings, "DB_DIR", os.getenv("CHROMA_DB_DIR", "/app/chroma_db")),
)

COLLECTION_NAME = getattr(
    settings,
    "COLLECTION_NAME",
    os.getenv("COLLECTION_NAME", "rh_rag_docs"),
)

EMBEDDING_MODEL = getattr(
    settings,
    "EMBEDDING_MODEL",
    os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
)

CHUNK_SIZE = int(getattr(settings, "CHUNK_SIZE", os.getenv("CHUNK_SIZE", "500")))
CHUNK_OVERLAP = int(getattr(settings, "CHUNK_OVERLAP", os.getenv("CHUNK_OVERLAP", "100")))
TOP_K = int(getattr(settings, "TOP_K", os.getenv("TOP_K", "5")))

TEMPERATURE = float(getattr(settings, "TEMPERATURE", os.getenv("TEMPERATURE", "0.0")))


# Cohere Rerank.
# Flujo:
#   Chroma recupera RERANK_INPUT_K candidatos.
#   Cohere Rerank reordena esos candidatos.
#   El sistema devuelve RERANK_TOP_K o top_k, según aplique.
RERANK_ENABLED = str(
    getattr(settings, "RERANK_ENABLED", os.getenv("RERANK_ENABLED", "false"))
).strip().lower() in {"1", "true", "yes", "y", "on"}

RERANK_INPUT_K = int(
    getattr(settings, "RERANK_INPUT_K", os.getenv("RERANK_INPUT_K", "20"))
)

RERANK_TOP_K = int(
    getattr(settings, "RERANK_TOP_K", os.getenv("RERANK_TOP_K", str(TOP_K)))
)

RERANK_MAX_CHARS_PER_DOC = int(
    getattr(
        settings,
        "RERANK_MAX_CHARS_PER_DOC",
        os.getenv("RERANK_MAX_CHARS_PER_DOC", "2500"),
    )
)

INDEX_EXTENSIONS = getattr(
    settings,
    "INDEX_EXTENSIONS",
    [
        ext.strip().lower()
        for ext in os.getenv("INDEX_EXTENSIONS", ".pdf,.txt,.md,.markdown").split(",")
        if ext.strip()
    ],
)

if isinstance(INDEX_EXTENSIONS, str):
    INDEX_EXTENSIONS = [
        ext.strip().lower()
        for ext in INDEX_EXTENSIONS.split(",")
        if ext.strip()
    ]


def _normalize_extension(ext: str) -> str:
    ext = (ext or "").strip().lower()
    if not ext:
        return ""
    return ext if ext.startswith(".") else f".{ext}"


INDEX_EXTENSIONS = [
    normalized
    for normalized in (_normalize_extension(ext) for ext in INDEX_EXTENSIONS)
    if normalized
]


_embedding_model: SentenceTransformer | None = None


# =========================
# Utilidades generales
# =========================

def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\uFFFD", "")
    text = text.replace("\x00", "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model

    if _embedding_model is None:
        print(f"[indexer] Cargando embedding model: {EMBEDDING_MODEL}", flush=True)
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    return _embedding_model


def _embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_embedding_model()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vectors.tolist()


# =========================
# Lectores de documentos
# =========================

def _read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages: list[str] = []

    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            print(f"[indexer] Error leyendo página {index} de {path}: {exc}", flush=True)
            text = ""

        if text.strip():
            pages.append(f"\n\n[Página {index}]\n{text.strip()}")

    return _normalize_text("\n".join(pages))


def _read_text_file(path: Path) -> str:
    return _normalize_text(path.read_text(encoding="utf-8", errors="ignore"))


def _read_source_file(path: Path) -> str:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _read_pdf(path)

    if suffix in {".txt", ".md", ".markdown"}:
        return _read_text_file(path)

    return ""


def _iter_source_files(data_dir: str) -> list[Path]:
    base = Path(data_dir)

    if not base.exists():
        raise RuntimeError(f"No existe DATA_DIR: {data_dir}")

    if not base.is_dir():
        raise RuntimeError(f"DATA_DIR no es una carpeta: {data_dir}")

    allowed = {ext.lower() for ext in INDEX_EXTENSIONS}

    files = [
        path
        for path in base.rglob("*")
        if path.is_file()
        and path.suffix.lower() in allowed
        and not path.name.startswith(".")
        and "/_backup" not in str(path).replace("\\", "/")
    ]

    return sorted(files)


# =========================
# Chunking
# =========================

def _split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = _normalize_text(text)

    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)

        # Intentar cortar bonito en salto de línea o punto.
        if end < text_len:
            newline_cut = text.rfind("\n", start, end)
            period_cut = text.rfind(". ", start, end)

            cut = max(newline_cut, period_cut)

            if cut > start + int(chunk_size * 0.55):
                end = cut + 1

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        start = max(end - overlap, start + 1)

    return chunks


# =========================
# ChromaDB
# =========================

def _get_chroma_client(db_dir: str | None = None):
    persist_dir = db_dir or CHROMA_DB_DIR
    Path(persist_dir).mkdir(parents=True, exist_ok=True)

    return chromadb.PersistentClient(
        path=persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _reset_collection(client):
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _get_collection(db_dir: str | None = None):
    client = _get_chroma_client(db_dir)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


# =========================
# Indexación
# =========================

def build_index(data_dir: str | None = None, db_dir: str | None = None):
    data_dir = data_dir or DATA_DIR
    db_dir = db_dir or CHROMA_DB_DIR

    files = _iter_source_files(data_dir)

    if not files:
        raise RuntimeError(f"No se encontraron documentos indexables en {data_dir}")

    print(f"[indexer] DATA_DIR={data_dir}", flush=True)
    print(f"[indexer] CHROMA_DB_DIR={db_dir}", flush=True)
    print(f"[indexer] COLLECTION_NAME={COLLECTION_NAME}", flush=True)
    print(f"[indexer] INDEX_EXTENSIONS={INDEX_EXTENSIONS}", flush=True)
    print(f"[indexer] Documentos encontrados: {len(files)}", flush=True)

    client = _get_chroma_client(db_dir)
    collection = _reset_collection(client)

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []

    total_chunks = 0
    indexed_files = 0
    skipped_files = 0

    base_path = Path(data_dir)

    for path in files:
        rel_path = str(path.relative_to(base_path))

        try:
            raw_text = _read_source_file(path)
        except Exception as exc:
            skipped_files += 1
            print(f"[indexer] Error leyendo {rel_path}: {type(exc).__name__}: {exc}", flush=True)
            continue

        chunks = _split_text(raw_text)

        if not chunks:
            skipped_files += 1
            print(f"[indexer] Documento sin texto útil: {rel_path}", flush=True)
            continue

        indexed_files += 1

        for index, chunk in enumerate(chunks):
            chunk_id = f"{rel_path}::chunk-{index}"

            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append(
                {
                    "source": rel_path,
                    "chunk": index,
                    "file_name": path.name,
                    "file_ext": path.suffix.lower(),
                }
            )

        total_chunks += len(chunks)
        print(f"[indexer] {rel_path}: {len(chunks)} chunks", flush=True)

    if not documents:
        raise RuntimeError("No se generaron chunks indexables.")

    embeddings = _embed_texts(documents)

    batch_size = 256
    for start in range(0, len(documents), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
            embeddings=embeddings[start:end],
        )

    return {
        "data_dir": data_dir,
        "db_dir": db_dir,
        "collection": COLLECTION_NAME,
        "files_found": len(files),
        "files_indexed": indexed_files,
        "files_skipped": skipped_files,
        "chunks_indexed": total_chunks,
        "embedding_model": EMBEDDING_MODEL,
        "extensions": sorted(list(set(INDEX_EXTENSIONS))),
        "rerank_enabled": RERANK_ENABLED,
        "rerank_model": None,  # rerank retirado (Cohere fuera del ecosistema)
    }


# =========================
# Rerank
# =========================

def _rerank_context_items(
    query: str,
    items: list[dict[str, Any]],
    top_n: int,
) -> list[dict[str, Any]]:
    """Slice directo de los candidatos de Chroma. El rerank Cohere fue RETIRADO
    (gemini-full-provider-migration D7: Cohere fuera del ecosistema; RERANK_ENABLED
    nunca estuvo activo en ningún entorno)."""
    return items[:top_n]


def retrieve_context_for_guardrail(question: str, top_k: int | None = None) -> list[dict[str, Any]]:
    query = _normalize_text(question)

    if not query:
        return []

    requested_k = _to_int(top_k, TOP_K)

    if RERANK_ENABLED:
        chroma_k = max(requested_k, RERANK_INPUT_K)
        final_k = min(requested_k, RERANK_TOP_K) if top_k is not None else RERANK_TOP_K
    else:
        chroma_k = requested_k
        final_k = requested_k

    try:
        collection = _get_collection()
        query_embedding = _embed_texts([query])[0]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=chroma_k,
            include=["documents", "distances", "metadatas"],
        )
    except Exception as exc:
        print(f"[indexer] Error recuperando contexto: {type(exc).__name__}: {exc}", flush=True)
        return []

    docs = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    ids = results.get("ids", [[]])[0]

    output: list[dict[str, Any]] = []

    for doc, distance, metadata, chunk_id in zip(docs, distances, metadatas, ids):
        # Chroma cosine distance: menor distancia = más parecido.
        # Convertimos a score simple 0-1 aproximado.
        try:
            score = max(0.0, 1.0 - float(distance))
        except Exception:
            score = 0.0

        output.append(
            {
                "id": chunk_id,
                "text": doc,
                "distance": distance,
                "score": score,
                "source": (metadata or {}).get("source"),
                "metadata": metadata or {},
            }
        )

    if RERANK_ENABLED:
        return _rerank_context_items(query=query, items=output, top_n=final_k)

    return output[:final_k]


# =========================
# LLM remoto: Gemini (proveedor único)
# =========================

def _llm_system_message() -> str:
    return (
        "Eres Mundo, del equipo de reclutamiento de Transmontes. "
        "Hablas como parte del equipo, nunca como un tercero; nunca te presentes "
        "como \"Capital Humano\". "
        "Sigue estrictamente las instrucciones del prompt. "
        "No inventes datos no proporcionados por los documentos o el sistema. "
        "Responde en español natural, claro y profesional."
    )


# ── Prompts de visión ────────────────────────────────────────────────────────
# Prompt para imágenes: extrae SOLO datos de perfilamiento del funnel.
_VISION_PROMPT_IMAGE = (
    "Eres un asistente de reclutamiento. Analiza la imagen (típicamente una INE, "
    "licencia, CURP, comprobante u otro documento) y extrae ÚNICAMENTE los datos "
    "PRESENTES y verificables en ella. Campos posibles: nombre, fecha_nacimiento, "
    "ciudad, licencia (A, B o E), apto_medico, documento.\n"
    "- SIEMPRE emite primero una línea 'tipo_documento: <valor>' clasificando la imagen "
    "con EXACTAMENTE uno de: licencia_federal, apto_medico, ine, carta_laboral, "
    "semanas_imss, comprobante_pago_renovacion, curp, rfc, acta_nacimiento, nss, "
    "comprobante_domicilio, comprobante_estudios, desconocido. Si la imagen no es un "
    "documento (persona, camión, paisaje, meme) usa 'desconocido'.\n"
    "- SIEMPRE emite después una línea 'legible: si' o 'legible: no' (no si está "
    "borrosa, cortada o no se distingue el texto).\n"
    "REGLAS ESTRICTAS:\n"
    "- Devuelve SOLO los campos que aparezcan en la imagen, uno por línea, en formato "
    "'clave: valor'. NO menciones, expliques ni enumeres los datos ausentes. NO "
    "escribas frases como 'no se puede determinar'. Si un dato no está, simplemente "
    "omítelo.\n"
    "- nombre: en una INE el bloque de nombre tiene TRES renglones, de arriba a abajo: "
    "primer apellido (paterno), segundo apellido (materno) y al final el/los nombre(s). "
    "Reconstruye el nombre completo en el orden natural 'nombre(s) apellido_paterno "
    "apellido_materno'. Ejemplo: renglones 'RAMOS' / 'ANGUIANO' / 'DAVID' → "
    "nombre: David Ramos Anguiano (NO 'David Anguiano Ramos').\n"
    "- NUNCA infieras años de experiencia como chofer ni tipo de unidad "
    "(sencillo / full / torton): esos datos NO aparecen en ningún documento; ignóralos "
    "por completo.\n"
    "- fecha_nacimiento: extráela SIEMPRE en formato AAAA-MM-DD. En una INE viene "
    "explícita. Si no, dedúcela de la CURP: los caracteres 5 a 10 codifican AAMMDD "
    "(p. ej. una CURP que empiece 'XXXX970701...' → 1997-07-01). NO calcules ni "
    "reportes la edad; solo la fecha de nacimiento.\n"
    "- ciudad: extrae SOLO el municipio o ciudad, NUNCA el estado. En el domicilio de "
    "una INE el ÚLTIMO apartado es el ESTADO (a veces abreviado: DGO., JAL., NL., etc.) "
    "y el municipio/ciudad es el apartado JUSTO ANTES. Devuelve únicamente ese "
    "municipio. Ejemplo: '..., GOMEZ PALACIO, DGO.' → ciudad: Gómez Palacio (NO "
    "Durango). NUNCA uses el nombre del estado ni su abreviatura como ciudad. NO emitas "
    "un campo 'estado'. Si el domicilio no es legible, omite ciudad.\n"
    "- Si la imagen NO contiene NINGÚN dato relevante, responde exactamente con una "
    "cadena vacía sin ningún otro texto."
)

# Prompt para stickers: infiere la intención del usuario.
_VISION_PROMPT_STICKER = (
    "La imagen es un sticker de WhatsApp. Determina la intención que expresa: "
    "afirmación (sí / de acuerdo), negación (no / rechazo), saludo, agradecimiento, "
    "despedida, emoción positiva (alegría, entusiasmo) o emoción negativa (tristeza, "
    "enojo). Responde en español con una expresión muy corta que transmita esa "
    "intención (p. ej. 'sí', 'no', 'hola', 'gracias', 'hasta luego', 'genial'). "
    "Si no puedes determinar la intención con confianza, responde exactamente con "
    "una cadena vacía sin ningún otro texto."
)


_VISION_BIRTHDATE_RE = re.compile(
    r"^\s*fecha_nacimiento\s*:\s*(\d{4})-(\d{2})-(\d{2})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _replace_birthdate_with_age(text: str) -> str:
    """Convierte una línea 'fecha_nacimiento: AAAA-MM-DD' en 'edad: X años'.

    El cálculo es determinista contra la fecha de hoy (incluye el borde del
    cumpleaños), nunca se delega al LLM. Si la fecha es inválida o futura, se
    elimina la línea para no propagar un dato basura al funnel.
    """
    from datetime import date

    def _sub(m: "re.Match[str]") -> str:
        try:
            born = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return ""
        today = date.today()
        age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        if age < 0 or age > 120:
            return ""
        return f"edad: {age} años"

    out = _VISION_BIRTHDATE_RE.sub(_sub, text)
    # Limpia líneas vacías que pudieran quedar tras una sustitución descartada.
    return "\n".join(line for line in out.splitlines() if line.strip()).strip()


def call_gemini_llm(prompt: str) -> str:
    """Generación RAG vía Gemini (proveedor ÚNICO — Groq y Cohere eliminados
    2026-07-07) con el system message de Mundo y config propia GEMINI_* (no se
    reciclan constantes GROQ_*). Ante fallo devuelve el mensaje de disculpa estándar
    (contrato de error del caller), sin invocar otro proveedor."""
    from app.gemini_client import (
        GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE, GeminiError, dispatch_generation,
    )

    try:
        return dispatch_generation(
            _llm_system_message(), prompt,
            temperature=GEMINI_TEMPERATURE, max_tokens=GEMINI_MAX_TOKENS,
        )
    except GeminiError as exc:
        print(f"[gemini] Error: {exc}", flush=True)
        return "Tuve un problema al generar la respuesta. Por favor intenta de nuevo."


def call_llm(prompt: str) -> str:
    # Gemini es el proveedor ÚNICO (gemini-full-provider-migration, 2026-07-07):
    # Groq y Cohere ya no forman parte del ecosistema. Sus funciones legacy de abajo
    # se retiran físicamente en D7 tras la verificación en vivo.
    return call_gemini_llm(prompt)
