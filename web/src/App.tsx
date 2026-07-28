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
import { LoginPage } from "./pages/LoginPage";
import { NoAccessPage } from "./pages/NoAccessPage";
import { ProhibitedWordsPage } from "./pages/ProhibitedWordsPage";
import { useAuth } from "./lib/auth";
import { defaultPath } from "./lib/permissions";

function MainHome() {
  const { user } = useAuth();
  return <Navigate to={defaultPath(user)} replace />;
}

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
            <MainHome />
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
        path="/no-access"
        element={
          <ProtectedRoute>
            <NoAccessPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
