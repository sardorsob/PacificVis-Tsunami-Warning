import { useEffect,useRef,useState } from "react";
import { EvidencePanel } from "./evidence/EvidencePanel";
import { loadManifest,fetchVerifiedAsset,validateGeometry,decodeStation,LatestRequest } from "./loader";
import { parseState,serializeState } from "./state";
import { loadLayers,type StoryLayers } from "./story/layers";
import { entryFor,keptPrev,type NavResult,type StoryNav } from "./story/nav";
import { PairedView } from "./story/PairedView";
import { StoryView,type StoryViewProps } from "./story/StoryView";
import { parseStoryParams,type StoryParams } from "./story/url";
import type { DemoGeometry,DemoManifest,DemoState,StationRecords,StationSelection } from "./types";

const message=(error:unknown)=>error instanceof Error?error.message:"Unexpected data failure.";
export function DemoApp() {
  const [manifest,setManifest]=useState<DemoManifest|null>(null);const [manifestError,setManifestError]=useState<string|null>(null);
  const [manifestAttempt,setManifestAttempt]=useState(0);
  useEffect(()=>{const request=new LatestRequest<DemoManifest>();setManifestError(null);
    void request.run(loadManifest).then(m=>{if(m)setManifest(m);}).catch(error=>setManifestError(message(error)));
    return()=>request.cancel();},[manifestAttempt]);
  if(!manifest)return <main className="story story--loading"><div><h1 className="story-title">Pacific station records</h1>
    <p className="story-small">Descriptive records, not validated arrivals or warning time.</p>
    {manifestError?<div role="alert" className="story-alert"><p>{manifestError}</p>
      <button type="button" onClick={()=>setManifestAttempt(v=>v+1)}>Retry verified bundle</button></div>
      :<p role="status" className="story-small">Loading descriptive station metadata…</p>}</div></main>;
  return <LoadedDemo key={manifestAttempt} manifest={manifest}/>;
}
function LoadedDemo({manifest}:{manifest:DemoManifest}) {
  const [initial]=useState(()=>parseState(window.location.search,manifest));
  const [story,setStory]=useState<StoryParams>(()=>parseStoryParams(window.location.search).params);const storyRef=useRef(story);storyRef.current=story;
  // Bumped on browser Back/Forward so the views restore the lens and clock without writing history.
  const [restoreKey,setRestoreKey]=useState(0);
  const href=(next:DemoState,s:StoryParams)=>`${window.location.pathname}${serializeState(next,s)}${window.location.hash}`;
  const [state,setState]=useState<DemoState>(initial.state);const stateRef=useRef(state);stateRef.current=state;
  const [issues,setIssues]=useState(()=>[...initial.issues,...parseStoryParams(window.location.search).issues]);
  const [geometry,setGeometry]=useState<DemoGeometry|null>(null),[geometryError,setGeometryError]=useState<string|null>(null);
  const [geometryAttempt,setGeometryAttempt]=useState(0);
  const [chunks,setChunks]=useState<Record<string,StationSelection>>({});const cache=useRef(new Map<string,StationRecords>());
  const [stationAttempt,setStationAttempt]=useState(0);
  const [evidenceId,setEvidenceId]=useState<string|null>(null);const evidenceTrigger=useRef<HTMLElement|null>(null);
  // The hash-verified map layers (published contours, 1:50m coastline), loaded once for every view; views keep working without them.
  const [layers,setLayers]=useState<StoryLayers|null>(null),[layersError,setLayersError]=useState<string|null>(null);
  const [layersAttempt,setLayersAttempt]=useState(0);
  useEffect(()=>{const request=new LatestRequest<StoryLayers>();setLayersError(null);
    void request.run(loadLayers).then(l=>{if(l)setLayers(l);}).catch(error=>setLayersError(message(error)));return()=>request.cancel();},[layersAttempt]);
  const layersPending=layers||layersError?null:layersAttempt?"retrying" as const:"loading" as const;
  useEffect(()=>{const request=new LatestRequest<DemoGeometry>();setGeometryError(null);
    void request.run(async signal=>validateGeometry(await fetchVerifiedAsset(manifest,manifest.geometry_path,signal),manifest))
      .then(g=>{if(g)setGeometry(g);}).catch(error=>setGeometryError(message(error)));return()=>request.cancel();},[manifest,geometryAttempt]);
  useEffect(()=>{
    const ids=[...new Set([state.selectedStationId,...(state.pinnedStationId?[state.pinnedStationId]:[])])];
    const controller=new AbortController();let active=true;
    for(const id of ids){const station=manifest.stations.find(s=>s.station_id===id)!;const cached=cache.current.get(id);
      if(cached){setChunks(c=>({...c,[id]:{station,status:"ready",records:cached,error:null}}));continue;}
      setChunks(c=>({...c,[id]:{station,status:"loading",records:null,error:null}}));
      void fetchVerifiedAsset(manifest,`stations/${id}.json`,controller.signal).then(raw=>{controller.signal.throwIfAborted();
        const records=decodeStation(raw,station,manifest);
        if(!active)return;cache.current.set(id,records);setChunks(c=>({...c,[id]:{station,status:"ready",records,error:null}}));})
        .catch(error=>{if(active&&!controller.signal.aborted)setChunks(c=>({...c,[id]:{station,status:"error",records:null,error:message(error)}}));});
    }
    return()=>{active=false;controller.abort();};
  },[manifest,state.selectedStationId,state.pinnedStationId,stationAttempt]);
  useEffect(()=>{const restore=()=>{const parsed=parseState(window.location.search,manifest),storyParsed=parseStoryParams(window.location.search);
    setState(parsed.state);setStory(storyParsed.params);setIssues([...parsed.issues,...storyParsed.issues]);setEvidenceId(null);setRestoreKey(k=>k+1);};
    window.addEventListener("popstate",restore);return()=>window.removeEventListener("popstate",restore);},[manifest]);
  // A reload keeps history.state: keep the previous step it records so story Back can still go back, not duplicate.
  useEffect(()=>{window.history.replaceState({step:story.step,prev:keptPrev(window.history.state,story.step)},"",href(initial.state,story));},[initial]);
  /** The one history writer: state + story fields → URL and entry ({step, prev} lets story Back use history.back()). */
  const write=(next:DemoState,params:StoryParams,history:"push"|"replace")=>{
    stateRef.current=next;storyRef.current=params;setState(next);setStory(params);
    window.history[history==="push"?"pushState":"replaceState"](entryFor(window.history.state,params.step,history),"",href(next,params));
  };
  /** A change made from a view's live screen: on a view switch the entry left keeps that moment (replace), then push. */
  const onState=(patch:Partial<DemoState>,live:StoryNav)=>{const {a,b,...params}=live;const here={...stateRef.current,selectedStationId:a,pinnedStationId:b};
    const switching=!!patch.view&&patch.view!==here.view;if(switching)write(here,params,"replace");
    setIssues([]);setEvidenceId(null);write({...here,...patch},params,"push");
    // The pressed switch button unmounts with the old view: keep keyboard focus on the switch in the new one.
    if(switching)window.setTimeout(()=>document.querySelector<HTMLElement>('.story-views [aria-pressed="true"]')?.focus({preventScroll:true}),0);};
  /** Applies a navigation result (push/replace/back/none) from story/nav.ts. */
  const writeNav=(r:NavResult)=>{
    if(r.history==="back"){window.history.back();return;}
    const {a,b,...params}=r.nav;const next={...stateRef.current,selectedStationId:a,pinnedStationId:b};
    if(r.history==="none"){stateRef.current=next;storyRef.current=params;setState(next);setStory(params);return;}
    write(next,params,r.history);
  };
  const selection=(id:string):StationSelection=>chunks[id]??{station:manifest.stations.find(s=>s.station_id===id)!,status:"loading",records:null,error:null};
  const openEvidence=(id:string)=>{evidenceTrigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setEvidenceId(id);};
  // A timeout, not an animation frame, so focus still returns in a hidden tab.
  const closeEvidence=()=>{setEvidenceId(null);window.setTimeout(()=>evidenceTrigger.current?.focus({preventScroll:true}),0);};
  const inspected=evidenceId?selection(evidenceId):null;
  const props:StoryViewProps={manifest,geometry,geometryError,state,selected:selection(state.selectedStationId),
    pinned:state.pinnedStationId?selection(state.pinnedStationId):null,onOpenEvidence:openEvidence,onRetryStation:()=>setStationAttempt(v=>v+1),
    onRetryGeometry:()=>setGeometryAttempt(v=>v+1),layers,layersError,layersPending,onRetryLayers:()=>setLayersAttempt(v=>v+1),params:story,onNav:writeNav,
    restoreKey,evidenceOpen:evidenceId!==null,issues,onDismissIssues:()=>setIssues([]),onState};
  // Story and Station lens share the stage; Paired is records first. The key remounts the view so each one starts from the URL.
  return <>{state.view==="paired"?<PairedView key="paired" {...props}/>:<StoryView key={state.view} {...props}/>}
    {inspected?.records&&<EvidencePanel manifest={manifest} station={inspected.station} records={inspected.records} windowId={state.windowId}
      productKey={state.productKey} onClose={closeEvidence}/>}</>;
}
