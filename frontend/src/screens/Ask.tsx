import { useId, useState, type FormEvent } from "react";

import { ApiError, ask, errorText, type Answer } from "@/api";
import { CitationPanel, MARKER } from "@/components/CitationPanel";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { navigate } from "@/router";
import { FormError } from "@/screens/Login";

/** The answer text, with each [n] that has a citation numbered n turned into its source button. */
function AnswerText({ answer }: { answer: Answer }) {
  if (!answer.found) return <p className="font-serif text-lg text-muted-foreground">{answer.answer}</p>;
  const byNumber = new Map(answer.citations.map((c) => [c.n, c]));
  // split with a capture group: odd indexes are the marker numbers.
  const parts = answer.answer.split(/\[(\d+)\]/).map((part, i) => {
    if (i % 2 === 0) return part;
    const citation = byNumber.get(Number(part));
    return citation ? <CitationPanel key={i} citation={citation} /> : `[${part}]`;
  });
  return <p className="max-w-[65ch] font-serif text-lg leading-[1.8] whitespace-pre-wrap">{parts}</p>;
}

export function Ask({ workspaceId }: { workspaceId: string }) {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const titleId = useId();
  const questionId = useId();

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = String(new FormData(event.currentTarget).get("question")).trim();
    setBusy(true);
    setAnswer(null);
    setError(null);
    try {
      setAnswer(await ask(workspaceId, question));
    } catch (e) {
      // The shell checks the session only when it mounts, so a session that expires since then lands here.
      if (e instanceof ApiError && e.status === 401) navigate("/login", { replace: true });
      else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby={titleId} className="space-y-8">
      <h2 id={titleId} className="text-2xl font-semibold tracking-tight">
        Ask
      </h2>
      <form
        onSubmit={onSubmit}
        className="rounded-lg border bg-background shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/30"
      >
        <Label htmlFor={questionId} className="sr-only">
          Question
        </Label>
        <Textarea
          id={questionId}
          name="question"
          required
          placeholder="How many weeks of parental leave do we offer?"
          className="min-h-28 resize-none border-0 bg-transparent px-4 pt-4 text-base shadow-none focus-visible:ring-0 dark:bg-transparent"
        />
        <div className="flex justify-end px-3 pb-3">
          <Button type="submit" disabled={busy}>
            Ask
          </Button>
        </div>
      </form>
      <div aria-live="polite" className="space-y-4">
        {busy && <p className="text-sm text-muted-foreground">Searching your documents...</p>}
        {error && <FormError>{error}</FormError>}
        {answer && (
          <article aria-label="Answer">
            <AnswerText answer={answer} />
          </article>
        )}
        {!answer && !busy && !error && (
          <p className="max-w-prose text-sm text-muted-foreground">
            Answers cite the passages they come from. Open a number like <span className={`${MARKER} px-1.5`}>1</span>{" "}
            to read the passage.
          </p>
        )}
      </div>
    </section>
  );
}
