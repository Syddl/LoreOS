import { CheckIcon, CopyIcon, KeyRoundIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import {
  ApiError,
  createApiKey,
  createInvite,
  errorText,
  listApiKeys,
  listInvites,
  listMembers,
  removeMember,
  revokeApiKey,
  type ApiKey,
  type Invite,
  type Member,
} from "@/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { navigate } from "@/router";
import { Field, FormError } from "@/screens/Login";

const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const when = (iso: string) => dateTime.format(new Date(iso));

/** A failed call shows its text in the section, except a 401: the session has ended, so log in again. */
function useFailure() {
  const [error, setError] = useState<string | null>(null);
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError && e.status === 401) navigate("/login", { replace: true });
    else setError(errorText(e));
  }, []);
  return { error, setError, fail };
}

function Section({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t pt-8 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
      <div className="space-y-1">
        <h3 id={id} className="font-medium tracking-tight">
          {title}
        </h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

/** A read-only field with a copy button. Without a clipboard (an http page that is not localhost), copy selects the text instead. */
function CopyField({ label, value }: { label: string; value: string }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      input.current?.select();
    }
  }

  return (
    <div className="grid w-full gap-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex gap-2">
        <Input id={id} ref={input} value={value} readOnly onFocus={(e) => e.currentTarget.select()} className="font-mono" />
        <Button type="button" variant="outline" onClick={() => void copy()} aria-label={`${copied ? "Copied" : "Copy"} ${label.toLowerCase()}`}>
          {copied ? <CheckIcon aria-hidden /> : <CopyIcon aria-hidden />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
    </div>
  );
}

function Members({ workspaceId }: { workspaceId: string }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const { error, setError, fail } = useFailure();

  useEffect(() => {
    listMembers(workspaceId).then(setMembers, fail);
  }, [workspaceId, fail]);

  async function remove(userId: string) {
    setError(null);
    try {
      await removeMember(workspaceId, userId);
      setMembers((all) => all && all.filter((m) => m.user_id !== userId));
    } catch (e) {
      fail(e);
    }
  }

  return (
    <Section title="Members" description="Everyone who can use this workspace. Owners can also delete documents and manage these settings.">
      {error && <FormError>{error}</FormError>}
      {members && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {members.map((m) => (
              <TableRow key={m.user_id}>
                <TableCell>{m.email}</TableCell>
                <TableCell>
                  <Badge variant={m.role === "owner" ? "secondary" : "outline"}>{m.role}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  <Button variant="ghost" size="sm" aria-label={`Remove ${m.email}`} onClick={() => void remove(m.user_id)}>
                    Remove
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Section>
  );
}

function Invites({ workspaceId }: { workspaceId: string }) {
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [link, setLink] = useState<{ url: string; expiresAt: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const { error, setError, fail } = useFailure();

  useEffect(() => {
    listInvites(workspaceId).then(setInvites, fail);
  }, [workspaceId, fail]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const invite = await createInvite(workspaceId);
      // The token rides in the fragment, which the browser never sends, so no access log records a live token.
      setLink({ url: `${window.location.origin}/invite#${invite.token}`, expiresAt: invite.expires_at });
      setInvites(await listInvites(workspaceId));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Invites" description="Each link lets one person join this workspace. It works once, until it expires.">
      <Button variant="outline" disabled={busy} onClick={() => void create()}>
        Create invite link
      </Button>
      {error && <FormError>{error}</FormError>}
      {link && (
        <div className="grid gap-2">
          <CopyField key={link.url} label="Invite link" value={link.url} />
          <Note>Send it privately: whoever opens it first joins. It expires {when(link.expiresAt)}.</Note>
        </div>
      )}
      {invites &&
        (invites.length === 0 ? (
          <Note>No pending invites.</Note>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Pending invite created</TableHead>
                <TableHead>Expires</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invites.map((i) => (
                <TableRow key={`${i.created_at} ${i.expires_at}`}>
                  <TableCell>{when(i.created_at)}</TableCell>
                  <TableCell>{when(i.expires_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ))}
    </Section>
  );
}

function ApiKeys({ workspaceId }: { workspaceId: string }) {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  // The only copy of a new key. Hide sets it to null, and nothing else ever holds it.
  const [newKey, setNewKey] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nameInput = useRef<HTMLInputElement>(null);
  const { error, setError, fail } = useFailure();

  useEffect(() => {
    listApiKeys(workspaceId).then(setKeys, fail);
  }, [workspaceId, fail]);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy(true);
    setError(null);
    try {
      const { key, ...created } = await createApiKey(workspaceId, String(new FormData(form).get("name")).trim());
      setNewKey(key);
      setKeys((all) => [...(all ?? []), { ...created, last_used_at: null, revoked_at: null }]);
      form.reset();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(keyId: string) {
    setError(null);
    try {
      await revokeApiKey(workspaceId, keyId);
      setKeys(await listApiKeys(workspaceId));
    } catch (e) {
      fail(e);
    }
  }

  return (
    <Section title="API keys" description="Scripts and integrations use a key to call the LoreOS API. A key has a member's access to this workspace.">
      <form onSubmit={(e) => void onCreate(e)} className="flex flex-wrap items-end gap-2">
        <div className="min-w-48 flex-1">
          <Field ref={nameInput} label="Key name" name="name" autoComplete="off" required />
        </div>
        <Button type="submit" disabled={busy}>
          Create key
        </Button>
      </form>
      {error && <FormError>{error}</FormError>}
      {newKey && (
        <Alert>
          <KeyRoundIcon aria-hidden />
          <AlertTitle>Copy the new key now</AlertTitle>
          <AlertDescription className="gap-3">
            <p>LoreOS shows it only this once. If it is lost, revoke it and create another.</p>
            <CopyField label="New API key" value={newKey} />
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setNewKey(null);
                nameInput.current?.focus();
              }}
            >
              Hide key
            </Button>
          </AlertDescription>
        </Alert>
      )}
      {keys &&
        (keys.length === 0 ? (
          <Note>No keys yet.</Note>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Prefix</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>
                  <span className="sr-only">Status</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.id}>
                  <TableCell>{k.name}</TableCell>
                  <TableCell className="font-mono">{k.prefix}</TableCell>
                  <TableCell>{when(k.created_at)}</TableCell>
                  <TableCell>{k.last_used_at ? when(k.last_used_at) : "Never"}</TableCell>
                  <TableCell className="text-right">
                    {k.revoked_at ? (
                      <Badge variant="outline" title={when(k.revoked_at)}>
                        Revoked
                      </Badge>
                    ) : (
                      <Button variant="ghost" size="sm" aria-label={`Revoke ${k.name}`} onClick={() => void revoke(k.id)}>
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ))}
    </Section>
  );
}

/** An owner's settings for one workspace: members, invite links and API keys. */
export function Settings({ workspaceId }: { workspaceId: string }) {
  return (
    <section aria-labelledby="settings-title" className="space-y-8">
      <h2 id="settings-title" className="text-2xl font-semibold tracking-tight">
        Settings
      </h2>
      <Members workspaceId={workspaceId} />
      <Invites workspaceId={workspaceId} />
      <ApiKeys workspaceId={workspaceId} />
    </section>
  );
}
