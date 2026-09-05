"use client";

import { useEffect, useState } from "react";
import { speak } from "@/lib/engine";
import { Visualizer } from "./Visualizer";

const EXAMPLES = [
  { name: "A clearer thought", app: "Notes", spoken: "Um, let's keep this simple. We need a quieter workspace and more time to think.", written: "Let's keep this simple. We need a quieter workspace and more time to think.", detail: "Filler removed. Your meaning stays yours." },
  { name: "Your vocabulary", app: "Message", spoken: "I'll push the swara update to get hub today.", written: "I'll push the Svara update to GitHub today.", detail: "Example personal dictionary: swara → Svara, get hub → GitHub." },
  { name: "Terminal friendly", app: "Terminal", spoken: "Review the changes.\nExplain the failing tests.\n", written: "Review the changes. Explain the failing tests.", detail: "Newlines become spaces. You decide when to press Enter." },
];

export function DictationDemo() {
  const [selected, setSelected] = useState(0);
  const [count, setCount] = useState(0);
  const [playing, setPlaying] = useState(false);
  const example = EXAMPLES[selected];
  const words = example.written.split(" ");
  const complete = count === words.length;

  useEffect(() => {
    if (!playing) return;
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (motion.matches) { setCount(words.length); setPlaying(false); return; }
    const id = window.setInterval(() => {
      if (document.hidden) return;
      setCount((n) => Math.min(n + 1, words.length));
      speak(350);
    }, 150);
    return () => window.clearInterval(id);
  }, [playing, words.length]);

  useEffect(() => { if (complete) setPlaying(false); }, [complete]);

  function choose(index: number) { setSelected(index); setCount(0); setPlaying(false); }
  function play() {
    if (playing) { setPlaying(false); return; }
    if (complete) setCount(0);
    setPlaying(true);
  }

  return (
    <section className="dictation-demo" aria-labelledby="demo-title" id="demo">
      <div className="demo-heading">
        <div><span className="eyebrow">A small rehearsal</span><h2 id="demo-title">A thought, <em>beautifully written.</em></h2></div>
        <p>See how speech becomes text. This is a scripted preview; your microphone stays off.</p>
      </div>
      <div className="demo-choices" aria-label="Dictation examples">
        {EXAMPLES.map((item, i) => <button key={item.name} aria-pressed={selected === i} onClick={() => choose(i)}><span>0{i + 1}</span>{item.name}</button>)}
      </div>
      <div className="demo-workspace">
        <div className="demo-source"><span className="demo-label">You say</span><p>“{example.spoken}”</p><Visualizer style={playing ? "spectrum" : "strings"} className="demo-signal" /></div>
        <div className="demo-output"><div className="demo-document-head"><span className="demo-label">{example.app}</span><span className="demo-local">● On your device</span></div>
          <div className="demo-transcript" aria-label="Example output">
            {count === 0 ? <span className="demo-placeholder">Your next thought starts here.</span> : words.slice(0, count).map((word, i) => <span className="demo-word" key={`${selected}-${i}`}>{word} </span>)}
            {playing && <span className="demo-caret" aria-hidden="true" />}
          </div>
          <div className="demo-progress" role="progressbar" aria-label="Preview progress" aria-valuenow={Math.round(count / words.length * 100)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${count / words.length * 100}%` }} /></div>
          <div className="demo-controls"><span role="status">{complete ? "Ready to use" : playing ? "Writing…" : count ? "Paused" : "Ready when you are"}</span><button className="btn btn-solid" onClick={play}>{playing ? "Pause" : complete ? "Replay preview ↺" : count ? "Continue preview →" : "Play preview →"}</button></div>
        </div>
      </div>
      <p className="demo-detail">{example.detail}</p>
    </section>
  );
}
