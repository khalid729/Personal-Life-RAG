export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";
export const API_KEY = import.meta.env.VITE_API_KEY || "";
export const ADMIN_KEY = import.meta.env.VITE_ADMIN_KEY || "";

export const apiClient = async (path: string, options: RequestInit = {}) => {
  const isAdmin = path.startsWith("/admin");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-API-Key": localStorage.getItem("api_key") || API_KEY,
    ...(isAdmin ? { "X-Admin-Key": localStorage.getItem("admin_key") || ADMIN_KEY } : {}),
    ...(options.headers as Record<string, string> || {}),
  };

  const res = await fetch(`${localStorage.getItem("api_base_url") || API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 403) {
    throw new Error("403: Configure API Key in Settings");
  }
  if (res.status === 404) {
    throw new Error("404: Not Found");
  }
  if (res.status >= 500) {
    const err = await res.json().catch(() => ({ detail: "Server Error" }));
    throw new Error(`500: ${err.detail || "Server Error"}`);
  }
  return res;
};
