import { useCallback, useEffect, useState } from "react";
import { Nav } from "./components/Nav";
import { Home } from "./pages/Home";
import { Prepare, type Selection } from "./pages/Prepare";
import { Watch } from "./pages/Watch";
import type { LibraryItem } from "./types";

type Route = { page: "home" } | { page: "prepare" } | { page: "video"; name: string; t: number | null };

/** The page for `#/`, `#/prepare` or `#/video/<name>[?t=<seconds>]`. Anything else is home. */
function route(hash: string): Route {
  if (hash === "#/prepare") return { page: "prepare" };
  const m = /^#\/video\/([\w-]+)(?:\?t=([\d.]+))?$/.exec(hash);
  return m ? { page: "video", name: m[1], t: m[2] ? Number(m[2]) : null } : { page: "home" };
}

export function App() {
  const [hash, setHash] = useState(location.hash);
  const [sections, setSections] = useState<string[]>([]);
  const [selection, setSelection] = useState<Selection | null>(null);

  useEffect(() => {
    const onChange = () => {
      setHash(location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  useEffect(() => {
    const set = (input: string) => () => {
      document.documentElement.dataset.input = input;
    };
    const key = set("keyboard");
    const pointer = set("pointer");
    window.addEventListener("keydown", key, true);
    window.addEventListener("pointerdown", pointer, true);
    return () => {
      window.removeEventListener("keydown", key, true);
      window.removeEventListener("pointerdown", pointer, true);
    };
  }, []);

  const r = route(hash);
  useEffect(() => {
    if (r.page !== "prepare") setSelection(null);
  }, [r.page]);

  const choose = useCallback((s: Selection) => {
    setSelection(s);
    location.hash = "#/prepare";
  }, []);
  const needsAnalysis = useCallback((item: LibraryItem) => {
    setSelection({ kind: "sample", item });
    location.replace("#/prepare"); // replace, so Back does not return to the page that redirects
  }, []);

  return (
    <>
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <Nav sections={r.page === "video" ? sections : []} />
      {r.page === "video" && <Watch key={r.name} name={r.name} initialT={r.t} onSections={setSections} onNeedsAnalysis={needsAnalysis} />}
      {r.page === "prepare" && <Prepare selection={selection} />}
      {r.page === "home" && <Home onChoose={choose} />}
    </>
  );
}
