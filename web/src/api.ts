/** Typed calls to the ADlyser API. Every failure becomes an ApiError with a readable message. */
import type {
  AddedBrand,
  Brand,
  DebugReport,
  EndEvent,
  JobStatus,
  LibraryItem,
  NodeEvent,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function failure(res: Response): Promise<ApiError> {
  let message = `${res.status} ${res.statusText}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // not JSON: keep the status line
  }
  return new ApiError(message, res.status);
}

async function request(url: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Cannot reach the server.", 0);
  }
  if (!res.ok) throw await failure(res);
  return res;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getLibrary = async (): Promise<LibraryItem[]> => (await request("/api/library")).json();

/** The finished analysis of a video, or null if it has not been analysed yet. */
export async function getReport(name: string): Promise<DebugReport | null> {
  try {
    return await (await request(`/data/${name}/debug.json`)).json();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** The VMAP manifest text, or null if there is none yet. */
export async function getVmap(name: string): Promise<string | null> {
  try {
    return await (await request(`/data/${name}/vmap.xml`)).text();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/** A frame of the video. `large` is the wider one for hero images. */
export const frameUrl = (name: string, t: number, size: "thumb" | "large" = "thumb"): string =>
  `/api/jobs/${name}/frame?t=${t.toFixed(1)}${size === "large" ? "&size=large" : ""}`;

export async function runJob(name: string): Promise<void> {
  await request(`/api/jobs/${name}/run`, { method: "POST" });
}

export async function getJob(name: string): Promise<{ status: JobStatus; events: NodeEvent[]; error: string }> {
  return (await request(`/api/jobs/${name}`)).json();
}

/**
 * Follow a job's progress. Calls `onNode` for every finished pipeline node (past ones first) and
 * `onEnd` once. Returns a function that stops listening.
 */
export function followJob(
  name: string,
  onNode: (event: NodeEvent) => void,
  onEnd: (event: EndEvent) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${name}/events`);
  let ended = false;
  source.onmessage = (msg: MessageEvent<string>) => {
    const event = JSON.parse(msg.data) as NodeEvent | EndEvent;
    if (event.type === "node") {
      onNode(event);
      return;
    }
    ended = true;
    source.close();
    onEnd(event);
  };
  source.onerror = () => {
    if (ended) return;
    source.close();
    onEnd({ type: "end", status: "error", error: "Lost the connection to the server." });
  };
  return () => {
    ended = true;
    source.close();
  };
}

/** Upload a video (with progress 0..1). Resolves to the new job's name; the analysis starts on the server. */
export function uploadVideo(file: File, onProgress: (fraction: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError("Cannot reach the server.", 0));
    xhr.onload = () => {
      let body: { name?: string; detail?: unknown } = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // keep the empty body
      }
      if (xhr.status === 202 && body.name) resolve(body.name);
      else reject(new ApiError(typeof body.detail === "string" ? body.detail : `Upload failed (${xhr.status})`, xhr.status));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const getAddedBrands = async (): Promise<AddedBrand[]> => (await request("/api/brands/added")).json();

export const previewBrand = async (text: string): Promise<Brand> =>
  (await request("/api/brands/preview", json({ text }))).json();

export const addBrand = async (text: string): Promise<AddedBrand> =>
  (await request("/api/brands", json({ text }))).json();

export async function removeBrand(id: string): Promise<void> {
  await request(`/api/brands/${id}`, { method: "DELETE" });
}
