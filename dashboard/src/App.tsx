import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppLayout } from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import ChatPage from "./pages/ChatPage";
import RemindersPage from "./pages/RemindersPage";
import TasksPage from "./pages/TasksPage";
import ProjectsPage from "./pages/ProjectsPage";
import FinancialPage from "./pages/FinancialPage";
import InventoryPage from "./pages/InventoryPage";
import KnowledgePage from "./pages/KnowledgePage";
import HomeAssistantPage from "./pages/HomeAssistantPage";
import LocationPage from "./pages/LocationPage";
import ProductivityPage from "./pages/ProductivityPage";
import GraphPage from "./pages/GraphPage";
import SearchPage from "./pages/SearchPage";
import IngestPage from "./pages/IngestPage";
import ProactivePage from "./pages/ProactivePage";
import UsersPage from "./pages/UsersPage";
import BackupPage from "./pages/BackupPage";
import SettingsPage from "./pages/SettingsPage";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AppLayout>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/reminders" element={<RemindersPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/financial" element={<FinancialPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/homeassistant" element={<HomeAssistantPage />} />
            <Route path="/location" element={<LocationPage />} />
            <Route path="/productivity" element={<ProductivityPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/ingest" element={<IngestPage />} />
            <Route path="/proactive" element={<ProactivePage />} />
            <Route path="/admin/users" element={<UsersPage />} />
            <Route path="/backup" element={<BackupPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppLayout>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
