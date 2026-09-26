import { useEffect, useState } from "react";
import { Nav } from "./components/Nav";
import { Library } from "./pages/Library";
import { Watch } from "./pages/Watch";

/** The page for a `#/watch/<name>` or `#/` hash. */
function route(hash: string): { page: "library" } | { page: "watch"; name: string; t: number | null } {
  const m = /^#\/watch\/([\w-]+)(?:\?t=([\d.]+))?$/.exec(hash);
  return m ? { page: "watch", name: m[1], t: m[2] ? Number(m[2]) : null } : { page: "library" };
}

export function App() {
  const [hash, setHash] = useState(location.hash);
  const [sections, setSections] = useState<string[]>([]);

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
      <Nav sections={r.page === "watch" ? sections : []} />
      {r.page === "watch" ? <Watch key={r.name} name={r.name} initialT={r.t} onSections={setSections} /> : <Library />}
    </>
  );
}
