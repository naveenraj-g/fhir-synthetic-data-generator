"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  query,
  type ComponentInfo,
  type ConnectorHealth,
  type BundleIndex,
  type ConnectorInfo,
  type GenerationRequest,
  type GenerationResult,
  type JobResponse,
  type PaginatedJobs,
  type Places,
  type PresetInfo,
  type PreviewResponse,
  type SpecialtyDef,
  type TermSearch,
} from "./client";

const HOUR = 60 * 60 * 1000;

/** Catalog data changes only when the backend config is edited, so it can be cached for a long time. */
const catalog = { staleTime: HOUR, gcTime: 2 * HOUR } as const;

export const usePresets = () =>
  useQuery({ queryKey: ["presets"], queryFn: () => api<PresetInfo[]>("/presets"), ...catalog });
export const useSlicers = () =>
  useQuery({ queryKey: ["slicers"], queryFn: () => api<ComponentInfo[]>("/slicers"), ...catalog });
export const useSinks = () =>
  useQuery({ queryKey: ["sinks"], queryFn: () => api<ComponentInfo[]>("/sinks"), ...catalog });
export const useConnectors = () =>
  useQuery({ queryKey: ["connectors"], queryFn: () => api<ConnectorInfo[]>("/connectors"), ...catalog });
export const useSpecialties = () =>
  useQuery({
    queryKey: ["specialties"],
    queryFn: () => api<Record<string, SpecialtyDef>>("/specialties"),
    ...catalog,
  });
export const useResourceGroups = () =>
  useQuery({
    queryKey: ["resource-groups"],
    queryFn: () => api<Record<string, string[]>>("/resource-groups"),
    ...catalog,
  });

/** Not cached for long: this is the "is Docker/the image there right now?" check. */
export const useConnectorHealth = (name: string | undefined) =>
  useQuery({
    queryKey: ["connector-health", name],
    queryFn: () => api<ConnectorHealth>(`/connectors/${name}/health`),
    enabled: !!name,
    staleTime: 30_000,
    retry: false,
  });

export const useTerms = (connector: string | undefined, q: string, kind?: string, limit = 25) =>
  useQuery({
    queryKey: ["terms", connector, q, kind, limit],
    queryFn: () => api<TermSearch>(`/connectors/${connector}/terms${query({ q, kind, limit })}`),
    enabled: !!connector,
    staleTime: HOUR,
    placeholderData: keepPreviousData,
    retry: false,
  });

/** The states Synthea can generate in, or (given a state) that state's cities: the only values it accepts. */
export const usePlaces = (connector: string | undefined, state?: string) =>
  useQuery({
    queryKey: ["places", connector, state ?? null],
    queryFn: () => api<Places>(`/connectors/${connector}/places${query({ state })}`),
    enabled: !!connector,
    staleTime: Infinity, // fixed by the Synthea version
    retry: false,
  });

/** The bundles of a finished job (patient name + counts), read from its stored files. 410 once they expire. */
export const useBundleIndex = (jobId: string) =>
  useQuery({
    queryKey: ["bundles", jobId],
    queryFn: () => api<BundleIndex>(`/generations/${jobId}/bundles`),
    staleTime: Infinity,
    retry: false,
  });

/** One whole FHIR bundle of a job, for the flow graph. */
export const useBundle = (jobId: string, index: number) =>
  useQuery({
    queryKey: ["bundle", jobId, index],
    queryFn: () => api<{ resourceType: "Bundle"; entry?: { fullUrl?: string; resource?: import("@/lib/fhir-graph").Resource }[] }>(`/generations/${jobId}/bundles/${index}`),
    staleTime: Infinity,
    retry: false,
  });

/** Jobs poll while anything is still running, then stop. */
const isActive = (s: string | undefined) => s === "queued" || s === "running";

export const useJob = (id: string) =>
  useQuery({
    queryKey: ["job", id],
    queryFn: () => api<JobResponse>(`/generations/${id}`),
    refetchInterval: (q) => (isActive(q.state.data?.status) ? 1500 : false),
    // A user starts a job and switches tabs: it must still be up to date when they come back (by default polling
    // pauses in background tabs, and the app turns off refetch-on-focus).
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

export const useJobs = (status: string | undefined, limit = 20, offset = 0) =>
  useQuery({
    queryKey: ["jobs", status, limit, offset],
    queryFn: () => api<PaginatedJobs>(`/generations/${query({ status, limit, offset })}`),
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.data.some((j) => isActive(j.status)) ? 2000 : 15_000),
    refetchIntervalInBackground: true,
    refetchOnWindowFocus: true,
  });

export const usePreview = (request: GenerationRequest | null) =>
  useQuery({
    queryKey: ["preview", request],
    queryFn: () =>
      api<PreviewResponse>("/generations/preview", { method: "POST", body: JSON.stringify(request) }),
    enabled: request !== null,
    retry: false,
    staleTime: 60_000,
    placeholderData: keepPreviousData,
  });

export function useCreateGeneration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (request: GenerationRequest) =>
      api<GenerationResult>("/generations/", { method: "POST", body: JSON.stringify(request) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

export function useDeleteJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api<void>(`/generations/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

/** Backend reachability + DB state, from the unversioned /health/ready endpoint. */
export const useBackendStatus = () =>
  useQuery({
    queryKey: ["backend-status"],
    queryFn: async () => {
      const res = await fetch("/backend/health/ready");
      const body = (await res.json()) as { status: string; checks: Record<string, string> };
      return { ok: res.ok, ...body };
    },
    refetchInterval: 30_000,
    retry: false,
  });
