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
    },
    "Groq": {
        "modelos": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "env": "GROQ_API_KEY",
    },
}
PRIMER_PROVEEDOR = list(PROVEEDORES.keys())[0]

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


def stream_groq(api_key, modelo, historial, system, temperatura):
    from groq import Groq

    client = Groq(api_key=api_key)
    mensajes = [{"role": "system", "content": system}] + historial
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
# Utilidades
# ---------------------------------------------------------------------------
def key_guardada(proveedor):
    """Key puesta una sola vez por el dueño: Secrets de Streamlit o variable de entorno."""
    nombre = PROVEEDORES[proveedor]["env"]
    try:
        if nombre in st.secrets:
            return str(st.secrets[nombre])
    except Exception:
        pass
    return os.getenv(nombre, "")


def obtener_api_key(proveedor):
    """Prioridad: key personal escrita en la barra lateral > key guardada."""
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
    return f"Ocurrió un error: {texto}"


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

prov_actual = st.session_state.get("proveedor", PRIMER_PROVEEDOR)

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

    temperatura = st.slider("Temperatura (creatividad)", 0.0, 1.0, 0.7, 0.05)
    system_prompt = st.text_area("Instrucciones del sistema", SYSTEM_POR_DEFECTO, height=140)
    modelo_custom = st.text_input(
        "Otro modelo (opcional)",
        placeholder="Escribe un nombre de modelo para usarlo en lugar del de la lista",
    )

    with st.expander("🔑 Usar mi propia API key (opcional)"):
        st.caption(
            "No hace falta. Si el dueño de la app ya la configuró, la IA funciona sola. "
            "Pon tu key aquí solo si quieres usar la tuya."
        )
        st.text_input(
            f"API key de {prov_actual.split(' ')[0]}",
            type="password",
            key=f"key_{prov_actual}",
        )

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
st.title("Estuardo Meza Sabe todo pregunta lo que quieras.....")

modelo_caption = modelo_custom.strip() or st.session_state.get(
    f"modelo_{prov_actual}", PROVEEDORES[prov_actual]["modelos"][0]
)
st.caption(f"Usando **{prov_actual}** · modelo `{modelo_caption}`")

# 1) Zona de mensajes (con scroll propio)
caja_chat = st.container(height=480, border=True)
with caja_chat:
    for m in st.session_state.mensajes:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

# 2) Cuadro de mensaje (dentro de un contenedor para que quede en su lugar)
with st.container():
    pregunta = st.chat_input("Escribe tu mensaje...")

# 3) Selector de API y modelo, debajo del cuadro de mensaje
col_api, col_modelo = st.columns(2)
with col_api:
    proveedor = st.selectbox("API a usar", list(PROVEEDORES.keys()), key="proveedor")
with col_modelo:
    modelo_lista = st.selectbox(
        "Modelo", PROVEEDORES[proveedor]["modelos"], key=f"modelo_{proveedor}"
    )
modelo = modelo_custom.strip() or modelo_lista

api_key = obtener_api_key(proveedor)
if not api_key:
    st.caption(
        f"⚠️ {proveedor} no tiene API key configurada. Elige otra API o escribe tu propia key "
        "en la barra lateral (🔑)."
    )

# ---------------------------------------------------------------------------
# Procesar la pregunta
# ---------------------------------------------------------------------------
if pregunta:
    if not api_key:
        st.warning(f"Falta la API key de {proveedor}.")
        st.stop()

    st.session_state.mensajes.append({"role": "user", "content": pregunta})
    with caja_chat:
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
                    primero = next(generador, "")

                def _todo():
                    yield primero
                    yield from generador

                respuesta = st.write_stream(_todo())
                st.session_state.mensajes.append({"role": "assistant", "content": respuesta})
            except Exception as e:
                st.error(mensaje_de_error(e))
                st.session_state.mensajes.pop()

# Descarga de la última respuesta
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
