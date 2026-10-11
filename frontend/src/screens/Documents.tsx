import type { Role } from "@/api";

// Stub: task 5.3 fills in upload, the list, polling and delete.
export function Documents(_: { workspaceId: string; role: Role }) {
  return (
    <section aria-labelledby="documents-title" className="space-y-4">
      <h2 id="documents-title" className="text-lg font-medium tracking-tight">
        Documents
      </h2>
    </section>
  );
}
