import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Tag,
  Users,
  Megaphone,
  CalendarDays,
  BarChart3,
  Sun,
  Moon,
  Monitor,
  ChevronLeft,
} from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { useState } from "react";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/brands", icon: Tag, label: "Brands" },
  { to: "/hcps", icon: Users, label: "HCPs" },
  { to: "/campaigns", icon: Megaphone, label: "Campaigns" },
  { to: "/events", icon: CalendarDays, label: "Events" },
  { to: "/analytics", icon: BarChart3, label: "Analytics" },
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
          className="w-8 h-8 rounded-lg flex items-center justify-center text-sm font-bold shrink-0"
          style={{
            backgroundColor: "var(--color-accent)",
            color: "var(--color-text-inverse)",
          }}
        >
          H
        </div>
        {!collapsed && (
          <span className="font-semibold text-sm whitespace-nowrap">
            HCP Speaker Program
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
