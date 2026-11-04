# Mi primera IA app (Streamlit + Gemini)

## Historial
Se guarda en el localStorage del navegador de cada persona (no en el servidor ni en GitHub).

## Correr en tu PC
1. pip install -r requirements.txt
2. Copia `.streamlit/secrets.toml.example` a `.streamlit/secrets.toml` y pon tu clave NUEVA.
3. streamlit run app.py

## Publicar con URL (Streamlit Community Cloud)
1. Sube la carpeta a un repositorio de GitHub (NO subas secrets.toml; ya está en .gitignore).
2. Entra a https://share.streamlit.io e inicia sesión con GitHub.
3. New app -> elige tu repo, rama main y archivo app.py.
4. Advanced settings -> Secrets: pega  GEMINI_API_KEY = "tu_clave"
5. Deploy. Te dará una URL tipo https://tu-app.streamlit.app
# Inteligencia-Artificial
