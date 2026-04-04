import { useState } from 'react';
import { AnalyzerForm } from './components/AnalyzerForm';
import { ResultsView } from './components/ResultsView';
import { SavedLists } from './components/SavedLists';
import { ScannedUrls } from './components/ScannedUrls';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs';
import { Tv2 } from 'lucide-react';

export interface CheckResult {
  disponible: boolean;
  ping: number;
  total: number;
  clave: string;
  url: string;
}

export interface Canal {
  nombre: string;
  url: string;
  extinf: string;
}

export interface FilterResult {
  total_filtrados: number;
  filtro: string;
  canales: Canal[];
}

export interface SavedList {
  nombre: string;
  url: string;
  filtro: string;
  fecha: string;
  total_canales: number;
  max_conn: number;
  caducidad: string;
  observaciones: string;
  ping: number;
  archivo: string;
}

export interface UrlEntry {
  url: string;
  portal: string;
  caducidad: string;
  max_conn: number;
  observaciones: string;
  ping: number;
  fecha_scan: string;
}

export interface BusquedaResultado {
  url: string;
  entrada: UrlEntry;
  encontrados: number;
  clave: string;
  canales: Canal[];
}

export default function App() {
  const [checkResult, setCheckResult] = useState<CheckResult | null>(null);
  const [filterResult, setFilterResult] = useState<FilterResult | null>(null);
  const [activeTab, setActiveTab] = useState('scanned');

  const handleSaveComplete = () => {
    setCheckResult(null);
    setFilterResult(null);
    setActiveTab('saved');
  };

  return (
    <div className="min-h-screen bg-[#0d1117] text-white">
      <header className="border-b border-white/10 bg-[#0d1117]/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3">
          <div className="bg-blue-600 p-2 rounded-lg">
            <Tv2 className="size-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tight">IPTV Panel</h1>
            <p className="text-xs text-slate-500">Analizador de listas M3U</p>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="mb-8">
            <TabsTrigger value="analyzer">Analizar</TabsTrigger>
            <TabsTrigger value="scanned">URLs escaneadas</TabsTrigger>
            <TabsTrigger value="saved">Listas guardadas</TabsTrigger>
          </TabsList>

          <TabsContent value="analyzer" className="space-y-6">
            <AnalyzerForm
              onCheckResult={(r) => { setCheckResult(r); setFilterResult(null); }}
            />
            {checkResult && (
              <ResultsView
                checkResult={checkResult}
                filterResult={filterResult}
                onFilterResult={setFilterResult}
                onSaveComplete={handleSaveComplete}
              />
            )}
          </TabsContent>

          <TabsContent value="scanned">
            <ScannedUrls onSaveComplete={() => setActiveTab('saved')} />
          </TabsContent>

          <TabsContent value="saved">
            <SavedLists />
          </TabsContent>
        </Tabs>
      </main>
    </div>
  );
}
