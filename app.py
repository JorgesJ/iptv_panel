from fastapi import FastAPI, Form, HTTPException, UploadFile, File, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import aiohttp
import asyncio
import requests
import json
import os
import io
import re
import time
import unicodedata
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = "listas.json"
URLS_FILE = "urls_escaneadas.json"
URLS_TXT_FILE = "urls_txt.json"
URLS_VERIFICADAS_FILE = "urls_verificadas.json"
M3U_FOLDER = "listas_m3u"
TIMEOUT = 10
MAX_PARALLEL = 10

if not os.path.exists(M3U_FOLDER):
    os.makedirs(M3U_FOLDER)

CACHE: dict = {}


def normalizar(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.upper())
        if unicodedata.category(c) != 'Mn'
    )


def cargar_listas():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_listas(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_urls():
    if not os.path.exists(URLS_FILE):
        return []
    try:
        with open(URLS_FILE, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return []


def guardar_urls(data):
    with open(URLS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_urls_txt():
    if not os.path.exists(URLS_TXT_FILE):
        return []
    with open(URLS_TXT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_urls_txt(data):
    with open(URLS_TXT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def cargar_urls_verificadas():
    if not os.path.exists(URLS_VERIFICADAS_FILE):
        return []
    with open(URLS_VERIFICADAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_urls_verificadas(data):
    with open(URLS_VERIFICADAS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def limpiar_nombre(nombre):
    nombre = re.sub(r'https?://', '', nombre)
    nombre = re.sub(r'[\\/*?:"<>|]', '_', nombre)
    return nombre.strip().strip('/')


MAC_PATTERN = re.compile(r'/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/')

def parsear_m3u(texto):
    lineas = texto.splitlines()
    canales = []
    for i, linea in enumerate(lineas):
        if not linea.startswith("#EXTINF"):
            continue
        partes = linea.split(",", 1)
        if len(partes) < 2:
            continue
        nombre = partes[1].strip()
        url_stream = lineas[i + 1].strip() if i + 1 < len(lineas) else ""
        if not url_stream or url_stream.startswith("#"):
            continue
        if '/series/' in url_stream.lower() or '/movie/' in url_stream.lower():
            continue
        # Descartar streams con MAC address en la URL
        if MAC_PATTERN.search(url_stream):
            continue
        canales.append({"nombre": nombre, "url": url_stream, "extinf": linea})
    return canales


def aplicar_filtro(canales, filtro):
    # Sin filtro o comodín = devolver todos
    if not filtro or not filtro.strip() or filtro.strip() == '*':
        return canales
    filtros = [normalizar(f.strip()) for f in filtro.split(',') if f.strip()]
    if not filtros:
        return canales
    def coincide(nombre):
        n = normalizar(nombre)
        for f in filtros:
            if n.startswith(f):
                return True
            if f in n:
                return True
        return False
    return [c for c in canales if coincide(c["nombre"])]


# ─── Endpoints principales ────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "IPTV Analyzer API activa"}


@app.post("/check")
def check(url: str = Form(...)):
    try:
        t0 = time.time()
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        ping = round((time.time() - t0) * 1000)
        r.raise_for_status()
    except requests.exceptions.Timeout:
        raise HTTPException(400, "La lista no responde (timeout)")
    except requests.exceptions.ConnectionError:
        raise HTTPException(400, "No se puede conectar con el servidor")
    except Exception as e:
        raise HTTPException(400, f"Error: {str(e)[:120]}")

    canales = parsear_m3u(r.text)
    if not canales:
        raise HTTPException(404, "La URL responde pero no contiene canales M3U validos")

    clave = f"{url}_{int(time.time())}"
    CACHE[clave] = {"url": url, "canales": canales}

    return JSONResponse({
        "disponible": True,
        "ping": ping,
        "total": len(canales),
        "clave": clave,
        "url": url,
    })


@app.post("/filtrar")
def filtrar(clave: str = Form(...), filtro: str = Form(...)):
    entrada = CACHE.get(clave)
    if not entrada:
        raise HTTPException(400, "Sesion expirada. Vuelve a comprobar la lista.")

    filtrados = aplicar_filtro(entrada["canales"], filtro)

    return JSONResponse({
        "total_filtrados": len(filtrados),
        "filtro": filtro,
        "canales": filtrados,
    })


@app.post("/save")
def save(
    nombre: str = Form(...),
    clave: str = Form(...),
    filtro: str = Form(...),
    max_conn: int = Form(default=1),
    caducidad: str = Form(default=""),
    observaciones: str = Form(default=""),
    ping: int = Form(default=0),
):
    entrada = CACHE.get(clave)
    if not entrada:
        raise HTTPException(400, "Sesion expirada.")

    canales = aplicar_filtro(entrada["canales"], filtro)
    if not canales:
        raise HTTPException(400, "No hay canales con el filtro indicado")

    nombre_limpio = re.sub(r'https?://', '', nombre)
    nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_limpio).strip()

    filename = os.path.join(M3U_FOLDER, f"{nombre_limpio}.m3u")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    listas = cargar_listas()
    listas = [l for l in listas if l["nombre"] != nombre_limpio]
    listas.append({
        "nombre": nombre_limpio,
        "url": entrada["url"],
        "filtro": filtro,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "total_canales": len(canales),
        "max_conn": max_conn,
        "caducidad": caducidad,
        "observaciones": observaciones,
        "ping": ping,
        "archivo": filename,
    })
    guardar_listas(listas)

    return JSONResponse({"ok": True, "guardados": len(canales)})


@app.get("/listas")
def get_listas():
    return JSONResponse(cargar_listas())


@app.get("/listas/{nombre:path}/canales")
def get_canales_lista(nombre: str):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")
    archivo = lista.get("archivo", "")
    if not archivo or not os.path.exists(archivo):
        raise HTTPException(404, "Archivo .m3u no encontrado")
    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()
    canales = parsear_m3u(contenido)
    return JSONResponse({"nombre": nombre, "total": len(canales), "canales": canales})


@app.get("/listas/{nombre:path}/conexiones")
def get_conexiones_lista(nombre: str):
    """Consulta conexiones activas via player_api.php"""
    from urllib.parse import unquote
    import re as _re
    nombre = unquote(nombre)
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")
    url = lista.get("url", "")
    if not url:
        raise HTTPException(400, "La lista no tiene URL")

    # Extraer credenciales de la URL
    m = _re.search(r'https?://([^/]+)/get\.php\?username=([^&]+)&password=([^&]+)', url)
    if not m:
        raise HTTPException(400, "No se pueden extraer credenciales de la URL")

    host = m.group(1)
    username = m.group(2)
    password = m.group(3)
    api_url = f"http://{host}/player_api.php?username={username}&password={password}"

    try:
        import requests as req
        r = req.get(api_url, headers={"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        ui = data.get("user_info", {})
        return JSONResponse({
            "activas": int(ui.get("active_connections", 0)),
            "max": int(ui.get("max_connections", 0)),
            "status": ui.get("status", ""),
            "caducidad": ui.get("exp_date", ""),
            "username": username,
            "api_url": api_url,
        })
    except Exception as e:
        raise HTTPException(400, f"Error consultando API: {str(e)[:100]}")



def actualizar_canales_lista(nombre: str):
    """Re-descarga la lista desde su URL y actualiza el archivo .m3u con canales españoles."""
    from urllib.parse import unquote
    import unicodedata as _ud
    import re as _re
    nombre = unquote(nombre)
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")
    url = lista.get("url", "")
    if not url:
        raise HTTPException(400, "La lista no tiene URL para re-descargar")

    try:
        import requests as req
        r = req.get(url, headers={"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}, timeout=30)
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(400, f"No se pudo descargar la lista: {str(e)[:100]}")

    todos = parsear_m3u(r.text)

    def es_espanol(c):
        n = ''.join(ch for ch in _ud.normalize('NFD', c['nombre'].upper()) if _ud.category(ch) != 'Mn')
        e = c.get('extinf', '')
        ei = ''.join(ch for ch in _ud.normalize('NFD', e.upper()) if _ud.category(ch) != 'Mn')
        if n.startswith('ES:') or n.startswith('ES ') or n.startswith('ES|'): return True
        if n.startswith('(ES)') or n.startswith('[ES]'): return True
        if n.startswith('ESP:') or n.startswith('ESP '): return True
        if '|ES|' in n: return True
        if 'ESPANA' in n or 'SPAIN' in n: return True
        if '| ES ' in n or '|ES ' in n: return True
        if 'ESPANA' in ei or 'SPAIN' in ei: return True
        gt = _re.search(r'group-title="([^"]*)"', e, _re.IGNORECASE)
        if gt:
            g = ''.join(ch for ch in _ud.normalize('NFD', gt.group(1).upper()) if _ud.category(ch) != 'Mn')
            if 'ESPANA' in g or 'SPAIN' in g or g.startswith('ES'): return True
        n2 = _re.sub(r'^\([^)]*\)\s*', '', n).strip()
        if n2.startswith('M+') or n2.startswith('M.') or n2.startswith('DAZN'): return True
        return False

    canales_es = [c for c in todos if es_espanol(c)]
    canales = canales_es if canales_es else todos

    archivo = lista.get("archivo", "")
    if not archivo:
        archivo = os.path.join(M3U_FOLDER, f"{nombre}.m3u")

    with open(archivo, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    listas = [{**l, "total_canales": len(canales)} if l["nombre"] == nombre else l for l in listas]
    guardar_listas(listas)

    return JSONResponse({"ok": True, "total": len(canales), "msg": f"Actualizados {len(canales)} canales"})



def delete_todas_listas():
    listas = cargar_listas()
    for lista in listas:
        archivo = lista.get("archivo", "")
        if archivo and os.path.exists(archivo):
            os.remove(archivo)
    guardar_listas([])
    return JSONResponse({"ok": True, "eliminadas": len(listas)})


@app.delete("/listas/{nombre:path}")
def delete_lista(nombre: str):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")
    archivo = lista.get("archivo", "")
    if archivo and os.path.exists(archivo):
        os.remove(archivo)
    guardar_listas([l for l in listas if l["nombre"] != nombre])
    return JSONResponse({"ok": True})


@app.get("/download/{nombre:path}")
def download_m3u(nombre: str):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")
    archivo = lista.get("archivo", "")
    if not archivo or not os.path.exists(archivo):
        raise HTTPException(404, "Archivo .m3u no encontrado")
    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()
    return StreamingResponse(
        io.BytesIO(contenido.encode("utf-8")),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.m3u"'},
    )


# ─── Endpoints URLs escaneadas ────────────────────────────────────────────────

@app.get("/urls")
def get_urls():
    return JSONResponse(cargar_urls())


@app.get("/urls/txt")
def get_urls_txt():
    return JSONResponse(cargar_urls_txt())


@app.post("/urls/txt/limpiar")
def limpiar_urls_txt():
    guardar_urls_txt([])
    return JSONResponse({"ok": True})


@app.get("/urls/verificadas")
def get_urls_verificadas():
    return JSONResponse(cargar_urls_verificadas())


@app.post("/urls/verificadas/limpiar")
def limpiar_urls_verificadas():
    guardar_urls_verificadas([])
    return JSONResponse({"ok": True})


@app.delete("/urls/verificadas/eliminar")
def eliminar_url_verificada(url: str = Form(...)):
    """Elimina una URL específica de urls_verificadas.json"""
    verificadas = cargar_urls_verificadas()
    nuevas = [v for v in verificadas if v["url"] != url]
    guardar_urls_verificadas(nuevas)
    return JSONResponse({"ok": True, "eliminadas": len(verificadas) - len(nuevas)})



@app.post("/urls/verificadas/importar")
async def importar_json_verificadas(archivo: UploadFile = File(...)):
    """Importa un JSON de urls_verificadas externo (ej: generado en Android)
    y lo fusiona con el local sin duplicados."""
    try:
        contenido = await archivo.read()
        nuevas_data = json.loads(contenido.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "El archivo no es un JSON válido")

    if not isinstance(nuevas_data, list):
        raise HTTPException(400, "El JSON debe ser una lista de URLs verificadas")

    existentes = cargar_urls_verificadas()
    urls_exist = {e["url"] for e in existentes}
    nuevas = [d for d in nuevas_data if d.get("url") and d["url"] not in urls_exist]
    todo = existentes + nuevas
    guardar_urls_verificadas(todo)

    return JSONResponse({"ok": True, "nuevas": len(nuevas), "total": len(todo)})


@app.post("/urls/buscar")
async def buscar_en_urls(filtro: str = Form(default=""), fuente: str = Form(default="telegram")):
    if fuente == "telegram":
        urls = cargar_urls()
    elif fuente == "verificadas":
        urls = cargar_urls_verificadas()
    else:
        urls = cargar_urls_txt()
    if not urls:
        raise HTTPException(400, "No hay URLs en esta fuente. Ejecuta el scanner primero.")

    total = len(urls)
    completadas = 0
    verificando = 0
    con_canales = []
    sin_canales = []
    lock = asyncio.Lock()

    async def verificar_streams(session, canales_muestra, sem_streams):
        """Intenta conectar a una muestra de canales. Devuelve % de éxito."""
        async def probar_stream(url_stream):
            # Intentar HEAD primero (más rápido)
            for method in ['HEAD', 'GET']:
                try:
                    if method == 'HEAD':
                        async with session.head(
                            url_stream,
                            timeout=aiohttp.ClientTimeout(total=5),
                            allow_redirects=True
                        ) as r:
                            if r.status in (200, 206):
                                return True
                    else:
                        async with session.get(
                            url_stream,
                            timeout=aiohttp.ClientTimeout(connect=3, total=6),
                            allow_redirects=True
                        ) as r:
                            if r.status in (200, 206):
                                # Leer solo los primeros bytes para confirmar
                                try:
                                    chunk = await asyncio.wait_for(r.content.read(512), timeout=3)
                                    return len(chunk) > 0
                                except Exception:
                                    return True  # Si responde 200 aunque no lea bytes, contar como OK
                except Exception:
                    continue
            return False

        tareas = [probar_stream(c["url"]) for c in canales_muestra]
        resultados = await asyncio.gather(*tareas)
        exitosos = sum(1 for r in resultados if r)
        return exitosos, len(resultados)

    async def procesar(session, entrada, sem, sem_streams):
        nonlocal completadas, verificando
        async with sem:
            url = entrada["url"]
            resultado = {"url": url, "entrada": entrada, "encontrados": 0, "canales": []}
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)
                ) as r:
                    if r.status in (200, 206):
                        texto = await r.text()
                        canales = parsear_m3u(texto)
                        filtrados = aplicar_filtro(canales, filtro)
                        if filtrados:
                            # Tomar muestra del 25% (min 5, max 20)
                            import random
                            n_muestra = max(5, min(20, len(filtrados) // 4))
                            muestra = random.sample(filtrados, min(n_muestra, len(filtrados)))

                            async with lock:
                                verificando += 1

                            # Verificar streams reales
                            exitosos, total_muestra = await verificar_streams(session, muestra, sem_streams)
                            pct_ok = (exitosos / total_muestra * 100) if total_muestra > 0 else 0

                            async with lock:
                                verificando -= 1

                            if pct_ok >= 75:
                                clave = f"scan_{url}_{int(time.time())}"
                                CACHE[clave] = {"url": url, "canales": filtrados}
                                resultado = {
                                    "url": url,
                                    "entrada": entrada,
                                    "encontrados": len(filtrados),
                                    "clave": clave,
                                    "canales": filtrados[:5],
                                    "streams_ok": exitosos,
                                    "streams_total": total_muestra,
                                    "pct_ok": round(pct_ok),
                                }
            except Exception:
                pass

            async with lock:
                completadas += 1
                if resultado["encontrados"] > 0:
                    con_canales.append(resultado)
                else:
                    sin_canales.append(url)

            return resultado

    async def stream():
        sem = asyncio.Semaphore(MAX_PARALLEL)
        sem_streams = asyncio.Semaphore(30)
        connector = aiohttp.TCPConnector(ssl=False)

        msg_inicio = json.dumps({"tipo": "inicio", "total": total})
        yield "data: " + msg_inicio + "\n\n"

        async with aiohttp.ClientSession(connector=connector) as session:
            tareas = [asyncio.ensure_future(procesar(session, u, sem, sem_streams)) for u in urls]
            ultimo_enviado = -1

            while not all(t.done() for t in tareas):
                await asyncio.sleep(0.5)
                snap_completadas = completadas
                if snap_completadas != ultimo_enviado:
                    ultimo_enviado = snap_completadas
                    msg = json.dumps({
                        "tipo": "progreso",
                        "completadas": snap_completadas,
                        "total": total,
                        "con_canales": len(con_canales),
                        "con_canales_data": list(con_canales),
                        "verificando": verificando,
                    })
                    yield "data: " + msg + "\n\n"

            await asyncio.gather(*tareas)

        # Depurar JSON: si la fuente es txt, eliminar las que no pasaron verificación
        if fuente == "txt" and con_canales:
            urls_ok = {r["url"] for r in con_canales}
            txt_actual = cargar_urls_txt()
            # Mantener solo las que pasaron el filtro y verificación, o las que no se escanearon
            urls_escaneadas_set = {u["url"] for u in urls}
            txt_depurado = [
                u for u in txt_actual
                if u["url"] in urls_ok or u["url"] not in urls_escaneadas_set
            ]
            guardar_urls_txt(txt_depurado)

        msg_fin = json.dumps({
            "tipo": "fin",
            "filtro": filtro,
            "total_urls": total,
            "con_canales": con_canales,
            "sin_canales": sin_canales,
        })
        yield "data: " + msg_fin + "\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/urls/guardar")
def guardar_desde_scan(
    nombre: str = Form(...),
    clave: str = Form(...),
    filtro: str = Form(...),
    max_conn: int = Form(default=1),
    caducidad: str = Form(default=""),
    observaciones: str = Form(default=""),
    ping: int = Form(default=0),
):
    canales = []
    url = ""
    descarga_ok = True

    # Si la clave empieza por "verificada_" viene de urls_verificadas.json
    if clave.startswith("verificada_"):
        url = clave[len("verificada_"):]
        try:
            headers = {"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}
            import requests as req
            r = req.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            todos = parsear_m3u(r.text)
            # Filtrar canales españoles con todos los patrones conocidos
            def es_canal_espanol(c):
                n = c['nombre'].upper()
                # Quitar acentos
                import unicodedata
                n = ''.join(ch for ch in unicodedata.normalize('NFD', n) if unicodedata.category(ch) != 'Mn')
                e = c.get('extinf', '').upper()
                e = ''.join(ch for ch in unicodedata.normalize('NFD', e) if unicodedata.category(ch) != 'Mn')
                if n.startswith('ES:') or n.startswith('ES ') or n.startswith('ES|'): return True
                if n.startswith('(ES)') or n.startswith('[ES]'): return True
                if n.startswith('ESP:') or n.startswith('ESP '): return True
                if '|ES|' in n: return True
                if 'ESPANA' in n or 'SPAIN' in n: return True
                if '| ES ' in n or '|ES ' in n: return True
                if 'ESPANA' in e or 'SPAIN' in e: return True
                # group-title en extinf
                import re as _re
                gt = _re.search(r'group-title="([^"]*)"', c.get('extinf',''), _re.IGNORECASE)
                if gt:
                    g = ''.join(ch for ch in unicodedata.normalize('NFD', gt.group(1).upper()) if unicodedata.category(ch) != 'Mn')
                    if 'ESPANA' in g or 'SPAIN' in g or g.startswith('ES'): return True
                # Canales Movistar y DAZN
                n2 = _re.sub(r'^\([^)]*\)\s*', '', n).strip()
                if n2.startswith('M+') or n2.startswith('M.') or n2.startswith('DAZN'): return True
                return False
            canales_es = [c for c in todos if es_canal_espanol(c)]
            canales = canales_es if canales_es else todos
        except Exception:
            # Si no se puede descargar (servidor bloquea IP), guardar URL sin canales
            descarga_ok = False
            canales = []
    else:
        entrada = CACHE.get(clave)
        if not entrada:
            raise HTTPException(400, "Sesion expirada. Vuelve a buscar.")
        canales = entrada["canales"]
        url = entrada["url"]

    nombre_limpio = re.sub(r'https?://', '', nombre)
    nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_limpio).strip()

    # Añadir MaxConn y caducidad al nombre del archivo
    sufijo = f"_Conn{max_conn}"
    if caducidad and caducidad != 'Unlimited':
        try:
            partes = caducidad.split('-')
            sufijo += f"_{partes[2]}_{partes[1]}_{partes[0][2:]}"
        except Exception:
            pass
    elif caducidad == 'Unlimited':
        sufijo += "_Unlim"
    nombre_archivo = nombre_limpio + sufijo

    # Guardar archivo .m3u si tenemos canales
    filename = os.path.join(M3U_FOLDER, f"{nombre_archivo}.m3u")
    if canales:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            for c in canales:
                f.write(c["extinf"] + "\n")
                f.write(c["url"] + "\n")
    else:
        # Guardar .m3u mínimo con solo la URL de la lista para poder abrirla luego
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1,{nombre_limpio}\n{url}\n")

    listas = cargar_listas()
    listas = [l for l in listas if l["nombre"] != nombre_limpio]
    listas.append({
        "nombre": nombre_limpio,
        "url": url,
        "filtro": filtro,
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "total_canales": len(canales),
        "max_conn": max_conn,
        "caducidad": caducidad,
        "observaciones": observaciones,
        "ping": ping,
        "archivo": filename,
        "descarga_ok": descarga_ok,
        "tipo_lista": "Cuenta Xtream (M3U)" if "get.php" in url.lower() else "Lista M3U",
    })
    guardar_listas(listas)

    return JSONResponse({
        "ok": True,
        "guardados": len(canales),
        "descarga_ok": descarga_ok,
        "msg": "Lista guardada" if descarga_ok else "URL guardada (lista no descargable desde esta IP - usa el VPS para obtener los canales)"
    })


@app.post("/urls/guardar-todas")
async def guardar_todas_desde_scan(request: Request):
    """
    Guarda múltiples listas en paralelo. Recibe lista de entradas con clave, nombre, metadata.
    Descarga todos los M3U en paralelo con aiohttp — mucho más rápido que en serie.
    """
    body = await request.json()
    entradas = body.get("entradas", [])
    filtro = body.get("filtro", "")

    if not entradas:
        raise HTTPException(400, "No hay entradas que guardar")

    def construir_nombre(nombre_raw, max_conn, caducidad):
        nombre_limpio = re.sub(r'https?://', '', nombre_raw)
        nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_limpio).strip()
        sufijo = f"_Conn{max_conn}"
        if caducidad and caducidad != 'Unlimited':
            try:
                partes = caducidad.split('-')
                sufijo += f"_{partes[2]}_{partes[1]}_{partes[0][2:]}"
            except Exception:
                pass
        elif caducidad == 'Unlimited':
            sufijo += "_Unlim"
        return nombre_limpio, nombre_limpio + sufijo

    async def descargar_y_guardar(session, entrada, sem):
        async with sem:
            url = entrada.get("url", "")
            max_conn = int(entrada.get("max_conn", 1))
            caducidad = entrada.get("caducidad", "")
            observaciones = entrada.get("observaciones", "")
            ping = int(entrada.get("ping", 0))
            nombre_raw = entrada.get("nombre", url)

            nombre_limpio, nombre_archivo = construir_nombre(nombre_raw, max_conn, caducidad)
            filename = os.path.join(M3U_FOLDER, f"{nombre_archivo}.m3u")
            canales = []
            descarga_ok = True

            try:
                headers = {"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    if r.status in (200, 206):
                        texto = await r.text()
                        todos = parsear_m3u(texto)
                        # Aplicar filtro si hay uno, si no todos
                        if filtro and filtro.strip():
                            canales = aplicar_filtro(todos, filtro)
                            if not canales:
                                canales = todos  # si no matchea nada, guardar todos
                        else:
                            # Sin filtro: intentar quedarse con ES primero
                            canales_es = [c for c in todos if
                                c['nombre'].upper().startswith('ES:') or
                                c['nombre'].upper().startswith('ES ') or
                                'ESPAÑA' in c['nombre'].upper() or
                                'ESPANA' in c['nombre'].upper()
                            ]
                            canales = canales_es if canales_es else todos
                    else:
                        descarga_ok = False
            except Exception:
                descarga_ok = False

            # Guardar archivo .m3u
            with open(filename, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                if canales:
                    for c in canales:
                        f.write(c["extinf"] + "\n")
                        f.write(c["url"] + "\n")
                else:
                    f.write(f"#EXTINF:-1,{nombre_limpio}\n{url}\n")

            return {
                "nombre": nombre_limpio,
                "url": url,
                "filtro": filtro,
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "total_canales": len(canales),
                "max_conn": max_conn,
                "caducidad": caducidad,
                "observaciones": observaciones,
                "ping": ping,
                "archivo": filename,
                "descarga_ok": descarga_ok,
                "tipo_lista": "Cuenta Xtream (M3U)" if "get.php" in url.lower() else "Lista M3U",
            }

    sem = asyncio.Semaphore(8)  # 8 descargas en paralelo
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [descargar_y_guardar(session, e, sem) for e in entradas]
        resultados = await asyncio.gather(*tareas)

    # Guardar todas en listas.json de una vez
    listas = cargar_listas()
    nombres_nuevos = {r["nombre"] for r in resultados}
    listas = [l for l in listas if l["nombre"] not in nombres_nuevos]
    listas.extend(resultados)
    guardar_listas(listas)

    return JSONResponse({
        "ok": True,
        "guardadas": len(resultados),
        "con_canales": sum(1 for r in resultados if r["total_canales"] > 0),
    })


@app.delete("/urls/eliminar")
def eliminar_url(url: str = Form(...)):
    urls = cargar_urls()
    guardar_urls([u for u in urls if u["url"] != url])
    return JSONResponse({"ok": True})


@app.post("/urls/guardar-todas")
async def guardar_todas_desde_scan(request: Request):
    """
    Guarda múltiples listas en paralelo desde el backend.
    Recibe lista de {url, nombre, max_conn, caducidad, observaciones, ping, filtro}.
    Descarga todas en paralelo con aiohttp y guarda en listas.json.
    El proceso ocurre en el servidor — no depende de que el frontend esté abierto.
    """
    body = await request.json()
    entradas = body.get("entradas", [])
    filtro = body.get("filtro", "")

    if not entradas:
        raise HTTPException(400, "No hay entradas que guardar")

    resultados_guardado = []
    lock = asyncio.Lock()

    async def procesar_entrada(session, entrada, sem):
        async with sem:
            url = entrada.get("url", "")
            nombre_raw = entrada.get("nombre", "")
            max_conn = int(entrada.get("max_conn", 1))
            caducidad = entrada.get("caducidad", "")
            observaciones = entrada.get("observaciones", "")
            ping = int(entrada.get("ping", 0))

            nombre_limpio = re.sub(r'https?://', '', nombre_raw)
            nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_limpio).strip()

            sufijo = f"_Conn{max_conn}"
            if caducidad and caducidad != 'Unlimited':
                try:
                    partes = caducidad.split('-')
                    sufijo += f"_{partes[2]}_{partes[1]}_{partes[0][2:]}"
                except Exception:
                    pass
            elif caducidad == 'Unlimited':
                sufijo += "_Unlim"
            nombre_archivo = nombre_limpio + sufijo
            filename = os.path.join(M3U_FOLDER, f"{nombre_archivo}.m3u")

            canales = []
            descarga_ok = True

            try:
                headers = {"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status in (200, 206):
                        texto = await r.text()
                        todos = parsear_m3u(texto)
                        # Aplicar filtro si hay, si no todos
                        if filtro and filtro.strip():
                            filtrados = aplicar_filtro(todos, filtro)
                            canales = filtrados if filtrados else todos
                        else:
                            # Sin filtro: intentar ES primero, si no todos
                            canales_es = [c for c in todos if
                                c['nombre'].upper().startswith('ES:') or
                                c['nombre'].upper().startswith('ES ') or
                                'ESPAÑA' in c['nombre'].upper() or
                                'ESPANA' in c['nombre'].upper()
                            ]
                            canales = canales_es if canales_es else todos
                    else:
                        descarga_ok = False
            except Exception:
                descarga_ok = False

            # Guardar .m3u
            with open(filename, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                if canales:
                    for c in canales:
                        f.write(c["extinf"] + "\n")
                        f.write(c["url"] + "\n")
                else:
                    f.write(f"#EXTINF:-1,{nombre_limpio}\n{url}\n")

            entrada_lista = {
                "nombre": nombre_limpio,
                "url": url,
                "filtro": filtro,
                "fecha": datetime.now().isoformat(timespec="seconds"),
                "total_canales": len(canales),
                "max_conn": max_conn,
                "caducidad": caducidad,
                "observaciones": observaciones,
                "ping": ping,
                "archivo": filename,
                "descarga_ok": descarga_ok,
                "tipo_lista": "Cuenta Xtream (M3U)" if "get.php" in url.lower() else "Lista M3U",
            }

            async with lock:
                listas = cargar_listas()
                listas = [l for l in listas if l["nombre"] != nombre_limpio]
                listas.append(entrada_lista)
                guardar_listas(listas)
                resultados_guardado.append({"nombre": nombre_limpio, "ok": True, "canales": len(canales)})

    sem = asyncio.Semaphore(8)  # 8 descargas en paralelo
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [procesar_entrada(session, e, sem) for e in entradas]
        await asyncio.gather(*tareas)

    return JSONResponse({
        "ok": True,
        "guardadas": len(resultados_guardado),
        "resultados": resultados_guardado,
    })


@app.post("/urls/importar-txt")
async def importar_txt(archivo: UploadFile = File(...)):
    """
    Procesa un archivo TXT con el formato del canal de Telegram.
    Extrae URLs, comprueba disponibilidad y las añade a urls_escaneadas.json.
    """
    contenido = await archivo.read()
    texto_completo = contenido.decode("utf-8", errors="ignore")

    def unicode_a_ascii(texto):
        rangos = [
            (0x1D400, 0x1D419, 'A'), (0x1D41A, 0x1D433, 'a'),
            (0x1D434, 0x1D44D, 'A'), (0x1D44E, 0x1D467, 'a'),
            (0x1D468, 0x1D481, 'A'), (0x1D482, 0x1D49B, 'a'),
            (0x1D49C, 0x1D4B5, 'A'), (0x1D4BB, 0x1D4C3, 'a'),
            (0x1D5A0, 0x1D5B9, 'A'), (0x1D5BA, 0x1D5D3, 'a'),
            (0x1D5D4, 0x1D5ED, 'A'), (0x1D5EE, 0x1D607, 'a'),
            (0x1D608, 0x1D621, 'A'), (0x1D622, 0x1D63B, 'a'),
            (0x1D63C, 0x1D655, 'A'), (0x1D656, 0x1D66F, 'a'),
        ]
        resultado = []
        for char in texto:
            cp = ord(char)
            convertido = False
            for inicio, fin, base in rangos:
                if inicio <= cp <= fin:
                    offset = cp - inicio
                    resultado.append(chr(ord('A' if base == 'A' else 'a') + offset))
                    convertido = True
                    break
            if not convertido:
                if 0x1D7CE <= cp <= 0x1D7D7:
                    resultado.append(chr(ord('0') + cp - 0x1D7CE))
                    convertido = True
            if not convertido:
                resultado.append(char)
        return ''.join(resultado)

    def parsear_bloque(texto_original):
        texto = unicode_a_ascii(texto_original)
        datos = {}

        portal = re.search(r'Portal\s*[:\-]\s*(https?://\S+)', texto, re.IGNORECASE)
        if portal:
            datos['portal'] = re.sub(r'\s+', '', portal.group(1).strip())

        exp = re.search(r'Exp\s*[:\-]\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
        if exp:
            partes = exp.group(1).split('/')
            datos['caducidad'] = f"{partes[2]}-{partes[1]}-{partes[0]}"
        else:
            exp_unl = re.search(r'Exp\s*[:\-]\s*(Unlimited|Ilimitado)', texto, re.IGNORECASE)
            if exp_unl:
                datos['caducidad'] = 'Unlimited'

        maxconn = re.search(r'MaxConn\s*[:\-]\s*(\d+)', texto, re.IGNORECASE)
        if maxconn:
            datos['max_conn'] = int(maxconn.group(1))

        status = re.search(r'Status\s*[:\-]\s*(.+)', texto, re.IGNORECASE)
        if status:
            datos['observaciones'] = status.group(1).strip()

        m3u = re.search(r'M3U\s*[:\-]\s*(https?://\S+)', texto, re.IGNORECASE)
        if m3u:
            datos['url_m3u'] = re.sub(r'\s+', '', m3u.group(1).strip())
        else:
            m3u2 = re.search(r'(https?://\S+type=m3u\S*)', texto_original, re.IGNORECASE)
            if m3u2:
                datos['url_m3u'] = re.sub(r'\s+', '', m3u2.group(1).strip())

        return datos

    # Separar bloques por la línea de separación o por el encabezado del scanner
    es_formato_bloques = bool(re.search(r'[^\x00-\x7F]{3,}', texto_completo[:500]))

    todas = []
    vistas = set()

    if es_formato_bloques:
        bloques = re.split(r'(?=👤|〓{3,})', texto_completo)
        for bloque in bloques:
            if 'get.php' not in bloque.lower() and 'type=m3u' not in bloque.lower():
                continue
            datos = parsear_bloque(bloque)
            if not datos.get('url_m3u'):
                continue
            if datos['url_m3u'] in vistas:
                continue
            vistas.add(datos['url_m3u'])
            todas.append(datos)
    else:
        # Formato URLs directas (una por línea)
        url_pattern = re.compile(
            r'https?://[^\s]*get\.php\?[^\s]*type=m3u[^\s]*',
            re.IGNORECASE
        )
        for linea in texto_completo.splitlines():
            linea = linea.strip()
            match = url_pattern.search(linea)
            if not match:
                continue
            url = match.group(0).rstrip('&')
            url_base = re.sub(r'&output=[^\s&]+', '', url)
            if url_base in vistas:
                continue
            vistas.add(url_base)
            todas.append({
                'url_m3u': url_base,
                'portal': '',
                'caducidad': '',
                'max_conn': 1,
                'observaciones': '',
            })

    if not todas:
        raise HTTPException(400, "No se encontraron URLs M3U en el archivo")

    # Comprobar disponibilidad
    async def comprobar(session, datos, sem):
        async with sem:
            url = datos['url_m3u']
            t0 = time.time()
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status not in (200, 206):
                        return None
            except Exception:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as r:
                        ping = round((time.time() - t0) * 1000)
                        if r.status not in (200, 206):
                            return None
                except Exception:
                    return None

            if ping > 1000:
                return None

            return {
                "url": url,
                "portal": datos.get('portal', ''),
                "caducidad": datos.get('caducidad', ''),
                "max_conn": datos.get('max_conn', 1),
                "observaciones": datos.get('observaciones', ''),
                "ping": ping,
                "fecha_scan": datetime.now().isoformat(timespec="seconds"),
            }

    sem = asyncio.Semaphore(MAX_PARALLEL)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [comprobar(session, d, sem) for d in todas]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r is not None]

    # Añadir al JSON existente (sin duplicados)
    existentes = cargar_urls_txt()
    urls_existentes = {e['url'] for e in existentes}
    nuevas = [d for d in disponibles if d['url'] not in urls_existentes]
    todo = existentes + nuevas
    guardar_urls_txt(todo)

    return JSONResponse({
        "ok": True,
        "total_encontradas": len(todas),
        "disponibles": len(disponibles),
        "nuevas": len(nuevas),
        "total_guardado": len(todo),
    })


@app.post("/urls/importar-txt-verificadas")
async def importar_txt_a_verificadas(archivo: UploadFile = File(...)):
    """
    Importa un TXT con URLs, hace ping, consulta player_api.php para obtener
    metadatos (MaxConn, caducidad, status) y guarda directamente en urls_verificadas.json.
    No intenta descargar las listas M3U completas.
    """
    contenido = await archivo.read()
    texto = contenido.decode("utf-8", errors="ignore")

    url_pattern = re.compile(r'https?://[^\s]*get\.php\?[^\s]*type=m3u[^\s]*', re.IGNORECASE)
    vistas = set()
    urls = []
    for linea in texto.splitlines():
        linea = linea.strip()
        match = url_pattern.search(linea)
        if not match:
            continue
        url = re.sub(r'&output=[^\s&]+', '', match.group(0).rstrip('&'))
        if url not in vistas:
            vistas.add(url)
            urls.append(url)

    if not urls:
        raise HTTPException(400, "No se encontraron URLs M3U en el archivo")

    async def obtener_info_y_ping(session, url, sem):
        async with sem:
            t0 = time.time()
            # Ping básico
            try:
                async with session.head(url, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status not in (200, 206) or ping > 2000:
                        return None
            except Exception:
                return None

            # Consultar player_api.php
            info = {}
            try:
                m = re.match(r'(https?://[^/]+)/get\.php\?username=([^&]+)&password=([^&]+)', url, re.IGNORECASE)
                if m:
                    api_url = f"{m.group(1)}/player_api.php?username={m.group(2)}&password={m.group(3)}"
                    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        if r.status == 200:
                            data = await r.json(content_type=None)
                            ui = data.get('user_info', {})
                            info['status'] = ui.get('status', '')
                            info['max_conn'] = int(ui.get('max_connections', 1) or 1)
                            info['observaciones'] = ui.get('status', '')
                            exp = ui.get('exp_date')
                            if exp and str(exp).isdigit():
                                from datetime import timezone
                                dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
                                info['caducidad'] = dt.strftime('%Y-%m-%d')
                            elif not exp:
                                info['caducidad'] = 'Unlimited'
                            else:
                                info['caducidad'] = str(exp)
            except Exception:
                pass

            return {
                "url": url,
                "portal": re.match(r'https?://[^/]+', url).group(0) if re.match(r'https?://[^/]+', url) else '',
                "caducidad": info.get('caducidad', ''),
                "max_conn": info.get('max_conn', 1),
                "observaciones": info.get('observaciones', ''),
                "ping": ping,
                "fecha_verificacion": datetime.now().isoformat(timespec="seconds"),
                "pct_streams": 0,
                "total_canales": 0,
            }

    sem = asyncio.Semaphore(MAX_PARALLEL)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [obtener_info_y_ping(session, u, sem) for u in urls]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r is not None]

    # Guardar en urls_verificadas.json sin duplicados
    existentes = cargar_urls_verificadas()
    urls_existentes = {e['url'] for e in existentes}
    nuevas = [d for d in disponibles if d['url'] not in urls_existentes]
    todo = existentes + nuevas
    guardar_urls_verificadas(todo)

    return JSONResponse({
        "ok": True,
        "total_encontradas": len(urls),
        "disponibles": len(disponibles),
        "nuevas": len(nuevas),
        "total_guardado": len(todo),
    })


def get_canales_lista(nombre: str):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    """Devuelve todos los canales de una lista guardada"""
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")

    archivo = lista.get("archivo", "")
    if not archivo or not os.path.exists(archivo):
        raise HTTPException(404, "Archivo .m3u no encontrado")

    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()

    canales = parsear_m3u(contenido)
    return JSONResponse({
        "nombre": nombre,
        "total": len(canales),
        "canales": canales,
    })


@app.post("/listas/{nombre:path}/reordenar")
async def reordenar_lista(nombre: str, request: Request):
    from urllib.parse import unquote
    from fastapi import Request
    nombre = unquote(unquote(nombre))

    # Intentar leer como JSON primero, luego como Form
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        canales_data = body.get("canales", body) if isinstance(body, dict) else body
    else:
        form = await request.form()
        import json as _json
        canales_raw = form.get("canales", "[]")
        canales_data = _json.loads(canales_raw)

    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, f"Lista no encontrada: {nombre}")

    archivo = lista.get("archivo", "")
    if not archivo:
        raise HTTPException(400, "Sin archivo .m3u")

    carpeta = os.path.dirname(archivo)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)

    with open(archivo, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales_data:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    listas = [l if l["nombre"] != nombre else {**l, "total_canales": len(canales_data)} for l in listas]
    guardar_listas(listas)

    return JSONResponse({"ok": True, "guardados": len(canales_data)})


@app.post("/listas/{nombre:path}/ordenar-movistar")
def ordenar_movistar(nombre: str):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    """Ordena los canales según la parrilla oficial de Movistar+ y elimina prefijos"""
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")

    archivo = lista.get("archivo", "")
    if not archivo or not os.path.exists(archivo):
        raise HTTPException(404, "Archivo .m3u no encontrado")

    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()

    canales = parsear_m3u(contenido)

    # Orden oficial Movistar+ por diales (nombre normalizado)
    ORDEN_MOVISTAR = [
        # Dial 1-6: Generalistas TDT
        "LA 1", "TVE LA 1", "LA 2", "TVE LA 2", "ANTENA 3", "CUATRO", "TELECINCO", "LA SEXTA",
        # Dial 7: Movistar Plus+
        "MOVISTAR PLUS", "#0",
        # Dial 8: Vamos
        "VAMOS",
        # Dial 9: Autonómica Valencia - À Punt
        "A PUNT", "APUNT",
        # Dial 12-25: Cine y series por M+
        "ESTRENOS", "HITS", "ORIGINALES", "DOCUMENTALES",
        "CLASICOS", "CLASICO", "ACCION", "COMEDIA", "DRAMA", "INDIE",
        "CINE ESPANOL",
        # Dial 27-49: Series y entretenimiento
        "SKYSHOWTIME", "SKY SHOWTIME",
        "TCM",
        "AXN MOVIES",
        "BBC SERIES", "BBC DRAMA",
        "BBC TOP GEAR",
        "BEMAD",
        "STAR CHANNEL",
        "AXN",
        "WARNER",
        "COMEDY CENTRAL",
        "CALLE 13",
        "COSMO",
        "SYFY",
        "VEO7", "VEO 7",
        "TRECE",
        "ENERGY",
        "FDF",
        "NEOX",
        "ATRESERIES",
        # Dial 50-51: Vamos deportes
        "VAMOS 2",
        # Dial 52: Primera Federación
        "PRIMERA FEDERACION",
        # Dial 54-59: LaLiga
        "LALIGA", "LA LIGA",
        "DAZN LALIGA", "DAZN LA LIGA",
        "HYPERMOTION",
        # Dial 60-65: Champions y deportes
        "LIGA DE CAMPEONES", "CHAMPIONS", "EUROPA LEAGUE", "CONFERENCE LEAGUE",
        "DEPORTES",
        "MOVISTAR DEPORTE",
        # Dial 66-81: Deportes especializados
        "ELLAS VAMOS", "ELLAS",
        "GOLF",
        "DAZN F1", "FORMULA 1", "FORMULA1", "F1",
        "MOTOGP",
        "DAZN 1", "DAZN 2", "DAZN 3", "DAZN 4",
        "EUROSPORT",
        "GOL",
        "TELEDEPORTE",
        "REAL MADRID TV",
        "CAZA Y PESCA",
        "UBEAT",
        "TAQUILLA",
        "BEIN SPORTS", "BEIN LALIGA", "BEIN",
        "TAQUILLA",
        # Dial 82-90: Documentales
        "NATIONAL GEOGRAPHIC", "NAT GEO",
        "DISCOVERY",
        "BBC HISTORY",
        "BBC EARTH",
        "DAZN BALONCESTO", "BALONCESTO",
        "DMAX",
        # Dial 92-98: Estilo de vida
        "BBC FOOD",
        "BBC LIFESTYLE",
        "DKISS",
        "DIVINITY",
        "NOVA",
        "MEGA",
        "TEN",
        "CANAL COCINA", "COCINA",
        # Dial 110-118: Infantil
        "BABYTV",
        "DISNEY JUNIOR",
        "NICK JR",
        "NICKELODEON",
        "DREAMWORKS",
        "BOING",
        "CLAN TVE", "CLAN",
        "DISNEY",
        # Dial 120-125: Música
        "MTV",
        "MEZZO",
        "STINGRAY",
        # Dial 127+: Informativos internacionales
        "24H", "24 HORAS", "CANAL 24",
        "BBC WORLD", "BBC NEWS",
        "CNN",
        "EURONEWS",
        "AL JAZEERA",
        "FRANCE 24",
        "CNBC",
        "TV5 MONDE",
        "BLOOMBERG",
        "SKY NEWS",
        "CGTN",
        # Internacionales
        "TVE INTERNACIONAL", "TVE INT",
        # Al final: resto de autonómicas que no son valencianas
        "TV3", "CANAL 33", "SUPER3", "3/24", "ESPORT3",
        "TVG", "TVG2", "TVG EUROPA",
        "ETB1", "ETB2", "ETB3", "ETB4", "ETB BASQUE",
        "CANAL SUR", "ANDALUCIA TV",
        "ARAGON TV",
        "TELEMADRID",
        "IB3",
        "CANAL EXTREMADURA",
        "MURCIA", "REGION DE MURCIA",
        "LA RIOJA TV",
        "TPA", "RTPA",
        "NAVARRA TV",
        "TV CANARIA",
        "CMM",
    ]

    def normalizar_nombre_canal(nombre):
        """Elimina prefijos tipo ES:, ESPAÑA -, Movistar , etc."""
        # Eliminar prefijos comunes
        nombre = re.sub(r'^ES\s*:\s*', '', nombre, flags=re.IGNORECASE)
        nombre = re.sub(r'^ESPA[NÑ]A\s*[-|:]\s*', '', nombre, flags=re.IGNORECASE)
        nombre = re.sub(r'^ES\s*\|\s*', '', nombre, flags=re.IGNORECASE)
        return nombre.strip()

    def normalizar_para_busqueda(nombre):
        """Quita prefijos adicionales para mejorar el matching con Movistar"""
        # Quitar prefijo Movistar para comparar solo el nombre del canal
        nombre = re.sub(r'^Movistar\s+', '', nombre, flags=re.IGNORECASE)
        nombre = re.sub(r'^M\+\s*', '', nombre, flags=re.IGNORECASE)
        nombre = re.sub(r'\s*(FHD|HD|UHD|VIP|HEVC)\s*$', '', nombre, flags=re.IGNORECASE)
        return nombre.strip()

    def normalizar_para_match(texto):
        """Normaliza texto para comparación: minúsculas, sin tildes, sin espacios extra"""
        import unicodedata as _ud
        texto = texto.upper().strip()
        # Quitar tildes
        texto = ''.join(
            c for c in _ud.normalize('NFD', texto)
            if _ud.category(c) != 'Mn'
        )
        # Quitar caracteres especiales excepto espacios y números
        texto = re.sub(r'[^A-Z0-9 ]', ' ', texto)
        # Reducir espacios múltiples
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto

    def get_orden_movistar(canal_nombre):
        nombre_sin_prefijo = normalizar_nombre_canal(canal_nombre)
        nombre_sin_movistar = normalizar_para_busqueda(nombre_sin_prefijo)
        nombre_limpio = normalizar_para_match(nombre_sin_movistar)
        nombre_completo = normalizar_para_match(nombre_sin_prefijo)
        mejor_pos = len(ORDEN_MOVISTAR)

        palabras_ignorar = {'HD', 'FHD', 'UHD', 'TV', 'POR', 'LAS', 'LOS', 'DEL', 'EL', 'LA', 'LE', 'THE', 'DE', 'EN', 'AL', 'UN', 'Y', 'TVE'}

        for i, patron in enumerate(ORDEN_MOVISTAR):
            patron_norm = normalizar_para_match(patron)
            palabras_patron = set(patron_norm.split()) - palabras_ignorar
            palabras_patron = {p for p in palabras_patron if len(p) >= 4}

            for nombre_a_probar in [nombre_limpio, nombre_completo]:
                palabras_nombre = set(nombre_a_probar.split()) - palabras_ignorar
                palabras_nombre = {p for p in palabras_nombre if len(p) >= 4}

                # 1. Coincidencia exacta (máxima prioridad)
                if nombre_a_probar == patron_norm:
                    return i

                # 2. Todas las palabras del patrón están en el nombre
                if palabras_patron and palabras_patron.issubset(palabras_nombre):
                    if i < mejor_pos:
                        mejor_pos = i
                        continue

                # 3. Todas las palabras del nombre están en el patrón
                if palabras_nombre and palabras_nombre.issubset(palabras_patron):
                    if i < mejor_pos:
                        mejor_pos = i
                        continue

                # 4. Al menos 2 palabras significativas coinciden
                palabras_comunes = palabras_patron & palabras_nombre
                if len(palabras_comunes) >= 2:
                    if i < mejor_pos:
                        mejor_pos = i

        return mejor_pos

    # Ordenar canales
    canales_ordenados = sorted(canales, key=lambda c: get_orden_movistar(c["nombre"]))

    # Limpiar prefijos en los nombres y en extinf
    import re as _re
    def limpiar_extinf(extinf, nombre_original):
        nombre_limpio = normalizar_nombre_canal(nombre_original)
        # Reemplazar el nombre en la línea extinf
        partes = extinf.split(",", 1)
        if len(partes) == 2:
            return partes[0] + "," + nombre_limpio
        return extinf

    canales_limpios = []
    for c in canales_ordenados:
        nombre_limpio = normalizar_nombre_canal(c["nombre"])
        extinf_limpio = limpiar_extinf(c["extinf"], c["nombre"])
        canales_limpios.append({
            "nombre": nombre_limpio,
            "url": c["url"],
            "extinf": extinf_limpio,
        })

    # Guardar el archivo reordenado
    with open(archivo, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales_limpios:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    # Actualizar total en listas.json
    listas = [l if l["nombre"] != nombre else {**l, "total_canales": len(canales_limpios)} for l in listas]
    guardar_listas(listas)

    return JSONResponse({
        "ok": True,
        "total": len(canales_limpios),
        "canales": canales_limpios,
    })


@app.delete("/listas/{nombre:path}/canales/{idx}")
def eliminar_canal(nombre: str, idx: int):
    from urllib.parse import unquote
    nombre = unquote(nombre)
    """Elimina un canal por índice de la lista guardada"""
    listas = cargar_listas()
    lista = next((l for l in listas if l["nombre"] == nombre), None)
    if not lista:
        raise HTTPException(404, "Lista no encontrada")

    archivo = lista.get("archivo", "")
    if not archivo or not os.path.exists(archivo):
        raise HTTPException(404, "Archivo .m3u no encontrado")

    with open(archivo, "r", encoding="utf-8") as f:
        contenido = f.read()

    canales = parsear_m3u(contenido)
    if idx < 0 or idx >= len(canales):
        raise HTTPException(400, "Índice fuera de rango")

    canales.pop(idx)

    with open(archivo, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    listas = [l if l["nombre"] != nombre else {**l, "total_canales": len(canales)} for l in listas]
    guardar_listas(listas)

    return JSONResponse({"ok": True, "total": len(canales)})


@app.get("/listas/descargar-todas")
def descargar_todas():
    """Descarga todas las listas guardadas como un archivo ZIP"""
    import zipfile
    import io
    listas = cargar_listas()
    if not listas:
        raise HTTPException(400, "No hay listas guardadas")

    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    nombre_zip = f"listas_iptv_{fecha}.zip"

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for lista in listas:
            archivo = lista.get("archivo", "")
            if archivo and os.path.exists(archivo):
                nombre_archivo = os.path.basename(archivo)
                zf.write(archivo, nombre_archivo)

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={nombre_zip}"}
    )


@app.post("/listas/ordenar-movistar-todas")
async def ordenar_movistar_todas():
    """Aplica el orden Movistar+ a todas las listas guardadas"""
    listas = cargar_listas()
    resultados = []
    for lista in listas:
        try:
            import requests as req
            nombre = lista["nombre"]
            # Llamar al endpoint de ordenar-movistar para cada lista
            # Reutilizar la lógica directamente
            archivo = lista.get("archivo", "")
            if not archivo or not os.path.exists(archivo):
                resultados.append({"nombre": nombre, "ok": False, "error": "Archivo no encontrado"})
                continue
            resultados.append({"nombre": nombre, "ok": True})
        except Exception as e:
            resultados.append({"nombre": lista["nombre"], "ok": False, "error": str(e)})

    # Llamar a ordenar_movistar para cada lista directamente
    errores = []
    exitos = 0
    for lista in listas:
        try:
            nombre = lista["nombre"]
            archivo = lista.get("archivo", "")
            if not archivo or not os.path.exists(archivo):
                continue

            with open(archivo, "r", encoding="utf-8") as f:
                contenido = f.read()

            canales = parsear_m3u(contenido)

            # Reutilizar la misma lógica de ordenar_movistar
            ORDEN_MOVISTAR_ALL = [
                "LA 1", "TVE LA 1", "LA 2", "TVE LA 2", "ANTENA 3", "CUATRO", "TELECINCO", "LA SEXTA",
                "MOVISTAR PLUS", "#0", "VAMOS", "A PUNT", "APUNT",
                "ESTRENOS", "HITS", "ORIGINALES", "DOCUMENTALES",
                "CLASICOS", "ACCION", "COMEDIA", "DRAMA", "INDIE", "CINE ESPANOL",
                "SKYSHOWTIME", "TCM", "AXN MOVIES", "BBC SERIES", "BBC TOP GEAR",
                "BEMAD", "STAR CHANNEL", "AXN", "WARNER", "COMEDY CENTRAL",
                "CALLE 13", "COSMO", "SYFY", "VEO7", "TRECE", "ENERGY", "FDF", "NEOX", "ATRESERIES",
                "VAMOS 2", "PRIMERA FEDERACION",
                "LALIGA", "LA LIGA", "DAZN LALIGA", "HYPERMOTION",
                "LIGA DE CAMPEONES", "CHAMPIONS", "EUROPA LEAGUE", "CONFERENCE LEAGUE",
                "DEPORTES", "MOVISTAR DEPORTE", "PARTIDAZO", "FUTBOL",
                "ELLAS VAMOS", "GOLF", "DAZN F1", "FORMULA 1", "F1", "MOTOGP", "MOTO GP",
                "DAZN 1", "DAZN 2", "EUROSPORT", "GOL", "TELEDEPORTE",
                "BEIN SPORTS", "BEIN LALIGA", "TAQUILLA",
                "NATIONAL GEOGRAPHIC", "NAT GEO", "DISCOVERY", "BBC HISTORY", "BBC EARTH",
                "DAZN BALONCESTO", "DMAX",
                "BBC FOOD", "BBC LIFESTYLE", "DKISS", "DIVINITY", "NOVA", "MEGA", "TEN",
                "CANAL COCINA", "COCINA",
                "BABYTV", "DISNEY JUNIOR", "NICK JR", "NICKELODEON", "DREAMWORKS", "BOING", "CLAN TVE", "CLAN", "DISNEY",
                "MTV", "MEZZO", "STINGRAY",
                "24H", "24 HORAS", "BBC WORLD", "CNN", "EURONEWS", "AL JAZEERA", "FRANCE 24",
                "CNBC", "TV5 MONDE", "BLOOMBERG", "SKY NEWS", "CGTN",
                "LALIGA 3", "LALIGA 4", "LALIGA 5",
                "TV3", "CANAL 33", "SUPER3", "3/24", "ESPORT3",
                "TVG", "TVG2", "TVG EUROPA", "ETB1", "ETB2", "ETB3", "ETB4", "ETB BASQUE",
                "CANAL SUR", "ANDALUCIA TV", "ARAGON TV", "TELEMADRID", "IB3",
                "CANAL EXTREMADURA", "MURCIA", "LA RIOJA TV", "TPA", "RTPA",
                "NAVARRA TV", "TV CANARIA", "CMM", "TVE INTERNACIONAL",
            ]

            palabras_ignorar = {'HD', 'FHD', 'UHD', 'TV', 'POR', 'LAS', 'LOS', 'DEL', 'EL', 'LA', 'LE', 'THE', 'DE', 'EN', 'AL', 'UN', 'Y', 'TVE'}

            def nm(texto):
                texto = texto.upper().strip()
                texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
                texto = re.sub(r'[^A-Z0-9 ]', ' ', texto)
                return re.sub(r'\s+', ' ', texto).strip()

            def get_palabras(texto):
                return {p for p in nm(texto).split() if len(p) >= 4 and p not in palabras_ignorar}

            def get_orden(canal_nombre):
                sin_prefijo = re.sub(r'^ES\s*:\s*', '', canal_nombre, flags=re.IGNORECASE)
                sin_prefijo = re.sub(r'^ESPA[NÑ]A\s*[-|:]\s*', '', sin_prefijo, flags=re.IGNORECASE)
                sin_movistar = re.sub(r'^Movistar\s+', '', sin_prefijo, flags=re.IGNORECASE)
                sin_movistar = re.sub(r'\s*(FHD|HD|UHD|VIP|HEVC)\s*$', '', sin_movistar, flags=re.IGNORECASE).strip()
                versiones = [nm(sin_movistar), nm(sin_prefijo)]
                mejor = len(ORDEN_MOVISTAR_ALL)
                for i, patron in enumerate(ORDEN_MOVISTAR_ALL):
                    patron_nm = nm(patron)
                    palabras_p = get_palabras(patron)
                    for v in versiones:
                        palabras_v = get_palabras(v)
                        if v == patron_nm: return i
                        if palabras_p and palabras_p.issubset(palabras_v):
                            if i < mejor: mejor = i
                        if palabras_v and palabras_v.issubset(palabras_p):
                            if i < mejor: mejor = i
                        comunes = palabras_p & palabras_v
                        if len(comunes) >= 2:
                            if i < mejor: mejor = i
                return mejor

            def limpiar_nombre(nombre_canal):
                nombre_canal = re.sub(r'^ES\s*:\s*', '', nombre_canal, flags=re.IGNORECASE)
                nombre_canal = re.sub(r'^ESPA[NÑ]A\s*[-|:]\s*', '', nombre_canal, flags=re.IGNORECASE)
                nombre_canal = re.sub(r'^ES\s*\|\s*', '', nombre_canal, flags=re.IGNORECASE)
                nombre_canal = re.sub(r'^Movistar\s+', '', nombre_canal, flags=re.IGNORECASE)
                return nombre_canal.strip()

            canales_ordenados = sorted(canales, key=lambda c: get_orden(c["nombre"]))

            canales_limpios = []
            for c in canales_ordenados:
                nombre_limpio = limpiar_nombre(c["nombre"])
                partes = c["extinf"].split(",", 1)
                extinf_limpio = partes[0] + "," + nombre_limpio if len(partes) == 2 else c["extinf"]
                canales_limpios.append({"nombre": nombre_limpio, "url": c["url"], "extinf": extinf_limpio})

            # Sobreescribir el archivo existente
            with open(archivo, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")
                for c in canales_limpios:
                    f.write(c["extinf"] + "\n")
                    f.write(c["url"] + "\n")

            exitos += 1
        except Exception as e:
            errores.append({"nombre": lista.get("nombre", "?"), "error": str(e)})

    return JSONResponse({"ok": True, "exitos": exitos, "errores": errores})


@app.post("/canales/probar-velocidad")
async def probar_velocidad(urls: list = Form(...)):
    """Prueba la velocidad de respuesta de una lista de URLs de stream"""
    import json as _json
    urls_list = _json.loads(urls[0]) if isinstance(urls, list) else _json.loads(urls)

    async def ping_url(session, url, sem):
        async with sem:
            t0 = time.time()
            try:
                async with session.head(
                    url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True
                ) as r:
                    ping = round((time.time() - t0) * 1000)
                    return {"url": url, "ping": ping, "ok": r.status in (200, 206)}
            except Exception:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=5)
                    ) as r:
                        ping = round((time.time() - t0) * 1000)
                        return {"url": url, "ping": ping, "ok": r.status in (200, 206)}
                except Exception:
                    return {"url": url, "ping": -1, "ok": False}

    sem = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [ping_url(session, url, sem) for url in urls_list]
        resultados = await asyncio.gather(*tareas)

    return JSONResponse(resultados)

@app.post("/check-m3u-file")
async def check_m3u_file(request: Request):
    """Consulta player_api de un servidor a partir de credenciales extraídas de un M3U"""
    data = await request.json()
    api_url = data.get('api_url', '')
    servidor = data.get('servidor', '')
    usuario = data.get('usuario', '')
    password = data.get('password', '')
    total_canales = data.get('total_canales', 0)
    nombre = data.get('nombre', '')

    import time
    t0 = time.time()
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                api_url,
                headers={"User-Agent": "VLC/3.0.20 LibVLC/3.0.20"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                ping = round((time.time() - t0) * 1000)
                if r.status not in (200, 206):
                    # Si es 451 (bloqueado por IP) devolver info básica sin API
                    if r.status == 451:
                        return JSONResponse({
                            'nombre': nombre,
                            'url': f"http://{servidor}/get.php?username={usuario}&password={password}&type=m3u",
                            'servidor': servidor,
                            'usuario': usuario,
                            'password': password,
                            'max_conn': 0,
                            'activas': 0,
                            'caducidad': '',
                            'status': 'Bloqueado por IP (activa Warp)',
                            'total_canales': total_canales,
                            'ping': ping,
                            'api_disponible': False,
                        })
                    raise HTTPException(400, f"Servidor respondió {r.status}")
                texto = await r.text()
                ping_val = round((time.time() - t0) * 1000)

                # Intentar parsear como JSON (Xtream API)
                try:
                    info = json.loads(texto)
                    user_info = info.get('user_info', {})

                    exp = user_info.get('exp_date')
                    if exp:
                        try:
                            caducidad = datetime.fromtimestamp(int(exp)).strftime('%Y-%m-%d')
                        except:
                            caducidad = str(exp)
                    else:
                        caducidad = 'Unlimited' if user_info.get('status') == 'Active' else ''

                    return JSONResponse({
                        'nombre': nombre,
                        'url': f"http://{servidor}/get.php?username={usuario}&password={password}&type=m3u",
                        'servidor': servidor,
                        'usuario': usuario,
                        'password': password,
                        'max_conn': int(user_info.get('max_connections', 0)),
                        'activas': int(user_info.get('active_cons', 0)),
                        'caducidad': caducidad,
                        'status': user_info.get('status', ''),
                        'total_canales': total_canales,
                        'ping': ping_val,
                        'api_disponible': True,
                    })
                except Exception:
                    # Servidor no expone API — devolver info básica del archivo
                    return JSONResponse({
                        'nombre': nombre,
                        'url': f"http://{servidor}/live/{usuario}/{password}/",
                        'servidor': servidor,
                        'usuario': usuario,
                        'password': password,
                        'max_conn': 0,
                        'activas': 0,
                        'caducidad': '',
                        'status': 'Sin API',
                        'total_canales': total_canales,
                        'ping': ping_val,
                        'api_disponible': False,
                    })
    except aiohttp.ClientError as e:
        raise HTTPException(400, f"Error de conexión: {str(e)[:80]}")
    except Exception as e:
        raise HTTPException(400, f"Error: {str(e)[:80]}")


@app.post("/listas/guardar-directo")
async def guardar_lista_directo(request: Request):
    """
    Guarda una lista M3U directamente desde el frontend (editor local).
    Recibe: nombre, canales (lista), url, max_conn, caducidad, observaciones, ping.
    Respeta el orden exacto de los canales recibidos.
    """
    body = await request.json()
    nombre_raw = body.get("nombre", "lista_editada")
    canales_data = body.get("canales", [])
    url_origen = body.get("url", "")
    max_conn = int(body.get("max_conn", 0))
    caducidad = body.get("caducidad", "")
    observaciones = body.get("observaciones", "")
    ping = int(body.get("ping", 0))

    if not canales_data:
        raise HTTPException(400, "No hay canales que guardar")

    nombre_limpio = re.sub(r'https?://', '', nombre_raw)
    nombre_limpio = re.sub(r'[\\/*?:"<>|]', '_', nombre_limpio).strip()
    if not nombre_limpio:
        nombre_limpio = "lista_editada"

    filename = os.path.join(M3U_FOLDER, f"{nombre_limpio}.m3u")
    with open(filename, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for c in canales_data:
            f.write(c["extinf"] + "\n")
            f.write(c["url"] + "\n")

    listas = cargar_listas()
    listas = [l for l in listas if l["nombre"] != nombre_limpio]
    listas.append({
        "nombre": nombre_limpio,
        "url": url_origen,
        "filtro": "",
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "total_canales": len(canales_data),
        "max_conn": max_conn,
        "caducidad": caducidad,
        "observaciones": observaciones,
        "ping": ping,
        "archivo": filename,
        "tipo_lista": "Lista M3U editada",
    })
    guardar_listas(listas)

    return JSONResponse({"ok": True, "guardados": len(canales_data), "nombre": nombre_limpio})
