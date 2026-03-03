import React, { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import {
  Home, MessageSquare, Bell, CheckSquare, FolderOpen, DollarSign,
  Package, BookOpen, MapPin, Zap, Network, Search, Upload,
  Sunrise, Users, Database, Settings, ChevronLeft, ChevronRight,
  Menu, X, Brain, House
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";

const navSections = [
  {
    label: "الرئيسية",
    items: [
      { to: "/", icon: Home, label: "لوحة التحكم" },
      { to: "/chat", icon: MessageSquare, label: "المحادثة" },
    ],
  },
  {
    label: "البيانات",
    items: [
      { to: "/reminders", icon: Bell, label: "التذكيرات" },
      { to: "/tasks", icon: CheckSquare, label: "المهام" },
      { to: "/projects", icon: FolderOpen, label: "المشاريع" },
      { to: "/financial", icon: DollarSign, label: "المالية" },
      { to: "/inventory", icon: Package, label: "المخزون" },
      { to: "/knowledge", icon: BookOpen, label: "المعرفة" },
    ],
  },
  {
    label: "الموقع",
    items: [
      { to: "/location", icon: MapPin, label: "الخريطة والأماكن" },
      { to: "/homeassistant", icon: House, label: "المنزل الذكي" },
    ],
  },
  {
    label: "الإنتاجية",
    items: [
      { to: "/productivity", icon: Zap, label: "السرعة والتركيز" },
    ],
  },
  {
    label: "النظام",
    items: [
      { to: "/graph", icon: Network, label: "مستعرض الرسم البياني" },
      { to: "/search", icon: Search, label: "البحث" },
      { to: "/ingest", icon: Upload, label: "استيراد البيانات" },
      { to: "/proactive", icon: Sunrise, label: "التلقائي" },
      { to: "/admin/users", icon: Users, label: "إدارة المستخدمين" },
      { to: "/backup", icon: Database, label: "النسخ الاحتياطي" },
      { to: "/settings", icon: Settings, label: "الإعدادات" },
    ],
  },
];

interface SidebarContentProps {
  collapsed?: boolean;
}

const SidebarContent: React.FC<SidebarContentProps> = ({ collapsed }) => {
  const location = useLocation();

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className={cn(
        "flex items-center gap-3 px-4 py-5 border-b border-sidebar-border",
        collapsed && "justify-center px-2"
      )}>
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
          <Brain className="w-5 h-5 text-primary-foreground" />
        </div>
        {!collapsed && (
          <div>
            <div className="font-bold text-sm text-sidebar-foreground">RAG Dashboard</div>
            <div className="text-xs text-muted-foreground">لوحة الحياة الشخصية</div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-4">
        {navSections.map((section) => (
          <div key={section.label}>
            {!collapsed && (
              <div className="px-3 mb-1 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {section.label}
              </div>
            )}
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const isActive = location.pathname === item.to ||
                  (item.to !== "/" && location.pathname.startsWith(item.to));
                return (
                  <li key={item.to}>
                    <NavLink
                      to={item.to}
                      className={cn(
                        "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-all duration-150",
                        "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                        isActive && "nav-active font-medium",
                        collapsed && "justify-center px-2"
                      )}
                      title={collapsed ? item.label : undefined}
                    >
                      <item.icon className="w-4 h-4 shrink-0" />
                      {!collapsed && <span>{item.label}</span>}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </div>
  );
};

interface AppSidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

export const AppSidebar: React.FC<AppSidebarProps> = ({ collapsed, onToggle }) => {
  return (
    <>
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:flex flex-col bg-sidebar border-l border-sidebar-border transition-all duration-300 shrink-0",
          collapsed ? "w-14" : "w-60"
        )}
      >
        <SidebarContent collapsed={collapsed} />
        <button
          onClick={onToggle}
          className="flex items-center justify-center py-3 border-t border-sidebar-border text-muted-foreground hover:text-foreground transition-colors"
        >
          {collapsed ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
      </aside>

      {/* Mobile hamburger */}
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden">
            <Menu className="w-5 h-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="right" className="w-60 p-0 bg-sidebar border-sidebar-border">
          <SidebarContent />
        </SheetContent>
      </Sheet>
    </>
  );
};
