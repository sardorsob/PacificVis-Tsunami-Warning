import { useEffect,useRef,useState } from "react";
import { EvidencePanel,SliceEvidencePanel } from "./evidence/EvidencePanel";
import { loadIndex,LatestRequest } from "./loader";
import { isSlice,loadBasemap,loadGeometry,loadStation,loadViewManifest,type SliceRecords } from "./slices";
import { eventSearch,parseEvent,parseState,serializeState } from "./state";
import { loadArrivals,type StoryArrivals } from "./story/arrivals";
import { ArrivalsView } from "./story/ArrivalsView";
import { loadLayers,type Coastline,type StoryLayers } from "./story/layers";
import { entryFor,keptPrev,type NavResult,type StoryNav } from "./story/nav";
import { NoRecordsPage,PairedView } from "./story/PairedView";
import { STORY_EVENT_ID } from "./story/steps";
import { StoryView,type StoryViewProps } from "./story/StoryView";
import { parseStoryParams,type StoryParams } from "./story/url";
import type { AnySelection,AnyStation,DemoState,EventEntry,EventsIndex,StageGeometry,StationRecords,ViewManifest } from "./types";

const message=(error:unknown)=>error instanceof Error?error.message:"Unexpected data failure.";
type Loaded={index:EventsIndex;entry:EventEntry;manifest:ViewManifest;issues:string[]};
export function DemoApp() {
  const [loaded,setLoaded]=useState<Loaded|null>(null);const [manifestError,setManifestError]=useState<string|null>(null);
  const [manifestAttempt,setManifestAttempt]=useState(0);const [eventChange,setEventChange]=useState(0);
  // The events index first, then the URL's event and the records manifest the index pins (verified before parsing, then read by its schema);
  // an event without records opens without stations.
  useEffect(()=>{const request=new LatestRequest<Loaded>();setManifestError(null);
    void request.run(async signal=>{const index=await loadIndex(signal);const {entry,issues}=parseEvent(window.location.search,index);
      return {index,entry,issues,manifest:await loadViewManifest(entry,signal)};}).then(l=>{if(l)setLoaded(l);}).catch(error=>setManifestError(message(error)));
    return()=>request.cancel();},[manifestAttempt,eventChange]);
  // Back/Forward onto another event reloads that event's manifest and remounts the view; within one event LoadedDemo restores.
  useEffect(()=>{if(!loaded)return;
    const restore=()=>{if(parseEvent(window.location.search,loaded.index).entry!==loaded.entry){setLoaded(null);setEventChange(v=>v+1);}};
    window.addEventListener("popstate",restore);return()=>window.removeEventListener("popstate",restore);},[loaded]);
  if(!loaded)return <main className="story story--loading"><div><h1 className="story-title">Pacific station records</h1>
    <p className="story-small">Descriptive records, not validated arrivals or warning time.</p>
    {manifestError?<div role="alert" className="story-alert"><p>{manifestError}</p>
      <button type="button" onClick={()=>setManifestAttempt(v=>v+1)}>Retry verified bundle</button></div>
      :<p role="status" className="story-small">Loading descriptive station metadata…</p>}</div></main>;
  // The event select pushes the new event's URL; this then loads it like Back/Forward onto another event does.
  return <LoadedDemo key={`${manifestAttempt}:${eventChange}`} {...loaded} onEventChange={()=>{setLoaded(null);setEventChange(v=>v+1);}}/>;
}
function LoadedDemo({index,entry,manifest,issues:eventIssues,onEventChange}:Loaded&{onEventChange:()=>void}) {
  const [initial]=useState(()=>parseState(window.location.search,manifest));
  // The guided steps belong to one event; the URL omits the default event, so every existing link stays as it was.
  const guided=entry.event_id===STORY_EVENT_ID,event=entry.event_id===index.default_event_id?null:entry.event_id;
  const [story,setStory]=useState<StoryParams>(()=>parseStoryParams(window.location.search,guided).params);const storyRef=useRef(story);storyRef.current=story;
  // Bumped on browser Back/Forward so the views restore the lens and clock without writing history.
  const [restoreKey,setRestoreKey]=useState(0);
  const stations:readonly AnyStation[]=manifest.stations;
  const href=(next:DemoState,s:StoryParams)=>`${window.location.pathname}${serializeState(next,s,event,stations.length>0)}${window.location.hash}`;
  const [state,setState]=useState<DemoState>(initial.state);const stateRef=useRef(state);stateRef.current=state;
  const [issues,setIssues]=useState(()=>[...eventIssues,...initial.issues,...parseStoryParams(window.location.search,guided).issues]);
  const [geometry,setGeometry]=useState<StageGeometry|null>(null),[geometryError,setGeometryError]=useState<string|null>(null);
  const [geometryAttempt,setGeometryAttempt]=useState(0),[basemap,setBasemap]=useState<Coastline|null>(null);
  const [chunks,setChunks]=useState<Record<string,AnySelection>>({});const cache=useRef(new Map<string,StationRecords|SliceRecords>());
  /** A station and its records, paired by the bundle's schema (stations and records come from the same manifest). */
  const pick=(station:AnyStation,status:AnySelection["status"],records:StationRecords|SliceRecords|null,error:string|null)=>({station,status,records,error}) as AnySelection;
  const [stationAttempt,setStationAttempt]=useState(0);
  const [evidenceId,setEvidenceId]=useState<string|null>(null);const evidenceTrigger=useRef<HTMLElement|null>(null);
  // The hash-verified map layers (published contours, 1:50m coastline), loaded once for every view; views keep working without them.
  const [layers,setLayers]=useState<StoryLayers|null>(null),[layersError,setLayersError]=useState<string|null>(null);
  const [layersAttempt,setLayersAttempt]=useState(0);
  // An event without listed contours (layers: null) loads none and is not an error.
  useEffect(()=>{if(!entry.layers)return;const request=new LatestRequest<StoryLayers>();setLayersError(null);
    void request.run(signal=>loadLayers(entry,signal)).then(l=>{if(l)setLayers(l);}).catch(error=>setLayersError(message(error)));
    return()=>request.cancel();},[entry,layersAttempt]);
  const layersPending=!entry.layers||layers||layersError?null:layersAttempt?"retrying" as const:"loading" as const;
  // The hash-verified reported-times file the index pins (none for some events: null; undefined while it loads); a file that fails any check
  // leaves the event without its marks.
  const [arrivals,setArrivals]=useState<StoryArrivals|"rejected"|null|undefined>(undefined);
  useEffect(()=>{const request=new LatestRequest<StoryArrivals|null>();
    void request.run(signal=>loadArrivals(entry,signal)).then(a=>{if(a!==undefined)setArrivals(a);}).catch(()=>setArrivals("rejected"));
    return()=>request.cancel();},[entry]);
  // The map: the bundle's geometry (or, without records, the index's epicentre) and the index's basemap, both verified; either failing offers Retry map.
  useEffect(()=>{const request=new LatestRequest<[StageGeometry,Coastline|null]>();setGeometryError(null);
    void request.run(signal=>Promise.all([loadGeometry(manifest,entry,signal),index.basemap?loadBasemap(index,signal):null]))
      .then(g=>{if(g){setGeometry(g[0]);setBasemap(g[1]);}}).catch(error=>setGeometryError(message(error)));return()=>request.cancel();},[manifest,geometryAttempt]);
  useEffect(()=>{
    if(manifest.schema_version===null)return; // no stations to load
    const ids=[...new Set([state.selectedStationId,...(state.pinnedStationId?[state.pinnedStationId]:[])])];
    const controller=new AbortController();let active=true;
    for(const id of ids){const station=stations.find(s=>s.station_id===id)!;const cached=cache.current.get(id);
      if(cached){setChunks(c=>({...c,[id]:pick(station,"ready",cached,null)}));continue;}
      setChunks(c=>({...c,[id]:pick(station,"loading",null,null)}));
      void loadStation(manifest,id,controller.signal).then(records=>{controller.signal.throwIfAborted();
        if(!active)return;cache.current.set(id,records);setChunks(c=>({...c,[id]:pick(station,"ready",records,null)}));})
        .catch(error=>{if(active&&!controller.signal.aborted)setChunks(c=>({...c,[id]:pick(station,"error",null,message(error))}));});
    }
    return()=>{active=false;controller.abort();};
  },[manifest,state.selectedStationId,state.pinnedStationId,stationAttempt]);
  useEffect(()=>{const restore=()=>{const {entry:next,issues:eventParsed}=parseEvent(window.location.search,index);
    if(next!==entry)return; // another event: DemoApp reloads and remounts
    const parsed=parseState(window.location.search,manifest),storyParsed=parseStoryParams(window.location.search,guided);
    setState(parsed.state);setStory(storyParsed.params);setIssues([...eventParsed,...parsed.issues,...storyParsed.issues]);
    setEvidenceId(null);setRestoreKey(k=>k+1);};
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
  /** Another event, from the live screen: the entry left keeps this moment (replace), then one push opens the new event on its defaults. */
  const onEvent=(id:string,live:StoryNav)=>{const next=index.events.find(e=>e.event_id===id);if(!next||next===entry)return;
    const {a,b,...params}=live;const here={...stateRef.current,selectedStationId:a,pinnedStationId:b};write(here,params,"replace");
    window.history.pushState(entryFor(window.history.state,"explore","push"),"",`${window.location.pathname}${eventSearch(here,params,next,index)}${window.location.hash}`);
    onEventChange();};
  /** Applies a navigation result (push/replace/back/none) from story/nav.ts. */
  const writeNav=(r:NavResult)=>{
    if(r.history==="back"){window.history.back();return;}
    const {a,b,...params}=r.nav;const next={...stateRef.current,selectedStationId:a,pinnedStationId:b};
    if(r.history==="none"){stateRef.current=next;storyRef.current=params;setState(next);setStory(params);return;}
    write(next,params,r.history);
  };
  const selection=(id:string):AnySelection|null=>{const station=stations.find(s=>s.station_id===id);return chunks[id]??(station?pick(station,"loading",null,null):null);};
  const openEvidence=(id:string)=>{evidenceTrigger.current=document.activeElement instanceof HTMLElement?document.activeElement:null;setEvidenceId(id);};
  // A timeout, not an animation frame, so focus still returns in a hidden tab.
  const closeEvidence=()=>{setEvidenceId(null);window.setTimeout(()=>evidenceTrigger.current?.focus({preventScroll:true}),0);};
  const inspected=evidenceId?selection(evidenceId):null;
  const props:StoryViewProps={manifest,geometry,geometryError,basemap,state,selected:selection(state.selectedStationId),
    pinned:state.pinnedStationId?selection(state.pinnedStationId):null,onOpenEvidence:openEvidence,onRetryStation:()=>setStationAttempt(v=>v+1),
    onRetryGeometry:()=>setGeometryAttempt(v=>v+1),layers,layersError,layersPending,onRetryLayers:()=>setLayersAttempt(v=>v+1),arrivals,params:story,onNav:writeNav,
    restoreKey,evidenceOpen:evidenceId!==null,issues,onDismissIssues:()=>setIssues([]),onState,entry,events:index.events,onEvent};
  // Story and Station lens share the stage; Paired and Reported times are pages. The key remounts the view so each one starts from the URL.
  // Paired and Station lens need a station: an event without records gets a plain note there.
  const recordsOnly=!stations.length&&(state.view==="paired"||state.view==="radial");
  return <>{recordsOnly?<NoRecordsPage key={`none-${state.view}`} {...props}/>:state.view==="paired"?<PairedView key="paired" {...props}/>:state.view==="times"?<ArrivalsView key="times" {...props}/>
    :<StoryView key={state.view} {...props}/>}
    {inspected?.records&&(isSlice(inspected)?manifest.schema_version==="2"&&<SliceEvidencePanel manifest={manifest} station={inspected.station}
      records={inspected.records} onClose={closeEvidence}/>:manifest.schema_version==="1"&&<EvidencePanel manifest={manifest} station={inspected.station}
      records={inspected.records} windowId={state.windowId} productKey={state.productKey} onClose={closeEvidence}/>)}</>;
}
