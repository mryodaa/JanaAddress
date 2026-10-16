// Тонкий клиент к REST API. Типы сгенерированы из OpenAPI (npm run gen:api -> schema.d.ts).
import type { components } from "./schema";

type S = components["schemas"];
export type OutputRecord = S["OutputRecord"];
export type ExplainRecord = S["ExplainRecord"];
export type FieldExplain = S["FieldExplain"];
export type StepTrace = S["StepTraceOut"];
export type SessionInfo = S["SessionInfo"];
export type SessionBrief = S["SessionBrief"];
export type RecordItem = S["RecordItem"];
export type RecordList = S["RecordList"];

export const FIELD_NAMES = [
  "province",
  "city",
  "district",
  "living_area",
  "street_type",
  "street_name",
  "house",
  "apartment",
  "entrance",
  "floor",
  "landmark",
] as const;
export type FieldName = (typeof FIELD_NAMES)[number];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* тело не JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{ status: string; reference?: { counts?: Record<string, number> } }>("/api/v1/health"),
  config: () => request<{ uncertain_threshold: number }>("/api/v1/config"),
  parseOne: (raw_address: string) =>
    request<ExplainRecord>("/api/v1/parse?explain=true", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ raw_address }),
    }),
  sessions: () => request<SessionBrief[]>("/api/v1/sessions"),
  session: (id: string) => request<SessionInfo>(`/api/v1/sessions/${id}`),
  records: (id: string, params: { uncertain?: boolean; q?: string }) => {
    const qs = new URLSearchParams();
    if (params.uncertain) qs.set("uncertain", "true");
    if (params.q) qs.set("q", params.q);
    return request<RecordList>(`/api/v1/sessions/${id}/records?${qs.toString()}`);
  },
  record: (id: string, idx: number) => request<RecordItem>(`/api/v1/sessions/${id}/records/${idx}`),
  patch: (id: string, idx: number, fields: Partial<Record<FieldName, string | null>>, reviewed = true) =>
    request<RecordItem>(`/api/v1/sessions/${id}/records/${idx}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ fields, reviewed }),
    }),
  exportUrl: (id: string) => `/api/v1/sessions/${id}/export`,
  upload: (file: File, onProgress?: (p: number) => void) =>
    new Promise<{ id: string; total: number }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);
      xhr.open("POST", `/api/v1/sessions?name=${encodeURIComponent(file.name)}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
        else {
          let msg = xhr.statusText;
          try {
            msg = JSON.parse(xhr.responseText).detail ?? msg;
          } catch {
            /* не JSON */
          }
          reject(new ApiError(xhr.status, String(msg)));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "сервис недоступен"));
      xhr.send(form);
    }),
};
