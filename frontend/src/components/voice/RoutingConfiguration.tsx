"use client";

import { useEffect, useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";

export type VoiceRoute = {
  routeId: string; department: string; language: string; destination: string;
  timezone: string; startHour: number; endHour: number; ringSeconds: number; priority: number;
};

const EMPTY: VoiceRoute = { routeId: "", department: "support", language: "*", destination: "", timezone: "America/Los_Angeles", startHour: 9, endHour: 17, ringSeconds: 20, priority: 100 };

export default function RoutingConfiguration({ initialRoutes = [], onSave }: { initialRoutes?: VoiceRoute[]; onSave?: (routes: VoiceRoute[]) => void | Promise<void> }) {
  const [routes, setRoutes] = useState(initialRoutes);
  const [draft, setDraft] = useState(EMPTY);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (initialRoutes.length || onSave) return;
    void fetch("/api/voice/routes", { credentials: "same-origin", cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error("load failed");
        const body = await response.json() as { routes?: Array<Record<string, unknown>> };
        setRoutes((body.routes ?? []).map(fromWire));
      }).catch(() => setError("No pudimos cargar las rutas de voz."));
  }, [initialRoutes, onSave]);
  const persist = async (next: VoiceRoute[]) => {
    if (onSave) return onSave(next);
    const csrf = readStoredCsrfToken();
    if (!csrf) throw new Error("secure session required");
    const response = await fetch("/api/voice/routes", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ routes: next.map(toWire) }) });
    if (!response.ok) throw new Error("save failed");
  };
  const add = () => {
    if (!draft.routeId.trim() || !/^\+[1-9]\d{7,14}$/.test(draft.destination)) return;
    setRoutes(current => [...current.filter(route => route.routeId !== draft.routeId), draft]);
    setDraft(EMPTY); setSaved(false);
  };
  return <main className="w-full p-8 text-[var(--ag-text)]">
    <p className="text-xs font-semibold uppercase tracking-wider text-violet-400">Twilio Voice</p>
    <h1 className="mt-1 text-2xl font-semibold">Rutas de transferencia</h1>
    <p className="mt-2 max-w-2xl text-sm text-[var(--ag-text-secondary)]">Define a quién llamar por departamento, idioma y horario. El orden es determinista y cada intento respeta su límite de timbrado.</p>
    <section className="mt-6 rounded-xl border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-5">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="ID de ruta" value={draft.routeId} onChange={value => setDraft({...draft, routeId: value})} />
        <Field label="Departamento" value={draft.department} onChange={value => setDraft({...draft, department: value})} />
        <Field label="Idioma (* = cualquiera)" value={draft.language} onChange={value => setDraft({...draft, language: value})} />
        <Field label="Teléfono E.164" value={draft.destination} onChange={value => setDraft({...draft, destination: value})} placeholder="+15551234567" />
        <Field label="Zona horaria" value={draft.timezone} onChange={value => setDraft({...draft, timezone: value})} />
        <Field label="Prioridad" type="number" value={String(draft.priority)} onChange={value => setDraft({...draft, priority: Number(value)})} />
      </div>
      <button type="button" onClick={add} className="mt-4 rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white">Agregar ruta</button>
    </section>
    <div className="mt-5 space-y-2">{routes.map(route => <div key={route.routeId} className="flex items-center justify-between rounded-lg border border-[var(--ag-card-border)] p-4 text-sm">
      <span><strong>{route.department}</strong> · {route.language} · {route.destination} · {route.timezone} {route.startHour}:00–{route.endHour}:00</span>
      <button type="button" onClick={() => setRoutes(current => current.filter(item => item.routeId !== route.routeId))} className="text-red-300">Eliminar</button>
    </div>)}</div>
    <button type="button" onClick={async () => { try { await persist(routes); setSaved(true); setError(""); } catch { setSaved(false); setError("No pudimos guardar la configuración."); } }} className="mt-5 rounded-lg border border-violet-500 px-4 py-2 text-sm">Guardar configuración</button>
    {saved ? <p role="status" className="mt-2 text-sm text-emerald-400">Configuración guardada.</p> : null}
    {error ? <p role="alert" className="mt-2 text-xs text-red-300">{error}</p> : null}
  </main>;
}

function toWire(route: VoiceRoute) {
  return { route_id: route.routeId, department: route.department, language: route.language,
    destination: route.destination, timezone: route.timezone, start_hour: route.startHour,
    end_hour: route.endHour, ring_seconds: route.ringSeconds, total_budget_seconds: 90, priority: route.priority };
}

function fromWire(route: Record<string, unknown>): VoiceRoute {
  return { routeId: String(route.route_id), department: String(route.department), language: String(route.language),
    destination: String(route.destination), timezone: String(route.timezone), startHour: Number(route.start_hour),
    endHour: Number(route.end_hour), ringSeconds: Number(route.ring_seconds), priority: Number(route.priority) };
}

function Field({ label, value, onChange, placeholder, type = "text" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; type?: string }) {
  return <label className="text-xs text-[var(--ag-text-secondary)]">{label}<input type={type} value={value} placeholder={placeholder} onChange={event => onChange(event.target.value)} className="mt-1 w-full rounded-lg border border-[var(--ag-card-border)] bg-transparent px-3 py-2 text-[var(--ag-text)]" /></label>;
}
