import type { Metadata } from "next";
import "../research.css";
import "../preferences.css";
import "../insights.css";
import "../capabilities.css";
import "../connections.css";
import "../custom-workflows.css";

import { AppShell } from "@/components/app-shell";
import { ToastProvider } from "@/components/toast-provider";

export const metadata: Metadata = { title: "Workspace" };

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <AppShell>{children}</AppShell>
    </ToastProvider>
  );
}
