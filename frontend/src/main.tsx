import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./AuthContext";
import { FarmProvider } from "./FarmContext";
import { LanguageProvider } from "./LanguageContext";
import { StatusProvider } from "./overview/StatusContext";
import { Layout, ProtectedRoute } from "./components";
import "./index.css";
import AddFarm from "./pages/AddFarm";
import Analyze from "./pages/Analyze";
import { LoginPage, RegisterPage } from "./pages/AuthPages";
import Dashboard from "./pages/Dashboard";
import Farms from "./pages/Farms";
import History from "./pages/History";
import Account from "./pages/Account";
import Diary from "./pages/Diary";
import WeatherPage from "./pages/WeatherPage";
import Insights from "./pages/Insights";
import Privacy from "./pages/Privacy";
import Profile from "./pages/Profile";
import Result from "./pages/Result";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LanguageProvider>
      <AuthProvider>
        <FarmProvider>
         <StatusProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route element={<ProtectedRoute />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/farms" element={<Farms />} />
                <Route path="/farms/new" element={<AddFarm />} />
                <Route path="/analyze" element={<Analyze />} />
                <Route path="/analyses/:id" element={<Result />} />
                <Route path="/history" element={<History />} />
                <Route path="/insights" element={<Insights />} />
                <Route path="/profile" element={<Profile />} />
                <Route path="/diary" element={<Diary />} />
                <Route path="/weather" element={<WeatherPage />} />
                <Route path="/account" element={<Account />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
         </StatusProvider>
        </FarmProvider>
      </AuthProvider>
      </LanguageProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
