/** Two-letter avatar initials from a display name, falling back to the email address. */
export function initialsOf(name: string, fallback: string): string {
  const parts = (name || fallback).split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}
