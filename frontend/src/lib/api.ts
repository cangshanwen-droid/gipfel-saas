const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api"

interface FetchOptions extends RequestInit {
  token?: string | null
}

export async function apiFetch(path: string, options: FetchOptions = {}) {
  const { token, ...fetchOptions } = options
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`
  }
  const res = await fetch(`${API_BASE}${path}`, { ...fetchOptions, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || err.message || `HTTP ${res.status}`)
  }
  return res.json()
}

// Auth
export async function login(username: string, password: string) {
  return apiFetch("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  })
}

export async function register(username: string, password: string) {
  return apiFetch("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  })
}

// Regions
export async function getRegions(token: string) {
  return apiFetch("/regions", { token })
}

export async function createRegion(token: string, data: any) {
  return apiFetch("/regions", { method: "POST", token, body: JSON.stringify(data) })
}

// Companies
export async function getCompanies(token: string) {
  return apiFetch("/companies", { token })
}

// Contracts
export async function getContracts(token: string, regionId?: number) {
  const query = regionId ? `?region_id=${regionId}` : ""
  return apiFetch(`/contracts${query}`, { token })
}

export async function createContract(token: string, data: any) {
  return apiFetch("/contracts", { method: "POST", token, body: JSON.stringify(data) })
}

export async function getContractTypes(token: string) {
  return apiFetch("/contracts/types/all", { token })
}

export async function summarizeRegion(token: string, regionId: number) {
  return apiFetch(`/contracts/summarize/${regionId}`, { token })
}

// Dashboard
export async function getDashboardSummary(token: string) {
  return apiFetch("/dashboard/summary", { token })
}

export async function getInfraTypes(token: string) {
  return apiFetch("/dashboard/infrastructure-types", { token })
}

// Formula
export async function calculateFormula(token: string, data: any) {
  return apiFetch("/formula/calculate", { method: "POST", token, body: JSON.stringify(data) })
}

export async function getFormulaLogs(token: string, regionId: number) {
  return apiFetch(`/formula/logs/${regionId}`, { token })
}

// Reports
export async function getLandAreaReport(token: string) {
  return apiFetch("/reports/land-area", { token })
}

export async function getLandAreaByRegion(token: string) {
  return apiFetch("/reports/land-area-by-region", { token })
}

// Infra
export async function infraCalculate(token: string, regionId: number) {
  return apiFetch(`/infra/calculate?region_id=${regionId}`, { token })
}

// Accounts
export async function getAccounts(token: string) {
  return apiFetch("/accounts", { token })
}

// Excel
export function getExcelExportUrl(token: string) {
  return `${API_BASE}/excel/export?token=${token}`
}
