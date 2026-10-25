import { useEffect, useRef, useState, type RefObject } from "react";
import { seek as seekClock, T_MAX, tick, toggle as toggleClock } from "./clock";
import { PULSE_MS } from "./reveal";
import { paintContours } from "./StoryMap";

// ponytail: clamp frame gaps (a hidden tab pauses animation frames) instead of pausing on visibilitychange.
const MAX_DT = 0.25, UI_MS = 100, SEEK_COMMIT_MS = 300;
const now = () => (typeof performance === "undefined" ? 0 : performance.now());
type Commit = (kind: "playEnd" | "seekEnd", t: number) => void;
type Options = { initialT: number; svgRef: RefObject<SVGSVGElement | null>; paths: Map<number, string>; motionOK: boolean; onCommit: Commit };

/**
 * The one owner of story time. React state updates at ≤ 10 Hz; contours are painted every frame by one loop that
 * serves both playback and fading pulses. The URL is written only when play ends or pauses, or 300 ms after a seek.
 */
export function useStoryClock({ initialT, svgRef, paths, motionOK, onCommit }: Options) {
  const [t, setT] = useState(initialT), [playing, setPlaying] = useState(false);
  const tRef = useRef(initialT), playingRef = useRef(false), untilRef = useRef(T_MAX);
  const frame = useRef(0), running = useRef(false), last = useRef(0), ui = useRef(0), seekTimer = useRef(0);
  const pulses = useRef(new Map<number, number>()), commit = useRef(onCommit), pathsRef = useRef(paths);
  commit.current = onCommit; pathsRef.current = paths;
  const paint = (at: number) => { if (svgRef.current) paintContours(svgRef.current, tRef.current, pulses.current, at, pathsRef.current); };
  const halt = () => { playingRef.current = false; setPlaying(false); setT(tRef.current); };
  const loop = (at: number) => {
    const dt = Math.min(MAX_DT, (at - last.current) / 1000); last.current = at;
    if (playingRef.current) {
      const r = tick({ t: tRef.current, playing: true }, dt), nt = Math.min(r.clock.t, untilRef.current);
      tRef.current = nt;
      if (motionOK) for (const h of r.crossed) if (h <= nt) pulses.current.set(h, at);
      if (!r.clock.playing || nt >= untilRef.current) { halt(); commit.current("playEnd", nt); }
      else if (at - ui.current > UI_MS) { ui.current = at; setT(nt); }
    }
    for (const [h, start] of pulses.current) if (at - start > PULSE_MS) pulses.current.delete(h);
    paint(at);
    if (playingRef.current || pulses.current.size) frame.current = requestAnimationFrame(loop); else running.current = false;
  };
  const kick = () => {
    if (running.current || typeof requestAnimationFrame !== "function") return;
    running.current = true; last.current = now(); frame.current = requestAnimationFrame(loop);
  };
  /** Pause; writes the clock to the URL unless a seek or restore will. */
  const stop = (write = true) => { if (!playingRef.current) return; halt(); if (write) commit.current("playEnd", tRef.current); };
  const play = (from: number, until = T_MAX) => {
    if (!motionOK) return;
    tRef.current = from; untilRef.current = until; playingRef.current = true; setPlaying(true); setT(from); kick();
  };
  const toggle = () => { const next = toggleClock({ t: tRef.current, playing: playingRef.current }); if (next.playing) play(next.t); else stop(); };
  const seek = (value: number) => {
    stop(false);
    const r = seekClock({ t: tRef.current, playing: false }, value);
    tRef.current = r.clock.t; setT(r.clock.t);
    if (motionOK && r.crossed.length) { const at = now(); for (const h of r.crossed.slice(-3)) pulses.current.set(h, at); kick(); }
    else paint(now());
    window.clearTimeout(seekTimer.current);
    seekTimer.current = window.setTimeout(() => commit.current("seekEnd", tRef.current), SEEK_COMMIT_MS);
  };
  /** Restore from the URL or a step: no URL write, no pulses. */
  const set = (value: number) => { if (playingRef.current) halt(); tRef.current = value; setT(value); paint(now()); };
  useEffect(() => { if (!playingRef.current) paint(now()); }, [t, paths]);
  useEffect(() => () => { cancelAnimationFrame(frame.current); window.clearTimeout(seekTimer.current); }, []);
  /** Drop a pending slider commit (browser Back/Forward is about to restore the clock). */
  const cancelSeek = () => window.clearTimeout(seekTimer.current);
  return { t, playing, play, stop, toggle, seek, set, cancelSeek, tRef };
}
