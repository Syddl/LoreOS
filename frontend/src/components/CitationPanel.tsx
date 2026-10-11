import type { Citation } from "@/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

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
          variant="secondary"
          size="xs"
          aria-label={`Source ${citation.n}`}
          className="mx-0.5 h-5 min-w-5 px-1 align-baseline tabular-nums"
        >
          {citation.n}
        </Button>
      </SheetTrigger>
      <SheetContent className="sm:max-w-md">
        <SheetHeader className="pr-12">
          <SheetTitle className="wrap-anywhere">{citation.filename}</SheetTitle>
          {where && <p className="text-sm text-muted-foreground">{where}</p>}
        </SheetHeader>
        <SheetDescription asChild>
          <blockquote className="mx-4 mb-4 overflow-y-auto border-l-2 pl-4 text-sm leading-relaxed whitespace-pre-wrap text-foreground">
            {citation.text}
          </blockquote>
        </SheetDescription>
      </SheetContent>
    </Sheet>
  );
}
