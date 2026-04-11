import { useEffect, useState, useRef } from 'react';
import {
  Search, Trash2, Save, Loader2, RefreshCw, Tv2,
  CheckCircle2, XCircle, Zap, Calendar, Wifi, X, Upload
} from 'lucide-react';
import type { UrlEntry, BusquedaResultado } from '../App';

interface Props {
  onSaveComplete: () => void;
}

interface Progreso {
  total: number;
  completadas: number;
  con_canales: number;
  verificando: number;
}

type SortField = 'caducidad' | 'max_conn' | 'ping' | 'encontrados' | 'pct_ok' | 'fecha_verificacion';

// Variables globales fuera del componente - persisten entre renders
let resultadosPersistidos: { con: BusquedaResultado[]; sin: string[]; filtro: string } | null = null;
let filtroPersistido = '';
let parcialesGlobal: BusquedaResultado[] = [];

export function ScannedUrls({ onSaveComplete }: Props) {
  const [urls, setUrls] = useState<UrlEntry[]>([]);
  const [urlsTxt, setUrlsTxt] = useState<UrlEntry[]>([]);
  const [urlsVerificadas, setUrlsVerificadas] = useState<UrlEntry[]>([]);
  const [fuente, setFuente] = useState<'telegram' | 'txt' | 'verificadas'>('telegram');
  const [loading, setLoading] = useState(true);
  const [filtro, setFiltro] = useState(filtroPersistido);
  const [buscando, setBuscando] = useState(false);
  const [progreso, setProgreso] = useState<Progreso | null>(null);
  const [resultados, setResultados] = useState<{
    con: BusquedaResultado[];
    sin: string[];
    filtro: string;
  } | null>(resultadosPersistidos);
  const [guardando, setGuardando] = useState<string | null>(null);
  const [guardandoTodas, setGuardandoTodas] = useState(false);
  const [eliminando, setEliminando] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [importando, setImportando] = useState(false);
  const [importResult, setImportResult] = useState('');
  const [importandoJson, setImportandoJson] = useState(false);
  const [sortField, setSortField] = useState<SortField>('fecha_verificacion');
  const [sortAsc, setSortAsc] = useState(false);
  const [minCanales, setMinCanales] = useState(20);
  const [limpiandoJson, setLimpiandoJson] = useState(false);

  // Refs - declaradas todas juntas al inicio
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const jsonInputRef = useRef<HTMLInputElement | null>(null);

  const handleCargarJsonGuardado = async () => {
    setResultados(null);
    resultadosPersistidos = null;
    setFuente('verificadas');
    setBuscando(false);
    setProgreso(null);
    setError('');
    try {
      const res = await fetch('http://localhost:8000/urls/verificadas');
      const data: UrlEntry[] = await res.json();
      setUrlsVerificadas(data);
      if (data.length === 0) {
        setError('No hay URLs verificadas. Importa un TXT primero.');
        return;
      }
      const r = convertirVerificadasAResultados(data);
      setResultados(r);
      resultadosPersistidos = r;
    } catch {
      setError('Error al cargar las URLs verificadas');
    }
  };

  const handleLimpiarVerificadas = async () => {
    if (!confirm('¿Eliminar todas las URLs verificadas?')) return;
    try {
      await fetch('http://localhost:8000/urls/verificadas/limpiar', { method: 'POST' });
      setUrlsVerificadas([]);
      setResultados(null);
      resultadosPersistidos = null;
      setFuente('telegram');
    } catch {
      setError('Error al limpiar las URLs verificadas');
    }
  };

  const handleImportarJsonVerificadas = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportandoJson(true);
    setImportResult('');
    try {
      const form = new FormData();
      form.append('archivo', file, file.name);
      const res = await fetch('http://localhost:8000/urls/verificadas/importar', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setImportResult(`✅ ${data.nuevas} nuevas listas verificadas importadas (${data.total} total)`);
      await fetchUrls();
      // Recargar verificadas y mostrar
      await handleCargarJsonGuardado();
    } catch (err: any) {
      setImportResult('⚠️ ' + (err.message || 'Error al importar el JSON'));
    } finally {
      setImportandoJson(false);
      if (jsonInputRef.current) jsonInputRef.current.value = '';
    }
  };

  const handleLimpiarJson = async () => {
    if (!confirm('¿Limpiar el JSON guardado? Se eliminarán todas las URLs acumuladas.')) return;
    setLimpiandoJson(true);
    try {
      await fetch('http://localhost:8000/urls/txt/limpiar', { method: 'POST' });
      await fetchUrls();
      if (fuente === 'txt') {
        setResultados(null);
        resultadosPersistidos = null;
      }
    } catch {
      setError('Error al limpiar el JSON');
    } finally {
      setLimpiandoJson(false);
    }
  };

  const convertirVerificadasAResultados = (data: UrlEntry[]) => {
    const comoResultados = data.map((entrada: any) => ({
      url: entrada.url,
      entrada: {
        ...entrada,
        ping: entrada.ping || 0,
        max_conn: entrada.max_conn || 1,
        caducidad: entrada.caducidad || '',
        observaciones: entrada.observaciones || '',
        portal: entrada.portal || entrada.url,
      },
      encontrados: entrada.total_canales || 0,
      clave: `verificada_${entrada.url}`,
      canales: [],
      pct_ok: entrada.pct_streams || 0,
    }));
    return { con: comoResultados, sin: [], filtro: 'Verificadas' };
  };

  const fetchUrls = async () => {
    setLoading(true);
    try {
      const [resTg, resTxt, resVerif] = await Promise.allSettled([
        fetch('http://localhost:8000/urls').then(r => r.json()),
        fetch('http://localhost:8000/urls/txt').then(r => r.json()),
        fetch('http://localhost:8000/urls/verificadas').then(r => r.json()),
      ]);
      if (resTg.status === 'fulfilled') setUrls(resTg.value);
      if (resTxt.status === 'fulfilled') setUrlsTxt(resTxt.value);
      if (resVerif.status === 'fulfilled') {
        const verificadas: UrlEntry[] = resVerif.value;
        setUrlsVerificadas(verificadas);
        if (verificadas.length > 0 && !resultadosPersistidos) {
          const r = convertirVerificadasAResultados(verificadas);
          setResultados(r);
          resultadosPersistidos = r;
          setFuente('verificadas');
        }
      }
    } catch {
      setError('No se pudo conectar con el servidor');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUrls(); }, []);
  useEffect(() => { resultadosPersistidos = resultados; }, [resultados]);
  useEffect(() => { filtroPersistido = filtro; }, [filtro]);

  const urlsActivas = fuente === 'telegram' ? urls : fuente === 'txt' ? urlsTxt : urlsVerificadas;

  const handleParar = () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  };

  const handleBuscar = async (e: React.FormEvent) => {
    e.preventDefault();

    // Si no hay filtro y la fuente es verificadas → cargar directamente sin escanear
    if (!filtro.trim() && fuente === 'verificadas') {
      await handleCargarJsonGuardado();
      return;
    }

    // Limpiar estado
    setBuscando(true);
    setError('');
    if (fuente !== 'verificadas') {
      setResultados(null);
      resultadosPersistidos = null;
    }
    setProgreso(null);
    parcialesGlobal = []; // Limpiar global

    // Crear nuevo controller
    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const form = new FormData();
      form.append('filtro', filtro.trim());
      form.append('fuente', fuente);

      const res = await fetch('http://localhost:8000/urls/buscar', {
        method: 'POST',
        body: form,
        signal: controller.signal,
      });

      if (!res.ok) {
        const d = await res.json();
        throw new Error(d.detail);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));

            if (data.tipo === 'inicio') {
              setProgreso({ total: data.total, completadas: 0, con_canales: 0, verificando: 0 });

            } else if (data.tipo === 'progreso') {
              setProgreso({
                total: data.total,
                completadas: data.completadas,
                con_canales: data.con_canales,
                verificando: data.verificando || 0,
              });
              // Guardar en variable global cada vez que llegan datos
              if (data.con_canales_data && Array.isArray(data.con_canales_data) && data.con_canales_data.length > 0) {
                parcialesGlobal = [...data.con_canales_data];
              }

            } else if (data.tipo === 'fin') {
              parcialesGlobal = [...data.con_canales];
              const r = { con: data.con_canales, sin: data.sin_canales, filtro: data.filtro };
              setResultados(r);
              resultadosPersistidos = r;
              setProgreso(null);
              setBuscando(false);
            }
          } catch (_) {
            // Ignorar líneas mal formadas
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        const copia = [...parcialesGlobal];
        console.log('Parado - parciales encontrados:', copia.length);
        // Primero limpiar estado
        setBuscando(false);
        setProgreso(null);
        setResultados(null);
        if (copia.length > 0) {
          const r = { con: copia, sin: [], filtro: filtro.trim() };
          resultadosPersistidos = r;
          // Doble setTimeout para forzar re-render después del abort
          setTimeout(() => {
            setResultados(r);
            setTimeout(() => setResultados({...r}), 50);
          }, 100);
        }
      } else {
        setError(err.message || 'Error desconocido');
        setBuscando(false);
        setProgreso(null);
      }
    }
  };

  const handleImportar = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setImportando(true);
    setImportResult('');
    try {
      const form = new FormData();
      form.append('archivo', file, file.name);
      const res = await fetch('http://localhost:8000/urls/importar-txt-verificadas', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      setImportResult(`✅ ${data.nuevas} nuevas URLs añadidas a verificadas (${data.disponibles} responden ping de ${data.total_encontradas} encontradas)`);
      await fetchUrls();
      await new Promise(r => setTimeout(r, 300));
      await handleCargarJsonGuardado();
    } catch (err: any) {
      setImportResult('⚠️ ' + err.message);
    } finally {
      setImportando(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleLimpiar = () => {
    setResultados(null);
    resultadosPersistidos = null;
    parcialesGlobal = [];
    setProgreso(null);
    setError('');
  };

  const handleGuardarTodas = async () => {
    if (!resultados || resultadosOrdenados.length === 0) return;
    if (!confirm(`¿Guardar las ${resultadosOrdenados.length} listas verificadas de golpe?`)) return;
    setGuardandoTodas(true);
    try {
      const entradas = resultadosOrdenados.map(resultado => ({
        nombre: limpiarNombre(resultado.entrada.portal, resultado.url),
        url: resultado.url,
        max_conn: resultado.entrada.max_conn || 1,
        caducidad: resultado.entrada.caducidad || '',
        observaciones: resultado.entrada.observaciones || '',
        ping: resultado.entrada.ping || 0,
      }));

      const res = await fetch('http://localhost:8000/urls/guardar-todas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entradas,
          filtro: resultados?.filtro || filtro,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error al guardar');
      setResultados(prev => prev ? { ...prev, con: [] } : prev);
      resultadosPersistidos = resultados ? { ...resultados, con: [] } : null;
    } catch (err: any) {
      setError(err.message || 'Error al guardar todas');
    } finally {
      setGuardandoTodas(false);
    }
  };

  const handleEliminarUrl = async (url: string) => {
    setEliminando(url);
    try {
      const form = new FormData();
      form.append('url', url);
      await fetch('http://localhost:8000/urls/eliminar', { method: 'DELETE', body: form });
      setUrls(prev => prev.filter(u => u.url !== url));
      if (resultados) {
        const nuevo = {
          ...resultados,
          sin: resultados.sin.filter(u => u !== url),
          con: resultados.con.filter(r => r.url !== url),
        };
        setResultados(nuevo);
        resultadosPersistidos = nuevo;
      }
    } catch {
      setError('Error al eliminar');
    } finally {
      setEliminando(null);
    }
  };

  const limpiarNombre = (portal: string, url: string): string => {
    const base = portal || url;
    const dominio = base.replace(/https?:\/\//, '').replace(/:\d+.*/, '').replace(/[\\/*?:"<>|]/g, '_').trim();
    const match = url.match(/[?&]username=([^&]+)/i);
    const usuario = match ? match[1].replace(/[\\/*?:"<>|@.]/g, '_') : '';
    return usuario ? dominio + '_' + usuario : dominio;
  };

  const handleGuardar = async (resultado: BusquedaResultado, forzar = false) => {
    setGuardando(resultado.url);
    try {
      const nombre = limpiarNombre(resultado.entrada.portal, resultado.url);
      const form = new FormData();
      form.append('nombre', nombre);
      form.append('clave', resultado.clave);
      form.append('filtro', resultados?.filtro || filtro);
      form.append('max_conn', String(resultado.entrada.max_conn || 1));
      form.append('caducidad', resultado.entrada.caducidad || '');
      form.append('observaciones', resultado.entrada.observaciones || '');
      form.append('ping', String(resultado.entrada.ping || 0));
      const res = await fetch('http://localhost:8000/urls/guardar', { method: 'POST', body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail);
      if (data.ya_existia && !forzar) {
        setGuardando(null);
        const sobreescribir = confirm(`"${nombre}" ya está en Listas guardadas.\n\n¿Sobreescribir con la versión nueva?`);
        if (sobreescribir) await handleGuardar(resultado, true);
        return;
      }
      if (!data.descarga_ok) {
        alert(`"${nombre}" guardada sin canales — el servidor bloqueó la descarga desde tu IP.\nPuedes usarla desde el VPS de Hetzner.`);
      }
      // Eliminar de resultados
      const nuevo = { ...resultados!, con: resultados!.con.filter(r => r.url !== resultado.url) };
      setResultados(nuevo);
      resultadosPersistidos = nuevo;
    } catch (err: any) {
      setError(err.message);
    } finally {
      setGuardando(null);
    }
  };

  const handleEliminarTodas = async () => {
    if (!resultados) return;
    for (const url of resultados.sin) {
      const form = new FormData();
      form.append('url', url);
      await fetch('http://localhost:8000/urls/eliminar', { method: 'DELETE', body: form });
    }
    setUrls(prev => prev.filter(u => !resultados.sin.includes(u.url)));
    const nuevo = { ...resultados, sin: [] };
    setResultados(nuevo);
    resultadosPersistidos = nuevo;
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) setSortAsc(!sortAsc);
    else { setSortField(field); setSortAsc(field === 'caducidad' || field === 'ping'); }
    if (field === 'pct_ok' || field === 'max_conn' || field === 'encontrados') setSortAsc(false);
  };

  const getSortValue = (r: BusquedaResultado) => {
    switch (sortField) {
      case 'fecha_verificacion': return (r.entrada as any).fecha_verificacion || (r.entrada as any).fecha_scan || '';
      case 'caducidad': { const c = r.entrada.caducidad; return (!c || c === 'Unlimited') ? 'zzzz' : c; }
      case 'max_conn': return r.entrada.max_conn;
      case 'ping': return r.entrada.ping;
      case 'encontrados': return r.encontrados;
      case 'pct_ok': return (r as any).pct_ok ?? 0;
      default: return '';
    }
  };

  const resultadosOrdenados = resultados
    ? [...resultados.con]
        .filter(r => fuente === 'verificadas' || r.encontrados >= minCanales)
        .sort((a, b) => {
          const va = getSortValue(a), vb = getSortValue(b);
          if (va < vb) return sortAsc ? -1 : 1;
          if (va > vb) return sortAsc ? 1 : -1;
          return 0;
        })
    : [];


  // Helper: URL verificada en las últimas 24h
  const esNuevaUrl = (entrada: any) => {
    try {
      const fecha = entrada.fecha_verificacion || entrada.fecha_scan || '';
      if (!fecha) return false;
      return (Date.now() - new Date(fecha).getTime()) < 24 * 60 * 60 * 1000;
    } catch { return false; }
  };

  if (loading) return (
    <div className="flex items-center justify-center py-24 gap-3 text-slate-500">
      <Loader2 className="size-5 animate-spin" /> Cargando URLs...
    </div>
  );

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-white font-semibold">URLs verificadas</h2>
          <p className="text-slate-500 text-sm">{urlsVerificadas.length} URLs disponibles</p>
        </div>
        <div className="flex items-center gap-2">
          {resultados && (
            <button onClick={handleLimpiar} className="flex items-center gap-2 px-4 py-2 text-sm text-slate-400 hover:text-white bg-white/5 hover:bg-white/10 rounded-xl transition-all">
              <X className="size-4" /> Limpiar
            </button>
          )}
          <button onClick={() => jsonInputRef.current?.click()} disabled={importandoJson}
            className="flex items-center gap-2 px-4 py-2 text-sm text-green-400 hover:text-green-300 bg-green-500/10 hover:bg-green-500/20 rounded-xl transition-all disabled:opacity-40">
            {importandoJson ? <Loader2 className="size-4 animate-spin" /> : '📥'}
            {importandoJson ? 'Importando...' : 'Importar JSON verificadas'}
          </button>
          <input ref={jsonInputRef} type="file" accept=".json" className="hidden" onChange={handleImportarJsonVerificadas} />
          <button onClick={fetchUrls} className="p-2 text-slate-500 hover:text-white transition-colors">
            <RefreshCw className="size-4" />
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <button onClick={handleCargarJsonGuardado}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all ${fuente === 'verificadas' ? 'bg-green-600 text-white' : 'bg-green-500/10 text-green-400 hover:text-green-300 hover:bg-green-500/20'}`}>
          ✅ Cargar verificadas ({urlsVerificadas.length})
        </button>
        {urlsVerificadas.length > 0 && (
          <button onClick={handleLimpiarVerificadas}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-red-400 hover:text-red-300 bg-red-500/10 hover:bg-red-500/20 transition-all">
            🗑️ Limpiar verificadas
          </button>
        )}
        {urlsTxt.length > 0 && (
          <button onClick={handleLimpiarJson} disabled={limpiandoJson}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium text-red-400 hover:text-red-300 bg-red-500/10 hover:bg-red-500/20 transition-all disabled:opacity-40">
            {limpiandoJson ? <Loader2 className="size-3.5 animate-spin" /> : '🗑️'}
            Limpiar JSON
          </button>
        )}
      </div>

      {importResult && (
        <div className={`rounded-xl px-4 py-3 text-sm ${importResult.startsWith('✅') ? 'bg-green-500/10 border border-green-500/20 text-green-300' : 'bg-red-500/10 border border-red-500/20 text-red-300'}`}>
          {importResult}
        </div>
      )}

      {urlsActivas.length === 0 && !resultados && fuente !== 'verificadas' ? (
        <div className="bg-white/5 border border-white/10 rounded-2xl p-16 text-center">
          <Tv2 className="size-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">No hay URLs en esta fuente</p>
        </div>
      ) : fuente === 'verificadas' && !resultados && !buscando ? (
        <div className="bg-white/5 border border-white/10 rounded-2xl p-16 text-center">
          <Tv2 className="size-12 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500">Pulsa "Cargar verificadas" para ver las URLs importadas</p>
        </div>
      ) : (
        <>
          <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
            <h3 className="text-white font-semibold mb-2">Buscar canales por filtro</h3>
            <p className="text-slate-500 text-sm mb-4">
              {fuente === 'verificadas' 
                ? 'Filtra las listas verificadas por canales que te interesan. Ej: ES:, ESPAÑA, Movistar, beIN'
                : 'Múltiples filtros separados por coma. Se verificará que el 75% de los canales emitan correctamente.'}
            </p>
            <form onSubmit={handleBuscar} className="flex gap-3 flex-wrap">
              <input type="text" value={filtro} onChange={(e) => setFiltro(e.target.value)}
                placeholder="Ej: ES:, ESPAÑA, Movistar, beIN" disabled={buscando}
                className="flex-1 min-w-48 bg-white/5 border border-white/20 rounded-xl px-4 py-3 text-white placeholder:text-slate-500 focus:outline-none focus:border-blue-400 transition-all disabled:opacity-50" />
              <div className="flex items-center gap-2 bg-white/5 border border-white/20 rounded-xl px-3">
                <span className="text-slate-500 text-xs whitespace-nowrap">Mín. canales:</span>
                <input type="number" value={minCanales}
                  onChange={(e) => setMinCanales(Math.max(1, parseInt(e.target.value) || 1))}
                  min="1" className="w-14 bg-transparent py-3 text-white text-sm focus:outline-none" />
              </div>
              <button type="submit" disabled={buscando}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white font-medium px-6 py-3 rounded-xl transition-all">
                {buscando ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
                {buscando ? 'Buscando...' : 'Buscar'}
              </button>
              {buscando && (
                <button type="button" onClick={handleParar}
                  className="flex items-center gap-2 bg-red-600 hover:bg-red-500 text-white font-medium px-4 py-3 rounded-xl transition-all">
                  ⏹ Parar
                </button>
              )}
            </form>

            {error && (
              <div className="mt-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3 text-red-300 text-sm">⚠️ {error}</div>
            )}

            {progreso && (
              <div className="mt-4 bg-blue-500/10 border border-blue-500/20 rounded-xl p-4 space-y-4">
                <div className="grid grid-cols-4 gap-3 text-center">
                  <div className="bg-white/5 rounded-xl p-3">
                    <div className="text-2xl font-bold text-white">{progreso.total}</div>
                    <div className="text-slate-400 text-xs mt-1">Total</div>
                  </div>
                  <div className="bg-blue-500/10 rounded-xl p-3">
                    <div className="text-2xl font-bold text-blue-400">{progreso.completadas}</div>
                    <div className="text-slate-400 text-xs mt-1">Escaneadas</div>
                  </div>
                  <div className="bg-yellow-500/10 rounded-xl p-3">
                    <div className="text-2xl font-bold text-yellow-400">{progreso.verificando}</div>
                    <div className="text-slate-400 text-xs mt-1">Verificando</div>
                  </div>
                  <div className="bg-slate-500/10 rounded-xl p-3">
                    <div className="text-2xl font-bold text-slate-400">{progreso.total - progreso.completadas}</div>
                    <div className="text-slate-400 text-xs mt-1">Pendientes</div>
                  </div>
                </div>
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs text-slate-500">
                    <span>Progreso de escaneo</span>
                    <span>{Math.round((progreso.completadas / progreso.total) * 100)}%</span>
                  </div>
                  <div className="bg-white/10 rounded-full h-2.5 overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full transition-all duration-300"
                      style={{ width: `${Math.round((progreso.completadas / progreso.total) * 100)}%` }} />
                  </div>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1.5 text-green-400">
                    <CheckCircle2 className="size-3" />
                    <span className="font-bold">{progreso.con_canales}</span>
                    <span className="text-slate-400">listas válidas con streams verificados</span>
                  </span>
                  {progreso.verificando > 0 && (
                    <span className="flex items-center gap-1.5 text-yellow-400">
                      <Loader2 className="size-3 animate-spin" /> Verificando streams...
                    </span>
                  )}
                </div>
                <div className="bg-white/5 rounded-lg px-3 py-2 text-xs text-slate-500">
                  🔍 Verificando que al menos el 75% de los canales emiten correctamente
                </div>
              </div>
            )}
          </div>

          {resultados && (
            <div className="space-y-4">
              {resultadosOrdenados.length > 0 && (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <CheckCircle2 className="size-4 text-green-400" />
                    <h3 className="text-white font-semibold">
                      Listas verificadas "{resultados.filtro}"
                      <span className="text-green-400 ml-2">({resultadosOrdenados.length})</span>
                    </h3>
                    <div className="ml-auto flex items-center gap-1.5 flex-wrap">
                      <button onClick={handleGuardarTodas} disabled={guardandoTodas || resultadosOrdenados.length === 0}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white rounded-lg text-xs font-medium transition-all">
                        {guardandoTodas ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
                        {guardandoTodas ? 'Guardando...' : `Guardar todas (${resultadosOrdenados.length})`}
                      </button>
                      <span className="text-slate-500 text-xs">Ordenar:</span>
                      {([['fecha_verificacion', 'Recientes'], ['caducidad', 'Caducidad'], ['max_conn', 'MaxConn'], ['ping', 'Velocidad'], ['pct_ok', 'Stream %'], ['encontrados', 'Canales']] as [SortField, string][]).map(([field, label]) => (
                        <button key={field} onClick={() => handleSort(field)}
                          className={`px-2.5 py-1 rounded-lg text-xs transition-all ${sortField === field ? 'bg-blue-600 text-white' : 'bg-white/5 text-slate-400 hover:text-white'}`}>
                          {label} {sortField === field ? (sortAsc ? '↑' : '↓') : ''}
                        </button>
                      ))}
                    </div>
                  </div>

                  {resultadosOrdenados.map((resultado) => {
                    const nombre = limpiarNombre(resultado.entrada.portal, resultado.url);
                    const pctOk = (resultado as any).pct_ok;
                    return (
                      <div key={resultado.url} className={`border rounded-2xl p-5 transition-all ${esNuevaUrl(resultado.entrada) ? 'bg-green-500/10 border-green-500/30 hover:border-green-500/50' : 'bg-white/5 border-white/10 hover:border-white/20'}`}>
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-white font-semibold">{nombre}</p>
                            <p className="text-slate-500 text-xs mt-0.5 truncate">{resultado.url}</p>
                          </div>
                          <span className="bg-green-500/20 text-green-400 text-xs px-2.5 py-1 rounded-full ml-3 shrink-0">
                            {resultado.encontrados} canales
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2 mb-3">
                          <span className="flex items-center gap-1.5 text-yellow-300 text-xs bg-yellow-500/10 px-2.5 py-1 rounded-full">
                            <Zap className="size-3" /> {resultado.entrada.ping}ms
                          </span>
                          {resultado.entrada.max_conn > 0 && (
                            <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                              <Wifi className="size-3" /> Max. {resultado.entrada.max_conn} conn.
                            </span>
                          )}
                          {resultado.entrada.caducidad && (
                            <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${resultado.entrada.caducidad === 'Unlimited' ? 'bg-green-500/10 text-green-300' : new Date(resultado.entrada.caducidad) < new Date(Date.now() + 30 * 24 * 60 * 60 * 1000) ? 'bg-red-500/10 text-red-300' : 'bg-white/10 text-slate-300'}`}>
                              <Calendar className="size-3" />
                              {resultado.entrada.caducidad === 'Unlimited' ? '♾ Unlimited' : `Caduca: ${resultado.entrada.caducidad}`}
                            </span>
                          )}
                          {pctOk !== undefined && (
                            <span className={`text-xs px-2.5 py-1 rounded-full ${pctOk >= 90 ? 'bg-green-500/10 text-green-300' : pctOk >= 75 ? 'bg-yellow-500/10 text-yellow-300' : 'bg-red-500/10 text-red-300'}`}>
                              ✅ {pctOk}% streams OK
                            </span>
                          )}
                          {resultado.entrada.observaciones && (
                            <span className="text-xs bg-white/10 text-slate-300 px-2.5 py-1 rounded-full">
                              {resultado.entrada.observaciones}
                            </span>
                          )}
                        </div>
                        {resultado.canales.length > 0 && (
                          <div className="flex flex-wrap gap-1 mb-3">
                            {resultado.canales.map((c, i) => (
                              <span key={i} className="text-xs bg-blue-500/10 text-blue-300 px-2 py-0.5 rounded">{c.nombre}</span>
                            ))}
                            {resultado.encontrados > 5 && <span className="text-xs text-slate-600">+{resultado.encontrados - 5} más</span>}
                          </div>
                        )}
                        <button onClick={() => handleGuardar(resultado)} disabled={guardando === resultado.url}
                          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm font-medium px-5 py-2 rounded-xl transition-all">
                          {guardando === resultado.url ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
                          {guardando === resultado.url ? 'Guardando...' : `Guardar ${resultado.encontrados} canales`}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}

              {resultados.sin.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <XCircle className="size-4 text-red-400" />
                    <h3 className="text-white font-semibold">
                      Sin canales <span className="text-red-400 ml-2">({resultados.sin.length})</span>
                    </h3>
                    <button onClick={handleEliminarTodas}
                      className="ml-auto flex items-center gap-1.5 text-xs text-red-400 hover:text-red-300 bg-red-500/10 hover:bg-red-500/20 px-3 py-1.5 rounded-lg transition-all">
                      <Trash2 className="size-3" /> Eliminar todas
                    </button>
                  </div>
                  <div className="bg-white/5 border border-white/10 rounded-xl divide-y divide-white/5">
                    {resultados.sin.map((url) => (
                      <div key={url} className="flex items-center justify-between px-4 py-3">
                        <span className="text-slate-500 text-xs truncate max-w-sm">{url}</span>
                        <button onClick={() => handleEliminarUrl(url)} disabled={eliminando === url}
                          className="p-1.5 text-slate-600 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-all shrink-0 ml-3">
                          {eliminando === url ? <Loader2 className="size-3 animate-spin" /> : <Trash2 className="size-3" />}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
