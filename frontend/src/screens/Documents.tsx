import { Trash2Icon } from "lucide-react";
import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent, type ReactNode } from "react";

import {
  addDocument,
  ApiError,
  deleteDocument,
  errorText,
  listDocuments,
  type Document,
  type DocumentStatus,
  type Role,
} from "@/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { navigate } from "@/router";
import { Field, FormError } from "@/screens/Login";

const POLL_MS = 2000;

const STATUS: Record<DocumentStatus, { label: string; variant: "outline" | "secondary" | "destructive" }> = {
  pending: { label: "Queued", variant: "outline" },
  processing: { label: "Processing", variant: "outline" },
  processed: { label: "Ready", variant: "secondary" },
  failed: { label: "Failed", variant: "destructive" },
};

const KIND: Record<string, string> = { md: "Markdown", txt: "Text", pdf: "PDF", docx: "Word", url: "Web page" };

const settling = (d: Document) => d.status === "pending" || d.status === "processing";

/** A 401 means the session ended while the page was open, so the user logs in again; anything else is shown. */
function report(e: unknown, show: (message: string) => void) {
  if (e instanceof ApiError && e.status === 401) navigate("/login", { replace: true });
  else show(errorText(e));
}

function DeleteDocument({ workspaceId, doc, onDeleted }: { workspaceId: string; doc: Document; onDeleted: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onConfirm() {
    setBusy(true);
    setError(null);
    try {
      await deleteDocument(workspaceId, doc.id);
      setOpen(false);
      onDeleted();
    } catch (e) {
      report(e, setError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        setError(null);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={`Delete ${doc.filename}`}>
          <Trash2Icon aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this document?</DialogTitle>
          <DialogDescription className="wrap-anywhere">
            {doc.filename} and its passages leave this workspace, and answers stop citing it. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {error && <FormError>{error}</FormError>}
        <DialogFooter>
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button variant="destructive" disabled={busy} onClick={() => void onConfirm()}>
            Delete document
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DocumentRow({ doc, remove }: { doc: Document; remove: ReactNode }) {
  const status = STATUS[doc.status];
  const passages = `${doc.chunk_count} passage${doc.chunk_count === 1 ? "" : "s"}`;
  return (
    <li className="grid gap-1.5 py-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="text-sm font-medium wrap-anywhere">{doc.filename}</p>
          <p className="flex gap-3 text-xs text-muted-foreground">
            <span>{KIND[doc.kind] ?? doc.kind}</span>
            {doc.status === "processed" && <span>{passages}</span>}
          </p>
        </div>
        <Badge variant={status.variant}>{status.label}</Badge>
        {remove}
      </div>
      {doc.status === "failed" && doc.error && <p className="text-sm text-destructive wrap-anywhere">{doc.error}</p>}
    </li>
  );
}

export function Documents({ workspaceId, role }: { workspaceId: string; role: Role }) {
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDocs(await listDocuments(workspaceId));
      setLoadError(null);
    } catch (e) {
      report(e, setLoadError);
    }
  }, [workspaceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Poll only while a document can still change; a settled list costs no requests.
  const busy = docs?.some(settling) ?? false;
  useEffect(() => {
    if (!busy) return;
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [busy, refresh]);

  async function add(source: File | string): Promise<boolean> {
    setAdding(true);
    setAddError(null);
    try {
      // A duplicate comes back as the existing document, which moves to the top.
      const doc = await addDocument(workspaceId, source);
      setDocs((prev) => [doc, ...(prev ?? []).filter((d) => d.id !== doc.id)]);
      return true;
    } catch (e) {
      report(e, setAddError);
      return false;
    } finally {
      setAdding(false);
    }
  }

  // Choosing a file uploads it; clearing the picker lets the same file be chosen again.
  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (file) void add(file);
  }

  // A failed URL stays in the field to correct.
  async function onUrl(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    if (await add(String(new FormData(form).get("url")).trim())) form.reset();
  }

  let list;
  if (docs === null) {
    list = !loadError && (
      <p role="status" className="text-sm text-muted-foreground">
        Loading documents...
      </p>
    );
  } else if (docs.length === 0) {
    list = <p className="text-sm text-muted-foreground">No documents yet. Upload a file or add a web page to start.</p>;
  } else {
    list = (
      <ul aria-label="Documents in this workspace" className="divide-y border-y">
        {docs.map((d) => (
          <DocumentRow
            key={d.id}
            doc={d}
            remove={
              role === "owner" && (
                <DeleteDocument
                  workspaceId={workspaceId}
                  doc={d}
                  onDeleted={() => setDocs((prev) => (prev ?? []).filter((x) => x.id !== d.id))}
                />
              )
            }
          />
        ))}
      </ul>
    );
  }

  return (
    <section aria-labelledby="documents-title" className="space-y-6">
      <div className="space-y-1">
        <h2 id="documents-title" className="text-lg font-medium tracking-tight">
          Documents
        </h2>
        <p className="text-sm text-muted-foreground">Answers come only from the documents listed here.</p>
      </div>
      <div className="grid gap-3">
        <Field label="Upload a file" type="file" onChange={onFile} />
        <form onSubmit={(e) => void onUrl(e)} className="flex items-end gap-2">
          <div className="flex-1">
            <Field label="Web page URL" name="url" type="url" placeholder="https://" autoComplete="url" required />
          </div>
          <Button type="submit" variant="outline" disabled={adding}>
            Add page
          </Button>
        </form>
        {addError && <FormError>{addError}</FormError>}
      </div>
      {loadError && <FormError>{`Could not load the documents: ${loadError}`}</FormError>}
      {list}
    </section>
  );
}
