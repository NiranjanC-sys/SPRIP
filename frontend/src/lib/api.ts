import type {
  ApiErrorEnvelope,
  LoginRequest,
  LoginResponse,
  MeResponse,
  MfaEnrolResponse,
  MfaConfirmResponse,
  Brand,
  Product,
  HCP,
  Campaign,
  Event,
  Analysis,
  FinanceVersion,
  PaginatedResponse,
  DashboardStats,
  RoiTrendResponse,
  EngagementResponse,
  RoiResult,
  ForecastItem,
  ExportStatus,
} from "@/types/api";

class ApiClientError extends Error {
  code: string;
  remediation?: string;

  constructor(code: string, message: string, remediation?: string) {
    super(message);
    this.name = "ApiClientError";
    this.code = code;
    this.remediation = remediation;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    let envelope: ApiErrorEnvelope | undefined;
    try {
      envelope = (await res.json()) as ApiErrorEnvelope;
    } catch {
      // non-JSON error body
    }
    if (envelope?.error) {
      throw new ApiClientError(
        envelope.error.code,
        envelope.error.message,
        envelope.error.remediation
      );
    }
    throw new ApiClientError(
      `HTTP_${res.status}`,
      `Request failed: ${res.statusText}`
    );
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  auth: {
    login: (body: LoginRequest) =>
      request<LoginResponse>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    mfaEnrol: () =>
      request<MfaEnrolResponse>("/api/v1/auth/mfa/enrol", {
        method: "POST",
      }),
    mfaConfirm: (code: string) =>
      request<MfaConfirmResponse>("/api/v1/auth/mfa/enrol/confirm", {
        method: "POST",
        body: JSON.stringify({ code }),
      }),
    mfaVerify: (code: string) =>
      request<LoginResponse>("/api/v1/auth/mfa/verify", {
        method: "POST",
        body: JSON.stringify({ code }),
      }),
    logout: () =>
      request<void>("/api/v1/auth/logout", { method: "POST" }),
    switchTenant: (tenantId: string) =>
      request<LoginResponse>("/api/v1/auth/switch-tenant", {
        method: "POST",
        body: JSON.stringify({ tenantId }),
      }),
  },
  me: () => request<MeResponse>("/api/v1/me"),
  brands: (cursor?: string) =>
    request<PaginatedResponse<Brand>>(
      `/api/v1/brands${cursor ? `?cursor=${cursor}` : ""}`
    ),
  products: (cursor?: string) =>
    request<PaginatedResponse<Product>>(
      `/api/v1/products${cursor ? `?cursor=${cursor}` : ""}`
    ),
  hcps: (cursor?: string) =>
    request<PaginatedResponse<HCP>>(
      `/api/v1/hcps${cursor ? `?cursor=${cursor}` : ""}`
    ),
  campaigns: (cursor?: string) =>
    request<PaginatedResponse<Campaign>>(
      `/api/v1/campaigns${cursor ? `?cursor=${cursor}` : ""}`
    ),
  events: (cursor?: string) =>
    request<PaginatedResponse<Event>>(
      `/api/v1/events${cursor ? `?cursor=${cursor}` : ""}`
    ),
  analyses: (cursor?: string) =>
    request<PaginatedResponse<Analysis>>(
      `/api/v1/analyses${cursor ? `?cursor=${cursor}` : ""}`
    ),
  financeVersions: () =>
    request<PaginatedResponse<FinanceVersion>>("/api/v1/finance/versions"),
  dashboardStats: () => request<DashboardStats>("/api/v1/dashboard/stats"),
  dashboardRoiTrend: () => request<RoiTrendResponse>("/api/v1/dashboard/roi-trend"),
  dashboardEngagement: () => request<EngagementResponse>("/api/v1/dashboard/engagement"),
  hcpDetail: (id: string) => request<any>(`/api/v1/hcps/${id}`),
  eventDetail: (id: string) => request<any>(`/api/v1/events/${id}`),
  campaignDetail: (id: string) => request<any>(`/api/v1/campaigns/${id}`),
  eventCosts: (eventId: string) => request<PaginatedResponse<any>>(`/api/v1/events/${eventId}/costs`),
  impacts: (cursor?: string) => request<PaginatedResponse<any>>(`/api/v1/analyses/impacts${cursor ? `?cursor=${cursor}` : ""}`),
  roiResults: (cursor?: string) =>
    request<PaginatedResponse<RoiResult>>(
      `/api/v1/roi/results${cursor ? `?cursor=${cursor}` : ""}`
    ),
  roiSummary: () => request<any>("/api/v1/roi/summary"),
  forecasts: (cursor?: string) =>
    request<PaginatedResponse<ForecastItem>>(
      `/api/v1/forecasts${cursor ? `?cursor=${cursor}` : ""}`
    ),
  createForecast: (body: { brandId: string; horizonMonths?: number }) =>
    request<any>("/api/v1/forecasts", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createExport: (body: { exportType: string; filters?: Record<string, unknown> }) =>
    request<ExportStatus>("/api/v1/exports", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  exportStatus: (taskId: string) =>
    request<ExportStatus>(`/api/v1/exports/${taskId}/status`),
  createCampaign: (body: Record<string, unknown>) =>
    request<Campaign>("/api/v1/campaigns", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

export { ApiClientError };
