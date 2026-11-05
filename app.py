import os
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Estuardo Meza Sabe todo", page_icon="🤖", layout="centered")

# ---------------------------------------------------------------------------
# Configuración de proveedores
# ---------------------------------------------------------------------------
PROVEEDORES = {
    "Gemini (Google)": {
        "modelos": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
        "env": "GEMINI_API_KEY",
        "secret": "GEMINI_API_KEY",
    },
    "OpenAI (ChatGPT)": {
        "modelos": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
        "env": "OPENAI_API_KEY",
        "secret": "OPENAI_API_KEY",
    },
    "Anthropic (Claude)": {
        "modelos": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
        "env": "ANTHROPIC_API_KEY",
        "secret": "ANTHROPIC_API_KEY",
    },
}

SYSTEM_POR_DEFECTO = (
    "Eres un asistente amable para estudiantes de informática. "
    "Responde siempre en español, de forma clara y con ejemplos cuando ayuden."
)


# ---------------------------------------------------------------------------
# Llamadas a cada API (todas devuelven un generador de texto en streaming)
# ---------------------------------------------------------------------------
def stream_gemini(api_key, modelo, historial, system, temperatura):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
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


def stream_openai(api_key, modelo, historial, system, temperatura):
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    mensajes = [{"role": "system", "content": system}] + historial
    stream = client.chat.completions.create(
        model=modelo, messages=mensajes, temperature=temperatura, stream=True
    )
    for evento in stream:
        if evento.choices and evento.choices[0].delta.content:
            yield evento.choices[0].delta.content


def stream_anthropic(api_key, modelo, historial, system, temperatura):
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=modelo,
        max_tokens=2048,
        system=system,
        messages=historial,
        temperature=temperatura,
    ) as stream:
        for texto in stream.text_stream:
            yield texto


FUNCIONES = {
    "Gemini (Google)": stream_gemini,
    "OpenAI (ChatGPT)": stream_openai,
    "Anthropic (Claude)": stream_anthropic,
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def obtener_api_key(proveedor, escrita_en_sidebar):
    """Prioridad: lo escrito en la barra lateral > st.secrets > variable de entorno."""
    if escrita_en_sidebar:
        return escrita_en_sidebar
    cfg = PROVEEDORES[proveedor]
    try:
        if cfg["secret"] in st.secrets:
            return st.secrets[cfg["secret"]]
    except Exception:
        pass
    return os.getenv(cfg["env"], "")


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
        return "La API key parece inválida o no tiene permisos. Revísala en la barra lateral."
    if any(p in bajo for p in ("quota", "rate limit", "429", "resource_exhausted")):
        return "Se alcanzó el límite de uso (cuota) de esta API. Espera un poco o prueba otro proveedor."
    if isinstance(e, ModuleNotFoundError):
        return f"Falta instalar una librería: {e}. Ejecuta `pip install -r requirements.txt`."
    if any(p in bajo for p in ("connection", "timeout", "network", "getaddrinfo")):
        return "No se pudo conectar. Revisa tu conexión a internet."
    return f"Ocurrió un error: {texto}"


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Lo que platicaste conmigo...")

    if st.button("Nueva conversación", icon=":material/add:", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()

    if st.session_state.mensajes:
        st.download_button(
            "💾 Descargar conversación",
            data=conversacion_a_texto(st.session_state.mensajes),
            file_name=f"conversacion_{datetime.now():%Y%m%d_%H%M}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    st.divider()
    st.markdown("**⚙️ Configuración**")

    proveedor = st.selectbox("API a usar", list(PROVEEDORES.keys()))
    cfg = PROVEEDORES[proveedor]

    modelo_lista = st.selectbox("Modelo", cfg["modelos"])
    modelo_custom = st.text_input(
        "Otro modelo (opcional)",
        placeholder="Escribe un nombre de modelo para usarlo en lugar del de la lista",
    )
    modelo = modelo_custom.strip() or modelo_lista

    key_sidebar = st.text_input(
        f"API key de {proveedor.split(' ')[0]}",
        type="password",
        help="Si la dejas vacía se busca en .streamlit/secrets.toml o en variables de entorno.",
    )
    api_key = obtener_api_key(proveedor, key_sidebar)

    temperatura = st.slider("Temperatura (creatividad)", 0.0, 1.0, 0.7, 0.05)
    system_prompt = st.text_area("Instrucciones del sistema", SYSTEM_POR_DEFECTO, height=140)

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
st.title("Estuardo Meza Sabe todo pregunta lo que quieras.....")
st.caption(f"Usando **{proveedor}** · modelo `{modelo}`")

for m in st.session_state.mensajes:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

pregunta = st.chat_input("Escribe tu mensaje...")

if pregunta:
    if not api_key:
        st.warning(f"Falta la API key de {proveedor}. Escríbela en la barra lateral.")
        st.stop()

    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with st.chat_message("user"):
        st.markdown(pregunta)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Pensando..."):
                generador = FUNCIONES[proveedor](
                    api_key,
                    modelo,
                    st.session_state.mensajes,
                    system_prompt,
                    temperatura,
                )
                # Se toma el primer fragmento dentro del spinner para que
                # desaparezca en cuanto empieza a llegar texto.
                primero = next(generador, "")

            def _todo():
                yield primero
                yield from generador

            respuesta = st.write_stream(_todo())
            st.session_state.mensajes.append({"role": "assistant", "content": respuesta})
        except Exception as e:
            st.error(mensaje_de_error(e))
            # Se quita la pregunta fallida para poder reintentar sin duplicarla
            st.session_state.mensajes.pop()

# Descarga de la última respuesta (como antes)
if st.session_state.mensajes and st.session_state.mensajes[-1]["role"] == "assistant":
    ultima = st.session_state.mensajes[-1]["content"]
    with st.expander("📄 Última respuesta de la IA"):
        st.markdown(ultima)
        st.download_button(
            "Descargar respuesta_ia.txt",
            data=ultima,
            file_name="respuesta_ia.txt",
            mime="text/plain",
        )
