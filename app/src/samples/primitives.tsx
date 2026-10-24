import { useId } from "react";
import { fixtureNotice, type StationFixture, type TracePoint } from "./fixtures";

export type StationMapProps = { stations: readonly StationFixture[]; highlightedId?: string };
export type StationChartProps = { station: StationFixture };

export function StationMap({ stations, highlightedId }: StationMapProps) {
  const titleId = useId();
  return <figure className="sample-map sample-figure">
    <svg viewBox="0 0 640 380" role="img" aria-labelledby={titleId}>
      <title id={titleId}>Schematic Pacific with fictional station positions. Invented examples, not to scale.</title>
      <rect width="640" height="380" rx="6" fill="#e7eff0" />
      <g fill="none" stroke="#c8d6d7" strokeWidth="1">
        <path d="M0 95H640 M0 190H640 M0 285H640 M160 0V380 M320 0V380 M480 0V380" />
      </g>
      <g fill="#b1c2bf" stroke="#859e99" strokeWidth="1.5">
        <path d="M0 0H130L115 32 129 55 102 73 109 104 82 124 77 151 56 168 38 144 26 105 0 93Z" />
        <path d="M0 240L46 221 76 230 106 257 126 298 104 332 63 350 0 345Z" />
        <path d="M640 0H526L514 29 533 47 518 73 549 97 562 124 583 136 588 174 610 194 640 183Z" />
        <path d="M640 219L608 211 588 235 597 267 617 290 621 332 640 350Z" />
        <path d="M322 253L330 245 338 254 332 267Z M352 280L363 274 370 285 360 294Z" />
      </g>
      <text x="320" y="92" textAnchor="middle" fill="#627b7b" fontSize="26" letterSpacing="4">PACIFIC</text>
      {stations.map((station) => {
        const [x, y] = station.mapPosition;
        return <g key={station.id} transform={`translate(${x * 640} ${y * 380})`}>
          <circle r="17" fill="none" stroke={highlightedId === station.id ? "#a94625" : "#32696e"} strokeWidth="1" />
          <circle r="7" fill={highlightedId === station.id ? "#a94625" : "#32696e"} />
          <text x="24" y="8" fill="#183b40" fontSize="26" fontWeight="600">{station.name}</text>
        </g>;
      })}
    </svg>
    <figcaption><span>Schematic Pacific · not to scale</span><span>{fixtureNotice}. Positions are fictional.</span></figcaption>
  </figure>;
}

function traceSegments(points: readonly TracePoint[]) {
  const segments: TracePoint[][] = [];
  let current: TracePoint[] = [];
  for (const point of points) {
    if (point.value === null) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push(point);
  }
  if (current.length) segments.push(current);
  return segments;
}

export function TraceChart({ station }: StationChartProps) {
  const titleId = useId();
  const x = (minute: number) => 52 + minute / 60 * 438;
  const y = (value: number) => 96 - value * 5;
  return <figure className="sample-trace sample-figure">
    <svg viewBox="0 0 520 220" role="img" aria-labelledby={titleId}>
      <title id={titleId}>{`${station.name}: invented water-level trace in cm over 0 to 60 minutes. Missing observations are gaps.`}</title>
      <g stroke="#dce3e1" strokeWidth="1"><path d="M52 46H490 M52 96H490 M52 146H490" /></g>
      <g fill="#52696c" fontSize="22">
        <text x="6" y="52">10</text><text x="18" y="102">0</text><text x="0" y="152">−10</text>
        <text x="52" y="24">cm</text>
        {[0, 20, 40, 60].map((minute) => <text key={minute} x={x(minute)} y="181" textAnchor="middle">{minute}</text>)}
        <text x="271" y="212" textAnchor="middle">Elapsed example time (minutes →)</text>
      </g>
      {traceSegments(station.points).map((segment, index) => <polyline key={index} data-trace-segment={index} fill="none" stroke="#32696e" strokeWidth="3" strokeLinejoin="round" strokeLinecap="round" points={segment.map((point) => `${x(point.minute)},${y(point.value!)}`).join(" ")} />)}
    </svg>
    <figcaption><span>{fixtureNotice}</span><span>Water-level illustration · gaps are unavailable, not zero.</span></figcaption>
  </figure>;
}

export function CoverageChart({ station }: StationChartProps) {
  const titleId = useId();
  return <figure className="sample-coverage sample-figure">
    <svg viewBox="0 0 520 112" role="img" aria-labelledby={titleId}>
      <title id={titleId}>{`${station.name}: illustrative observation coverage. Filled cells available, outlined cells unavailable. Invented examples.`}</title>
      {station.points.map((point) => <rect key={point.minute} x={43 + point.minute / 60 * 438} y="12" width="18" height="22" rx="2" fill={point.value === null ? "none" : "#32696e"} stroke={point.value === null ? "#788d8c" : "#32696e"} strokeWidth="1.5" strokeDasharray={point.value === null ? "3 2" : undefined} />)}
      <g fill="#52696c" fontSize="22"><text x="52" y="63">0</text><text x="490" y="63" textAnchor="end">60 minutes →</text>
        <rect x="52" y="82" width="14" height="14" fill="#32696e" /><text x="74" y="97">Available</text>
        <rect x="273" y="82" width="14" height="14" fill="none" stroke="#788d8c" strokeDasharray="3 2" /><text x="296" y="97">Unavailable</text>
      </g>
    </svg>
    <figcaption><span>{fixtureNotice}</span><span>Each cell is a 5-minute example sample; final cell is at minute 60.</span></figcaption>
  </figure>;
}
