// Тонкий клиент к REST API. Типы сгенерированы из OpenAPI (npm run gen:api -> schema.d.ts).
import type { components } from "./schema";

type S = components["schemas"];
export type ExplainRecord = S["ExplainRecord"];
export type FieldExplain = S["FieldExplain"];
export type StepTrace = S["StepTraceOut"];
export type SessionInfo = S["SessionInfo"];
export type SessionBrief = S["SessionBrief"];
export type SessionCreated = S["SessionCreated"];
export type RecordItem = S["RecordItem"];
export type RecordList = S["RecordList"];
export type Health = S["HealthOut"];
export type AppConfig = S["ConfigOut"];

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

export type SortKey = "idx" | "confidence" | "raw" | "added";
export type SortDir = "asc" | "desc";

/** Фильтры и порядок списка записей: одинаковы для страницы и для поиска места записи. */
export interface ListParams {
  uncertain?: boolean;
  reviewed?: boolean;
  edited?: boolean;
  q?: string;
  sort?: SortKey;
  dir?: SortDir;
  /** столбец гистограммы сводки (0..9): уверенность в [b/10, (b+1)/10) */
  bucket?: number | null;
  /** отложенные оператором: true только они, false без них */
  skipped?: boolean;
  /** записи без raw_address: true только они, false без них */
  noAddress?: boolean;
  /** порог неуверенности из настроек вместо сохранённого в сессии */
  threshold?: number;
}

/** Изменение записи: поля (null = очистить) и статус проверки. */
export interface RecordChange {
  fields?: Partial<Record<FieldName, string | null>>;
  /** true подтвердить, false снять подтверждение */
  reviewed?: boolean;
  /** true отложить, false вернуть в очередь */
  skipped?: boolean;
}

/** Поля, которые можно выбрать в экспорте (id и raw_address выгружаются всегда). */
export const EXPORT_FIELDS = [...FIELD_NAMES, "confidence"] as const;
export type ExportField = (typeof EXPORT_FIELDS)[number];

export interface ExportOptions {
  /** фильтры текущего списка; без них весь пакет */
  params?: ListParams;
  /** null или все поля: параметр не передаётся, ответ в полном формате жюри */
  fields?: ExportField[] | null;
  format?: "json" | "csv";
  sources?: boolean;
}

/** status 0: сеть или сервер недоступны; текст сервера (detail) только вторичен, UI переводит по статусу. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Событие «нужен ключ доступа»: любой 401 от API, форму входа показывает AuthGate. */
export const AUTH_EVENT = "jana:auth-required";

function authRequired(status: number): void {
  if (status === 401) window.dispatchEvent(new Event(AUTH_EVENT));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (e) {
    throw new ApiError(0, e instanceof Error ? e.message : String(e));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* тело не JSON */
    }
    // вход по ключу (POST /auth) сам показывает ошибку в форме: снова открывать её не нужно
    if (!path.startsWith("/api/v1/auth")) authRequired(res.status);
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

function listQuery(params: ListParams): URLSearchParams {
  const qs = new URLSearchParams();
  if (params.uncertain) qs.set("uncertain", "true");
  if (params.reviewed !== undefined) qs.set("reviewed", String(params.reviewed));
  if (params.edited !== undefined) qs.set("edited", String(params.edited));
  if (params.q) qs.set("q", params.q);
  if (params.sort && params.sort !== "idx") qs.set("sort", params.sort);
  if (params.dir && params.dir !== "asc") qs.set("dir", params.dir);
  if (params.bucket != null) qs.set("bucket", String(params.bucket));
  if (params.skipped !== undefined) qs.set("skipped", String(params.skipped));
  if (params.noAddress !== undefined) qs.set("no_address", String(params.noAddress));
  if (params.threshold !== undefined) qs.set("threshold", String(params.threshold));
  return qs;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  /** Вход в UI по ключу: сервер ставит cookie HttpOnly, ключ в браузере не хранится. */
  login: (key: string) =>
    request<{ required: boolean; ok: boolean }>("/api/v1/auth", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  config: () => request<AppConfig>("/api/v1/config"),
  parseOne: (raw_address: string) =>
    request<ExplainRecord>("/api/v1/parse?explain=true", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ raw_address }),
    }),
  sessions: () => request<SessionBrief[]>("/api/v1/sessions"),
  session: (id: string, threshold?: number) =>
    request<SessionInfo>(`/api/v1/sessions/${id}${threshold !== undefined ? `?threshold=${threshold}` : ""}`),
  /** Страница списка: offset/limit по серверу, порядок и фильтры тоже на сервере. */
  records: (id: string, params: ListParams, offset: number, limit: number) => {
    const qs = listQuery(params);
    qs.set("offset", String(offset));
    qs.set("limit", String(limit));
    return request<RecordList>(`/api/v1/sessions/${id}/records?${qs.toString()}`);
  },
  position: (id: string, idx: number, params: ListParams) => {
    const qs = listQuery(params);
    qs.set("idx", String(idx));
    return request<S["RecordPosition"]>(`/api/v1/sessions/${id}/records/position?${qs.toString()}`);
  },
  record: (id: string, idx: number) => request<RecordItem>(`/api/v1/sessions/${id}/records/${idx}`),
  patch: (id: string, idx: number, change: RecordChange) =>
    request<RecordItem>(`/api/v1/sessions/${id}/records/${idx}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        fields: change.fields ?? {},
        reviewed: change.reviewed,
        skipped: change.skipped,
      }),
    }),
  deleteSession: (id: string) =>
    request<{ deleted: boolean }>(`/api/v1/sessions/${id}`, { method: "DELETE" }),
  /** Без опций: весь пакет как ответ батча. С опциями: фильтры и порядок списка, выбранные поля, формат. */
  exportUrl: (id: string, opts?: ExportOptions) => {
    const qs = opts?.params ? listQuery(opts.params) : new URLSearchParams();
    if (opts?.fields) qs.set("fields", opts.fields.join(","));
    if (opts?.format && opts.format !== "json") qs.set("format", opts.format);
    if (opts?.sources) qs.set("sources", "true");
    const s = qs.toString();
    return `/api/v1/sessions/${id}/export${s ? `?${s}` : ""}`;
  },
  upload: (file: File, onProgress?: (p: number) => void) =>
    new Promise<SessionCreated>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const form = new FormData();
      form.append("file", file);
      xhr.open("POST", `/api/v1/sessions?name=${encodeURIComponent(file.name)}`);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as SessionCreated);
          } catch {
            reject(new ApiError(xhr.status, "bad response"));
          }
          return;
        }
        let msg = xhr.statusText;
        try {
          msg = (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? msg;
        } catch {
          /* не JSON */
        }
        authRequired(xhr.status);
        reject(new ApiError(xhr.status, String(msg)));
      };
      xhr.onerror = () => reject(new ApiError(0, "network error"));
      xhr.send(form);
    }),
};
