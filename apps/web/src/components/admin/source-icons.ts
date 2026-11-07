import { createElement } from "react";
import {
  Archive,
  BookOpen,
  Cloud,
  Database,
  FolderSync,
  GitBranch,
  Globe,
  HardDrive,
  Library,
  LifeBuoy,
  Server,
  Ticket,
  Upload,
  type LucideIcon,
} from "lucide-react";

/** One icon per kind of data source (connect page, chatbot knowledge). */
export const SOURCE_ICONS: Record<string, LucideIcon> = {
  upload: Upload,
  sharepoint: Cloud,
  sharepoint_server: Server,
  webdav: FolderSync,
  smb: HardDrive,
  s3: Archive,
  website: Globe,
  confluence: BookOpen,
  cmis: Library,
  git: GitBranch,
  servicenow: LifeBuoy,
  jira: Ticket,
  database: Database,
};

/** The icon for a kind of source (decorative). */
export function KindIcon({ kind, className }: { kind: string; className?: string }) {
  return createElement(SOURCE_ICONS[kind] ?? Database, { "aria-hidden": true, className });
}
