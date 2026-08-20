export interface ApiError {
  code: string;
  message: string;
  remediation?: string;
}

export interface ApiErrorEnvelope {
  error: ApiError;
}

export interface PaginatedResponse<T> {
  items: T[];
  nextCursor?: string | null;
  total: number;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TenantSummary {
  id: string;
  name: string;
  code: string;
  status: string;
  role?: string;
}

export interface SessionUser {
  id: string;
  email: string;
  displayName: string;
  isPlatformAdmin: boolean;
  mfaEnrolled: boolean;
}

export interface LoginResponse {
  user: SessionUser;
  mfaRequired: boolean;
  mfaEnrolmentRequired?: boolean;
  mustChangePassword?: boolean;
  tenants: TenantSummary[];
  activeTenantId?: string;
  expiresAt?: string;
}

export interface MeResponse {
  user: SessionUser;
  activeTenant?: TenantSummary;
  memberships: MembershipSummary[];
  permissions: string[];
  roles: string[];
  isVendor: boolean;
  brandScope?: string[];
  vendorId?: string;
  reauthUntil?: string;
}

export interface MembershipSummary {
  tenant: TenantSummary;
  role: string;
  allBrands: boolean;
  brandIds: string[];
  vendorId?: string;
  grantedAt?: string;
}

export interface MfaEnrolResponse {
  secret: string;
  qrCodeUri: string;
}

export interface MfaConfirmResponse {
  codes: string[];
}

export interface User {
  id: string;
  email: string;
  name?: string;
  memberships?: Array<{
    tenantId: string;
    role: string;
  }>;
  [key: string]: unknown;
}

export interface Brand {
  id: string;
  name: string;
  description?: string;
  createdAt?: string;
  [key: string]: unknown;
}

export interface Product {
  id: string;
  name: string;
  brandId?: string;
  [key: string]: unknown;
}

export interface HCP {
  id: string;
  name: string;
  specialty?: string;
  tier?: string;
  email?: string;
  region?: string;
  [key: string]: unknown;
}

export interface Campaign {
  id: string;
  name: string;
  status?: string;
  brandId?: string;
  startDate?: string;
  endDate?: string;
  budget?: number;
  [key: string]: unknown;
}

export interface Event {
  id: string;
  name: string;
  date?: string;
  campaignId?: string;
  status?: string;
  location?: string;
  attendees?: number;
  cost?: number;
  roi?: number;
  [key: string]: unknown;
}

export interface Analysis {
  id: string;
  name?: string;
  status?: string;
  createdAt?: string;
  [key: string]: unknown;
}

export interface FinanceVersion {
  id: string;
  version?: string;
  createdAt?: string;
  [key: string]: unknown;
}
