import { useState, type FormEvent } from "react";

import { errorText, MIN_PASSWORD, passwordTooShort, signup } from "@/api";
import { Button } from "@/components/ui/button";
import { homeOf, Link, navigate } from "@/router";
import { AuthPage, Field, FormError } from "@/screens/Login";

export function Signup() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password"));
    if (passwordTooShort(password)) {
      setError(`Use a password of at least ${MIN_PASSWORD} characters.`);
      return;
    }
    const workspace = String(form.get("workspace")).trim();
    setBusy(true);
    setError(null);
    try {
      navigate(homeOf(await signup(String(form.get("email")), password, workspace || undefined)));
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <AuthPage title="Create the first account">
      <form onSubmit={onSubmit} className="grid gap-4">
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          hint={`At least ${MIN_PASSWORD} characters.`}
          required
        />
        <Field label="Workspace name (optional)" name="workspace" autoComplete="off" />
        {error && <FormError>{error}</FormError>}
        <Button type="submit" disabled={busy}>
          Create account
        </Button>
      </form>
      <p className="text-sm text-muted-foreground">
        Already have an account?{" "}
        <Link to="/login" className="text-foreground underline underline-offset-4">
          Log in
        </Link>
      </p>
    </AuthPage>
  );
}
