import { ChevronsUpDownIcon, PlusIcon } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";

import { ApiError, createWorkspace, errorText, logout, me, type Me, type Workspace } from "@/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { homeOf, Link, navigate } from "@/router";
import { Ask } from "@/screens/Ask";
import { Documents } from "@/screens/Documents";
import { FormError } from "@/screens/Login";
import { Settings } from "@/screens/Settings";

function WorkspaceSwitcher({ workspaces, current }: { workspaces: Workspace[]; current: Workspace | undefined }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="max-w-56">
          <span className="sr-only">Workspace:</span>{" "}
          <span className="truncate">{current?.name ?? "Choose a workspace"}</span>
          <ChevronsUpDownIcon aria-hidden className="text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuLabel>Your workspaces</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={current?.id ?? ""} onValueChange={(id) => navigate(`/w/${id}`)}>
          {workspaces.map((w) => (
            <DropdownMenuRadioItem key={w.id} value={w.id}>
              <span className="truncate">{w.name}</span>
              {w.role === "owner" && <span className="ml-auto text-xs text-muted-foreground">owner</span>}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function CreateWorkspace({ onCreated }: { onCreated: (workspace: Workspace) => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameId = useId();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("name")).trim();
    setBusy(true);
    setError(null);
    try {
      onCreated(await createWorkspace(name));
      setOpen(false);
    } catch (e) {
      setError(errorText(e));
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
        <Button variant="ghost" size="sm">
          <PlusIcon aria-hidden />
          New workspace
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New workspace</DialogTitle>
          <DialogDescription>Its documents, members and API keys are separate from every other workspace. You become its owner.</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor={nameId}>Name</Label>
            <Input id={nameId} name="name" autoComplete="off" required />
          </div>
          {error && <FormError>{error}</FormError>}
          <DialogFooter>
            <Button type="submit" disabled={busy}>
              Create workspace
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** The signed-in frame: switcher, workspace creation, settings for owners, logout, and the workspace's screens. */
export function Shell({ workspaceId, settings }: { workspaceId: string | null; settings: boolean }) {
  const [account, setAccount] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    me().then(setAccount, (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) navigate("/login", { replace: true });
      else setError(errorText(e));
    });
  }, []);

  // "/" (or any unknown path) opens the first workspace.
  const landing = account && !workspaceId && account.workspaces[0] ? homeOf(account) : null;
  useEffect(() => {
    if (landing) navigate(landing, { replace: true });
  }, [landing]);

  async function onLogout() {
    try {
      await logout();
    } catch (e) {
      // A 401 means the session had already expired: that is logged out too.
      if (!(e instanceof ApiError && e.status === 401)) {
        setError(errorText(e));
        return;
      }
    }
    navigate("/login");
  }

  if (!account || landing) {
    return (
      <main className="mx-auto max-w-6xl px-4 py-12">
        {error ? (
          <FormError>{`Could not load your account: ${error}. Reload the page to try again.`}</FormError>
        ) : (
          <p role="status" className="text-sm text-muted-foreground">
            Loading...
          </p>
        )}
      </main>
    );
  }

  const current = account.workspaces.find((w) => w.id === workspaceId);
  let content;
  if (!workspaceId) {
    content = (
      <p className="max-w-prose text-sm text-muted-foreground">
        You are not in any workspace yet. Create one with New workspace, or open an invite link from a workspace owner.
      </p>
    );
  } else if (!current) {
    content = (
      <p className="max-w-prose text-sm text-muted-foreground">
        This workspace does not exist or you are not a member. Choose one of yours from the workspace menu.
      </p>
    );
  } else if (settings) {
    content =
      current.role === "owner" ? (
        <Settings key={current.id} workspaceId={current.id} />
      ) : (
        <p className="text-sm text-muted-foreground">Only owners can open this workspace's settings.</p>
      );
  } else {
    // One key on the pair, so a switch replaces both screens. The same key on two siblings made React keep the old
    // ones and add the new, stacking every workspace visited.
    content = (
      <div key={current.id} className="grid gap-10 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <Documents workspaceId={current.id} role={current.role} />
        <Ask workspaceId={current.id} />
      </div>
    );
  }

  const pageLink =
    "rounded-md px-3 py-1.5 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-[current=page]:bg-accent aria-[current=page]:text-foreground";

  return (
    <div className="min-h-svh">
      <header className="border-b">
        <nav aria-label="Workspace" className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-3">
          <span className="mr-3 text-lg font-semibold tracking-tighter">LoreOS</span>
          {account.workspaces.length > 0 && <WorkspaceSwitcher workspaces={account.workspaces} current={current} />}
          <CreateWorkspace
            onCreated={(w) => {
              setAccount({ ...account, workspaces: [...account.workspaces, w] });
              navigate(`/w/${w.id}`);
            }}
          />
          {current?.role === "owner" && (
            <div className="flex items-center gap-1">
              <Link to={`/w/${current.id}`} aria-current={settings ? undefined : "page"} className={pageLink}>
                Documents
              </Link>
              <Link to={`/w/${current.id}/settings`} aria-current={settings ? "page" : undefined} className={pageLink}>
                Settings
              </Link>
            </div>
          )}
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">{account.user.email}</span>
            <Button variant="outline" size="sm" onClick={() => void onLogout()}>
              Log out
            </Button>
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        {error && <FormError>{error}</FormError>}
        {content}
      </main>
    </div>
  );
}
