import { useState, useRef } from 'react';
import { Loader2, Search, Upload, Wifi, Zap, Calendar, Tv2, Trash2, Download } from 'lucide-react';
import type { CheckResult } from '../App';

interface Props {
  onCheckResult: (r: CheckResult) => void;
}

interface M3UInfo {
  nombre: string;
  url: string;
  servidor: string;
  usuario: string;
  password: string;
  max_conn: number;
  activas: number;
  caducidad: string;
  status: string;
  total_canales: number;
  ping: number;
  api_disponible: boolean;
}

interface Canal {
  nombre: string;
  url: string;
  extinf: string;
}

export function AnalyzerForm({ onCheckResult }: Props) {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // M3U file analyzer (bloque 2)
  const [m3uInfo, setM3uInfo] = useState<M3UInfo | null>(null);
  const [loadingM3u, setLoadingM3u] = useState(false);
  const [errorM3u, setErrorM3u] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Editor M3U (bloque 3)
  const [editorCanales, setEditorCanales] = useState<Canal[]>([]);
  const [editorNombre, setEditorNombre] = useState('');
  const [editorInfo, setEditorInfo] = useState<M3UInfo | null>(null);
  const [editorLoadingInfo, setEditorLoadingInfo] = useState(false);
  const [editorBuscar, setEditorBuscar] = useState('');
  const [editorSeleccionados, setEditorSeleccionados] = useState<Set<number>>(new Set());
  const [editorEliminandoIdx, setEditorEliminandoIdx] = useState<number | null>(null);
  const [editorEliminandoSel, setEditorEliminandoSel] = useState(false);
  const [editorFiltrando, setEditorFiltrando] = useState(false);
  const [editorMensaje, setEditorMensaje] = useState('');
  const editorFileRef = useRef<HTMLInputElement | null>(null);

  // ─── Bloque 1: Comprobar URL ──────────────────────────────────────────────

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const form = new FormData();
      form.append('url', url.trim());
      const res = await fetch('http://localhost:8000/check', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error desconocido');
      onCheckResult(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  // ─── Bloque 2: Analizar archivo M3U ──────────────────────────────────────

  const handleM3uFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoadingM3u(true);
    setErrorM3u('');
    setM3uInfo(null);
    try {
      const texto = await file.text();
      const urlMatch2 = texto.match(/https?:\/\/([^\s\/]+)\/get\.php\?username=([^&\s]+)&password=([^&\s]+)/);
      const urlMatch = texto.match(/https?:\/\/([^\s\/]+)\/live\/([^\/\s]+)\/([^\/\s]+)\//);
      let servidor = '', usuario = '', password = '', apiUrl = '';
      if (urlMatch2) {
        servidor = urlMatch2[1]; usuario = urlMatch2[2]; password = urlMatch2[3];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else if (urlMatch) {
        servidor = urlMatch[1]; usuario = urlMatch[2]; password = urlMatch[3];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else {
        throw new Error('No se encontraron credenciales en el archivo M3U');
      }
      const totalCanales = (texto.match(/#EXTINF/g) || []).length;
      const res = await fetch(`http://localhost:8000/check-m3u-file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_url: apiUrl, servidor, usuario, password, total_canales: totalCanales, nombre: file.name }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error al consultar el servidor');
      setM3uInfo(data);
    } catch (err: any) {
      setErrorM3u(err.message);
    } finally {
      setLoadingM3u(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // ─── Bloque 3: Editor M3U ─────────────────────────────────────────────────

  const parsearM3U = (texto: string): Canal[] => {
    const lineas = texto.split('\n');
    const canales: Canal[] = [];
    for (let i = 0; i < lineas.length; i++) {
      const linea = lineas[i].trim();
      if (!linea.startsWith('#EXTINF')) continue;
      const partes = linea.split(',');
      if (partes.length < 2) continue;
      const nombre = partes.slice(1).join(',').trim();
      const urlStream = lineas[i + 1]?.trim() ?? '';
      if (!urlStream || urlStream.startsWith('#')) continue;
      canales.push({ nombre, url: urlStream, extinf: linea });
    }
    return canales;
  };

  const consultarInfoServidor = async (texto: string, nombreArchivo: string): Promise<M3UInfo | null> => {
    try {
      const urlMatch2 = texto.match(/https?:\/\/([^\s\/]+)\/get\.php\?username=([^&\s]+)&password=([^&\s]+)/);
      const urlMatch = texto.match(/https?:\/\/([^\s\/]+)\/live\/([^\/\s]+)\/([^\/\s]+)\//);
      let servidor = '', usuario = '', password = '', apiUrl = '';
      if (urlMatch2) {
        servidor = urlMatch2[1]; usuario = urlMatch2[2]; password = urlMatch2[3];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else if (urlMatch) {
        servidor = urlMatch[1]; usuario = urlMatch[2]; password = urlMatch[3];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else {
        return null;
      }
      const totalCanales = (texto.match(/#EXTINF/g) || []).length;
      const res = await fetch(`http://localhost:8000/check-m3u-file`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_url: apiUrl, servidor, usuario, password, total_canales: totalCanales, nombre: nombreArchivo }),
      });
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  };

  const handleEditorFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setEditorMensaje('');
    setEditorBuscar('');
    setEditorSeleccionados(new Set());
    setEditorInfo(null);
    try {
      const texto = await file.text();
      const canales = parsearM3U(texto);
      if (canales.length === 0) {
        setEditorMensaje('⚠️ No se encontraron canales en el archivo');
        return;
      }
      setEditorCanales(canales);
      setEditorNombre(file.name.replace(/\.m3u8?$/i, ''));
      setEditorMensaje(`✅ ${canales.length} canales cargados`);

      // Consultar info del servidor en segundo plano
      setEditorLoadingInfo(true);
      consultarInfoServidor(texto, file.name).then(info => {
        setEditorInfo(info);
        setEditorLoadingInfo(false);
      });
    } catch {
      setEditorMensaje('⚠️ Error al leer el archivo');
    } finally {
      if (editorFileRef.current) editorFileRef.current.value = '';
    }
  };

  const canalesFiltrados = editorCanales.filter(c =>
    !editorBuscar || c.nombre.toLowerCase().includes(editorBuscar.toLowerCase())
  );

  const toggleSelEditor = (idx: number) => {
    setEditorSeleccionados(prev => {
      const nuevo = new Set(prev);
      if (nuevo.has(idx)) nuevo.delete(idx); else nuevo.add(idx);
      return nuevo;
    });
  };

  const toggleTodosEditor = () => {
    if (editorSeleccionados.size === canalesFiltrados.length) {
      setEditorSeleccionados(new Set());
    } else {
      setEditorSeleccionados(new Set(canalesFiltrados.map((_, i) => i)));
    }
  };

  const handleBorrarUno = (idxVisible: number) => {
    setEditorEliminandoIdx(idxVisible);
    const canalABorrar = canalesFiltrados[idxVisible];
    const nuevos = editorCanales.filter(c => !(c.url === canalABorrar.url && c.nombre === canalABorrar.nombre));
    setEditorCanales(nuevos);
    setEditorSeleccionados(new Set());
    setEditorMensaje(`✅ Canal eliminado. Quedan ${nuevos.length} canales.`);
    setTimeout(() => setEditorEliminandoIdx(null), 300);
  };

  const handleBorrarSeleccionados = () => {
    if (editorSeleccionados.size === 0) return;
    if (!confirm(`¿Eliminar ${editorSeleccionados.size} canales seleccionados?`)) return;
    setEditorEliminandoSel(true);
    const urlsBorrar = new Set(Array.from(editorSeleccionados).map(i => canalesFiltrados[i]?.url).filter(Boolean));
    const nuevos = editorCanales.filter(c => !urlsBorrar.has(c.url));
    setEditorCanales(nuevos);
    setEditorSeleccionados(new Set());
    setEditorMensaje(`✅ Eliminados ${editorSeleccionados.size} canales. Quedan ${nuevos.length}.`);
    setEditorEliminandoSel(false);
  };

  const handleMantenerES = () => {
    const noEs = editorCanales.filter(c => {
      const n = c.nombre.toUpperCase();
      return !n.startsWith('ES:') && !n.startsWith('ES ') && !n.includes('ESPAÑA') && !n.includes('ESPANA') && !n.includes('(ES)');
    });
    if (noEs.length === 0) { setEditorMensaje('✅ Todos los canales ya son españoles'); return; }
    if (!confirm(`¿Eliminar ${noEs.length} canales no españoles? Quedarán ${editorCanales.length - noEs.length}.`)) return;
    setEditorFiltrando(true);
    const nuevos = editorCanales.filter(c => {
      const n = c.nombre.toUpperCase();
      return n.startsWith('ES:') || n.startsWith('ES ') || n.includes('ESPAÑA') || n.includes('ESPANA') || n.includes('(ES)');
    });
    setEditorCanales(nuevos);
    setEditorSeleccionados(new Set());
    setEditorMensaje(`✅ Eliminados ${noEs.length} canales no españoles. Quedan ${nuevos.length}.`);
    setEditorFiltrando(false);
  };

  const handleDescargar = () => {
    if (editorCanales.length === 0) return;
    let contenido = '#EXTM3U\n';
    for (const c of editorCanales) {
      contenido += c.extinf + '\n' + c.url + '\n';
    }
    const blob = new Blob([contenido], { type: 'application/octet-stream' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${editorNombre}_editado.m3u`;
    a.click();
  };

  // ─── Componente reutilizable: badges de info del servidor ─────────────────

  const InfoBadges = ({ info, totalActual }: { info: M3UInfo; totalActual?: number }) => (
    <div className="flex flex-wrap gap-2">
      <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
        <Tv2 className="size-3" /> {totalActual ?? info.total_canales} canales
      </span>
      {info.api_disponible ? (
        <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${info.activas > 0 ? 'bg-orange-500/20 text-orange-300' : 'bg-green-500/20 text-green-300'}`}>
          <Wifi className="size-3" /> {info.activas}/{info.max_conn} conexiones
        </span>
      ) : (
        <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-yellow-500/20 text-yellow-300">
          <Wifi className="size-3" /> API no disponible
        </span>
      )}
      {info.ping > 0 && (
        <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${info.ping < 300 ? 'bg-green-500/10 text-green-300' : info.ping < 700 ? 'bg-yellow-500/10 text-yellow-300' : 'bg-red-500/10 text-red-300'}`}>
          <Zap className="size-3" /> {info.ping}ms
        </span>
      )}
      {info.caducidad && (
        <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${info.caducidad === 'Unlimited' ? 'bg-green-500/10 text-green-300' : new Date(info.caducidad) < new Date(Date.now() + 30 * 24 * 60 * 60 * 1000) ? 'bg-red-500/10 text-red-300' : 'bg-white/10 text-slate-300'}`}>
          <Calendar className="size-3" />
          {info.caducidad === 'Unlimited' ? '♾ Unlimited' : `Caduca: ${info.caducidad}`}
        </span>
      )}
      {info.status && (
        <span className={`text-xs px-2.5 py-1 rounded-full ${info.status.toLowerCase() === 'active' ? 'bg-green-500/10 text-green-300' : 'bg-white/10 text-slate-300'}`}>
          {info.status}
        </span>
      )}
      {info.api_disponible && info.max_conn > 0 && (
        <span className="text-xs px-2.5 py-1 rounded-full bg-blue-500/10 text-blue-300">
          Xtream API ✓
        </span>
      )}
    </div>
  );

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* Bloque 1: Comprobar URL */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
        <h2 className="text-white font-semibold mb-4">Comprobar lista M3U</h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="flex gap-3">
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://ejemplo.com/lista.m3u"
              disabled={loading}
              className="flex-1 bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-400 transition-all disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loading || !url.trim()}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium px-6 py-3 rounded-xl transition-all"
            >
              {loading ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
              {loading ? 'Comprobando...' : 'Comprobar'}
            </button>
          </div>
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-300 text-sm">
              ⚠️ {error}
            </div>
          )}
        </form>
      </div>

      {/* Bloque 2: Analizar archivo M3U */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
        <h2 className="text-white font-semibold mb-2">Analizar archivo M3U guardado</h2>
        <p className="text-slate-500 text-sm mb-4">Sube un archivo .m3u para ver MaxConn, conexiones activas y caducidad sin guardarlo.</p>
        <div className="flex gap-3 items-center">
          <input ref={fileInputRef} type="file" accept=".m3u,.m3u8" className="hidden" onChange={handleM3uFile} />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={loadingM3u}
            className="flex items-center gap-2 bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white font-medium px-6 py-3 rounded-xl transition-all"
          >
            {loadingM3u ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
            {loadingM3u ? 'Consultando...' : 'Subir archivo M3U'}
          </button>
        </div>
        {errorM3u && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-300 text-sm mt-3">
            ⚠️ {errorM3u}
          </div>
        )}
        {m3uInfo && (
          <div className="mt-4 bg-white/5 border border-white/10 rounded-xl p-4 space-y-3">
            <p className="text-white font-medium truncate">{m3uInfo.nombre}</p>
            <p className="text-slate-400 text-xs font-mono truncate">{m3uInfo.url}</p>
            <InfoBadges info={m3uInfo} />
          </div>
        )}
      </div>

      {/* Bloque 3: Editor de canales M3U */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
        <h2 className="text-white font-semibold mb-2">Editar canales de archivo M3U</h2>
        <p className="text-slate-500 text-sm mb-4">
          Carga un archivo .m3u, borra los canales que no quieras y descarga el resultado limpio.
        </p>

        <div className="flex gap-3 items-center flex-wrap">
          <input ref={editorFileRef} type="file" accept=".m3u,.m3u8" className="hidden" onChange={handleEditorFile} />
          <button
            onClick={() => editorFileRef.current?.click()}
            className="flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-medium px-6 py-3 rounded-xl transition-all"
          >
            <Upload className="size-4" />
            {editorCanales.length > 0 ? 'Cargar otro archivo' : 'Cargar archivo M3U'}
          </button>

          {editorCanales.length > 0 && (
            <button
              onClick={handleDescargar}
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-medium px-6 py-3 rounded-xl transition-all"
            >
              <Download className="size-4" />
              Descargar editado ({editorCanales.length} canales)
            </button>
          )}
        </div>

        {editorMensaje && (
          <div className={`mt-3 rounded-xl px-4 py-3 text-sm ${editorMensaje.startsWith('✅') ? 'bg-green-500/10 border border-green-500/20 text-green-300' : 'bg-red-500/10 border border-red-500/20 text-red-300'}`}>
            {editorMensaje}
          </div>
        )}

        {/* Cabecera info servidor */}
        {editorCanales.length > 0 && (
          <div className="mt-4 bg-black/20 border border-white/10 rounded-xl p-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-white font-medium text-sm truncate">{editorNombre}</p>
              {editorLoadingInfo && (
                <span className="flex items-center gap-1.5 text-slate-500 text-xs shrink-0 ml-2">
                  <Loader2 className="size-3 animate-spin" /> Consultando servidor...
                </span>
              )}
            </div>
            {editorInfo ? (
              <InfoBadges info={editorInfo} totalActual={editorCanales.length} />
            ) : !editorLoadingInfo ? (
              <div className="flex flex-wrap gap-2">
                <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                  <Tv2 className="size-3" /> {editorCanales.length} canales
                </span>
                <span className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-yellow-500/20 text-yellow-300">
                  <Wifi className="size-3" /> API no disponible
                </span>
              </div>
            ) : null}
          </div>
        )}

        {/* Tabla de canales */}
        {editorCanales.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <span className="text-slate-400 text-sm">{canalesFiltrados.length} canales</span>
              <input
                type="text"
                value={editorBuscar}
                onChange={(e) => { setEditorBuscar(e.target.value); setEditorSeleccionados(new Set()); }}
                placeholder="Buscar canal..."
                className="flex-1 min-w-40 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-blue-400"
              />
              <div className="flex gap-2 ml-auto flex-wrap">
                {editorSeleccionados.size > 0 && (
                  <button
                    onClick={handleBorrarSeleccionados}
                    disabled={editorEliminandoSel}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all"
                  >
                    {editorEliminandoSel ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                    Eliminar {editorSeleccionados.size} seleccionados
                  </button>
                )}
                <button
                  onClick={handleMantenerES}
                  disabled={editorFiltrando}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all"
                >
                  {editorFiltrando ? <Loader2 className="size-3.5 animate-spin" /> : '🇪🇸'}
                  Mantener solo ES:
                </button>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 overflow-hidden">
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-[#0d1117] border-b border-white/10">
                    <tr>
                      <th className="w-8 px-3 py-2.5">
                        <input
                          type="checkbox"
                          checked={canalesFiltrados.length > 0 && editorSeleccionados.size === canalesFiltrados.length}
                          onChange={toggleTodosEditor}
                          className="cursor-pointer accent-blue-500"
                        />
                      </th>
                      <th className="text-left px-4 py-2.5 text-slate-500 font-medium w-10">#</th>
                      <th className="text-left px-4 py-2.5 text-slate-500 font-medium">Canal</th>
                      <th className="text-left px-4 py-2.5 text-slate-500 font-medium hidden sm:table-cell">URL</th>
                      <th className="w-8"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {canalesFiltrados.map((canal, i) => (
                      <tr
                        key={i}
                        onClick={() => toggleSelEditor(i)}
                        className={`border-b border-white/5 cursor-pointer transition-colors ${editorSeleccionados.has(i) ? 'bg-blue-500/10' : 'hover:bg-white/5'}`}
                      >
                        <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={editorSeleccionados.has(i)}
                            onChange={() => toggleSelEditor(i)}
                            className="cursor-pointer accent-blue-500"
                          />
                        </td>
                        <td className="px-4 py-2 text-slate-600 text-xs">{i + 1}</td>
                        <td className="px-4 py-2 text-white text-sm">{canal.nombre}</td>
                        <td className="px-4 py-2 text-slate-600 text-xs truncate max-w-xs hidden sm:table-cell">{canal.url}</td>
                        <td className="px-2 py-2" onClick={e => e.stopPropagation()}>
                          <button
                            onClick={() => handleBorrarUno(i)}
                            disabled={editorEliminandoIdx === i}
                            className="p-1 text-slate-600 hover:text-red-400 hover:bg-red-400/10 rounded transition-all"
                          >
                            {editorEliminandoIdx === i ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
