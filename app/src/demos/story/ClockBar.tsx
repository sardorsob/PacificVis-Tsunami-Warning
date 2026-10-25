import type { CSSProperties } from "react";
import { clockLabel, T_MAX, utcAt } from "./clock";
import { rampGradient } from "./palette";

type ClockBarProps = { t: number; playing: boolean; disabled: boolean; originUtc: string; reduced: boolean; onToggle: () => void; onSeek: (t: number) => void; style?: CSSProperties };
/** Play/pause and a slider whose track is the published-hour ramp. With reduced motion the button steps one hour instead. */
export function ClockBar({ t, playing, disabled, originUtc, reduced, onToggle, onSeek, style }: ClockBarProps) {
  return <section className="story-panel story-clockbar" aria-label="Story clock" style={style}>
    <button type="button" className="story-play" onClick={onToggle} disabled={disabled || (reduced && t >= T_MAX)} aria-label={reduced ? "Step the published clock forward one hour" : playing ? "Pause the published clock" : "Play the published clock"}>{reduced ? "+1 h" : playing ? "❚❚" : "▶"}</button>
    <div className="story-clockbar__track">
      <input type="range" min={0} max={T_MAX} step={0.05} value={t} disabled={disabled} style={{ ["--story-ramp" as string]: rampGradient() }}
        aria-label="Hours after the earthquake" aria-valuetext={`${clockLabel(t)}, ${utcAt(originUtc, t)}`} onChange={e => onSeek(Number(e.target.value))}/>
      <div className="story-clockbar__ticks" aria-hidden="true">{[0, 5, 10, 15, 20, 25, 30].map(h => <span key={h}>{h} h</span>)}</div>
    </div>
    <p className="story-clockbar__read"><b>{clockLabel(t)}</b><span>{utcAt(originUtc, t)} · NOAA/NCEI published contours</span></p>
  </section>;
}
