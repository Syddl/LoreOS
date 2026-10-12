import { useEffect, useState, type FormEvent } from "react";

import { acceptInvite, ApiError, errorText, me, MIN_PASSWORD, passwordTooShort, type Me } from "@/api";
import { Button } from "@/components/ui/button";
import { homeOf, Link, navigate } from "@/router";
import { AuthPage, Field, FormError } from "@/screens/Login";

// The link is /invite#<token>: a fragment never reaches the server, so no access log holds a live token.
export function Invite() {
  // Read once into state: the effect below empties the hash, and accept still needs the token.
  const [token] = useState(() => window.location.hash.slice(1));
  // Replace the history entry without the fragment, so the back button and session history never hold the token.
  useEffect(() => {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }, []);
  // undefined while loading, null when logged out
  const [current, setCurrent] = useState<Me | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    me().then(setCurrent, (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) setCurrent(null);
      else setError(errorText(e));
    });
  }, [token]);

  async function accept(body: Parameters<typeof acceptInvite>[0]) {
    setBusy(true);
    setError(null);
    try {
      const after = await acceptInvite(body);
      const joined = after.workspaces.find((w) => !current?.workspaces.some((b) => b.id === w.id));
      navigate(joined ? `/w/${joined.id}` : homeOf(after));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (passwordTooShort(password)) {
      setError(`Use a password of at least ${MIN_PASSWORD} characters.`);
      return;
    }
    void accept({ token, email: String(form.get("email")), password });
  }

  if (!token) {
    return (
      <AuthPage title="Join a workspace">
        <FormError>This invite link is missing its code. Ask the workspace owner to send the link again.</FormError>
      </AuthPage>
    );
  }

  return (
    <AuthPage title="Join a workspace">
      {current === undefined && !error && (
        <p role="status" className="text-sm text-muted-foreground">
          Checking your invite...
        </p>
      )}
      {current && (
        <div className="grid gap-4">
          <p className="text-sm">
            You are logged in as <span className="font-medium">{current.user.email}</span>. Joining adds the workspace to your account.
          </p>
          {error && <FormError>{error}</FormError>}
          <Button onClick={() => void accept({ token })} disabled={busy}>
            Join workspace
          </Button>
        </div>
      )}
      {current === null && (
        <>
          <form onSubmit={onCreate} className="grid gap-4">
            <Field label="Email" name="email" type="email" autoComplete="email" required />
            <Field
              label="Password"
              name="password"
              type="password"
              autoComplete="new-password"
              hint={`At least ${MIN_PASSWORD} characters.`}
              required
            />
            {error && <FormError>{error}</FormError>}
            <Button type="submit" disabled={busy}>
              Create account and join
            </Button>
          </form>
          <p className="text-sm text-muted-foreground">
            Already have an account?{" "}
            <Link to="/login" className="text-foreground underline underline-offset-4">
              Log in
            </Link>
            , then open this invite link again.
          </p>
        </>
      )}
      {current === undefined && error && <FormError>{error}</FormError>}
    </AuthPage>
  );
}
