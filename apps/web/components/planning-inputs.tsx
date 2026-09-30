"use client";

import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import type { PlanningPlace, TravelMode, UserStop } from "@truth-of-fun/api-client";

export type StopDraft = { id: number; kind: UserStop["kind"]; title: string; place: string; start: string; end: string; lat: string; lng: string };
export type OriginDraft = { name: string; lat: string; lng: string };

export function placeInput(draft: OriginDraft): PlanningPlace | undefined {
  if (!draft.name.trim() && !draft.lat && !draft.lng) return undefined;
  return { name: draft.name.trim() || undefined,
    lat: draft.lat ? Number(draft.lat) : undefined,
    lng: draft.lng ? Number(draft.lng) : undefined };
}

export function stopInputs(drafts: StopDraft[]): UserStop[] {
  return drafts.map((stop) => ({ kind: stop.kind, title: stop.title,
    place: placeInput({ name: stop.place, lat: stop.lat, lng: stop.lng }) ?? {},
    start_at: new Date(stop.start).toISOString(),
    end_at: stop.end ? new Date(stop.end).toISOString() : null }));
}

export function PlanningInputs({ origin, setOrigin, mode, setMode, stops, setStops, disabled }: {
  origin: OriginDraft; setOrigin: (value: OriginDraft) => void;
  mode: TravelMode; setMode: (value: TravelMode) => void;
  stops: StopDraft[]; setStops: (value: StopDraft[]) => void; disabled: boolean;
}) {
  const update = (index: number, patch: Partial<StopDraft>) => setStops(stops.map((stop, i) => i === index ? { ...stop, ...patch } : stop));
  return <fieldset disabled={disabled} className="space-y-4 rounded-ui border border-slate-800 p-4">
    <legend className="px-2 text-sm font-semibold">Starting point and your stops</legend>
    <Input label="Starting point (optional)" value={origin.name} maxLength={120} onChange={e => setOrigin({ ...origin, name: e.target.value })} />
    <p className="text-xs text-slate-400">Used for directions. Add coordinates to influence which event is nearest.</p>
    <div className="grid grid-cols-2 gap-3">
      <Input label="Origin latitude (optional)" type="number" step="any" min={-90} max={90} value={origin.lat} onChange={e => setOrigin({ ...origin, lat: e.target.value })} />
      <Input label="Origin longitude (optional)" type="number" step="any" min={-180} max={180} value={origin.lng} onChange={e => setOrigin({ ...origin, lng: e.target.value })} />
    </div>
    <Select label="Travel mode" value={mode} onChange={e => setMode(e.target.value as TravelMode)}>
      <option value="driving">Driving</option><option value="walking">Walking</option><option value="bicycling">Cycling</option><option value="transit">Transit</option>
    </Select>
    <p className="text-xs text-slate-400">Travel allowances are approximate; check Maps for traffic and transit times.</p>
    {stops.map((stop, index) => <fieldset key={stop.id} className="space-y-3 border-t border-slate-800 pt-3">
      <legend className="text-sm">Your stop {index + 1}</legend>
      <Select label={`Stop ${index + 1} kind`} value={stop.kind} onChange={e => update(index, { kind: e.target.value as UserStop["kind"] })}>
        <option value="meeting">Meeting point</option><option value="walk">Walk</option><option value="activity">Activity</option>
      </Select>
      <Input label={`Stop ${index + 1} title`} required maxLength={160} value={stop.title} onChange={e => update(index, { title: e.target.value })} />
      <Input label={`Stop ${index + 1} place`} maxLength={120} value={stop.place} onChange={e => update(index, { place: e.target.value })} />
      <Input label={`Stop ${index + 1} start (your device time zone)`} required type="datetime-local" value={stop.start} onChange={e => update(index, { start: e.target.value })} />
      <Input label={`Stop ${index + 1} end (optional, your device time zone)`} type="datetime-local" value={stop.end} onChange={e => update(index, { end: e.target.value })} />
      <div className="grid grid-cols-2 gap-3">
        <Input label={`Stop ${index + 1} latitude (optional)`} type="number" step="any" min={-90} max={90} value={stop.lat} onChange={e => update(index, { lat: e.target.value })} />
        <Input label={`Stop ${index + 1} longitude (optional)`} type="number" step="any" min={-180} max={180} value={stop.lng} onChange={e => update(index, { lng: e.target.value })} />
      </div>
      <Button type="button" onClick={() => setStops(stops.filter((_, i) => i !== index))}>Remove stop {index + 1}</Button>
    </fieldset>)}
    <Button type="button" disabled={stops.length >= 10} onClick={() => setStops([...stops, { id: Math.max(0, ...stops.map(s => s.id)) + 1, kind: "meeting", title: "", place: "", start: "", end: "", lat: "", lng: "" }])}>Add your own stop</Button>
    <p className="text-xs text-slate-400">Use plain text for your stops. Shared plans label them “Added by the planner”; places and coordinates are your statements.</p>
  </fieldset>;
}
