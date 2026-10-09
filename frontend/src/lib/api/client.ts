import type { components } from "./schema";

/** Types generated from the backend's OpenAPI document (`pnpm gen:api`). */
export type Schemas = components["schemas"];
export type GenerationRequest = Schemas["GenerationRequest"];
export type ResolvedSpec = Schemas["ResolvedSpec"];
export type PreviewResponse = Schemas["PreviewResponse"];
export type JobResponse = Schemas["JobResponse"];
export type GenerationResult = Schemas["GenerationResultResponse"];
export type PaginatedJobs = Schemas["PaginatedJobResponse"];
export type PresetInfo = Schemas["PresetInfo"];
export type ComponentInfo = Schemas["ComponentInfo"];
export type ConnectorInfo = Schemas["ConnectorInfo"];
export type ConnectorHealth = Schemas["ConnectorHealthResponse"];
export type TermInfo = Schemas["TermInfo"];
export type TermSearch = Schemas["TermSearchResponse"];
export type Places = Schemas["PlacesResponse"];
export type BundleIndex = Schemas["BundleIndexResponse"];
export type JobStatus =JobResponse["status"];
export type SpecialtyDef = {
  description?: string;
  conditions?: string[];
  procedures?: string[];
  medications?: string[];
  match?: "all" | "any";
  age_range?: [number, number];
};

/**
 * Requests go to `/backend/...`, which next.config.ts rewrites to the FastAPI server. That keeps the browser
 * on one origin (no CORS) and the backend address out of the client bundle.
 */
export const API_BASE = "/backend";
const V1 = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
    readonly details: unknown[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    // The backend's envelope: {"error": {"code", "message", "details"}}
    if (body?.error) {
      return new ApiError(body.error.message, res.status, body.error.code, body.error.details ?? []);
    }
    // FastAPI/pydantic default shape, in case a route bypasses the envelope.
    if (typeof body?.detail === "string") return new ApiError(body.detail, res.status, "HTTP_ERROR");
  } catch {
    /* not JSON */
  }
  return new ApiError(`Request failed (${res.status})`, res.status, "HTTP_ERROR");
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${V1}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      "Cannot reach the backend. Is the API running (just dev) and BACKEND_URL correct?",
      0,
      "NETWORK_ERROR",
    );
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const downloadUrl = (path: string) => `${API_BASE}${path}`;

export function query(params: Record<string, string | number | undefined | null>) {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  const s = usp.toString();
  return s ? `?${s}` : "";
}
