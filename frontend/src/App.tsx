import { Shell } from "@/components/Shell";
import { usePath } from "@/router";
import { Invite } from "@/screens/Invite";
import { Login } from "@/screens/Login";
import { Signup } from "@/screens/Signup";

// /w/:id shows Documents and Ask, /w/:id/settings the owner's settings; every other path is "/",
// which opens the first workspace, or /login on a 401.
const WORKSPACE = /^\/w\/([^/]+)(\/settings)?\/?$/;

export default function App() {
  const path = usePath();
  if (path === "/login") return <Login />;
  if (path === "/signup") return <Signup />;
  if (path === "/invite") return <Invite />;
  const match = WORKSPACE.exec(path);
  return <Shell workspaceId={match?.[1] ?? null} settings={match?.[2] !== undefined} />;
}
