import { Navigate, Route, Routes } from "react-router-dom";
import {
  FeatureRoute,
  MultiFeatureRoute,
  ProtectedRoute,
} from "./components/ProtectedRoute";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DouyinPage } from "./pages/DouyinPage";
import { DouyinTranscribePage } from "./pages/DouyinTranscribePage";
import { EditorPage } from "./pages/EditorPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { ProhibitedWordsPage } from "./pages/ProhibitedWordsPage";
import { ScriptAnalysisPage } from "./pages/ScriptAnalysisPage";
import { ScriptLibraryDetailPage } from "./pages/ScriptLibraryDetailPage";
import { ScriptLibraryPage } from "./pages/ScriptLibraryPage";
import { ToolsPage } from "./pages/ToolsPage";

export function App() {
  const isAdminHost =
    window.location.hostname === "admin.chenjianru.asia" ||
    window.location.hostname.startsWith("admin.");

  if (isAdminHost) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage adminMode />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AdminPage />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <HomePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tools"
        element={
          <ProtectedRoute>
            <ToolsPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/subtitle"
        element={
          <FeatureRoute permission="subtitle_workspace">
            <DashboardPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/tasks/:taskId"
        element={
          <FeatureRoute permission="subtitle_workspace">
            <EditorPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/douyin"
        element={
          <FeatureRoute permission="douyin_download">
            <DouyinPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/douyin-transcribe"
        element={
          <MultiFeatureRoute
            permissions={["douyin_download", "subtitle_workspace"]}
          >
            <DouyinTranscribePage />
          </MultiFeatureRoute>
        }
      />
      <Route
        path="/prohibited-words"
        element={
          <FeatureRoute permission="prohibited_word_check">
            <ProhibitedWordsPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/script-analysis"
        element={
          <FeatureRoute permission="script_analysis">
            <ScriptAnalysisPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/script-library"
        element={
          <FeatureRoute permission="script_library">
            <ScriptLibraryPage />
          </FeatureRoute>
        }
      />
      <Route
        path="/script-library/:scriptId"
        element={
          <FeatureRoute permission="script_library">
            <ScriptLibraryDetailPage />
          </FeatureRoute>
        }
      />
      <Route path="/no-access" element={<Navigate to="/tools" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
