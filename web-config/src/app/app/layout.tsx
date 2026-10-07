import type { Metadata } from "next";
import "./sample-workspace.css";
import { SampleWorkspaceProvider } from "./sample-workspace";

export const metadata: Metadata = { title: "Sample workspace" };

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <SampleWorkspaceProvider>{children}</SampleWorkspaceProvider>;
}
