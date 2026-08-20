import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Tag,
  Users,
  Megaphone,
  CalendarDays,
  BarChart3,
  TrendingUp,
  Upload,
  Sun,
  Moon,
  Monitor,
  ChevronLeft,
  PieChart,
  LineChart,
  Download,
  ShieldCheck,
} from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { useState } from "react";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/brands", icon: Tag, label: "Brands" },
  { to: "/hcps", icon: Users, label: "HCPs" },
  { to: "/campaigns", icon: Megaphone, label: "Campaigns" },
  { to: "/events", icon: CalendarDays, label: "Events" },
  { to: "/import", icon: Upload, label: "Import" },
  { to: "/analytics/dashboard", icon: TrendingUp, label: "ROI Analytics" },
  { to: "/analytics", icon: BarChart3, label: "Analytics" },
  { to: "/roi", icon: PieChart, label: "ROI Results" },
  { to: "/forecasts", icon: LineChart, label: "Forecasts" },
  { to: "/exports", icon: Download, label: "Exports" },
  { to: "/data-steward", icon: ShieldCheck, label: "Data Steward" },
];

export function Sidebar() {
  const { theme, cycle } = useTheme();
  const [collapsed, setCollapsed] = useState(false);

  const themeIcon =
    theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <aside
      className={`flex flex-col border-r transition-all duration-200 ${collapsed ? "w-16" : "w-56"}`}
      style={{
        backgroundColor: "var(--color-bg-sidebar)",
        borderColor: "var(--color-border-default)",
      }}
    >
      {/* Logo */}
      <div
        className="flex items-center gap-2 px-4 h-14 border-b"
        style={{ borderColor: "var(--color-border-default)" }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
          style={{
            backgroundColor: "var(--color-accent)",
          }}
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            {/* Chart bars */}
            <rect x="2" y="12" width="3" height="6" rx="0.5" fill="var(--color-text-inverse)" opacity="0.7" />
            <rect x="6.5" y="8" width="3" height="10" rx="0.5" fill="var(--color-text-inverse)" opacity="0.85" />
            <rect x="11" y="5" width="3" height="13" rx="0.5" fill="var(--color-text-inverse)" />
            {/* Pulse/trend line */}
            <polyline
              points="1,10 5,9 8,6 12,3 16,5 19,2"
              stroke="var(--color-text-inverse)"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
            {/* Medical cross */}
            <rect x="15" y="10" width="4" height="1.5" rx="0.3" fill="var(--color-text-inverse)" />
            <rect x="16.25" y="8.75" width="1.5" height="4" rx="0.3" fill="var(--color-text-inverse)" />
          </svg>
        </div>
        {!collapsed && (
          <span className="font-semibold text-sm whitespace-nowrap">
            SPRIP
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 py-2 px-2 space-y-0.5 overflow-y-auto">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                isActive ? "active-nav" : "inactive-nav"
              }`
            }
            style={({ isActive }) => ({
              backgroundColor: isActive
                ? "var(--color-accent-soft)"
                : "transparent",
              color: isActive
                ? "var(--color-accent)"
                : "var(--color-text-secondary)",
            })}
          >
            <Icon size={18} className="shrink-0" />
            {!collapsed && label}
          </NavLink>
        ))}
      </nav>

      {/* Bottom controls */}
      <div
        className="p-2 border-t space-y-1"
        style={{ borderColor: "var(--color-border-default)" }}
      >
        <button
          onClick={cycle}
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full transition-colors hover:opacity-80"
          style={{ color: "var(--color-text-secondary)" }}
          title={`Theme: ${theme}`}
        >
          {(() => {
            const ThIcon = themeIcon;
            return <ThIcon size={18} className="shrink-0" />;
          })()}
          {!collapsed && (
            <span className="capitalize">{theme}</span>
          )}
        </button>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm w-full transition-colors hover:opacity-80"
          style={{ color: "var(--color-text-secondary)" }}
        >
          <ChevronLeft
            size={18}
            className={`shrink-0 transition-transform ${collapsed ? "rotate-180" : ""}`}
          />
          {!collapsed && "Collapse"}
        </button>
      </div>
    </aside>
  );
}
