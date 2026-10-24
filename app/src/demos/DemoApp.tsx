import { useEffect,useRef,useState } from "react";
import type { ComponentType } from "react";
import { loadManifest,fetchVerifiedAsset,validateGeometry,decodeStation,LatestRequest } from "./loader";
import { PairedDemo } from "./PairedDemo";
import { parseState,serializeState } from "./state";
import { parseStoryParams,storyQuery,type StoryParams } from "./story/url";
import type { StoryRouteProps } from "./story/StoryRoute";
import type { DemoGeometry,DemoManifest,DemoState,EvidenceProps,ProductKey,RadialProps,StationRecords,StationSelection } from "./types";

export type DemoAppProps={radialRenderer?:ComponentType<RadialProps>;evidenceRenderer?:ComponentType<EvidenceProps>;storyRenderer?:ComponentType<StoryRouteProps>};
const message=(error:unknown)=>error instanceof Error?error.message:"Unexpected data failure.";
export function DemoApp({radialRenderer:Radial,evidenceRenderer:Evidence,storyRenderer:Story}:DemoAppProps) {
  const [manifest,setManifest]=useState<DemoManifest|null>(null);const [manifestError,setManifestError]=useState<string|null>(null);const [manifestAttempt,setManifestAttempt]=useState(0);
  useEffect(()=>{const request=new LatestRequest<DemoManifest>();setManifestError(null);void request.run(loadManifest).then(m=>{if(m)setManifest(m);}).catch(error=>setManifestError(message(error)));return()=>request.cancel();},[manifestAttempt]);
  if(!manifest)return <main className="demo-app"><h1>Pacific station records</h1><p>Descriptive records, not validated arrivals or warning time.</p>{manifestError?<div role="alert"><p>{manifestError}</p><button type="button" onClick={()=>setManifestAttempt(v=>v+1)}>Retry verified bundle</button></div>:<p role="status">Loading descriptive station metadata…</p>}</main>;
  return <LoadedDemo key={manifestAttempt} manifest={manifest} Radial={Radial} Evidence={Evidence} Story={Story}/>;
}
function LoadedDemo({manifest,Radial,Evidence,Story}:{manifest:DemoManifest;Radial?:ComponentType<RadialProps>;Evidence?:ComponentType<EvidenceProps>;Story?:ComponentType<StoryRouteProps>}) {
  const [initial]=useState(()=>parseState(window.location.search,manifest));
  const [story,setStory]=useState<StoryParams>(()=>parseStoryParams(window.location.search).params);
  const href=(next:DemoState,s:StoryParams)=>`${window.location.pathname}${serializeState(next)}${next.view==="story"?`&${storyQuery(s)}`:""}${window.location.hash}`;
  const [state,setState]=useState<DemoState>(initial.state);const [issues,setIssues]=useState(initial.issues);
  const [geometry,setGeometry]=useState<DemoGeometry|null>(null),[geometryError,setGeometryError]=useState<string|null>(null),[geometryAttempt,setGeometryAttempt]=useState(0);
  const [chunks,setChunks]=useState<Record<string,StationSelection>>({});const cache=useRef(new Map<string,StationRecords>());const [stationAttempt,setStationAttempt]=useState(0);
  const [evidenceId,setEvidenceId]=useState<string|null>(null);const evidenceTrigger=useRef<HTMLElement|null>(null);
  useEffect(()=>{const request=new LatestRequest<DemoGeometry>();setGeometryError(null);void request.run(async signal=>validateGeometry(await fetchVerifiedAsset(manifest,manifest.geometry_path,signal),manifest)).then(g=>{if(g)setGeometry(g);}).catch(error=>setGeometryError(message(error)));return()=>request.cancel();},[manifest,geometryAttempt]);
  useEffect(()=>{
    const ids=[...new Set([state.selectedStationId,...(state.pinnedStationId?[state.pinnedStationId]:[])])];const controller=new AbortController();let active=true;
    for(const id of ids){const station=manifest.stations.find(s=>s.station_id===id)!;const cached=cache.current.get(id);
      if(cached){setChunks(c=>({...c,[id]:{station,status:"ready",records:cached,error:null}}));continue;}
      setChunks(c=>({...c,[id]:{station,status:"loading",records:null,error:null}}));
      void fetchVerifiedAsset(manifest,`stations/${id}.json`,controller.signal).then(raw=>{controller.signal.throwIfAborted();const records=decodeStation(raw,station,manifest);if(!active)return;cache.current.set(id,records);setChunks(c=>({...c,[id]:{station,status:"ready",records,error:null}}));}).catch(error=>{if(active&&!controller.signal.aborted)setChunks(c=>({...c,[id]:{station,status:"error",records:null,error:message(error)}}));});
    }
    return()=>{active=false;controller.abort();};
  },[manifest,state.selectedStationId,state.pinnedStationId,stationAttempt]);
  useEffect(()=>{const restore=()=>{const parsed=parseState(window.location.search,manifest);setState(parsed.state);setStory(parseStoryParams(window.location.search).params);setIssues(parsed.issues);setEvidenceId(null);};window.addEventListener("popstate",restore);return()=>window.removeEventListener("popstate",restore);},[manifest]);
  useEffect(()=>{window.history.replaceState(null,"",href(initial.state,story));},[initial]);
  const update=(patch:Partial<DemoState>,replace=false)=>{const next={...state,...patch};setState(next);setIssues([]);setEvidenceId(null);window.history[replace?"replaceState":"pushState"](null,"",href(next,story));};
  const selection=(id:string):StationSelection=>chunks[id]??{station:manifest.stations.find(s=>s.station_id===id)!,status:"loading",records:null,error:null};
  const selected=selection(state.selectedStationId),pinned=state.pinnedStationId?selection(state.pinnedStationId):null;
  const openEvidence=(id:string)=>{evidenceTrigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setEvidenceId(id);};
  const closeEvidence=()=>{setEvidenceId(null);requestAnimationFrame(()=>evidenceTrigger.current?.focus({preventScroll:true}));};
  const props:RadialProps={manifest,geometry,geometryError,state,selected,pinned,onSelectStation:id=>update({selectedStationId:id}),onOpenEvidence:openEvidence,onRetryStation:()=>setStationAttempt(v=>v+1),onRetryGeometry:()=>setGeometryAttempt(v=>v+1)};
  const inspected=evidenceId?selection(evidenceId):null;
  if(state.view==="story"&&Story)return <Story {...props} onSelectStation={id=>update({selectedStationId:id},true)} params={story}
    onParams={(p,push)=>{setStory(p);window.history[push?"pushState":"replaceState"](null,"",href(state,p));}} onPinStation={id=>update({pinnedStationId:id},true)}/>;
  return <main className="demo-app" data-demo-view={state.view}>
    <header className="demo-heading"><div><h1>Pacific station records</h1><p>Descriptive records, not validated arrivals or warning time.</p></div><nav aria-label="Record view"><button type="button" aria-pressed={state.view==="paired"} onClick={()=>update({view:"paired"})}>Paired</button><button type="button" disabled={!Radial} aria-pressed={state.view==="radial"} onClick={()=>update({view:"radial"})}>Station lens{!Radial?" · not implemented":""}</button></nav></header>
    {issues.length>0&&<aside className="data-error" role="status"><p>URL state repaired:</p><ul>{issues.map((issue,i)=><li key={i}>{issue}</li>)}</ul></aside>}
    <section className="demo-controls" aria-label="Shared station and record controls">
      <p className="active-summary">○ Selected: <strong>{selected.station.name}</strong> · ◇ Pinned: <strong>{pinned?.station.name??"none"}</strong> · {state.windowId==="source_full"?"Station-specific bounds; not a common period":"Shared UTC window"}</p>
      <div className="primary-controls"><label><span>Selected station</span><select value={state.selectedStationId} onChange={event=>update({selectedStationId:event.target.value})}>{manifest.stations.map(s=><option key={s.station_id} value={s.station_id}>{s.name} · {s.station_id}</option>)}</select></label><label><span>UTC window</span><select value={state.windowId} onChange={event=>update({windowId:event.target.value})}>{manifest.windows.map(w=><option key={w.id} value={w.id}>{w.label}</option>)}</select></label></div>
      <details className="more-controls"><summary><span className="more-controls__full">More controls · {selected.station.products.find(p=>p.key===state.productKey)!.label}</span><span className="more-controls__compact">More · pinned: {pinned?.station.name??"none"}</span></summary><div><label>Product intent<select value={state.productKey} onChange={event=>update({productKey:event.target.value as ProductKey})}>{selected.station.products.map(p=><option key={p.key} value={p.key}>{p.label}{!p.available?" · unavailable at selected station":""}</option>)}</select></label><label>Pinned reference<select value={state.pinnedStationId??""} onChange={event=>update({pinnedStationId:event.target.value||null})}><option value="">No reference pinned</option>{manifest.stations.map(s=><option key={s.station_id} value={s.station_id}>{s.name} · {s.station_id}</option>)}</select></label><button type="button" onClick={()=>update({pinnedStationId:state.selectedStationId})}>Pin selected as reference</button><button type="button" disabled={!state.pinnedStationId} onClick={()=>update({pinnedStationId:null})}>Clear reference</button></div><p>Each station keeps its own y-scale, product, units and datum. Changing a station never substitutes an unavailable product.</p></details>
    </section>
    {state.view==="paired"?<PairedDemo {...props}/>:Radial?<Radial {...props}/>:<section className="unimplemented" role="status"><h2>Station lens is not implemented yet</h2><p>Your station, reference, window and product state is retained.</p><button type="button" onClick={()=>update({view:"paired"})}>Return to paired records</button></section>}
    {inspected?.records&&(Evidence?<Evidence manifest={manifest} station={inspected.station} records={inspected.records} windowId={state.windowId} productKey={state.productKey} onClose={closeEvidence}/>:<aside className="unimplemented" role="status"><h2>Evidence panel is not implemented yet</h2><p>Current source and support remain beside the actual trace; no substitute table is supplied.</p><button type="button" onClick={closeEvidence}>Close</button></aside>)}
    <footer className="demo-limits"><p>{manifest.bundle_id} · internal descriptive evidence only. No validated arrivals, warning time or continuous ocean field.</p><p>Integrity is checked against this local manifest, not a signature against replacement of the entire bundle. Source terms and unknown datums remain in force.</p></footer>
  </main>;
}
