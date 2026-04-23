"""
menu.py - IPTV Panel CLI
========================
Menu principal para gestionar listas IPTV desde consola.
"""

import os
import sys
import json
import asyncio
import aiohttp
import re
import time
import random
import unicodedata
import zipfile
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── Suprimir errores gaierror/DNS de aiohttp en consola ─────────────────────
logging.getLogger('asyncio').setLevel(logging.CRITICAL)
logging.getLogger('aiohttp').setLevel(logging.CRITICAL)
logging.disable(logging.WARNING)

# ─── Archivos ─────────────────────────────────────────────────────────────────
URLS_TELEGRAM_FILE  = "urls_escaneadas.json"
URLS_TXT_FILE       = "urls_txt.json"
URLS_VERIFICADAS    = "urls_verificadas.json"
LISTAS_FILE         = "listas.json"
M3U_FOLDER          = "listas_m3u"
SCAN_HISTORY_FOLDER = "scan_history"

# ─── Configuración ────────────────────────────────────────────────────────────
TIMEOUT_LISTA       = 30
TIMEOUT_STREAM      = 15
MAX_PAR_LISTAS      = 8
MAX_PAR_STREAMS     = 15  # Reducido para no saturar servidores
MIN_PCT_STREAMS     = 75
MIN_CANALES         = 10
BYTES_A_LEER        = 32768  # 32KB — suficiente para verificar patrón MPEG-TS real
MAX_PING            = 6000

# Headers que simulan VLC — detecta servidores que bloquean VLC específicamente
HEADERS_VLC = {
    "User-Agent": "VLC/3.0.20 LibVLC/3.0.20",
    "Accept": "*/*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Connection": "keep-alive",
    "Icy-MetaData": "1",
}

# Telegram — credenciales desde .env
API_ID   = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
CANAL    = os.getenv("TELEGRAM_CANAL", "")
TOPIC_ID = int(os.getenv("TELEGRAM_TOPIC_ID", "0"))

MPEG_TS_SYNC = b'\x47'
HLS_HEADER   = b'#EXTM3U'
MAC_PATTERN  = re.compile(r'/([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}/')

def normalizar_url_m3u(url: str) -> str:
    """Normaliza una URL M3U: quita &output=..., convierte type=m3u_plus a type=m3u."""
    url = re.sub(r'&output=[^\s&]+', '', url).rstrip('&')
    url = re.sub(r'type=m3u_plus', 'type=m3u', url, flags=re.IGNORECASE)
    url = re.sub(r'type=m3u8', 'type=m3u', url, flags=re.IGNORECASE)
    return url


# Token GitHub — leído desde .env
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Foro LinuxSat — credenciales desde .env
FORO_USER = os.getenv("FORO_LINUXSAT_USER", "")
FORO_PASS = os.getenv("FORO_LINUXSAT_PASS", "")
FORO_URL  = "https://www.linuxsat-support.com"
FORO_BOARD = "/board/590-iptv-streaming/"

# ─── Utilidades ───────────────────────────────────────────────────────────────

def limpiar_pantalla():
    os.system('cls' if os.name == 'nt' else 'clear')

def cargar_json(fichero):
    if not os.path.exists(fichero):
        return []
    with open(fichero, 'r', encoding='utf-8') as f:
        return json.load(f)

def guardar_json(fichero, data):
    with open(fichero, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def normalizar(texto):
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.upper())
        if unicodedata.category(c) != 'Mn'
    )

def tiene_espana(nombre, extinf=''):
    n = normalizar(nombre)
    e = normalizar(extinf)

    # Prefijos de país españoles en el nombre
    if n.startswith('ES:') or n.startswith('ES ') or n.startswith('ES|'):
        return True
    if n.startswith('(ES)') or n.startswith('[ES]'):
        return True
    if n.startswith('ESP:') or n.startswith('ESP '):
        return True
    if '|ES|' in n:
        return True
    if 'ESPANA' in n or 'SPAIN' in n:
        return True
    # Formato → ESPAÑA | canal ←
    if 'ESPANA' in n or '| ES ' in n or '|ES ' in n:
        return True

    # Buscar en el group-title del EXTINF: group-title="ESPAÑA"
    if 'ESPANA' in e or 'SPAIN' in e:
        return True
    # group-title con ES explícito
    gt_match = re.search(r'group-title="([^"]*)"', extinf, re.IGNORECASE)
    if gt_match:
        gt = normalizar(gt_match.group(1))
        if 'ESPANA' in gt or 'SPAIN' in gt or gt.startswith('ES') or 'ESPANOL' in gt:
            return True

    # Quitar calificadores de calidad al inicio: (FHD), (HD), (SD), (FHD REPUESTO), etc.
    n_limpio = re.sub(r'^\([^)]*\)\s*', '', n).strip()

    # Canales Movistar+ (M+ y M.)
    if n_limpio.startswith('M+') or n_limpio.startswith('M.') or n_limpio.startswith('M '):
        return True

    # DAZN (exclusivo de España en esta región)
    if n_limpio.startswith('DAZN'):
        return True

    # Canales españoles conocidos sin prefijo
    CANALES_ES = {
        'LA 1', 'LA 2', 'LA SEXTA', 'ANTENA 3', 'ANTENA3', 'CUATRO', 'TELECINCO',
        'TELEMADRID', 'CANAL SUR', 'TV3', 'TV3 CAT', 'CANAL 33', 'ESPORT 3',
        'ESPORT3', 'A PUNT', 'ARAGON TV', 'ETB 1', 'ETB 2', 'ETB1', 'ETB2',
        'TVG', 'TVG 2', 'IB3', 'CMM', 'TVE INTERNACIONAL', 'CLAN TVE', 'CLAN',
        '24 HORAS', '24H', '24HORAS', 'TELEDEPORTE',
        'ENERGY', 'NEOX', 'FDF', 'NOVA', 'MEGA', 'ATRESERIES', 'DIVINITY',
        'DKISS', 'DMAX', 'TEN', 'TRECE', 'BOING', 'DISNEY CHANNEL', 'DISNEY JUNIOR',
        'NICK JR', 'NICKELODEON', 'BABY TV', 'DREAMWORKS',
        'GOL', 'GOL PLAY', 'LALIGA TV', 'LALIGA TV HYPERMOTION',
        'EUROSPORT 1', 'EUROSPORT 2', 'REAL MADRID TV', 'BARCA TV',
        'ACB', 'TDTV',
        'TCM', 'AXN', 'AXN MOVIES', 'AMC', 'SYFY', 'WARNER TV', 'CALLE 13',
        'COSMO', 'ODISEA', 'HISTORIA', 'DISCOVERY', 'NATIONAL GEOGRAPHIC',
        'NAT GEO', 'BBC EARTH', 'HOLLYWOOD', 'PARAMOUNT CHANNEL',
        'CANAL COCINA', 'CANAL DECASA', 'DKISS', 'MTV', 'MEZZO', 'MEZZO LIVE',
        'STAR CHANNEL', 'DARK', 'SOMOS', 'FACTORIA DE FICCION', 'XTRM',
        'BE MAD', 'BEMAD', 'SUNDANCE', 'COMEDY CENTRAL',
        'CANAL SUR ANDALUCIA', 'CANAL EXTREMADURA', 'CASTILLA LA MANCHA',
        'ARAGON TV INT', 'TELEMADRID INT', 'TV CANARIA',
        'CAZA Y PESCA', 'CAZAVISION', 'IBERALIA TV', 'EL TORO TV',
        'BETIS TV', 'RALLY TV', 'GARAGE TV', 'TORO TV', 'ONETORO',
        'EURONEWS', 'CNN', 'MAX PPV', 'PLUS+', 'ENFAMILIA',
    }

    for canal in CANALES_ES:
        if n_limpio == canal or n_limpio.startswith(canal + ' ') or n_limpio.startswith(canal + '_'):
            return True

    return False

def parsear_m3u(texto, filtro_espana=True):
    lineas = texto.splitlines()
    canales = []
    for i, linea in enumerate(lineas):
        if not linea.startswith('#EXTINF'):
            continue
        partes = linea.split(',', 1)
        if len(partes) < 2:
            continue
        nombre = partes[1].strip()
        url = lineas[i+1].strip() if i+1 < len(lineas) else ''
        if not url or url.startswith('#'):
            continue
        if '/series/' in url.lower() or '/movie/' in url.lower():
            continue
        if MAC_PATTERN.search(url):
            continue
        if filtro_espana and not tiene_espana(nombre, linea):
            continue
        canales.append({'nombre': nombre, 'url': url, 'extinf': linea})
    return canales

def unicode_a_ascii(texto):
    rangos = [
        (0x1D400,0x1D419,'A'),(0x1D41A,0x1D433,'a'),
        (0x1D434,0x1D44D,'A'),(0x1D44E,0x1D467,'a'),
        (0x1D468,0x1D481,'A'),(0x1D482,0x1D49B,'a'),
        (0x1D5A0,0x1D5B9,'A'),(0x1D5BA,0x1D5D3,'a'),
        (0x1D5D4,0x1D5ED,'A'),(0x1D5EE,0x1D607,'a'),
        (0x1D608,0x1D621,'A'),(0x1D622,0x1D63B,'a'),
        (0x1D63C,0x1D655,'A'),(0x1D656,0x1D66F,'a'),
    ]
    resultado = []
    for char in texto:
        cp = ord(char)
        convertido = False
        for inicio, fin, base in rangos:
            if inicio <= cp <= fin:
                resultado.append(chr(ord('A' if base=='A' else 'a') + cp - inicio))
                convertido = True
                break
        if not convertido:
            if 0x1D7CE <= cp <= 0x1D7D7:
                resultado.append(chr(ord('0') + cp - 0x1D7CE))
                convertido = True
        if not convertido:
            resultado.append(char)
    return ''.join(resultado)

