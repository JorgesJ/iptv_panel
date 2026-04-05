import { useEffect, useState, useRef } from 'react';
import {
  Trash2, Download, RefreshCw, Loader2, Tv2, Calendar,
  Wifi, Zap, ArrowUpDown, FileText, Eye, GripVertical, Save
} from 'lucide-react';
import type { SavedList } from '../App';

type SortField = 'fecha' | 'total_canales' | 'caducidad' | 'max_conn' | 'ping';

interface Canal {
  nombre: string;
  url: string;
  extinf: string;
}

const SORT_BTNS: { field: SortField; label: string }[] = [
  { field: 'fecha', label: 'Recientes' },
  { field: 'caducidad', label: 'Caducidad' },
  { field: 'max_conn', label: 'MaxConn' },
  { field: 'ping', label: 'Velocidad' },
  { field: 'total_canales', label: 'Canales' },
  { field: 'fecha', label: 'Fecha' },
];

export function SavedLists() {
  const [listas, setListas] = useState<SavedList[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [eliminandoTodas, setEliminandoTodas] = useState(false);
  const [ordenandoTodasMovistar, setOrdenandoTodasMovistar] = useState(false);
  const [mensajeGlobal, setMensajeGlobal] = useState('');
  const [sortField, setSortField] = useState<SortField>('fecha');
  const [sortAsc, setSortAsc] = useState(false);

  // Ver/editar canales
  const [viendoCanales, setViendoCanales] = useState<string | null>(null);
  const [canales, setCanales] = useState<Canal[]>([]);
  const [loadingCanales, setLoadingCanales] = useState(false);
  const [buscarCanal, setBuscarCanal] = useState('');
  const [modoEdicion, setModoEdicion] = useState(false);
  const [guardandoOrden, setGuardandoOrden] = useState(false);
  const [ordenandoMovistar, setOrdenandoMovistar] = useState(false);
  const [canalesEditados, setCanalesEditados] = useState<Canal[]>([]);
  const dragIdx = useRef<number | null>(null);

  const fetchListas = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch('http://localhost:8000/listas');
      if (!res.ok) throw new Error();
      setListas(await res.json());
    } catch {
      setError('No se pudo conectar con el servidor');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchListas(); }, []);

  const handleDescargarTodas = async () => {
    try {
      const res = await fetch('http://localhost:8000/listas/descargar-todas');
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'listas_iptv.zip';
      a.click();
    } catch {
      setError('Error al descargar todas las listas');
    }
  };

  const handleOrdenarTodasMovistar = async () => {
    if (!confirm(`¿Aplicar orden Movistar+ a TODAS las listas (${listas.length})? Se sobreescribirán todos los archivos.`)) return;
    setOrdenandoTodasMovistar(true);
    setMensajeGlobal('');
    try {
      const res = await fetch('http://localhost:8000/listas/ordenar-movistar-todas', { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error('Error al ordenar');
      setMensajeGlobal(`✅ ${data.exitos} listas ordenadas con Movistar+${data.errores.length > 0 ? ` (${data.errores.length} errores)` : ''}`);
      await fetchListas();
    } catch {
      setMensajeGlobal('⚠️ Error al ordenar las listas');
    } finally {
      setOrdenandoTodasMovistar(false);
    }
  };

  const handleEliminarTodas = async () => {
    if (!confirm(`¿Eliminar TODAS las listas guardadas (${listas.length})? Esta acción no se puede deshacer.`)) return;
    setEliminandoTodas(true);
    try {
      await fetch('http://localhost:8000/listas', { method: 'DELETE' });
      setListas([]);
      setViendoCanales(null);
    } catch {
      setError('Error al eliminar todas las listas');
    } finally {
      setEliminandoTodas(false);
    }
  };

  const handleDelete = async (nombre: string) => {
    if (!confirm(`¿Eliminar "${nombre}"?`)) return;
    setDeleting(nombre);
    try {
      await fetch(`http://localhost:8000/listas/${encodeURIComponent(nombre)}`, { method: 'DELETE' });
      setListas((prev) => prev.filter((l) => l.nombre !== nombre));
      if (viendoCanales === nombre) setViendoCanales(null);
    } catch {
      setError('Error al eliminar');
    } finally {
      setDeleting(null);
    }
  };

  const handleDownload = async (nombre: string) => {
    setDownloading(nombre);
    try {
      const res = await fetch(`http://localhost:8000/download/${encodeURIComponent(nombre)}`);
      if (!res.ok) throw new Error();
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${nombre}.m3u`;
      a.click();
    } catch {
      setError('Error al descargar');
    } finally {
      setDownloading(nombre);
      setDownloading(null);
    }
  };

  const handleVerCanales = async (nombre: string) => {
    if (viendoCanales === nombre) { setViendoCanales(null); return; }
    setLoadingCanales(true);
    setViendoCanales(nombre);
    setBuscarCanal('');
    setModoEdicion(false);
    try {
      const res = await fetch(`http://localhost:8000/listas/${encodeURIComponent(nombre)}/canales`);
      const data = await res.json();
      setCanales(data.canales || []);
      setCanalesEditados(data.canales || []);
    } catch {
      setError('Error al cargar canales');
      setCanales([]);
      setCanalesEditados([]);
    } finally {
      setLoadingCanales(false);
    }
  };

  const handleGuardarOrden = async (nombre: string) => {
    setGuardandoOrden(true);
    try {
      const res = await fetch(`http://localhost:8000/listas/${encodeURIComponent(nombre)}/reordenar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ canales: canalesEditados }),
      });
      if (!res.ok) throw new Error();
      setCanales(canalesEditados);
      setModoEdicion(false);
      setListas(prev => prev.map(l => l.nombre === nombre ? { ...l, total_canales: canalesEditados.length } : l));
    } catch {
      setError('Error al guardar el orden');
    } finally {
      setGuardandoOrden(false);
    }
  };

  const handleOrdenarMovistar = async (nombre: string) => {
    setOrdenandoMovistar(true);
    try {
      const res = await fetch(`http://localhost:8000/listas/${encodeURIComponent(nombre)}/ordenar-movistar`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error();
      setCanales(data.canales);
      setCanalesEditados(data.canales);
      setListas(prev => prev.map(l => l.nombre === nombre ? { ...l, total_canales: data.total } : l));
    } catch {
      setError('Error al ordenar');
    } finally {
      setOrdenandoMovistar(false);
    }
  };

  const [eliminandoCanal, setEliminandoCanal] = useState<number | null>(null);
  const [seleccionados, setSeleccionados] = useState<Set<number>>(new Set());
  const [eliminandoSeleccion, setEliminandoSeleccion] = useState(false);
  const [filtrando, setFiltrando] = useState(false);

  const handleEliminarCanal = async (nombre: string, idxVisible: number) => {
    // Calcular el índice real en canales[] a partir del índice visible en canalesMostrados[]
    const canalAEliminar = canalesMostrados[idxVisible];
    const idxReal = canales.findIndex(c => c.url === canalAEliminar.url && c.nombre === canalAEliminar.nombre);
    if (idxReal === -1) return;
    setEliminandoCanal(idxVisible);
    try {
      const res = await fetch(
        `http://localhost:8000/listas/${encodeURIComponent(nombre)}/canales/${idxReal}`,
        { method: 'DELETE' }
      );
      const data = await res.json();
      if (!res.ok) throw new Error();
      const nuevos = canales.filter((_, i) => i !== idxReal);
      setCanales(nuevos);
      setCanalesEditados(nuevos);
      setSeleccionados(new Set());
      setListas(prev => prev.map(l => l.nombre === nombre ? { ...l, total_canales: data.total } : l));
    } catch {
      setError('Error al eliminar canal');
    } finally {
      setEliminandoCanal(null);
    }
  };

  const handleEliminarSeleccionados = async (nombre: string) => {
    if (seleccionados.size === 0) return;
    if (!confirm(`¿Eliminar ${seleccionados.size} canales seleccionados?`)) return;
    setEliminandoSeleccion(true);
    try {
      // Obtener los canales a eliminar por sus URLs (identificador único)
      const urlsAEliminar = new Set(
        Array.from(seleccionados).map(idx => canalesMostrados[idx]?.url).filter(Boolean)
      );
      const nuevos = canales.filter(c => !urlsAEliminar.has(c.url));
      // Guardar la lista completa reordenada (reutilizamos el endpoint de reordenar)
      const res = await fetch(
        `http://localhost:8000/listas/${encodeURIComponent(nombre)}/reordenar`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ canales: nuevos }) }
      );
      if (!res.ok) throw new Error();
      setCanales(nuevos);
      setCanalesEditados(nuevos);
      setSeleccionados(new Set());
      setListas(prev => prev.map(l => l.nombre === nombre ? { ...l, total_canales: nuevos.length } : l));
    } catch {
      setError('Error al eliminar canales seleccionados');
    } finally {
      setEliminandoSeleccion(false);
    }
  };

  const handleMantenerEspana = async (nombre: string) => {
    const noEspana = canales.filter(c => {
      const n = c.nombre.toUpperCase();
      return !n.startsWith('ES:') && !n.startsWith('ES ') && !n.includes('ESPAÑA') && !n.includes('ESPANA');
    });
    if (noEspana.length === 0) {
      setMensajeGlobal('✅ Todos los canales ya son españoles');
      return;
    }
    if (!confirm(`¿Eliminar ${noEspana.length} canales no españoles? Quedarán ${canales.length - noEspana.length} canales.`)) return;
    setFiltrando(true);
    try {
      const nuevos = canales.filter(c => {
        const n = c.nombre.toUpperCase();
        return n.startsWith('ES:') || n.startsWith('ES ') || n.includes('ESPAÑA') || n.includes('ESPANA');
      });
      const res = await fetch(
        `http://localhost:8000/listas/${encodeURIComponent(nombre)}/reordenar`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ canales: nuevos }) }
      );
      if (!res.ok) throw new Error();
      setCanales(nuevos);
      setCanalesEditados(nuevos);
      setSeleccionados(new Set());
      setListas(prev => prev.map(l => l.nombre === nombre ? { ...l, total_canales: nuevos.length } : l));
      setMensajeGlobal(`✅ Eliminados ${noEspana.length} canales no españoles. Quedan ${nuevos.length}.`);
    } catch {
      setError('Error al filtrar canales españoles');
    } finally {
      setFiltrando(false);
    }
  };

  const toggleSeleccion = (idx: number) => {
    setSeleccionados(prev => {
      const nuevo = new Set(prev);
      if (nuevo.has(idx)) nuevo.delete(idx); else nuevo.add(idx);
      return nuevo;
    });
  };

  const toggleTodos = () => {
    if (seleccionados.size === canalesMostrados.length) {
      setSeleccionados(new Set());
    } else {
      setSeleccionados(new Set(canalesMostrados.map((_, i) => i)));
    }
  };

  // Drag & Drop
  const handleDragStart = (idx: number) => { dragIdx.current = idx; };
  const handleDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    if (dragIdx.current === null || dragIdx.current === idx) return;
    const nuevo = [...canalesEditados];
    const [item] = nuevo.splice(dragIdx.current, 1);
    nuevo.splice(idx, 0, item);
    dragIdx.current = idx;
    setCanalesEditados(nuevo);
  };
  const handleDragEnd = () => { dragIdx.current = null; };

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(field === 'caducidad' || field === 'ping'); }
  };

  const getSortValue = (lista: SavedList) => {
    switch (sortField) {
      case 'fecha': return lista.fecha;
      case 'caducidad': return (!lista.caducidad || lista.caducidad === 'Unlimited') ? 'zzzz' : lista.caducidad;
      case 'max_conn': return lista.max_conn;
      case 'ping': return lista.ping;
      case 'total_canales': return lista.total_canales;
      default: return '';
    }
  };


  // Helper: lista añadida en las últimas 24h
  const esNueva = (fecha: string) => {
    try {
      const dt = new Date(fecha);
      return (Date.now() - dt.getTime()) < 24 * 60 * 60 * 1000;
    } catch { return false; }
  };

  const listasSorted = [...listas].sort((a, b) => {
    const va = getSortValue(a), vb = getSortValue(b);
    if (va < vb) return sortAsc ? -1 : 1;
    if (va > vb) return sortAsc ? 1 : -1;
    return 0;
  });

  const canalesMostrados = modoEdicion
    ? (canalesEditados || [])
    : ((canales || []).filter(c => !buscarCanal || (c.nombre || '').toLowerCase().includes(buscarCanal.toLowerCase())));

  if (loading) return (
    <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
      <Loader2 className="size-5 animate-spin" /> Cargando listas...
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-white font-semibold">
          Listas guardadas <span className="text-slate-500 font-normal">({listas.length})</span>
        </h2>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-slate-500 text-xs">Ordenar:</span>
          {SORT_BTNS.map(({ field, label }) => (
            <button key={field} onClick={() => handleSort(field)}
              className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs transition-all ${sortField === field ? 'bg-blue-600 text-white' : 'bg-white/5 text-slate-400 hover:text-white'}`}>
              <ArrowUpDown className="size-3" />
              {label} {sortField === field ? (sortAsc ? '↑' : '↓') : ''}
            </button>
          ))}
          {listas.length > 0 && (
            <button
              onClick={handleDescargarTodas}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-green-400 hover:text-green-300 bg-green-500/10 hover:bg-green-500/20 rounded-lg transition-all"
            >
              <Download className="size-3" /> Descargar todas (.zip)
            </button>
          )}
          {listas.length > 0 && (
            <button
              onClick={handleOrdenarTodasMovistar}
              disabled={ordenandoTodasMovistar}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-blue-400 hover:text-blue-300 bg-blue-500/10 hover:bg-blue-500/20 rounded-lg transition-all disabled:opacity-40"
            >
              {ordenandoTodasMovistar ? <Loader2 className="size-3 animate-spin" /> : '📺'}
              {ordenandoTodasMovistar ? 'Ordenando...' : 'Orden Movistar+ todas'}
            </button>
          )}
          {listas.length > 0 && (
            <button
              onClick={handleEliminarTodas}
              disabled={eliminandoTodas}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-red-400 hover:text-red-300 bg-red-500/10 hover:bg-red-500/20 rounded-lg transition-all disabled:opacity-40"
            >
              {eliminandoTodas ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
              Eliminar todas
            </button>
          )}
          <button onClick={fetchListas} className="p-1.5 text-slate-500 hover:text-white transition-colors">
            <RefreshCw className="size-4" />
          </button>
        </div>
      </div>

      {mensajeGlobal && (
        <div className={`rounded-xl px-4 py-3 text-sm ${mensajeGlobal.startsWith('✅') ? 'bg-green-500/10 border border-green-500/20 text-green-300' : 'bg-red-500/10 border border-red-500/20 text-red-300'}`}>
          {mensajeGlobal}
        </div>
      )}

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3 text-red-400 text-sm">⚠️ {error}</div>
      )}

      {listasSorted.length === 0 ? (
        <div className="bg-white/5 border border-white/10 rounded-2xl p-16 text-center">
          <Tv2 className="size-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">No hay listas guardadas</p>
        </div>
      ) : (
        <div className="space-y-3">
          {listasSorted.map((lista) => (
            <div key={lista.nombre} className="bg-white/5 border border-white/10 rounded-2xl overflow-hidden hover:border-white/20 transition-all">
              <div className="p-5">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1 min-w-0">
                    <h3 className="text-white font-semibold">{lista.nombre}</h3>
                    {lista.url && <p className="text-slate-600 text-xs mt-0.5 truncate max-w-sm">{lista.url}</p>}
                  </div>
                  <div className="flex gap-1.5 ml-3 shrink-0 flex-wrap justify-end">
                    <button onClick={() => handleVerCanales(lista.nombre)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${viendoCanales === lista.nombre ? 'bg-purple-600 text-white' : 'text-slate-400 hover:text-purple-400 hover:bg-purple-400/10'}`}>
                      <Eye className="size-3.5" />
                      {viendoCanales === lista.nombre ? 'Ocultar' : 'Ver canales'}
                    </button>
                    <button onClick={() => handleDownload(lista.nombre)} disabled={downloading === lista.nombre}
                      className="p-2 text-slate-400 hover:text-blue-400 hover:bg-blue-400/10 rounded-lg transition-all">
                      {downloading === lista.nombre ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
                    </button>
                    <button onClick={() => handleDelete(lista.nombre)} disabled={deleting === lista.nombre}
                      className="p-2 text-slate-400 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-all">
                      {deleting === lista.nombre ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                    </button>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 mb-2">
                  <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                    <Tv2 className="size-3" /> {lista.total_canales} canales
                  </span>
                  <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                    <Wifi className="size-3" /> Max. {lista.max_conn} conn.
                  </span>
                  {lista.ping > 0 && (
                    <span className="flex items-center gap-1.5 text-yellow-300 text-xs bg-yellow-500/10 px-2.5 py-1 rounded-full">
                      <Zap className="size-3" /> {lista.ping}ms
                    </span>
                  )}
                  {lista.caducidad && (
                    <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${lista.caducidad === 'Unlimited' ? 'bg-green-500/10 text-green-300' : new Date(lista.caducidad) < new Date(Date.now() + 30 * 24 * 60 * 60 * 1000) ? 'bg-red-500/10 text-red-300' : 'bg-white/10 text-slate-300'}`}>
                      <Calendar className="size-3" />
                      {lista.caducidad === 'Unlimited' ? '♾ Unlimited' : `Caduca: ${lista.caducidad}`}
                    </span>
                  )}
                  {lista.filtro && (
                    <span className="text-xs bg-blue-500/10 text-blue-300 px-2.5 py-1 rounded-full">Filtro: {lista.filtro}</span>
                  )}
                </div>

                {lista.observaciones && (
                  <div className="flex items-start gap-2 bg-white/5 rounded-xl px-3 py-2">
                    <FileText className="size-3 text-slate-500 mt-0.5 shrink-0" />
                    <p className="text-slate-400 text-xs">{lista.observaciones}</p>
                  </div>
                )}
                {lista.tipo_lista && (
                  <span className={`inline-flex text-xs px-2.5 py-1 rounded-full font-medium mt-1 ${
                    lista.tipo_lista === 'Stream .ts directo'
                      ? 'bg-purple-500/20 text-purple-300'
                      : lista.tipo_lista.includes('Xtream')
                      ? 'bg-blue-500/10 text-blue-300'
                      : 'bg-white/10 text-slate-300'
                  }`}>
                    {lista.tipo_lista === 'Stream .ts directo' ? '📡 ' : '📋 '}
                    {lista.tipo_lista}
                  </span>
                )}
                <p className="text-slate-600 text-xs mt-2">
                  Guardada: {new Date(lista.fecha).toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </p>
              </div>

              {/* Panel canales */}
              {viendoCanales === lista.nombre && (
                <div className="border-t border-white/10 bg-black/20 p-5">
                  {loadingCanales ? (
                    <div className="flex items-center justify-center py-8 gap-3 text-slate-500">
                      <Loader2 className="size-5 animate-spin" /> Cargando canales...
                    </div>
                  ) : (
                    <>
                      {/* Controles */}
                      <div className="flex items-center gap-2 mb-3 flex-wrap">
                        <span className="text-slate-400 text-sm">{canalesMostrados.length} canales</span>
                        {!modoEdicion && (
                          <input type="text" value={buscarCanal} onChange={(e) => { setBuscarCanal(e.target.value); setSeleccionados(new Set()); }}
                            placeholder="Buscar canal..."
                            className="flex-1 min-w-40 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-blue-400" />
                        )}
                        <div className="flex gap-2 ml-auto flex-wrap">
                          {!modoEdicion ? (
                            <>
                              {seleccionados.size > 0 && (
                                <button onClick={() => handleEliminarSeleccionados(lista.nombre)} disabled={eliminandoSeleccion}
                                  className="flex items-center gap-1.5 px-3 py-1.5 bg-red-600 hover:bg-red-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all">
                                  {eliminandoSeleccion ? <Loader2 className="size-3.5 animate-spin" /> : <Trash2 className="size-3.5" />}
                                  Eliminar {seleccionados.size} seleccionados
                                </button>
                              )}
                              <button onClick={() => handleMantenerEspana(lista.nombre)} disabled={filtrando}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-600 hover:bg-orange-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all">
                                {filtrando ? <Loader2 className="size-3.5 animate-spin" /> : '🇪🇸'}
                                {filtrando ? 'Filtrando...' : 'Mantener solo ES:'}
                              </button>
                              <button onClick={() => { setModoEdicion(true); setCanalesEditados([...canales]); setSeleccionados(new Set()); }}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white rounded-lg text-xs transition-all">
                                <GripVertical className="size-3.5" /> Reordenar
                              </button>
                              <button onClick={() => handleOrdenarMovistar(lista.nombre)} disabled={ordenandoMovistar}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white rounded-lg text-xs transition-all font-medium">
                                {ordenandoMovistar ? <Loader2 className="size-3.5 animate-spin" /> : '📺'}
                                {ordenandoMovistar ? 'Ordenando...' : 'Orden Movistar+'}
                              </button>
                            </>
                          ) : (
                            <>
                              <button onClick={() => setModoEdicion(false)}
                                className="px-3 py-1.5 bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white rounded-lg text-xs transition-all">
                                Cancelar
                              </button>
                              <button onClick={() => handleGuardarOrden(lista.nombre)} disabled={guardandoOrden}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all">
                                {guardandoOrden ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                                {guardandoOrden ? 'Guardando...' : 'Guardar orden'}
                              </button>
                            </>
                          )}
                        </div>
                      </div>

                      {modoEdicion && (
                        <p className="text-slate-500 text-xs mb-2">🖱️ Arrastra los canales para reordenarlos</p>
                      )}

                      {/* Tabla canales */}
                      <div className="rounded-xl border border-white/10 overflow-hidden">
                        <div className="max-h-96 overflow-y-auto">
                          <table className="w-full text-sm">
                            <thead className="sticky top-0 bg-[#0d1117] border-b border-white/10">
                              <tr>
                                {modoEdicion && <th className="w-8 px-3 py-2.5"></th>}
                                {!modoEdicion && (
                                  <th className="w-8 px-3 py-2.5">
                                    <input type="checkbox"
                                      checked={canalesMostrados.length > 0 && seleccionados.size === canalesMostrados.length}
                                      onChange={toggleTodos}
                                      className="cursor-pointer accent-blue-500" />
                                  </th>
                                )}
                                <th className="text-left px-4 py-2.5 text-slate-500 font-medium w-10">#</th>
                                <th className="text-left px-4 py-2.5 text-slate-500 font-medium">Canal</th>
                                <th className="text-left px-4 py-2.5 text-slate-500 font-medium hidden sm:table-cell">URL</th>
                                {!modoEdicion && <th className="w-8"></th>}
                              </tr>
                            </thead>
                            <tbody>
                              {canalesMostrados.map((canal, i) => (
                                <tr key={i}
                                  draggable={modoEdicion}
                                  onDragStart={modoEdicion ? () => handleDragStart(i) : undefined}
                                  onDragOver={modoEdicion ? (e) => handleDragOver(e, i) : undefined}
                                  onDragEnd={modoEdicion ? handleDragEnd : undefined}
                                  onClick={!modoEdicion ? () => toggleSeleccion(i) : undefined}
                                  className={`border-b border-white/5 transition-colors ${modoEdicion ? 'cursor-grab hover:bg-blue-500/5' : 'cursor-pointer ' + (seleccionados.has(i) ? 'bg-blue-500/10' : 'hover:bg-white/5')}`}>
                                  {modoEdicion && (
                                    <td className="px-3 py-2 text-slate-600">
                                      <GripVertical className="size-4" />
                                    </td>
                                  )}
                                  {!modoEdicion && (
                                    <td className="px-3 py-2" onClick={e => e.stopPropagation()}>
                                      <input type="checkbox" checked={seleccionados.has(i)} onChange={() => toggleSeleccion(i)}
                                        className="cursor-pointer accent-blue-500" />
                                    </td>
                                  )}
                                  <td className="px-4 py-2 text-slate-600 text-xs">{i + 1}</td>
                                  <td className="px-4 py-2 text-white text-sm">{canal.nombre}</td>
                                  <td className="px-4 py-2 text-slate-600 text-xs truncate max-w-xs hidden sm:table-cell">{canal.url}</td>
                                  {!modoEdicion && (
                                    <td className="px-2 py-2" onClick={e => e.stopPropagation()}>
                                      <button
                                        onClick={() => handleEliminarCanal(lista.nombre, i)}
                                        disabled={eliminandoCanal === i}
                                        className="p-1 text-slate-600 hover:text-red-400 hover:bg-red-400/10 rounded transition-all"
                                      >
                                        {eliminandoCanal === i ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
                                      </button>
                                    </td>
                                  )}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
