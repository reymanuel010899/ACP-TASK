"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";
import type { ContactBranch } from "@/components/contacts/ContactsTree";
import CampaignAuthorization, { type CampaignPreview } from "./CampaignAuthorization";

type Campaign = {
  campaignId: string;
  name: string;
  body: string;
  purpose: string;
  channel: string;
  sender: string;
  status: string;
  audienceTotal?: number;
  outcomes?: Record<string, number>;
  estimatedSpendMicros: number;
  createdAt: number;
};

type PreviewResponse = {
  campaign_id: string;
  eligible_count: number;
  estimated_spend_micros: number;
  audience: Array<{ contact_id: string; channel: string; masked_destination: string; branch_id: string }>;
  exclusion_reasons: Record<string, number>;
  envelope_hash: string;
};

const STATUS_LABELS: Record<string, string> = {
  audience_previewed: "Pendiente de autorización",
  authorized: "Autorizada",
  running: "Enviando",
  drained: "Completada",
  reconciling: "Verificando entregas",
  blocked_connection: "Conexión bloqueada",
  paused: "Pausada",
  stopped: "Detenida",
  expired: "Expirada",
};

function flattenBranches(branches: ContactBranch[]): ContactBranch[] {
  return branches.flatMap((branch) => [branch, ...flattenBranches(branch.children)]);
}