def parsear_bloque_telegram(texto_original):
    texto = unicode_a_ascii(texto_original)
    datos = {}
    portal = re.search(r'Portal\s*[:\-]\s*(https?://\S+)', texto, re.IGNORECASE)
    if portal:
        datos['portal'] = re.sub(r'\s+', '', portal.group(1))
    exp = re.search(r'Exp\s*[:\-]\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if exp:
        p = exp.group(1).split('/')
        datos['caducidad'] = f"{p[2]}-{p[1]}-{p[0]}"
    else:
        if re.search(r'Exp\s*[:\-]\s*(Unlimited|Ilimitado)', texto, re.IGNORECASE):
            datos['caducidad'] = 'Unlimited'
    maxconn = re.search(r'MaxConn\s*[:\-]\s*(\d+)', texto, re.IGNORECASE)
    if maxconn:
        datos['max_conn'] = int(maxconn.group(1))
    status = re.search(r'Status\s*[:\-]\s*(.+)', texto, re.IGNORECASE)
    if status:
        datos['observaciones'] = status.group(1).strip()
    m3u = re.search(r'M3U\s*[:\-]\s*(https?://\S+)', texto, re.IGNORECASE)
    if m3u:
        url_raw = re.sub(r'\s+', '', m3u.group(1))
        url_raw = re.sub(r'&output=[^\s&]+', '', url_raw).rstrip('&')
        url_raw = re.sub(r'type=m3u_plus', 'type=m3u', url_raw, flags=re.IGNORECASE)
        url_raw = re.sub(r'type=m3u8', 'type=m3u', url_raw, flags=re.IGNORECASE)
        datos['url_m3u'] = url_raw
    else:
        m3u2 = re.search(r'(https?://\S+type=m3u\S*)', texto_original, re.IGNORECASE)
        if m3u2:
            url_raw = re.sub(r'\s+', '', m3u2.group(1))
            url_raw = re.sub(r'&output=[^\s&]+', '', url_raw).rstrip('&')
            url_raw = re.sub(r'type=m3u_plus', 'type=m3u', url_raw, flags=re.IGNORECASE)
            url_raw = re.sub(r'type=m3u8', 'type=m3u', url_raw, flags=re.IGNORECASE)
            datos['url_m3u'] = url_raw
    return datos

# ─── Verificación de streams ──────────────────────────────────────────────────

def validar_mpegts(chunk: bytes) -> bool:
    """Verifica que el chunk tiene estructura MPEG-TS válida.
    Los paquetes MPEG-TS miden exactamente 188 bytes y empiezan por 0x47.
    Si hay al menos 3 paquetes consecutivos con sync byte en posición correcta,
    es un stream real."""
    if len(chunk) < 188 * 3:
        return False
    # Buscar el primer sync byte
    inicio = chunk.find(b'\x47')
    if inicio == -1:
        return False
    # Verificar que el patrón se repite cada 188 bytes (al menos 3 veces)
    validos = 0
    pos = inicio
    while pos + 188 <= len(chunk):
        if chunk[pos:pos+1] == b'\x47':
            validos += 1
        else:
            break
        pos += 188
    return validos >= 3

def validar_hls(chunk: bytes) -> bool:
    """Verifica que el chunk es una playlist HLS válida con segmentos reales."""
    try:
        texto = chunk.decode('utf-8', errors='ignore')
        return '#EXTM3U' in texto and ('#EXTINF' in texto or '#EXT-X-STREAM-INF' in texto)
    except Exception:
        return False


def detectar_tipo_lista(url):
    """Detecta el tipo de lista según la URL."""
    url_lower = url.lower()
    if url_lower.endswith('.ts') or '/live/' in url_lower and '.ts' in url_lower:
        return 'Stream .ts directo'
    elif 'get.php' in url_lower and 'type=m3u' in url_lower:
        return 'Cuenta Xtream (M3U)'
    elif 'get.php' in url_lower:
        return 'Cuenta Xtream'
    else:
        return 'Lista M3U'

async def verificar_stream(session, url, sem):
    async with sem:
        try:
            # Primero HEAD rápido
            async with session.head(
                url, headers=HEADERS_VLC,
                timeout=aiohttp.ClientTimeout(connect=10, total=10),
                allow_redirects=True
            ) as r:
                if r.status in (200, 206):
                    return True
        except Exception:
            pass
        # Si HEAD falla, intentar GET con lectura mínima
        try:
            async with session.get(
                url,
                headers=HEADERS_VLC,
                timeout=aiohttp.ClientTimeout(connect=10, total=TIMEOUT_STREAM)
            ) as r:
                if r.status not in (200, 206):
                    return False
                chunk = await asyncio.wait_for(r.content.read(BYTES_A_LEER), timeout=15)
                if not chunk or len(chunk) < 100:
                    return False
                # Validar estructura real del stream
                if chunk[0:1] == MPEG_TS_SYNC:
                    return validar_mpegts(chunk)
                if chunk[:7] == HLS_HEADER:
                    return validar_hls(chunk)
                if b'\x47' in chunk[:200]:
                    return validar_mpegts(chunk)
                # Si llega aquí con datos, aceptar como válido
                return True
        except Exception:
            return False

async def obtener_info_cuenta(session, url_m3u):
    """Consulta player_api.php para obtener caducidad, MaxConn y estado."""
    try:
        # Extraer base, username y password de la URL M3U
        m = re.match(r'(https?://[^/]+)/get\.php\?username=([^&]+)&password=([^&]+)', url_m3u, re.IGNORECASE)
        if not m:
            return {}
        base, username, password = m.group(1), m.group(2), m.group(3)
        api_url = f"{base}/player_api.php?username={username}&password={password}"
        async with session.get(
            api_url,
            headers=HEADERS_VLC,
            timeout=aiohttp.ClientTimeout(connect=4, total=8)
        ) as r:
            if r.status not in (200, 206):
                return {}
            data = await r.json(content_type=None)
            info = data.get('user_info', {})
            resultado = {}
            # Caducidad
            exp = info.get('exp_date')
            if exp:
                try:
                    if str(exp).isdigit():
                        from datetime import timezone
                        dt = datetime.fromtimestamp(int(exp), tz=timezone.utc)
                        resultado['caducidad'] = dt.strftime('%Y-%m-%d')
                    else:
                        resultado['caducidad'] = str(exp)
                except Exception:
                    pass
            elif info.get('is_trial') == '0' and not exp:
                resultado['caducidad'] = 'Unlimited'
            # MaxConn
            max_conn = info.get('max_connections')
            if max_conn:
                try:
                    resultado['max_conn'] = int(max_conn)
                except Exception:
                    pass
            # Estado
            status = info.get('status', '')
            if status:
                resultado['observaciones'] = status
            # Portal
            resultado['portal'] = base
            return resultado
    except Exception:
        return {}


    async with sem_listas:
        url = entrada['url']
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_LISTA)) as r:
                if r.status not in (200, 206):
                    return None
                texto = await r.text()
        except Exception:
            return None

        canales = parsear_m3u(texto, filtro_espana=True)
        if len(canales) < min_canales:
            return None

        # Muestra del 30% (min 8, max 25) — más representativa
        n = max(8, min(25, len(canales) * 3 // 10))
        muestra = random.sample(canales, min(n, len(canales)))

        tareas = [verificar_stream(session, c['url'], sem_streams) for c in muestra]
        resultados = await asyncio.gather(*tareas)
        exitosos = sum(1 for r in resultados if r)
        pct = round(exitosos / len(resultados) * 100) if resultados else 0

        if pct < min_pct:
            return None

        # Calcular ping
        t0 = time.time()
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                ping = round((time.time() - t0) * 1000)
        except Exception:
            ping = entrada.get('ping', 0)

        return {
            'url': url,
            'portal': entrada.get('portal', ''),
            'caducidad': entrada.get('caducidad', ''),
            'max_conn': entrada.get('max_conn', 1),
            'observaciones': entrada.get('observaciones', ''),
            'tipo_lista': detectar_tipo_lista(url),
            'ping': ping,
            'pct_streams': pct,
            'total_canales': len(canales),
            'fecha_verificacion': datetime.now().isoformat(timespec='seconds'),
        }

async def verificar_lista(session, entrada, sem_listas, sem_streams, min_canales, min_pct, filtro_espana=True, min_conn=1):
    async with sem_listas:
        url = entrada['url']
        try:
            async with session.get(url, headers=HEADERS_VLC, timeout=aiohttp.ClientTimeout(total=TIMEOUT_LISTA)) as r:
                if r.status not in (200, 206):
                    return None
                texto = await r.text()
        except Exception:
            return None

        canales = parsear_m3u(texto, filtro_espana=filtro_espana)
        if len(canales) < min_canales:
            return None

        # Muestra del 30% (min 8, max 25)
        n = max(8, min(25, len(canales) * 3 // 10))
        muestra = random.sample(canales, min(n, len(canales)))

        tareas = [verificar_stream(session, c['url'], sem_streams) for c in muestra]
        resultados = await asyncio.gather(*tareas)
        exitosos = sum(1 for r in resultados if r)
        pct = round(exitosos / len(resultados) * 100) if resultados else 0

        if pct < min_pct:
            return None

        # Filtro MaxConn — descarta si max_conn conocido es menor al mínimo
        max_conn = entrada.get('max_conn', 0)  # 0 = desconocido
        if min_conn > 1:
            # Si max_conn no está confirmado (0 o 1 por defecto), re-consultar API
            if max_conn <= 1:
                info = await obtener_info_cuenta(session, url)
                max_conn = info.get('max_conn', 0)
                entrada['max_conn'] = max_conn
            if max_conn == 0:
                return None  # Desconocido tras consulta — descartar
            if max_conn < min_conn:
                return None  # Menor del mínimo requerido

        t0 = time.time()
        try:
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                ping = round((time.time() - t0) * 1000)
        except Exception:
            ping = entrada.get('ping', 0)

        return {
            'url': url,
            'portal': entrada.get('portal', ''),
            'caducidad': entrada.get('caducidad', ''),
            'max_conn': max_conn,
            'observaciones': entrada.get('observaciones', ''),
            'tipo_lista': detectar_tipo_lista(url),
            'ping': ping,
            'pct_streams': pct,
            'total_canales': len(canales),
            'fecha_verificacion': datetime.now().isoformat(timespec='seconds'),
        }


async def escanear_y_verificar(urls_entrada, min_canales, min_pct, acumular=False, filtro_espana=True, min_conn=1):
    total = len(urls_entrada)
    verificadas = []
    descartadas = 0
    completadas = 0

    sem_listas  = asyncio.Semaphore(MAX_PAR_LISTAS)
    sem_streams = asyncio.Semaphore(MAX_PAR_STREAMS)
    connector   = aiohttp.TCPConnector(ssl=False)

    print(f"\n{'='*60}")
    print(f"  Verificando {total} listas...")
    print(f"  Mínimo canales {'españoles' if filtro_espana else 'totales'}: {min_canales}")
    print(f"  Mínimo % streams OK: {min_pct}%")
    if min_conn > 1:
        print(f"  Mínimo MaxConn: {min_conn}")
    print(f"  (Esto puede tardar varios minutos)")
    print(f"{'='*60}\n")

    async def procesar(session, entrada):
        nonlocal completadas, descartadas
        resultado = await verificar_lista(session, entrada, sem_listas, sem_streams, min_canales, min_pct, filtro_espana=filtro_espana, min_conn=min_conn)
        completadas += 1
        pct_progreso = round(completadas / total * 100)
        barra = '█' * (pct_progreso // 5) + '░' * (20 - pct_progreso // 5)
        if resultado:
            verificadas.append(resultado)
            print(f"\r  [{barra}] {pct_progreso}% | ✅ {len(verificadas)} OK | ❌ {descartadas} desc. | {completadas}/{total}", end='', flush=True)
        else:
            descartadas += 1
            print(f"\r  [{barra}] {pct_progreso}% | ✅ {len(verificadas)} OK | ❌ {descartadas} desc. | {completadas}/{total}", end='', flush=True)
        return resultado

    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [procesar(session, u) for u in urls_entrada]
        await asyncio.gather(*tareas)

    print(f"\n\n  Resultado: {len(verificadas)} listas válidas de {total}")

    # Si 0 pasaron verificación
    if len(verificadas) == 0 and total > 0:
        print(f"\n  ⚠️  Ninguna lista pasó el filtro de streams.")
        print(f"  Esto puede deberse a que el servidor bloquea tu IP de España.")
        print(f"  💡 Prueba a verificar el TXT desde el VPS con verificar_urls_vps.py")

    # Guardar
    if acumular:
        existentes = cargar_json(URLS_VERIFICADAS)
        urls_exist = {e['url'] for e in existentes}
        nuevas = [v for v in verificadas if v['url'] not in urls_exist]
        todo = existentes + nuevas
        print(f"  Acumuladas: {len(nuevas)} nuevas añadidas al JSON ({len(todo)} total)")
    else:
        todo = verificadas

    guardar_json(URLS_VERIFICADAS, todo)
    print(f"  Guardadas en: {URLS_VERIFICADAS}\n")
    return todo

# ─── Opciones del menú ────────────────────────────────────────────────────────

# Valores por defecto para modo automático (opción T - Todas las fuentes)
AUTO_MIN_CANALES  = 10
AUTO_MIN_STREAMS  = 75
AUTO_MIN_CONN     = 3
AUTO_ACUMULAR     = False

def pedir_opciones(filtro_espana=True, automatico=False):
    if automatico:
        print(f"\n  ⚡ Modo automático — usando valores por defecto:")
        print(f"     Mínimo canales: {AUTO_MIN_CANALES}")
        print(f"     Mínimo streams: {AUTO_MIN_STREAMS}%")
        print(f"     Mínimo MaxConn: {AUTO_MIN_CONN}")
        print(f"     Acumular JSON:  {'Sí' if AUTO_ACUMULAR else 'No'}")
        return AUTO_MIN_CANALES, AUTO_MIN_STREAMS, AUTO_MIN_CONN, AUTO_ACUMULAR

    print("\n  Opciones de verificación:")
    try:
        if filtro_espana:
            min_c = int(input(f"  Mínimo de canales españoles [{MIN_CANALES}]: ") or MIN_CANALES)
        else:
            min_c = int(input(f"  Mínimo de canales totales [{MIN_CANALES}]: ") or MIN_CANALES)
        min_p = int(input(f"  Mínimo % streams OK [{MIN_PCT_STREAMS}]: ") or MIN_PCT_STREAMS)
        min_conn = int(input(f"  Mínimo MaxConn (1=cualquiera) [1]: ") or 1)
        acumular = input("  ¿Acumular al JSON existente? (s/N): ").strip().lower() == 's'
    except (ValueError, KeyboardInterrupt):
        min_c, min_p, min_conn, acumular = MIN_CANALES, MIN_PCT_STREAMS, 1, False
    return min_c, min_p, min_conn, acumular

# ─── Canales de Telegram ──────────────────────────────────────────────────────

CANALES = [
    {"id": 1, "username": CANAL,              "nombre": "CrackAndroid",           "privado": True,  "topic_id": TOPIC_ID},
    {"id": 2, "username": "satglobaltv",      "nombre": "Aguila SAT HICHAM",      "privado": False, "topic_id": None},
    {"id": 3, "username": "tugaiptv2025",     "nombre": "TUGA GRATIS IPTV",       "privado": False, "topic_id": None},
    {"id": 4, "username": "iptv270",          "nombre": "Listas M3U Free",        "privado": False, "topic_id": None},
    {"id": 5, "username": "ListIptvWorld",    "nombre": "List IPTV World",        "privado": False, "topic_id": None},
    {"id": 6, "username": "Xtream_Iptv_Code", "nombre": "Xtream IPTV Codes",     "privado": False, "topic_id": None},
    {"id": 7, "username": "canalestvspain",   "nombre": "Canales TV Spain",       "privado": False, "topic_id": None},
    {"id": 8, "username": "tvpelisflixhd_plus","nombre": "TVPELISFLIXHD Plus",   "privado": False, "topic_id": None},
    {"id": 9, "username": "https://t.me/+qhqptj4NiDcwNjky", "nombre": "Canal Privado RATTENPAPST", "privado": True, "topic_id": None},
]

# ─── Opción 1: Escanear Telegram ──────────────────────────────────────────────

async def escanear_telegram(automatico=False):
    try:
        from telethon import TelegramClient
        from telethon.tl.functions.channels import JoinChannelRequest
    except ImportError:
        print("  Necesitas instalar telethon: pip install telethon")
        input("\n  Pulsa Enter para continuar...")
        return

    print("\n  Selecciona canal a escanear:")
    for c in CANALES:
        print(f"  [{c['id']}] {c['nombre']}")
    print(f"  [0] Todos los canales")
    print(f"  [X] Volver")
    sel = input("\n  Elige: ").strip()

    if sel.upper() == 'X':
        return

    if sel == '0':
        canales_sel = CANALES
    elif sel.isdigit() and 1 <= int(sel) <= len(CANALES):
        canales_sel = [CANALES[int(sel)-1]]
    else:
        print("  Opcion no valida")
        input("\n  Pulsa Enter para continuar...")
        return

    url_pattern = re.compile(
        r'https?://[^\s]*get\.php\?[^\s]*type=m3u[^\s]*',
        re.IGNORECASE
    )

    todas = []
    vistas = set()

    async with TelegramClient("iptv_session", API_ID, API_HASH) as client:
        print("  Conectado a Telegram")

        for canal in canales_sel:
            encontradas = 0
            leidos = 0
            print(f"\n  Leyendo {canal['nombre']}...")
            try:
                if canal['privado']:
                    entidad = canal['username']
                    try:
                        await client(JoinChannelRequest(entidad))
                    except Exception:
                        pass
                    async for msg in client.iter_messages(entidad, limit=5000):
                        if not msg.text:
                            continue
                        # Si tiene topic_id configurado, filtrar por topic
                        if canal['topic_id'] is not None:
                            if msg.reply_to is None:
                                continue
                            t_id = getattr(msg.reply_to, 'reply_to_top_id', None) or getattr(msg.reply_to, 'reply_to_msg_id', None)
                            if t_id != canal['topic_id']:
                                continue
                        # Sin topic_id → leer todos los mensajes que tengan URLs
                        if 'get.php' not in msg.text.lower():
                            continue
                        leidos += 1
                        for match in url_pattern.finditer(msg.text):
                            url = normalizar_url_m3u(match.group(0).rstrip('&'))
                            if url not in vistas:
                                vistas.add(url)
                                todas.append({'url_m3u': url, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': ''})
                                encontradas += 1
                else:
                    entidad = await client.get_entity(canal['username'])
                    async for msg in client.iter_messages(entidad, limit=2000):
                        if not msg.text:
                            continue
                        if 'get.php' not in msg.text.lower():
                            continue
                        leidos += 1
                        for match in url_pattern.finditer(msg.text):
                            url = re.sub(r'&output=[^\s&]+', '', match.group(0).rstrip('&'))
                            if url not in vistas:
                                vistas.add(url)
                                todas.append({'url_m3u': url, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': ''})
                                encontradas += 1
            except Exception as e:
                print(f"  Error en {canal['nombre']}: {e}")
                continue
            print(f"  {canal['nombre']}: {leidos} mensajes -> {encontradas} URLs nuevas")

    if not todas:
        print("\n  No se encontraron URLs.")
        input("\n  Pulsa Enter para continuar...")
        return

    print(f"\n  Total: {len(todas)} URLs unicas")

    # ── Comparar con TXTs anteriores — solo procesar URLs nuevas ─────────────
    scan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCAN_HISTORY_FOLDER)
    txts_anteriores = sorted([
        f for f in os.listdir(scan_dir)
        if f.startswith('global_') and f.endswith('.txt')
    ]) if os.path.exists(scan_dir) else []
    urls_conocidas = set()
    if txts_anteriores:
        for txt in txts_anteriores:
            try:
                with open(os.path.join(scan_dir, txt), 'r', encoding='utf-8') as f:
                    for linea in f:
                        u = linea.strip()
                        if u:
                            urls_conocidas.add(u)
            except Exception:
                pass
        # Añadir también las URLs ya verificadas (buenas o malas ya procesadas)
        verificadas_previas = cargar_json(URLS_VERIFICADAS)
        for v in verificadas_previas:
            urls_conocidas.add(v.get('url', ''))
        nuevas = [d for d in todas if d['url_m3u'] not in urls_conocidas]
        ya_conocidas = len(todas) - len(nuevas)
        print(f"  📂 TXTs anteriores encontrados: {len(txts_anteriores)}")
        print(f"  🔄 URLs ya conocidas (se saltan): {ya_conocidas}")
        print(f"  ✨ URLs nuevas a verificar: {len(nuevas)}")
        if not nuevas:
            print("\n  ℹ️  No hay URLs nuevas respecto a escaneos anteriores.")
            input("\n  Pulsa Enter para continuar...")
            return
        todas = nuevas
    else:
        print("  ℹ️  No hay TXTs anteriores — procesando todas las URLs")
    # ─────────────────────────────────────────────────────────────────────────

    # Ping básico
    print("  Comprobando disponibilidad...")
    sem = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(ssl=False)
    completadas_ping = 0
    ok_ping = 0
    total_ping = len(todas)

    async def ping_url(session, datos, sem):
        nonlocal completadas_ping, ok_ping
        async with sem:
            url = datos['url_m3u']
            t0 = time.time()
            resultado = None
            try:
                async with session.get(url, headers=HEADERS_VLC, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status in (200, 206) and ping <= MAX_PING:
                        chunk = await r.content.read(512)
                        if chunk and len(chunk) > 10:
                            info = await obtener_info_cuenta(session, url)
                            resultado = {
                                'url': url,
                                'ping': ping,
                                'portal': info.get('portal', ''),
                                'caducidad': info.get('caducidad', ''),
                                'max_conn': info.get('max_conn', 0),
                                'observaciones': info.get('observaciones', ''),
                            }
            except Exception:
                pass
            completadas_ping += 1
            if resultado:
                ok_ping += 1
            pct = round(completadas_ping / total_ping * 100)
            barra = 'X' * (pct // 5) + '.' * (20 - pct // 5)
            fallos = completadas_ping - ok_ping
            print(f"\r  [{barra}] {pct}% | OK: {ok_ping} | Desc: {fallos} | {completadas_ping}/{total_ping}", end='', flush=True)
            return resultado

    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [ping_url(session, d, sem) for d in todas]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r]
    print(f"\n  {len(disponibles)} URLs responden al ping")

    if not disponibles:
        print("  Ninguna URL disponible.")
        input("\n  Pulsa Enter para continuar...")
        return

    if len(canales_sel) > 1:
        nombre_canal = "global"
    else:
        nombre_canal = canales_sel[0]['nombre'].replace(' ', '_').replace('(', '').replace(')', '').replace('/', '_')

    scan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCAN_HISTORY_FOLDER)
    os.makedirs(scan_dir, exist_ok=True)
    nombre_txt = f"global_{nombre_canal}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    ruta_txt = os.path.join(scan_dir, nombre_txt)
    with open(ruta_txt, 'w', encoding='utf-8') as f:
        for d in disponibles:
            f.write(d['url'] + '\n')
    print(f"  TXT guardado: {ruta_txt}")

    # ── Log de escaneo ────────────────────────────────────────────────────────
    nombre_log = f"scan_log_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    ruta_log = os.path.join(scan_dir, nombre_log)
    with open(ruta_log, 'w', encoding='utf-8') as flog:
        flog.write(f"=== LOG DE ESCANEO TELEGRAM ===\n")
        flog.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        flog.write(f"Canales escaneados: {[c['nombre'] for c in canales_sel]}\n")
        flog.write(f"Total URLs únicas encontradas: {len(todas)}\n")
        flog.write(f"URLs que responden ping: {len(disponibles)}\n")
        flog.write(f"URLs descartadas (sin respuesta): {len(todas) - len(disponibles)}\n")
        flog.write(f"\n--- URLs que responden ping ---\n")
        for d in disponibles:
            flog.write(f"  OK | {d['url']}\n")
    print(f"  📋 Log guardado: {ruta_log}")
    # ─────────────────────────────────────────────────────────────────────────

    min_c, min_p, min_conn, acumular = pedir_opciones(filtro_espana=True, automatico=automatico)
    await escanear_y_verificar(disponibles, min_c, min_p, acumular, filtro_espana=True, min_conn=min_conn)

    if not automatico:
        input("\n  Pulsa Enter para continuar...")




# ─── Opción 2: Importar TXT ───────────────────────────────────────────────────

async def importar_txt():
    print("\n  📄 Importar archivo TXT")

    # Buscar TXT en el directorio actual
    txts = [f for f in sorted(os.listdir('.')) if f.endswith('.txt')]
    rutas_seleccionadas = []

    if txts:
        print("\n  Archivos TXT encontrados en esta carpeta:")
        for i, f in enumerate(txts):
            print(f"    [{i+1}] {f}")
        print(f"    [0] Escribir ruta manualmente")
        print(f"    [X] Volver")
        print("\n  💡 Puedes seleccionar varios: ej. 1,3,5 o 1-4")
        try:
            opcion = input("\n  Elige archivo(s): ").strip()
            if opcion.upper() == 'X':
                return
            if opcion == '0':
                ruta = input("  Ruta del archivo TXT: ").strip().strip('"')
                rutas_seleccionadas = [ruta]
            else:
                # Parsear selección múltiple: "1,3,5" o "1-4" o "2"
                indices = set()
                for parte in opcion.split(','):
                    parte = parte.strip()
                    if '-' in parte:
                        try:
                            inicio, fin = parte.split('-')
                            for n in range(int(inicio), int(fin)+1):
                                if 1 <= n <= len(txts):
                                    indices.add(n)
                        except ValueError:
                            pass
                    else:
                        try:
                            n = int(parte)
                            if 1 <= n <= len(txts):
                                indices.add(n)
                        except ValueError:
                            pass
                rutas_seleccionadas = [txts[i-1] for i in sorted(indices)]
                if not rutas_seleccionadas:
                    print("  ❌ Selección no válida")
                    input("\n  Pulsa Enter para continuar...")
                    return
        except KeyboardInterrupt:
            return
    else:
        ruta = input("  Ruta del archivo TXT: ").strip().strip('"')
        rutas_seleccionadas = [ruta]

    print(f"\n  📂 Procesando {len(rutas_seleccionadas)} archivo(s)...")

    # Procesar todos los archivos seleccionados acumulando URLs
    todas = []
    vistas = set()

    for ruta in rutas_seleccionadas:
        if not os.path.exists(ruta):
            print(f"  ❌ Archivo no encontrado: {ruta}")
            continue

        print(f"  📄 Leyendo: {ruta}")

        # Leer con detección automática de encoding
        raw = open(ruta, 'rb').read()
        # Detectar BOM
        if raw.startswith(b'\xff\xfe'):
            texto = raw.decode('utf-16-le', errors='ignore')
        elif raw.startswith(b'\xfe\xff'):
            texto = raw.decode('utf-16-be', errors='ignore')
        elif raw.startswith(b'\xef\xbb\xbf'):
            texto = raw.decode('utf-8-sig', errors='ignore')
        else:
            texto = raw.decode('utf-8', errors='ignore')

        lineas = texto.splitlines()

        # Detectar si es formato de bloques Telegram (tiene separadores 👤 o 〓〓〓)
        es_formato_bloques = bool(re.search(r'👤|〓{3,}', texto))

        if es_formato_bloques:
            bloques = re.split(r'(?=👤|〓{3,})', texto)
            for bloque in bloques:
                if 'get.php' not in bloque.lower() and 'type=m3u' not in bloque.lower():
                    continue
                datos = parsear_bloque_telegram(bloque)
                if not datos.get('url_m3u') or datos['url_m3u'] in vistas:
                    continue
                vistas.add(datos['url_m3u'])
                todas.append(datos)
        else:
            # Formato de URLs directas (una por línea)
            url_pattern = re.compile(
                r'https?://[^\s]*get\.php\?[^\s]*type=m3u[^\s]*',
                re.IGNORECASE
            )
            for linea in lineas:
                linea = linea.strip()
                match = url_pattern.search(linea)
                if not match:
                    continue
                url = match.group(0).rstrip('&')
                url_base = normalizar_url_m3u(url)
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
        urls_este_archivo = sum(1 for d in todas if True)
        print(f"  ✅ {ruta}: URLs acumuladas hasta ahora: {len(todas)}")

    if not todas:
        print("  ❌ No se encontraron URLs M3U en ningún archivo")
        input("\n  Pulsa Enter para continuar...")
        return

    print(f"  📋 {len(todas)} URLs únicas encontradas en total")

    # Comprobar ping básico
    print("  ⚡ Comprobando disponibilidad básica...")
    sem = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(ssl=False)
    disponibles = []
    completadas_ping = 0
    ok_ping = 0
    total_ping = len(todas)

    async def ping_url_txt(session, datos, sem):
        nonlocal completadas_ping, ok_ping
        async with sem:
            url = datos['url_m3u']
            t0 = time.time()
            resultado = None
            try:
                # GET en lugar de HEAD — detecta servidores que bloquean acceso real
                async with session.get(url, headers=HEADERS_VLC, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status in (200, 206) and ping <= MAX_PING:
                        # Leer solo los primeros bytes para confirmar que hay contenido
                        chunk = await r.content.read(512)
                        if chunk and len(chunk) > 10:
                            # Consultar info de cuenta (caducidad, MaxConn, estado)
                            info = await obtener_info_cuenta(session, url)
                            resultado = {
                                **datos,
                                'url': url,
                                'ping': ping,
                                'portal': info.get('portal', ''),
                                'caducidad': info.get('caducidad', ''),
                                'max_conn': info.get('max_conn', 1),
                                'observaciones': info.get('observaciones', ''),
                            }
            except Exception:
                pass
            completadas_ping += 1
            if resultado:
                ok_ping += 1
            pct = round(completadas_ping / total_ping * 100)
            barra = '█' * (pct // 5) + '░' * (20 - pct // 5)
            fallos = completadas_ping - ok_ping
            print(f"\r  [{barra}] {pct}% | ✅ {ok_ping} OK | ❌ {fallos} desc. | {completadas_ping}/{total_ping}", end='', flush=True)
            return resultado

    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [ping_url_txt(session, d, sem) for d in todas]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r]
    print(f"\n  ✅ {len(disponibles)} URLs responden (ping OK)")

    # Acumular al JSON de TXT
    existentes = cargar_json(URLS_TXT_FILE)
    urls_exist = {e['url'] for e in existentes}
    nuevas = [d for d in disponibles if d['url'] not in urls_exist]
    todo = existentes + nuevas
    guardar_json(URLS_TXT_FILE, todo)
    print(f"  💾 {len(nuevas)} nuevas URLs añadidas al JSON ({len(todo)} total en {URLS_TXT_FILE})")

    # Verificar streams
    min_c, min_p, min_conn, acumular = pedir_opciones()
    await escanear_y_verificar(disponibles, min_c, min_p, acumular, min_conn=min_conn)

    # Limpiar urls_txt.json — ya están procesadas, no repetir en el próximo import
    guardar_json(URLS_TXT_FILE, [])
    print(f"  🗑️  {URLS_TXT_FILE} limpiado (ya procesadas)")
    input("\n  Pulsa Enter para continuar...")

# ─── Opción R: Re-verificar historial ────────────────────────────────────────

async def reverificar_historial():
    print("\n  🔄 Re-verificar historial de escaneos")
    print("  ─────────────────────────────────────────────────────────────")

    # Buscar solo TXTs de URLs (global_*.txt y foro_ping_*.txt), excluir logs
    if not os.path.exists(SCAN_HISTORY_FOLDER):
        print(f"  ❌ No existe la carpeta {SCAN_HISTORY_FOLDER}")
        input("\n  Pulsa Enter para continuar...")
        return

    txts = sorted([
        os.path.join(SCAN_HISTORY_FOLDER, f)
        for f in os.listdir(SCAN_HISTORY_FOLDER)
        if f.endswith('.txt') and (f.startswith('global_') or f.startswith('foro_ping_'))
    ])

    if not txts:
        print(f"  ❌ No se encontraron TXTs de historial en {SCAN_HISTORY_FOLDER}")
        input("\n  Pulsa Enter para continuar...")
        return

    # Submenú de selección
    while True:
        print(f"\n  📂 TXTs de historial encontrados ({len(txts)}):")
        for i, f in enumerate(txts):
            nombre = os.path.basename(f)
            tam = os.path.getsize(f)
            print(f"    [{i+1:>2}] {nombre}  ({tam//1024} KB)")
        print()
        print("   [T] Re-verificar TODOS")
        print("   [S] Seleccionar archivos")
        print("   [X] Volver")
        print()

        try:
            opcion = input("  Elige: ").strip().upper()
        except KeyboardInterrupt:
            return

        if opcion == 'X':
            return

        rutas_seleccionadas = []

        if opcion == 'T':
            rutas_seleccionadas = txts
        elif opcion == 'S':
            print("\n  💡 Selección: ej. 1,3,5 o 1-4")
            try:
                sel = input("  Elige archivo(s): ").strip()
                if sel.upper() == 'X':
                    continue
                indices = set()
                for parte in sel.split(','):
                    parte = parte.strip()
                    if '-' in parte:
                        try:
                            inicio, fin = parte.split('-')
                            for n in range(int(inicio), int(fin)+1):
                                if 1 <= n <= len(txts):
                                    indices.add(n)
                        except ValueError:
                            pass
                    else:
                        try:
                            n = int(parte)
                            if 1 <= n <= len(txts):
                                indices.add(n)
                        except ValueError:
                            pass
                rutas_seleccionadas = [txts[i-1] for i in sorted(indices)]
                if not rutas_seleccionadas:
                    print("  ❌ Selección no válida")
                    continue
            except KeyboardInterrupt:
                return
        else:
            print("  ❌ Opción no válida")
            continue

        # Leer y acumular URLs de los archivos seleccionados
        print(f"\n  📂 Leyendo {len(rutas_seleccionadas)} archivo(s)...")
        todas = []
        vistas = set()

        url_pattern = re.compile(
            r'https?://[^\s]*get\.php\?[^\s]*type=m3u[^\s]*',
            re.IGNORECASE
        )

        for ruta in rutas_seleccionadas:
            try:
                raw = open(ruta, 'rb').read()
                if raw.startswith(b'\xff\xfe'):
                    texto = raw.decode('utf-16-le', errors='ignore')
                elif raw.startswith(b'\xfe\xff'):
                    texto = raw.decode('utf-16-be', errors='ignore')
                elif raw.startswith(b'\xef\xbb\xbf'):
                    texto = raw.decode('utf-8-sig', errors='ignore')
                else:
                    texto = raw.decode('utf-8', errors='ignore')

                for linea in texto.splitlines():
                    linea = linea.strip()
                    match = url_pattern.search(linea)
                    if not match:
                        continue
                    url = re.sub(r'&output=[^\s&]+', '', match.group(0).rstrip('&'))
                    if url not in vistas:
                        vistas.add(url)
                        todas.append({'url_m3u': url, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': ''})
                print(f"  ✅ {os.path.basename(ruta)}: {len(vistas)} URLs acumuladas")
            except Exception as e:
                print(f"  ⚠️  Error leyendo {ruta}: {e}")

        if not todas:
            print("  ❌ No se encontraron URLs en los archivos seleccionados")
            input("\n  Pulsa Enter para continuar...")
            continue

        print(f"\n  📋 {len(todas)} URLs únicas extraídas del historial")
        print("  ⚡ Comprobando disponibilidad y consultando APIs...")

        # Ping + consulta API (igual que importar_txt)
        sem = asyncio.Semaphore(20)
        connector = aiohttp.TCPConnector(ssl=False)
        disponibles = []
        completadas_ping = 0
        ok_ping = 0
        total_ping = len(todas)

        async def ping_historial(session, datos, sem):
            nonlocal completadas_ping, ok_ping
            async with sem:
                url = datos['url_m3u']
                t0 = time.time()
                resultado = None
                try:
                    async with session.get(url, headers=HEADERS_VLC, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as r:
                        ping = round((time.time() - t0) * 1000)
                        if r.status in (200, 206) and ping <= MAX_PING:
                            chunk = await r.content.read(512)
                            if chunk and len(chunk) > 10:
                                info = await obtener_info_cuenta(session, url)
                                resultado = {
                                    'url': url,
                                    'portal': info.get('portal', ''),
                                    'caducidad': info.get('caducidad', datos.get('caducidad', '')),
                                    'max_conn': info.get('max_conn', datos.get('max_conn', 1)),
                                    'observaciones': info.get('observaciones', ''),
                                    'ping': ping,
                                    'fecha_verificacion': datetime.now().isoformat(timespec='seconds'),
                                    'pct_streams': 0,
                                    'total_canales': 0,
                                }
                except Exception:
                    pass
                completadas_ping += 1
                if resultado:
                    ok_ping += 1
                pct = round(completadas_ping / total_ping * 100)
                barra = '█' * (pct // 5) + '░' * (20 - pct // 5)
                fallos = completadas_ping - ok_ping
                print(f"\r  [{barra}] {pct}% | ✅ {ok_ping} OK | ❌ {fallos} desc. | {completadas_ping}/{total_ping}", end='', flush=True)
                return resultado

        async with aiohttp.ClientSession(connector=connector) as session:
            tareas = [ping_historial(session, d, sem) for d in todas]
            resultados = await asyncio.gather(*tareas)

        disponibles = [r for r in resultados if r]
        print(f"\n  ✅ {len(disponibles)} URLs responden al ping")

        if not disponibles:
            print("  ⚠️  Ninguna URL respondió. Puede que tu IP esté bloqueada.")
            print("  💡 Prueba desde el VPS para mejores resultados.")
            input("\n  Pulsa Enter para continuar...")
            continue

        # Verificar streams
        min_c, min_p, min_conn, acumular = pedir_opciones(filtro_espana=True)
        await escanear_y_verificar(disponibles, min_c, min_p, acumular, filtro_espana=True, min_conn=min_conn)

        input("\n  Pulsa Enter para continuar...")
        return


# ─── Opción 3: Ver resumen de URLs verificadas ────────────────────────────────

def ver_verificadas():
    datos = cargar_json(URLS_VERIFICADAS)
    if not datos:
        print("\n  ❌ No hay URLs verificadas. Ejecuta el scanner primero.")
        input("\n  Pulsa Enter para continuar...")
        return

    print(f"\n  📊 URLs verificadas: {len(datos)}")
    print(f"  {'─'*70}")
    print(f"  {'Servidor':<35} {'Canales':>8} {'Stream%':>8} {'Caduca':<14} {'MaxConn':>7}")
    print(f"  {'─'*70}")

    # Ordenar por caducidad
    def sort_key(x):
        c = x.get('caducidad', '')
        if not c or c == 'Unlimited':
            return 'zzzz'
        return c

    for d in sorted(datos, key=sort_key):
        url = d['url'].replace('http://', '').replace('https://', '')
        servidor = url[:33] + '..' if len(url) > 35 else url
        caducidad = d.get('caducidad', '?')
        if caducidad == 'Unlimited':
            caducidad = '♾ Unlimited'
        print(f"  {servidor:<35} {d.get('total_canales',0):>8} {d.get('pct_streams',0):>7}% {caducidad:<14} {d.get('max_conn',1):>7}")

    print(f"  {'─'*70}")
    input("\n  Pulsa Enter para continuar...")

# ─── Opción 4: Limpiar JSON verificadas ───────────────────────────────────────

def limpiar_verificadas():
    datos = cargar_json(URLS_VERIFICADAS)
    if not datos:
        print("\n  ❌ El JSON está vacío.")
        input("\n  Pulsa Enter para continuar...")
        return

    confirma = input(f"\n  ¿Eliminar todas las {len(datos)} URLs verificadas? (s/N): ")
    if confirma.lower() == 's':
        guardar_json(URLS_VERIFICADAS, [])
        print("  ✅ JSON limpiado.")
    input("\n  Pulsa Enter para continuar...")

# ─── Opción 5: Re-verificar JSON existente ────────────────────────────────────

# ─── Opción 5: Buscar en GitHub ──────────────────────────────────────────────

async def buscar_github(automatico=False):
    print("\n  🐙 Buscar URLs M3U en GitHub")
    print("  Busca repositorios y archivos con URLs type=m3u_plus, type=m3u y streams .ts directos.")
    print()

    # Token — usa el guardado en GITHUB_TOKEN o pide uno
    if GITHUB_TOKEN:
        token = GITHUB_TOKEN
        print(f"  🔑 Usando token guardado")
    else:
        token = input("  Token GitHub (Enter para saltar, límite 60 req/h sin token): ").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Captura URLs get.php (cuentas Xtream) y streams .ts directos
    url_pattern = re.compile(
        r'https?://[^\s\'"<>]*(?:get\.php\?[^\s\'"<>]*type=m3u[^\s\'"<>]*|/[^\s\'"<>]+/[^\s\'"<>]+/[^\s\'"<>]+\.ts)',
        re.IGNORECASE
    )

    todas = []
    vistas = set()

    async def extraer_urls_de_texto(texto):
        encontradas = []
        for match in url_pattern.finditer(texto):
            url = match.group(0).rstrip('&,;\'\"')
            url_base = normalizar_url_m3u(url)
            if url_base not in vistas:
                vistas.add(url_base)
                encontradas.append(url_base)
        return encontradas

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:

        # ── Búsqueda 1: Repositorios actualizados ────────────────────────────
        print("  🔍 Buscando repositorios con type=m3u_plus...")
        paginas = 3
        for pagina in range(1, paginas + 1):
            try:
                params = {
                    'q': 'iptv get.php username password type=m3u',
                    'sort': 'updated',
                    'order': 'desc',
                    'per_page': 30,
                    'page': pagina,
                }
                async with session.get(
                    'https://api.github.com/search/repositories',
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status == 403:
                        data_err = await r.json()
                        print(f"\n  ⚠️  Rate limit o acceso denegado: {data_err.get('message','403')}")
                        break
                    if r.status != 200:
                        data_err = await r.text()
                        print(f"\n  ⚠️  Error HTTP {r.status}: {data_err[:100]}")
                        break
                    data = await r.json()
                    repos = data.get('items', [])
                    if not repos:
                        break
                    print(f"  📦 Página {pagina}: {len(repos)} repositorios")

                    for repo in repos:
                        # Buscar el README de cada repo
                        try:
                            readme_url = f"https://api.github.com/repos/{repo['full_name']}/readme"
                            async with session.get(readme_url, timeout=aiohttp.ClientTimeout(total=10)) as rr:
                                if rr.status == 200:
                                    rdata = await rr.json()
                                    import base64
                                    contenido = base64.b64decode(rdata.get('content', '')).decode('utf-8', errors='ignore')
                                    urls = await extraer_urls_de_texto(contenido)
                                    if urls:
                                        print(f"    ✅ {repo['full_name']}: {len(urls)} URLs")
                                        for u in urls:
                                            todas.append({'url_m3u': u, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': ''})
                        except Exception:
                            pass
                    await asyncio.sleep(1)  # Respetar rate limit
            except Exception as e:
                print(f"\n  ❌ Error en búsqueda de repos: {e}")
                break

        # ── Búsqueda 2: Código con URLs directas ─────────────────────────────
        print("\n  🔍 Buscando código con URLs M3U directas...")
        queries = [
            'get.php username password type=m3u_plus',
            'get.php username password type=m3u',
            'iptv get.php type=m3u_plus username',
            'xtream codes get.php type=m3u',
        ]
        for query in queries:
            try:
                params = {'q': query, 'per_page': 30, 'page': 1}
                async with session.get(
                    'https://api.github.com/search/code',
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15)
                ) as r:
                    if r.status == 403:
                        print("  ⚠️  Límite de API. Espera o usa token.")
                        break
                    if r.status != 200:
                        continue
                    data = await r.json()
                    items = data.get('items', [])
                    print(f"  📄 '{query[:40]}...': {len(items)} archivos")

                    for item in items[:10]:  # Máximo 10 archivos por query
                        try:
                            raw_url = item.get('html_url', '').replace(
                                'github.com', 'raw.githubusercontent.com'
                            ).replace('/blob/', '/')
                            async with session.get(raw_url, timeout=aiohttp.ClientTimeout(total=10)) as rr:
                                if rr.status == 200:
                                    contenido = await rr.text(errors='ignore')
                                    urls = await extraer_urls_de_texto(contenido)
                                    if urls:
                                        print(f"    ✅ {item['repository']['full_name']}/{item['name']}: {len(urls)} URLs")
                                        for u in urls:
                                            todas.append({'url_m3u': u, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': ''})
                        except Exception:
                            pass
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"  ❌ Error: {e}")

    if not todas:
        print("\n  ❌ No se encontraron URLs M3U en GitHub.")
        input("\n  Pulsa Enter para continuar...")
        return

    # Deduplicar
    unicas = list({d['url_m3u']: d for d in todas}.values())
    print(f"\n  📋 {len(unicas)} URLs únicas encontradas en GitHub")

    # Filtrar URLs ya verificadas anteriormente
    verificadas_previas = {v.get('url', '') for v in cargar_json(URLS_VERIFICADAS)}
    unicas_filtradas = [d for d in unicas if d.get('url_m3u', '') not in verificadas_previas]
    ya_conocidas_gh = len(unicas) - len(unicas_filtradas)
    if ya_conocidas_gh > 0:
        print(f"  🔄 URLs ya conocidas (se saltan): {ya_conocidas_gh}")
        print(f"  ✨ URLs nuevas a verificar: {len(unicas_filtradas)}")
    unicas = unicas_filtradas
    if not unicas:
        print("  ℹ️  No hay URLs nuevas de GitHub respecto a escaneos anteriores.")
        return

    # Ping básico
    print("  ⚡ Comprobando disponibilidad básica...")
    sem = asyncio.Semaphore(20)
    connector2 = aiohttp.TCPConnector(ssl=False)
    completadas_ping = 0
    ok_ping = 0
    total_ping = len(unicas)

    async def ping_github(session, datos, sem):
        nonlocal completadas_ping, ok_ping
        async with sem:
            url = datos['url_m3u']
            t0 = time.time()
            resultado = None
            try:
                async with session.get(url, headers=HEADERS_VLC, timeout=aiohttp.ClientTimeout(total=8), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status in (200, 206) and ping <= MAX_PING:
                        chunk = await r.content.read(512)
                        if chunk and len(chunk) > 10:
                            info = await obtener_info_cuenta(session, url)
                            resultado = {
                                **datos,
                                'url': url,
                                'ping': ping,
                                'portal': info.get('portal', ''),
                                'caducidad': info.get('caducidad', ''),
                                'max_conn': info.get('max_conn', 1),
                                'observaciones': info.get('observaciones', ''),
                            }
            except Exception:
                pass
            completadas_ping += 1
            if resultado:
                ok_ping += 1
            pct = round(completadas_ping / total_ping * 100)
            barra = '█' * (pct // 5) + '░' * (20 - pct // 5)
            fallos = completadas_ping - ok_ping
            print(f"\r  [{barra}] {pct}% | ✅ {ok_ping} OK | ❌ {fallos} desc. | {completadas_ping}/{total_ping}", end='', flush=True)
            return resultado

    async with aiohttp.ClientSession(connector=connector2) as session:
        tareas = [ping_github(session, d, sem) for d in unicas]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r]
    print(f"\n  ✅ {len(disponibles)} URLs responden (ping OK)")

    if not disponibles:
        print("  ❌ Ninguna URL respondió al ping.")
        input("\n  Pulsa Enter para continuar...")
        return

    # Opciones para las URLs encontradas en GitHub
    if automatico:
        print(f"\n  ⚡ Modo automático — verificando las {len(disponibles)} URLs de GitHub...")
        min_c, min_p, min_conn, acumular = pedir_opciones(filtro_espana=False, automatico=True)
        disponibles_norm = [{**d, 'url': d.get('url', d.get('url_m3u', ''))} for d in disponibles]
        await escanear_y_verificar(disponibles_norm, min_c, min_p, acumular, filtro_espana=False, min_conn=min_conn)
        return

    print(f"\n  ¿Qué quieres hacer con las {len(disponibles)} URLs?")
    print("  [1] Verificar streams y guardar en urls_verificadas.json")
    print("  [0] Volver al menú principal")
    accion = input("  Elige: ").strip()

    if accion == '0':
        return

    if accion == '1':
        # Verificar streams — sin filtro España para GitHub (listas internacionales)
        min_c, min_p, min_conn, acumular = pedir_opciones(filtro_espana=False)
        disponibles_norm = [{**d, 'url': d.get('url', d.get('url_m3u', ''))} for d in disponibles]
        await escanear_y_verificar(disponibles_norm, min_c, min_p, acumular, filtro_espana=False, min_conn=min_conn)

    input("\n  Pulsa Enter para continuar...")




def extraer_canales_espana_m3u(contenido_bytes, nombre_origen):
    """Extrae canales españoles de un M3U y guarda el archivo filtrado."""
    FILTROS_ES = ['┃ES┃', 'ES|', '|ES ', 'ESPAÑA', 'ESPANA', 'SPAIN',
                  'M+', 'MOVISTAR', 'DAZN', 'LALIGA', 'LIGA', 'RFEF',
                  'VAMOS', 'TELECINCO', 'ANTENA 3', 'LA 1', 'LA 2',
                  'CUATRO', 'LA SEXTA', 'EUROSPORT']
    try:
        texto = contenido_bytes.decode('utf-8-sig', errors='ignore')
        lineas = texto.splitlines()
        canales_es = []
        i = 0
        while i < len(lineas):
            linea = lineas[i].strip()
            if linea.startswith('#EXTINF'):
                nombre = linea.split(',', 1)[-1].strip() if ',' in linea else ''
                url = lineas[i+1].strip() if i+1 < len(lineas) else ''
                n = nombre.upper()
                if any(x in n for x in FILTROS_ES):
                    if url and not url.startswith('#') and 'play/live' in url:
                        canales_es.append((linea, url))
            i += 1
        if canales_es:
            scan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCAN_HISTORY_FOLDER)
            os.makedirs(scan_dir, exist_ok=True)
            fecha = datetime.now().strftime('%Y%m%d_%H%M%S')
            nombre_limpio = re.sub(r'[^a-zA-Z0-9_]', '_', nombre_origen)[:30]
            ruta_m3u = os.path.join(scan_dir, f"stalker_{nombre_limpio}_{fecha}.m3u")
            with open(ruta_m3u, 'w', encoding='utf-8') as f:
                f.write('#EXTM3U\n')
                for extinf, url in canales_es:
                    f.write(extinf + '\n' + url + '\n')
            print(f"\n  💾 M3U Stalker guardado: {os.path.basename(ruta_m3u)} ({len(canales_es)} canales ES)")
        return len(canales_es)
    except Exception:
        return 0

# ─── Opción 6: Escanear foro LinuxSat ────────────────────────────────────────

async def escanear_foro(automatico=False):
    import requests as req
    from bs4 import BeautifulSoup
    import zipfile as zf
    import io

    if not FORO_USER or not FORO_PASS:
        print("  ❌ Credenciales del foro no configuradas en .env")
        print("  Añade FORO_LINUXSAT_USER y FORO_LINUXSAT_PASS al .env")
        input("\n  Pulsa Enter para continuar...")
        return

    print("\n  🌐 Escaneando foro LinuxSat-Support...")
    print(f"  👤 Usuario: {FORO_USER}")

    url_pattern = re.compile(
        r"https?://[^\s'\"<>]*get\.php\?[^\s'\"<>]*type=m3u[^\s'\"<>]*",
        re.IGNORECASE
    )

    session = req.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    # ── Login ─────────────────────────────────────────────────────────────────
    print("  🔐 Iniciando sesión...")
    try:
        # Paso 1: obtener página de login y token CSRF dinámico
        r = session.get(f"{FORO_URL}/cms/login/", timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        # WoltLab genera el token CSRF en el JS de la página, buscar en el HTML
        token = ""
        # Buscar en scripts inline: SECURITY_TOKEN = "..." o securityToken: "..."
        import re as _re
        for patron in [
            r'"securityToken"\s*:\s*"([a-f0-9\-+/=]{20,})"',
            r'SECURITY_TOKEN\s*=\s*"([a-f0-9\-+/=]{20,})"',
            r'"security_token"\s*:\s*"([a-f0-9\-+/=]{20,})"',
            r'name="t"\s+value="([a-f0-9\-+/=]{20,})"',
            r'value="([a-f0-9]{40,}-[A-Za-z0-9+/=]{10,})"',
        ]:
            m = _re.search(patron, r.text)
            if m:
                token = m.group(1)
                print(f"  🔑 Token CSRF encontrado ({len(token)} chars)")
                break

        if not token:
            # Intentar obtener token via ajax-proxy (WoltLab lo expone aquí)
            try:
                r_ajax = session.get(
                    f"{FORO_URL}/index.php?ajax-proxy/",
                    timeout=10
                )
                m = _re.search(r'"securityToken"\s*:\s*"([^"]+)"', r_ajax.text)
                if m:
                    token = m.group(1)
                    print(f"  🔑 Token CSRF via ajax ({len(token)} chars)")
            except Exception:
                pass

        # Campos exactos del formulario POST de WoltLab Suite (capturados con DevTools)
        login_data = {
            "username": FORO_USER,
            "password": FORO_PASS,
            "url":      f"{FORO_URL}/",
        }
        if token:
            login_data["t"] = token

        r = session.post(
            f"{FORO_URL}/cms/login/",
            data=login_data,
            timeout=15,
            allow_redirects=True
        )

        # Verificar login — comprobar en la página principal
        r_check = session.get(f"{FORO_URL}/", timeout=15)
        logueado = (
            FORO_USER.lower() in r_check.text.lower() or
            "logout" in r_check.text.lower() or
            "log-out" in r_check.text.lower()
        )

        if not logueado:
            print("  ❌ Login fallido — verifica usuario y contraseña en .env")
            input("\n  Pulsa Enter para continuar...")
            return
        print("  ✅ Login correcto")
    except Exception as e:
        print(f"  ❌ Error al conectar con el foro: {e}")
        input("\n  Pulsa Enter para continuar...")
        return

    # ── Listar hilos del board IPTV ───────────────────────────────────────────
    todas = []
    vistas = set()
    pagina = 1
    max_paginas = 10  # Máximo 10 páginas para no saturar

    print(f"  📋 Leyendo hilos de la sección IPTV...")

    while pagina <= max_paginas:
        try:
            url_board = f"{FORO_URL}{FORO_BOARD}?pageNo={pagina}"
            r = session.get(url_board, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # Buscar links a hilos
            links_hilos = []
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/thread/" in href and href not in links_hilos:
                    if not href.startswith("http"):
                        href = FORO_URL + href
                    links_hilos.append(href)

            if not links_hilos:
                break

            total_hilos_pag = len(links_hilos[:30])
            print(f"  📄 Página {pagina}: {len(links_hilos)} hilos | URLs encontradas hasta ahora: {len(todas)}")

            for idx_hilo, url_hilo in enumerate(links_hilos[:30], 1):  # Máx 30 hilos por página
                print(f"\r  ⏳ Pág {pagina}/{max_paginas} — Hilo {idx_hilo}/{total_hilos_pag} — {len(todas)} URLs encontradas", end='', flush=True)
                try:
                    r_hilo = session.get(url_hilo, timeout=15)
                    soup_hilo = BeautifulSoup(r_hilo.text, "html.parser")

                    # Extraer URLs del texto
                    texto_hilo = r_hilo.text
                    for match in url_pattern.finditer(texto_hilo):
                        url = match.group(0).rstrip('&,;\'"')
                        url_base = normalizar_url_m3u(url)
                        if url_base not in vistas:
                            vistas.add(url_base)
                            todas.append({'url_m3u': url_base, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': 'LinuxSat'})

                    # Buscar adjuntos
                    for a in soup_hilo.find_all("a", href=True):
                        href = a["href"]
                        if not href.startswith("http"):
                            href = FORO_URL + href
                        # Adjuntos típicos de WoltLab
                        if any(x in href for x in ["/attachment/", "?download=", "filebase"]):
                            ext = href.split("?")[0].lower()
                            if any(ext.endswith(e) for e in [".txt", ".m3u", ".m3u8", ".zip"]) or "/attachment/" in href:
                                try:
                                    r_adj = session.get(href, timeout=15)
                                    contenido = r_adj.content
                                    # Si es zip, descomprimir
                                    if href.endswith(".zip") or r_adj.headers.get("content-type","").startswith("application/zip"):
                                        try:
                                            with zf.ZipFile(io.BytesIO(contenido)) as z:
                                                for nombre_zip in z.namelist():
                                                    texto_zip = z.read(nombre_zip).decode("utf-8", errors="ignore")
                                                    for match in url_pattern.finditer(texto_zip):
                                                        url = match.group(0).rstrip('&,;\'"')
                                                        url_base = normalizar_url_m3u(url)
                                                        if url_base not in vistas:
                                                            vistas.add(url_base)
                                                            todas.append({'url_m3u': url_base, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': 'LinuxSat-adjunto'})
                                        except Exception:
                                            pass
                                    else:
                                        texto_adj = contenido.decode("utf-8", errors="ignore")
                                        # Si es M3U con streams Stalker (play/live.php) — filtrar canales ES
                                        if '#extm3u' in texto_adj.lower() and 'play/live' in texto_adj.lower():
                                            nombre_adj = a.get_text(strip=True) or 'foro_stalker'
                                            n_es = extraer_canales_espana_m3u(contenido, nombre_adj)
                                            if n_es > 0:
                                                print(f"\n  🇪🇸 M3U Stalker: {n_es} canales ES guardados", flush=True)
                                        else:
                                            for match in url_pattern.finditer(texto_adj):
                                                url = match.group(0).rstrip('&,;\'"')
                                                url_base = normalizar_url_m3u(url)
                                                if url_base not in vistas:
                                                    vistas.add(url_base)
                                                    todas.append({'url_m3u': url_base, 'portal': '', 'caducidad': '', 'max_conn': 1, 'observaciones': 'LinuxSat-adjunto'})
                                except Exception:
                                    pass
                except Exception:
                    continue

            pagina += 1
            await asyncio.sleep(1)  # Respetar el servidor

        except Exception as e:
            print(f"  ❌ Error en página {pagina}: {e}")
            break

    if not todas:
        print("\n  ❌ No se encontraron URLs M3U en el foro.")
        input("\n  Pulsa Enter para continuar...")
        return

    # Deduplicar
    unicas = list({d['url_m3u']: d for d in todas}.values())
    print(f"\n  📋 {len(unicas)} URLs únicas encontradas en LinuxSat")

    # Filtrar URLs ya verificadas anteriormente
    verificadas_previas = {v.get('url', '') for v in cargar_json(URLS_VERIFICADAS)}
    unicas_filtradas = [d for d in unicas if d.get('url_m3u', '') not in verificadas_previas]
    ya_conocidas_foro = len(unicas) - len(unicas_filtradas)
    if ya_conocidas_foro > 0:
        print(f"  🔄 URLs ya conocidas (se saltan): {ya_conocidas_foro}")
        print(f"  ✨ URLs nuevas a verificar: {len(unicas_filtradas)}")
    unicas = unicas_filtradas
    if not unicas:
        print("  ℹ️  No hay URLs nuevas del foro respecto a escaneos anteriores.")
        return

    # Ping básico
    print("  ⚡ Comprobando disponibilidad básica...")
    sem = asyncio.Semaphore(20)
    connector = aiohttp.TCPConnector(ssl=False)
    completadas_ping = 0
    ok_ping = 0
    total_ping = len(unicas)

    async def ping_foro(session_aio, datos, sem):
        nonlocal completadas_ping, ok_ping
        async with sem:
            url = datos['url_m3u']
            t0 = time.time()
            resultado = None
            try:
                async with session_aio.head(url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as r:
                    ping = round((time.time() - t0) * 1000)
                    if r.status in (200, 206) and ping <= MAX_PING:
                        info = await obtener_info_cuenta(session_aio, url)
                        resultado = {
                            **datos,
                            'url': url,
                            'ping': ping,
                            'portal': info.get('portal', ''),
                            'caducidad': info.get('caducidad', ''),
                            'max_conn': info.get('max_conn', 1),
                            'observaciones': info.get('observaciones', 'LinuxSat'),
                        }
            except Exception:
                pass
            completadas_ping += 1
            if resultado:
                ok_ping += 1
            pct = round(completadas_ping / total_ping * 100)
            barra = '█' * (pct // 5) + '░' * (20 - pct // 5)
            fallos = completadas_ping - ok_ping
            print(f"\r  [{barra}] {pct}% | ✅ {ok_ping} OK | ❌ {fallos} desc. | {completadas_ping}/{total_ping}", end='', flush=True)
            return resultado

    async with aiohttp.ClientSession(connector=connector) as session_aio:
        tareas = [ping_foro(session_aio, d, sem) for d in unicas]
        resultados = await asyncio.gather(*tareas)

    disponibles = [r for r in resultados if r]
    print(f"\n  ✅ {len(disponibles)} URLs responden (ping OK)")

    if not disponibles:
        print("  ❌ Ninguna URL respondió al ping.")
        input("\n  Pulsa Enter para continuar...")
        return

    # Guardar TXT con URLs que pasan el ping antes de verificar
    scan_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), SCAN_HISTORY_FOLDER)
    os.makedirs(scan_dir, exist_ok=True)
    nombre_ping_txt = f"foro_ping_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    ruta_ping_txt = os.path.join(scan_dir, nombre_ping_txt)
    with open(ruta_ping_txt, 'w', encoding='utf-8') as f:
        for d in disponibles:
            f.write(d['url'] + '\n')
    print(f"  💾 TXT con {len(disponibles)} URLs guardado: {ruta_ping_txt}")

    # Verificar streams
    min_c, min_p, min_conn, acumular = pedir_opciones(filtro_espana=True, automatico=automatico)
    await escanear_y_verificar(disponibles, min_c, min_p, acumular, filtro_espana=True, min_conn=min_conn)
    if not automatico:
        input("\n  Pulsa Enter para continuar...")

# ─── Menú principal ───────────────────────────────────────────────────────────

def mostrar_menu():
    verif  = cargar_json(URLS_VERIFICADAS)
    listas = cargar_json(LISTAS_FILE)

    print("\n" + "="*60)
    print("   IPTV Panel - Menu principal")
    print("="*60)
    print(f"   URLs verificadas: {len(verif)}")
    print(f"   Listas guardadas: {len(listas)}")
    print("="*60)
    print()
    print("   [1] Escanear Telegram")
    print("   [2] Importar archivo TXT")
    print("   [3] Ver resumen de URLs verificadas")
    print("   [4] Limpiar URLs verificadas")
    print("   [5] Buscar en GitHub")
    print("   [6] Escanear foro LinuxSat")
    print("   [T] Todas las fuentes (Telegram + GitHub + Foro)")
    print("   [R] Re-verificar historial de escaneos")
    print()
    print("   [0] Salir")
    print()

async def main():
    while True:
        limpiar_pantalla()
        mostrar_menu()
        try:
            opcion = input("   Elige una opcion: ").strip()
        except KeyboardInterrupt:
            print("\n\n  Hasta luego!")
            break

        if opcion == '1':
            await escanear_telegram()
        elif opcion == '2':
            await importar_txt()
        elif opcion == '3':
            ver_verificadas()
        elif opcion == '4':
            limpiar_verificadas()
        elif opcion == '5':
            await buscar_github()
        elif opcion == '6':
            await escanear_foro()
        elif opcion.upper() == 'T':
            print("\n  🔄 Escaneando todas las fuentes en modo automático...")
            print(f"  ⚡ Valores: canales≥{AUTO_MIN_CANALES} | streams≥{AUTO_MIN_STREAMS}% | MaxConn≥{AUTO_MIN_CONN}")
            print("  🧹 Limpiando URLs verificadas anteriores...")
            guardar_json(URLS_VERIFICADAS, [])
            await escanear_telegram(automatico=True)
            await buscar_github(automatico=True)
            await escanear_foro(automatico=True)
            print("\n  ✅ Escaneo completo de todas las fuentes finalizado.")
        elif opcion.upper() == 'R':
            await reverificar_historial()
        elif opcion == '0':
            print("\n  Hasta luego!")
            break
        else:
            print("\n  Opcion no valida")
            time.sleep(1)

if __name__ == "__main__":
    import ctypes
    try:
        # ─── Desactivar QuickEdit mode de Windows ─────────────────────────────
        # QuickEdit pausa el script cuando se hace clic en la ventana CMD.
        # Lo desactivamos para que el script no se congele al cambiar de ventana.
        kernel32 = ctypes.windll.kernel32
        # Obtener handle de la consola
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        # Leer modo actual
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        # ENABLE_QUICK_EDIT_MODE = 0x0040, ENABLE_EXTENDED_FLAGS = 0x0080
        # Quitar QuickEdit (bit 0x0040), mantener el resto
        nuevo_modo = (mode.value & ~0x0040) | 0x0080
        kernel32.SetConsoleMode(handle, nuevo_modo)

        # ─── Evitar que Windows suspenda el proceso durante escaneos largos ───
        ES_CONTINUOUS       = 0x80000000
        ES_SYSTEM_REQUIRED  = 0x00000001
        ES_DISPLAY_REQUIRED = 0x00000002
        kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )
    except Exception:
        pass  # No es Windows o no tiene permisos
    asyncio.run(main())
