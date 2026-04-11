import { useState, useRef } from 'react';
import { Loader2, Search, Upload, Wifi, Zap, Calendar, Tv2 } from 'lucide-react';
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
}

export function AnalyzerForm({ onCheckResult }: Props) {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // M3U file analyzer
  const [m3uInfo, setM3uInfo] = useState<M3UInfo | null>(null);
  const [loadingM3u, setLoadingM3u] = useState(false);
  const [errorM3u, setErrorM3u] = useState('');
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const form = new FormData();
      form.append('url', url.trim());

      const res = await fetch('http://localhost:8000/check', {
        method: 'POST',
        body: form,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Error desconocido');
      onCheckResult(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleM3uFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setLoadingM3u(true);
    setErrorM3u('');
    setM3uInfo(null);

    try {
      const texto = await file.text();

      // Extraer credenciales del M3U
      const urlMatch = texto.match(/https?:\/\/[^\s]+\/live\/([^\s\/]+)\/([^\s\/]+)\//);
      const urlMatch2 = texto.match(/https?:\/\/([^:\/\s]+(?::\d+)?)\/get\.php\?username=([^\&\s]+)&password=([^\&\s]+)/);

      let servidor = '', usuario = '', password = '', apiUrl = '';

      if (urlMatch2) {
        // Formato get.php
        servidor = urlMatch2[1];
        usuario = urlMatch2[2];
        password = urlMatch2[3];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else if (urlMatch) {
        // Formato /live/user/pass/id.ts
        const baseMatch = texto.match(/(https?:\/\/[^\/\s]+)/);
        servidor = baseMatch ? baseMatch[1].replace(/https?:\/\//, '') : '';
        usuario = urlMatch[1];
        password = urlMatch[2];
        apiUrl = `http://${servidor}/player_api.php?username=${usuario}&password=${password}`;
      } else {
        throw new Error('No se encontraron credenciales en el archivo M3U');
      }

      // Contar canales
      const totalCanales = (texto.match(/#EXTINF/g) || []).length;

      // Consultar API del servidor
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

  return (
    <div className="space-y-4">
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

      {/* Analizador de archivo M3U */}
      <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
        <h2 className="text-white font-semibold mb-2">Analizar archivo M3U guardado</h2>
        <p className="text-slate-500 text-sm mb-4">Sube un archivo .m3u para ver MaxConn, conexiones activas y caducidad sin guardarlo.</p>

        <div className="flex gap-3 items-center">
          <input
            ref={fileInputRef}
            type="file"
            accept=".m3u,.m3u8"
            className="hidden"
            onChange={handleM3uFile}
          />
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

            <div className="flex flex-wrap gap-2 mt-2">
              <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                <Tv2 className="size-3" /> {m3uInfo.total_canales} canales
              </span>
              <span className={`flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full ${m3uInfo.activas > 0 ? 'bg-orange-500/20 text-orange-300' : 'bg-green-500/20 text-green-300'}`}>
                <Wifi className="size-3" /> {m3uInfo.activas}/{m3uInfo.max_conn} conexiones
              </span>
              {m3uInfo.ping > 0 && (
                <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                  <Zap className="size-3" /> {m3uInfo.ping}ms
                </span>
              )}
              {m3uInfo.caducidad && (
                <span className="flex items-center gap-1.5 text-slate-300 text-xs bg-white/10 px-2.5 py-1 rounded-full">
                  <Calendar className="size-3" /> {m3uInfo.caducidad === 'Unlimited' ? 'Unlimited' : `Caduca: ${m3uInfo.caducidad}`}
                </span>
              )}
              {m3uInfo.status && (
                <span className="text-xs px-2.5 py-1 rounded-full bg-white/10 text-slate-300">
                  {m3uInfo.status}
                </span>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
