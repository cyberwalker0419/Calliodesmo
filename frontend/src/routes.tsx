import { createBrowserRouter, Navigate } from "react-router-dom";
import App from "./App";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { AskPanel } from "@/features/qa/AskPanel";
import { LibraryPage } from "@/features/library/LibraryPage";
import { IngestPage } from "@/features/ingest/IngestPage";
import { UserManage } from "@/features/admin/UserManage";
import { TeamProjectManage } from "@/features/admin/TeamProjectManage";
import { DocumentCommunityManage } from "@/features/admin/DocumentCommunityManage";
import { ContributionsPanel } from "@/features/collab/ContributionsPanel";
import { AnalysisPage } from "@/features/analysis/AnalysisPage";
import { SettingsPage } from "@/features/settings/SettingsPage";

export const routes = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/app",
    element: (
      <RequireAuth>
        <App />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/app/qa" replace /> },
      { path: "qa", element: <AskPanel /> },
      { path: "library", element: <LibraryPage /> },
      { path: "ingest", element: <IngestPage /> },
      { path: "analysis", element: <AnalysisPage /> },
      { path: "admin/users", element: <UserManage /> },
      { path: "admin/teams", element: <TeamProjectManage /> },
      { path: "admin/communities", element: <DocumentCommunityManage /> },
      { path: "collab", element: <ContributionsPanel /> },
      { path: "settings", element: <SettingsPage /> },
    ],
  },
  { path: "*", element: <Navigate to="/app" replace /> },
]);