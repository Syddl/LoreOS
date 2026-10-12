import type { Citation } from "@/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/** The highlighter look of a citation marker, shared with the hint that shows one before the first answer. */
export const MARKER = "rounded-sm bg-highlight font-sans text-xs font-semibold text-highlight-foreground tabular-nums";

function location({ heading_path, page }: Citation): string | null {
  if (heading_path.length > 0) return heading_path.join(" > ");
  return page === null ? null : `page ${page}`;
}

/**
 * One [n] marker and the side panel it opens. Each marker is its own Sheet trigger, so Radix
 * returns focus to that marker when the panel closes.
 */
export function CitationPanel({ citation }: { citation: Citation }) {
  const where = location(citation);
  return (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          size="xs"
          aria-label={`Source ${citation.n}`}
          className={`${MARKER} mx-0.5 h-5 min-w-5 px-1 align-[0.1em] hover:bg-highlight-strong`}
        >
          {citation.n}
        </Button>
      </SheetTrigger>
      <SheetContent className="gap-0 sm:max-w-lg">
        <SheetHeader className="gap-1 border-b px-6 pt-6 pb-5 pr-14">
          <SheetTitle className="wrap-anywhere">{citation.filename}</SheetTitle>
          {where && <p className="text-sm text-muted-foreground">{where}</p>}
        </SheetHeader>
        {/* Classes go on the description: asChild concatenates rather than merges, and its muted colour won. */}
        <SheetDescription asChild className="overflow-y-auto px-6 py-6 font-serif text-[1.0625rem] leading-[1.9] text-foreground">
          <blockquote>
            <span className="box-decoration-clone bg-highlight-wash px-0.5 whitespace-pre-wrap">{citation.text}</span>
          </blockquote>
        </SheetDescription>
      </SheetContent>
    </Sheet>
  );
}
