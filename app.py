import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path

import streamlit as st

st.set_page_config(
    page_title="Estuardo Meza · Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------------
# Estilos CSS Personalizados para UI Moderna
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    /* Estilo del fondo global y tipografía */
    .stApp {
        background-color: #0d1117;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Fondo y estilo de la barra lateral */
    section[data-testid="stSidebar"] {
        background-color: #161b22;
        border-right: 1px solid #30363d;
    }

    /* Título principal con gradiente */
    .main-title {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }

    .sub-title {
        color: #8b949e;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    /* Contenedor principal de mensajes */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        border: 1px solid #30363d !important;
        background-color: #161b22 !important;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }

    /* Estilo de los globos de mensaje del chat */
    .stChatMessage {
        background-color: #21262d !important;
        border: 1px solid #30363d;
        border-radius: 12px !important;
        padding: 12px 16px !important;
        margin-bottom: 12px !important;
        color: #c9d1d9 !important;
    }

    /* Mensajes del usuario resaltados */
    div[data-testid="stChatMessage"]:has(span[aria-label="user"]) {
        background-color: #1f242d !important;
        border-left: 4px solid #38bdf8 !important;
    }

    /* Botón principal (Nueva conversación) */
    div.stButton > button {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
    }

    /* Input del chat */
    div[data-testid="stChatInput"] input {
        border-radius: 10px !important;
        border: 1px solid #30363d !important;
        background-color: #161b22 !important;
        color: white !important;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Guardado del historial
# ---------------------------------------------------------------------------
CARPETA = Path("conversaciones")
CARPETA.mkdir(exist_ok=True)

def nuevo_id():
    return uuid.uuid4().hex

def id_valido(cid):
    return bool(re.fullmatch(r"[0-9a-f]{32}", cid or ""))

def guardar_conversacion(cid, mensajes):
    if not id_valido(cid):
        return
    tmp = CARPETA / f"{cid}.tmp"
    tmp.write_text(json.dumps(mensajes, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CARPETA / f"{cid}.json")

def cargar_conversacion(cid):
    if not id_valido(cid):
        return []
    try:
        return json.loads((CARPETA / f"{cid}.json").read_text(encoding="utf-8"))
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Configuración de proveedores
# ---------------------------------------------------------------------------
PROVEEDORES = {
    "Gemini (Google)": {
        "modelos": ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-4-argon"],
        "env": "GEMINI_API_KEY",
    },
    "Groq": {
        "modelos": ["openai/gpt-oss-20b", "openai/gpt-oss-120b"],
        "env": "GROQ_API_KEY",
    },
}
PRIMER_PROVEEDOR = list(PROVEEDORES.keys())[0]

SYSTEM_POR_DEFECTO = (
    "Eres un asistente amable para estudiantes de informática. "
    "Responde siempre en español, de forma clara y con ejemplos cuando ayuden."
)

# ---------------------------------------------------------------------------
# Llamadas API
# ---------------------------------------------------------------------------
def stream_gemini(api_key, modelo, historial, system, temperatura):
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key, http_options=types.HttpOptions(timeout=15000)
    )
    contenido = [
        types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[types.Part(text=m["content"])],
        )
        for m in historial
    ]
    config = types.GenerateContentConfig(
        system_instruction=system, temperature=temperatura
    )
    for chunk in client.models.generate_content_stream(
        model=modelo, contents=contenido, config=config
    ):
        if chunk.text:
            yield chunk.text

def stream_groq(api_key, modelo, historial, system, temperatura):
    from groq import Groq

    client = Groq(api_key=api_key, timeout=15.0, max_retries=0)
    mensajes = [{"role": "system", "content": system}] + [
        {"role": m["role"], "content": m["content"]} for m in historial
    ]
    stream = client.chat.completions.create(
        model=modelo, messages=mensajes, temperature=temperatura, stream=True
    )
    for evento in stream:
        if evento.choices and evento.choices[0].delta.content:
            yield evento.choices[0].delta.content

FUNCIONES = {
    "Gemini (Google)": stream_gemini,
    "Groq": stream_groq,
}

# ---------------------------------------------------------------------------
# Utilidades & Resistencia
# ---------------------------------------------------------------------------
def key_guardada(proveedor):
    nombre = PROVEEDORES[proveedor]["env"]
    try:
        if nombre in st.secrets:
            return str(st.secrets[nombre])
    except Exception:
        pass
    return os.getenv(nombre, "")

def obtener_api_key(proveedor):
    personal = st.session_state.get(f"key_{proveedor}", "").strip()
    return personal or key_guardada(proveedor)

def conversacion_a_texto(mensajes):
    lineas = []
    for m in mensajes:
        quien = "Tú" if m["role"] == "user" else "IA"
        lineas.append(f"{quien}:\n{m['content']}\n")
    return "\n".join(lineas)

def mensaje_de_error(e):
    texto = str(e)
    bajo = texto.lower()
    if any(p in bajo for p in ("api key", "api_key", "authentication", "unauthorized", "401", "permission")):
        return "La API key parece inválida o no tiene permisos."
    if any(p in bajo for p in ("quota", "rate limit", "429", "resource_exhausted", "credit")):
        return "Se alcanzó el límite de uso (cuota) de esta API. Espera un poco o prueba otra."
    if isinstance(e, ModuleNotFoundError):
        return f"Falta instalar una librería: {e}. Revisa que requirements.txt la incluya."
    if any(p in bajo for p in ("connection", "timeout", "network", "getaddrinfo")):
        return "No se pudo conectar. Revisa tu conexión a internet."
    if any(p in bajo for p in ("503", "unavailable", "high demand", "overloaded")):
        return "Todos los modelos disponibles están saturados en este momento. Intenta de nuevo en un minuto."
    if any(p in bajo for p in ("404", "not_found", "not found", "no longer available", "does not exist")):
        return "Ese modelo no existe o ya no está disponible. Elige otro de la lista."
    return f"Ocurrió un error: {texto}"

def _contiene(e, palabras):
    bajo = str(e).lower()
    return any(p in bajo for p in palabras)

def es_error_auth(e):
    return _contiene(e, ("api key", "api_key", "authentication", "unauthorized", "401", "403", "permission"))

def es_error_cuota(e):
    return _contiene(e, ("quota", "rate limit", "429", "resource_exhausted", "credit"))

def es_error_temporal(e):
    return _contiene(
        e,
        ("503", "502", "504", "500", "unavailable", "high demand", "overloaded",
         "timeout", "timed out", "connection", "temporarily", "internal"),
    )

def construir_candidatos(proveedor, modelo):
    candidatos, vistos = [], set()

    def agregar(p, m):
        key = obtener_api_key(p)
        if key and (p, m) not in vistos:
            vistos.add((p, m))
            candidatos.append((p, m, key))

    agregar(proveedor, modelo)
    for m in PROVEEDORES[proveedor]["modelos"]:
        agregar(proveedor, m)
    for p in PROVEEDORES:
        if p != proveedor:
            for m in PROVEEDORES[p]["modelos"]:
                agregar(p, m)
    return candidatos

def abrir_stream_resiliente(proveedor, modelo, historial, system, temperatura, resistente, aviso):
    candidatos = construir_candidatos(proveedor, modelo)
    if not resistente:
        candidatos = candidatos[:1]

    ultimo_error = None
    sin_acceso = set()

    for i, (prov, mod, key) in enumerate(candidatos):
        if prov in sin_acceso:
            continue
        intentos = 1 if not resistente else (3 if i == 0 else 2)

        for intento in range(1, intentos + 1):
            try:
                gen = FUNCIONES[prov](key, mod, historial, system, temperatura)
                primero = next(gen, "")
                nota = None
                if (prov, mod) != (proveedor, modelo):
                    nota = f"⚠️ `{modelo}` no respondió. Respondió `{prov} · {mod}`."
                return gen, primero, nota
            except Exception as e:
                ultimo_error = e
                if es_error_auth(e):
                    sin_acceso.add(prov)
                    break
                if es_error_cuota(e) or not es_error_temporal(e):
                    break
                if intento < intentos:
                    espera = 2 * intento
                    aviso(f"⏳ `{mod}` saturado. Reintentando en {espera}s...")
                    time.sleep(espera)

        siguientes = [c for c in candidatos[i + 1:] if c[0] not in sin_acceso]
        if siguientes:
            aviso(f"🔁 Cambiando a `{siguientes[0][1]}`...")

    raise ultimo_error or RuntimeError("No hay modelos disponibles.")

# ---------------------------------------------------------------------------
# Estado de la sesión
# ---------------------------------------------------------------------------
if "cid" not in st.session_state:
    cid = st.query_params.get("c", "")
    if not id_valido(cid):
        cid = nuevo_id()
    st.query_params["c"] = cid
    st.session_state.cid = cid
    st.session_state.mensajes = cargar_conversacion(cid)

# ---------------------------------------------------------------------------
# Barra lateral (Sidebar reorganizada)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 💬 Historial")
    if st.button("➕ Nueva conversación", use_container_width=True):
        st.session_state.cid = nuevo_id()
        st.query_params["c"] = st.session_state.cid
        st.session_state.mensajes = []
        st.rerun()

    if st.session_state.mensajes:
        st.download_button(
            "💾 Descargar chat",
            data=conversacion_a_texto(st.session_state.mensajes),
            file_name=f"chat_{datetime.now():%Y%m%d_%H%M}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.divider()

    # Controles de Modelo colocados en la barra lateral
    st.markdown("### 🤖 Modelo de IA")
    proveedor = st.selectbox("Proveedor", list(PROVEEDORES.keys()), key="proveedor")
    modelo_lista = st.selectbox("Modelo base", PROVEEDORES[proveedor]["modelos"], key=f"modelo_{proveedor}")
    modelo_custom = st.text_input("Otro modelo (opcional)", placeholder="Ej. gemini-1.5-pro")
    modelo = modelo_custom.strip() or modelo_lista

    st.divider()

    st.markdown("### ⚙️ Ajustes")
    temperatura = st.slider("Creatividad (Temperatura)", 0.0, 1.0, 0.7, 0.05)
    system_prompt = st.text_area("Instrucciones de la IA", SYSTEM_POR_DEFECTO, height=120)
    resistente = st.checkbox("🛡️ Modo resistente", value=True)

    with st.expander("🔑 Clave API personal"):
        st.text_input(
            f"API Key ({proveedor.split(' ')[0]})",
            type="password",
            key=f"key_{proveedor}",
        )

# ---------------------------------------------------------------------------
# Zona Principal (Chat Area)
# ---------------------------------------------------------------------------
st.markdown('<div class="main-title">Estuardo Meza · IA Assistant</div>', unsafe_allow_html=True)
st.markdown(f'<div class="sub-title">Conectado a <b>{proveedor}</b> mediante <code>{modelo}</code></div>', unsafe_allow_html=True)

api_key = obtener_api_key(proveedor)
if not api_key:
    st.info(f"💡 Selecciona o configura una API Key para comenzar a chatear.")

# Contenedor con barra de desplazamiento para los mensajes
caja_chat = st.container(height=520, border=True)
with caja_chat:
    for m in st.session_state.mensajes:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("nota"):
                st.caption(m["nota"])

pregunta = st.chat_input("Escribe tu pregunta de informática...")

# ---------------------------------------------------------------------------
# Procesar Respuesta
# ---------------------------------------------------------------------------
if pregunta:
    if not api_key:
        st.warning(f"Falta la API key para {proveedor}.")
        st.stop()

    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with caja_chat:
        with st.chat_message("user"):
            st.markdown(pregunta)

        with st.chat_message("assistant"):
            estado = st.empty()
            try:
                with st.spinner("Generando respuesta..."):
                    generador, primero, nota = abrir_stream_resiliente(
                        proveedor,
                        modelo,
                        st.session_state.mensajes,
                        system_prompt,
                        temperatura,
                        resistente,
                        lambda texto: estado.caption(texto),
                    )
                estado.empty()

                def _todo():
                    yield primero
                    yield from generador

                respuesta = st.write_stream(_todo())
                if nota:
                    st.caption(nota)
                st.session_state.mensajes.append(
                    {"role": "assistant", "content": respuesta, "nota": nota}
                )
                guardar_conversacion(st.session_state.cid, st.session_state.mensajes)
            except Exception as e:
                estado.empty()
                st.error(mensaje_de_error(e))
                st.session_state.mensajes.pop()