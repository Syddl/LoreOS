import { useId, useState, type ComponentProps, type FormEvent, type ReactNode } from "react";

import { ApiError, errorText, login } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { homeOf, Link, navigate } from "@/router";

/** The frame shared by login, signup and invite acceptance. */
export function AuthPage({ title, children }: { title: string; children: ReactNode }) {
  const titleId = useId();
  return (
    <main className="mx-auto flex min-h-svh w-full max-w-sm flex-col justify-center gap-10 px-4 py-12">
      <header className="space-y-3">
        <p className="font-serif text-5xl font-semibold">LoreOS</p>
        <p className="text-sm text-muted-foreground">Answers from your organization's documents, with the sources to check them.</p>
      </header>
      <section aria-labelledby={titleId} className="space-y-6 border-t pt-8">
        <h1 id={titleId} className="text-xl font-medium tracking-tight">
          {title}
        </h1>
        {children}
      </section>
    </main>
  );
}

export function Field({ label, hint, ...props }: ComponentProps<typeof Input> & { label: string; hint?: string }) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} aria-describedby={hint ? hintId : undefined} {...props} />
      {hint && (
        <p id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

export function FormError({ children }: { children: ReactNode }) {
  return (
    <Alert variant="destructive">
      <AlertDescription>{children}</AlertDescription>
    </Alert>
  );
}

function waitText(seconds: number) {
  const [n, unit] = seconds < 60 ? [seconds, "second"] : [Math.ceil(seconds / 60), "minute"];
  return `${n} ${unit}${n === 1 ? "" : "s"}`;
}

function loginError(error: unknown) {
  if (error instanceof ApiError && error.status === 429 && error.retryAfter !== null) {
    return `Too many login attempts. Try again in ${waitText(error.retryAfter)}.`;
  }
  return errorText(error);
}

export function Login() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      navigate(homeOf(await login(String(form.get("email")), String(form.get("password")))));
    } catch (e) {
      setError(loginError(e));
      setBusy(false);
    }
  }

  return (
    <AuthPage title="Log in">
      <form onSubmit={onSubmit} className="grid gap-4">
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        {error && <FormError>{error}</FormError>}
        <Button type="submit" disabled={busy}>
          Log in
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">
        Setting up LoreOS for the first time?{" "}
        <Link to="/signup" className="text-foreground underline underline-offset-4">
          Create the first account
        </Link>
      </p>
    </AuthPage>
  );
}
