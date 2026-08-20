import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { ToastProvider } from "@/context/ToastContext";
import { Sidebar } from "@/components/Sidebar";
import { LoginPage } from "@/pages/LoginPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { BrandsPage } from "@/pages/BrandsPage";
import { HCPsPage } from "@/pages/HCPsPage";
import { CampaignsPage } from "@/pages/CampaignsPage";
import { EventsPage } from "@/pages/EventsPage";
import { AnalyticsDashboardPage } from "@/pages/AnalyticsDashboardPage";
import { HCPDetailPage } from "@/pages/HCPDetailPage";
import { EventDetailPage } from "@/pages/EventDetailPage";
import { CampaignDetailPage } from "@/pages/CampaignDetailPage";
import { ImportPage } from "@/pages/ImportPage";
import { DataStewardPage } from "@/pages/DataStewardPage";
import { RoiResultsPage } from "@/pages/RoiResultsPage";
import { ForecastsPage } from "@/pages/ForecastsPage";
import { ExportsPage } from "@/pages/ExportsPage";
import { Loader2, LogOut } from "lucide-react";

function ProtectedLayout() {
  const { user, loading, logout } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2
          size={32}
          className="animate-spin"
          style={{ color: "var(--color-accent)" }}
        />
      </div>
    );
  }

  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <header
          className="h-14 flex items-center justify-between px-6 border-b shrink-0"
          style={{ borderColor: "var(--color-border-default)" }}
        >
          <div className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
            {user.activeTenant?.name ?? "Platform"}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
              {user.user.email}
            </span>
            <button
              onClick={logout}
              className="p-2 rounded-lg transition-colors hover:opacity-80"
              style={{ color: "var(--color-text-tertiary)" }}
              title="Sign out"
            >
              <LogOut size={16} />
            </button>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const isAdmin = user?.roles?.includes("PHARMA_ADMIN") ?? false;
  if (!isAdmin) return <Navigate to="/" replace />;
  return <>{children}</>;
}

function LoginRoute() {
  const { user, loading, needsMfa } = useAuth();
  if (loading) return null;
  if (user && !needsMfa) return <Navigate to="/" replace />;
  return <LoginPage />;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route element={<ProtectedLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="brands" element={<BrandsPage />} />
            <Route path="hcps" element={<HCPsPage />} />
            <Route path="campaigns" element={<CampaignsPage />} />
            <Route path="events" element={<EventsPage />} />
            <Route path="import" element={<ImportPage />} />
            <Route path="data-steward" element={<DataStewardPage />} />
            <Route path="analytics/dashboard" element={<AdminRoute><AnalyticsDashboardPage /></AdminRoute>} />
            <Route path="hcps/:id" element={<HCPDetailPage />} />
            <Route path="events/:id" element={<EventDetailPage />} />
            <Route path="campaigns/:id" element={<CampaignDetailPage />} />
            <Route path="roi" element={<AdminRoute><RoiResultsPage /></AdminRoute>} />
            <Route path="forecasts" element={<AdminRoute><ForecastsPage /></AdminRoute>} />
            <Route path="exports" element={<ExportsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