export default function CampaignsContent() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [branches, setBranches] = useState<ContactBranch[]>([]);
  const [showComposer, setShowComposer] = useState(false);
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [branchId, setBranchId] = useState("");
  const [purpose, setPurpose] = useState("service");
  const [body, setBody] = useState("");
  const branchOptions = useMemo(() => flattenBranches(branches), [branches]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [campaignResponse, branchResponse] = await Promise.all([
        fetch("/api/campaigns", { credentials: "same-origin", cache: "no-store" }),
        fetch("/api/contacts/branches", { credentials: "same-origin", cache: "no-store" }),
      ]);
      const campaignPayload = await campaignResponse.json() as { campaigns?: Campaign[]; error?: string };
      const branchPayload = await branchResponse.json() as { branches?: ContactBranch[]; error?: string };
      if (!campaignResponse.ok) throw new Error(campaignPayload.error ?? "No pudimos cargar las campañas.");
      if (!branchResponse.ok) throw new Error(branchPayload.error ?? "No pudimos cargar las carpetas.");
      setCampaigns(campaignPayload.campaigns ?? []);
      setBranches(branchPayload.branches ?? []);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos cargar campañas.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { queueMicrotask(() => void load()); }, [load]);
  useEffect(() => {
    if (!campaigns.some((campaign) => ["authorized", "running"].includes(campaign.status))) return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [campaigns, load]);

  function closeComposer() {
    if (busy) return;
    setShowComposer(false);
    setPreview(null);
    setError("");
  }

  async function createPreview(event: React.FormEvent) {
    event.preventDefault();
    const csrf = readStoredCsrfToken();
    if (!csrf) return setError("Tu sesión segura debe renovarse.");
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/campaigns/preview", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ name, branchId, purpose, body }),
      });
      const payload = await response.json() as PreviewResponse & { error?: string };
      if (!response.ok) throw new Error(payload.error ?? "No pudimos preparar la campaña.");
      setPreview({
        campaignId: payload.campaign_id,
        eligibleCount: payload.eligible_count,
        estimatedSpendMicros: payload.estimated_spend_micros,
        audience: payload.audience.map((row) => ({
          contactId: row.contact_id, channel: row.channel,
          maskedDestination: row.masked_destination, branchId: row.branch_id,
        })),
        exclusionReasons: payload.exclusion_reasons,
        envelopeHash: payload.envelope_hash,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos preparar la campaña.");
    } finally { setBusy(false); }
  }

  async function authorize(campaignId: string, envelopeHash: string) {
    const csrf = readStoredCsrfToken();
    if (!csrf) return setError("Tu sesión segura debe renovarse.");
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/campaigns/${encodeURIComponent(campaignId)}/authorize`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ envelopeHash }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error ?? "No pudimos lanzar la campaña.");
      setMessage("Campaña autorizada. Los mensajes se están enviando.");
      setShowComposer(false); setPreview(null); setName(""); setBody(""); setBranchId("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No pudimos lanzar la campaña.");
    } finally { setBusy(false); }
  }

  return (
    <main className="box-border flex w-full flex-col gap-[18px] p-[18px_20px_28px]">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[var(--ag-purple)]">Mensajería</p>
          <h1 className="mt-1 text-[24px] font-bold tracking-[-0.02em] text-[var(--ag-text)]">Campañas</h1>
          <p className="mt-1 text-[11px] text-[var(--ag-text-secondary)]">Envía SMS a una audiencia con consentimiento y un presupuesto autorizado.</p>
        </div>
        <button type="button" onClick={() => { setShowComposer(true); setError(""); }} className="rounded-[8px] bg-[#5D20DC] px-[14px] py-[8px] text-[11px] font-semibold text-white shadow-[0_6px_18px_rgba(93,32,220,0.22)] hover:bg-[#6b2ce6] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#8B5CF6]">
          + Nueva campaña
        </button>
      </header>

      {message ? <p role="status" className="rounded-[8px] border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-300">{message}</p> : null}
      {!showComposer && error ? <p role="alert" className="text-[11px] text-red-300">{error}</p> : null}

      <section aria-labelledby="campaign-list-title" className="overflow-hidden rounded-[12px] border border-[var(--ag-card-border)] bg-[var(--ag-card)]">
        <div className="flex items-center justify-between border-b border-[var(--ag-divider)] px-4 py-3">
          <h2 id="campaign-list-title" className="text-[12px] font-semibold text-[var(--ag-text)]">Actividad de campañas</h2>
          <span className="text-[10px] text-[var(--ag-text-muted)]">{campaigns.length} total</span>
        </div>
        {loading ? <p className="p-5 text-[11px] text-[var(--ag-text-muted)]">Cargando campañas…</p> : campaigns.length === 0 ? (
          <div className="px-5 py-12 text-center">
            <div className="mx-auto flex size-10 items-center justify-center rounded-full bg-[var(--ag-chip)] text-[18px] text-[var(--ag-purple)]">◉</div>
            <p className="mt-3 text-[12px] font-semibold text-[var(--ag-text)]">Todavía no hay campañas</p>
            <p className="mt-1 text-[10px] text-[var(--ag-text-muted)]">Crea una campaña para revisar la audiencia antes de enviar.</p>
          </div>
        ) : (
          <div className="divide-y divide-[var(--ag-divider)]">
            {campaigns.map((campaign) => {
              const completed = campaign.outcomes?.completed ?? 0;
              const total = campaign.audienceTotal ?? 0;
              const progress = total ? Math.round((completed / total) * 100) : 0;
              return <article key={campaign.campaignId} className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1.4fr)_110px_120px] md:items-center">
                <div className="min-w-0">
                  <div className="flex items-center gap-2"><h3 className="truncate text-[12px] font-semibold text-[var(--ag-text)]">{campaign.name}</h3><span className="rounded-full bg-[var(--ag-chip)] px-2 py-0.5 text-[9px] text-[var(--ag-text-secondary)]">SMS</span></div>
                  <p className="mt-1 truncate text-[10px] text-[var(--ag-text-muted)]">{campaign.body}</p>
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--ag-divider)]"><div className="h-full rounded-full bg-[#6D28D9] transition-[width]" style={{ width: `${progress}%` }} /></div>
                </div>
                <div><p className="text-[10px] text-[var(--ag-text-muted)]">Audiencia</p><p className="text-[12px] font-semibold text-[var(--ag-text)]">{completed}/{total}</p></div>
                <div className="md:text-right"><span className="inline-flex rounded-full border border-[var(--ag-card-border)] px-2 py-1 text-[9px] font-medium text-[var(--ag-text-secondary)]">{STATUS_LABELS[campaign.status] ?? campaign.status}</span></div>
              </article>;
            })}
          </div>
        )}
      </section>

      {showComposer ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center bg-[rgba(4,3,12,0.74)] p-[18px] backdrop-blur-[3px]" onMouseDown={(event) => { if (event.target === event.currentTarget) closeComposer(); }}>
          <section role="dialog" aria-modal="true" aria-labelledby="campaign-dialog-title" className="flex max-h-[calc(100vh-36px)] w-full max-w-[720px] flex-col overflow-hidden rounded-[14px] border border-[var(--ag-card-border)] bg-[var(--ag-bg)] shadow-[0_30px_100px_rgba(0,0,0,0.58)]">
            <header className="flex items-center justify-between border-b border-[var(--ag-divider)] px-5 py-4"><div><h2 id="campaign-dialog-title" className="text-[15px] font-semibold text-[var(--ag-text)]">Nueva campaña SMS</h2><p className="mt-1 text-[10px] text-[var(--ag-text-muted)]">Primero preparamos una vista previa. Nada se envía sin tu autorización.</p></div><button type="button" disabled={busy} onClick={closeComposer} aria-label="Cerrar" className="size-8 rounded-[7px] text-[18px] text-[var(--ag-text-muted)] hover:bg-white/[0.06]">×</button></header>
            <div className="min-h-0 overflow-y-auto p-5">
              {error ? <p role="alert" className="mb-4 rounded-[8px] border border-red-500/25 bg-red-500/10 px-3 py-2 text-[11px] text-red-300">{error}</p> : null}
              {!preview ? (
                <form onSubmit={createPreview} className="space-y-4">
                  <label className="block text-[11px] font-medium text-[var(--ag-text-secondary)]">Nombre<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="Recordatorio de citas" className="mt-1.5 w-full rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-3 py-2.5 text-[12px] text-[var(--ag-text)] outline-none focus:border-[#7C3AED]" /></label>
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="block text-[11px] font-medium text-[var(--ag-text-secondary)]">Audiencia<select required value={branchId} onChange={(event) => setBranchId(event.target.value)} className="mt-1.5 w-full rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-3 py-2.5 text-[12px] text-[var(--ag-text)]"><option value="">Selecciona una carpeta</option>{branchOptions.map((branch) => <option key={branch.branchId} value={branch.branchId}>{branch.path} · {branch.contactCount}</option>)}</select></label>
                    <label className="block text-[11px] font-medium text-[var(--ag-text-secondary)]">Finalidad<select value={purpose} onChange={(event) => setPurpose(event.target.value)} className="mt-1.5 w-full rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-3 py-2.5 text-[12px] text-[var(--ag-text)]"><option value="service">Servicio</option><option value="transactional">Transaccional</option><option value="utility">Utilidad</option><option value="marketing">Marketing</option><option value="authentication">Autenticación</option></select></label>
                  </div>
                  <label className="block text-[11px] font-medium text-[var(--ag-text-secondary)]">Mensaje<textarea required maxLength={1600} rows={5} value={body} onChange={(event) => setBody(event.target.value)} placeholder="Hola, te recordamos que…" className="mt-1.5 w-full resize-y rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-3 py-2.5 text-[12px] leading-5 text-[var(--ag-text)] outline-none focus:border-[#7C3AED]" /><span className="mt-1 block text-right text-[9px] text-[var(--ag-text-muted)]">{body.length}/1600</span></label>
                  <div className="flex justify-end gap-2 border-t border-[var(--ag-divider)] pt-4"><button type="button" onClick={closeComposer} className="rounded-[8px] border border-[var(--ag-card-border)] px-4 py-2 text-[11px] font-semibold text-[var(--ag-text-secondary)]">Cancelar</button><button type="submit" disabled={busy} className="rounded-[8px] bg-[#5D20DC] px-4 py-2 text-[11px] font-semibold text-white disabled:opacity-50">{busy ? "Preparando…" : "Revisar audiencia"}</button></div>
                </form>
              ) : <CampaignAuthorization preview={preview} busy={busy} onAuthorize={authorize} />}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
