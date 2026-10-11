// A small pathname router: the address bar is the only route state.
import { createElement, useSyncExternalStore, type AnchorHTMLAttributes, type MouseEvent } from "react";

import type { Me } from "@/api";

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname);
}

/** pushState fires no popstate, so navigate dispatches one for usePath to hear. */
export function navigate(to: string, { replace = false } = {}): void {
  if (replace) window.history.replaceState(null, "", to);
  else window.history.pushState(null, "", to);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

type LinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { to: string };

/** A real <a href>, so middle-click and modified clicks still open a new tab. */
export function Link({ to, onClick, ...props }: LinkProps) {
  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    navigate(to);
  };
  return createElement("a", { ...props, href: to, onClick: handleClick });
}

/** Where a signed-in user lands: their first workspace, or "/" (the shell's empty state) when they have none. */
export const homeOf = (me: Me) => (me.workspaces[0] ? `/w/${me.workspaces[0].id}` : "/");
