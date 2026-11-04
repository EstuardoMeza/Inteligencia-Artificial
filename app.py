import hashlib
import json
import uuid

import streamlit as st
from google import genai
from streamlit_js_eval import streamlit_js_eval

st.set_page_config(page_title="Mi primera IA app", page_icon="✨", layout="wide")

LS_KEY = "mi_ia_chats_v1"  # nombre con el que se guarda en el navegador


# ---------- Configuración ----------
def obtener_secreto(nombre, defecto=None):
    try:
        return st.secrets[nombre]
    except Exception:
        return defecto


MODELO = obtener_secreto("MODELO", "gemini-3.5-flash-lite")
API_KEY = obtener_secreto("GEMINI_API_KEY")

if not API_KEY:
    st.error(
        "Falta la clave GEMINI_API_KEY. Agrégala en .streamlit/secrets.toml "
        "(local) o en Settings → Secrets (Streamlit Cloud)."
    )
    st.stop()


@st.cache_resource
def obtener_cliente(api_key):
    return genai.Client(api_key=api_key)


client = obtener_cliente(API_KEY)


# ---------- Conversaciones ----------
def nueva_conversacion():
    chat_id = str(uuid.uuid4())
    st.session_state.chats[chat_id] = {"titulo": "Nueva conversación", "messages": []}
    st.session_state.chat_actual = chat_id


def seleccionar(chat_id):
    st.session_state.chat_actual = chat_id


def eliminar(chat_id):
    st.session_state.chats.pop(chat_id, None)
    if not st.session_state.chats:
        nueva_conversacion()
    elif st.session_state.chat_actual == chat_id:
        st.session_state.chat_actual = list(st.session_state.chats.keys())[-1]


def borrar_todo():
    st.session_state.chats = {}
    nueva_conversacion()


# ---------- Cargar el historial guardado en ESTE navegador ----------
if "chats" not in st.session_state:
    guardado = streamlit_js_eval(
        js_expressions=f"localStorage.getItem('{LS_KEY}') || ''",
        key="cargar_historial",
    )
    if guardado is None:  # el navegador todavía no respondió
        st.info("Cargando tus conversaciones…")
        st.stop()

    chats, actual = {}, None
    try:
        if guardado:
            datos = json.loads(guardado)
            chats = datos.get("chats", {})
            actual = datos.get("actual")
    except Exception:
        chats = {}

    st.session_state.chats = chats
    if chats:
        st.session_state.chat_actual = (
            actual if actual in chats else list(chats.keys())[-1]
        )
    else:
        nueva_conversacion()


def guardar_historial():
    """Guarda todo en el localStorage del navegador de quien usa la app."""
    datos = json.dumps(
        {
            "chats": st.session_state.chats,
            "actual": st.session_state.chat_actual,
        },
        ensure_ascii=False,
    )
    huella = hashlib.md5(datos.encode("utf-8")).hexdigest()
    streamlit_js_eval(
        js_expressions=f"(localStorage.setItem('{LS_KEY}', {json.dumps(datos)}), 'ok')",
        key=f"guardar_{huella}",
    )


# ---------- Barra lateral tipo Gemini ----------
with st.sidebar:
    st.markdown("### Estuardo Meza Sabe todo pregunta lo que quiera.....")
    st.button(
        "➕ Nueva conversación",
        use_container_width=True,
        on_click=nueva_conversacion,
    )
    st.markdown("##### Recientes")
    for chat_id in reversed(list(st.session_state.chats.keys())):
        chat_item = st.session_state.chats[chat_id]
        activo = chat_id == st.session_state.chat_actual
        col_titulo, col_borrar = st.columns([5, 1])
        col_titulo.button(
            chat_item["titulo"],
            key=f"sel_{chat_id}",
            use_container_width=True,
            type="primary" if activo else "secondary",
            on_click=seleccionar,
            args=(chat_id,),
        )
        col_borrar.button(
            "🗑️",
            key=f"del_{chat_id}",
            help="Eliminar conversación",
            on_click=eliminar,
            args=(chat_id,),
        )
    st.divider()
    st.button(
        "Borrar todo el historial",
        use_container_width=True,
        on_click=borrar_todo,
    )
    st.caption("Tus conversaciones se guardan solo en este navegador.")

# ---------- Conversación actual ----------
chat = st.session_state.chats[st.session_state.chat_actual]

st.title("Mi primera IA app")

for i, message in enumerate(chat["messages"]):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] == "assistant":
            st.download_button(
                "⬇️ Descargar respuesta",
                message["content"],
                file_name=f"respuesta_{i}.txt",
                key=f"descarga_{st.session_state.chat_actual}_{i}",
            )

if prompt := st.chat_input("Escribe el mensaje que deseas preguntar"):
    with st.chat_message("user"):
        st.markdown(prompt)
    chat["messages"].append({"role": "user", "content": prompt})

    # El título de la conversación sale del primer mensaje
    if len(chat["messages"]) == 1:
        chat["titulo"] = prompt[:28] + ("…" if len(prompt) > 28 else "")

    # Gemini usa "model" en lugar de "assistant"
    historial = [
        {
            "role": "model" if m["role"] == "assistant" else "user",
            "parts": [{"text": m["content"]}],
        }
        for m in chat["messages"]
    ]

    with st.chat_message("assistant"):
        with st.spinner("Pensando..."):
            try:
                respuesta = client.models.generate_content(
                    model=MODELO,
                    contents=historial,
                )
                respuesta_ia = respuesta.text or "(La IA no devolvió texto)"
            except Exception as e:
                respuesta_ia = f"Error al conectar con Gemini: {e}"

    chat["messages"].append({"role": "assistant", "content": respuesta_ia})
    st.rerun()

# Al final de cada ejecución: guardar el historial en el navegador
guardar_historial()
