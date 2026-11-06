import os
import time
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Estuardo Meza Sabe todo", page_icon="🤖", layout="centered")

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
    # Solo role y content: Groq rechaza campos extra (como "nota")
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
    if any(p in bajo for p in ("503", "unavailable", "high demand", "overloaded")):
        return "Todos los modelos disponibles están saturados en este momento. Intenta de nuevo en un minuto."
    if any(p in bajo for p in ("404", "not_found", "not found", "no longer available", "does not exist")):
        return "Ese modelo no existe o ya no está disponible. Elige otro de la lista."
    return f"Ocurrió un error: {texto}"


# ---------------------------------------------------------------------------
# Resistencia: reintentos + cambio automático de modelo / proveedor
# ---------------------------------------------------------------------------
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
    """Orden de intentos: el elegido -> otros modelos del mismo proveedor -> otros proveedores
    (solo los que tengan API key disponible)."""
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
    """Devuelve (generador, primer_trozo, nota). Reintenta si el modelo está saturado y,
    si no se recupera, prueba con el siguiente modelo o proveedor."""
    candidatos = construir_candidatos(proveedor, modelo)
    if not resistente:
        candidatos = candidatos[:1]

    ultimo_error = None
    sin_acceso = set()  # proveedores con la key inválida: no vale la pena seguir con ellos

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
                    nota = (
                        f"⚠️ {proveedor} · `{modelo}` no respondió, "
                        f"así que contestó {prov} · `{mod}`."
                    )
                return gen, primero, nota
            except Exception as e:
                ultimo_error = e
                if es_error_auth(e):
                    sin_acceso.add(prov)
                    break
                if es_error_cuota(e) or not es_error_temporal(e):
                    break  # reintentar no ayuda: pasar al siguiente
                if intento < intentos:
                    espera = 2 * intento
                    aviso(f"⏳ `{mod}` está saturado. Reintentando en {espera}s...")
                    time.sleep(espera)

        siguientes = [c for c in candidatos[i + 1:] if c[0] not in sin_acceso]
        if siguientes:
            aviso(f"🔁 Cambiando a `{siguientes[0][1]}`...")

    raise ultimo_error or RuntimeError("No hay modelos disponibles.")


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

    resistente = st.checkbox(
        "🛡️ Modo resistente",
        value=True,
        help="Si un modelo está saturado, reintenta y cambia solo a otro modelo u otra IA "
        "(las que tengan API key configurada).",
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
            if m.get("nota"):
                st.caption(m["nota"])

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
            estado = st.empty()
            try:
                with st.spinner("Pensando..."):
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
            except Exception as e:
                estado.empty()
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
