import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import { App } from "./App";
import { ToastProvider } from "./components/Toast";
import { I18nProvider } from "./i18n";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: false, retry: 1 } },
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <I18nProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </I18nProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
}
