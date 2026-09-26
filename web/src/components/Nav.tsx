import { useEffect, useState } from "react";

const LABEL: Record<string, string> = { analysis: "Analysis", trace: "Decision Trace", brands: "Brands" };
/** A section counts as current once its top has passed this fraction of the viewport height. */
const CURRENT_AT = 0.4;

/** The section nearest the top of the viewport, among those on the page. */
function useCurrentSection(ids: string[]): string | null {
  const [current, setCurrent] = useState<string | null>(null);
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      let found: string | null = ids[0] ?? null;
      for (const id of ids) {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= window.innerHeight * CURRENT_AT) found = id;
      }
      setCurrent(found);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [ids]);
  return current;
}

interface Props {
  /** Ids of the sections on the current page, in order. Empty on the library. */
  sections: string[];
}

/** The top navigation: Library always, and the sections of an episode page when one is open. */
export function Nav({ sections }: Props) {
  const current = useCurrentSection(sections);
  return (
    <header className="nav">
      <a className="wordmark" href="#/" aria-label="ADlyser, library">
        <b>AD</b>lyser
      </a>
      <nav aria-label="Primary">
        <a href="#/" aria-current={sections.length === 0 ? "page" : undefined}>
          Library
        </a>
        {sections.map((id) => (
          <button key={id} type="button" aria-current={current === id ? "location" : undefined} onClick={() => document.getElementById(id)?.scrollIntoView()}>
            {LABEL[id] ?? id}
          </button>
        ))}
      </nav>
      <span className="nav-note">Measure with tools · Decide with AI · Guard with code</span>
    </header>
  );
}
