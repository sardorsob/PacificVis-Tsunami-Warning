import type { AnyStation, DemoState, EventEntry, EventsIndex, ProductKey, ViewManifest } from "./types";
import { PRODUCT_KEYS } from "./loader";
import { STEPS,type StepId } from "./story/steps";
import { STORY_FIELDS,stepId,storyQuery,type StoryParams } from "./story/url";

/** The URL's event: none means the index default; an unknown one is repaired to the default, visibly. */
export function parseEvent(search: string, index: EventsIndex): {entry:EventEntry;issues:string[]} {
  const params=new URLSearchParams(search);const issues:string[]=[];const fallback=index.events.find(e=>e.event_id===index.default_event_id)!;
  if(params.getAll("event").length>1)issues.push("Repeated URL field “event”: first value used.");
  const id=params.get("event");const entry=id===null?fallback:index.events.find(e=>e.event_id===id);
  if(!entry)issues.push(`Unknown event: ${fallback.label} restored.`);
  return {entry:entry??fallback,issues};
}
export function parseState(search: string, manifest: ViewManifest): {state:DemoState;issues:string[]} {
  const params=new URLSearchParams(search);const issues:string[]=[];const stations:readonly AnyStation[]=manifest.stations;
  const state:DemoState={view:"story",sort:"time",...manifest.default_state};
  // Records schema 2 has one raw product.
  const products:readonly ProductKey[]=manifest.schema_version==="1"?PRODUCT_KEYS:["raw_value"];
  const name=(id:string|null)=>stations.find(s=>s.station_id===id)?.name??"none";
  const fields=["event","view","selected","pinned","window","product","sort",...STORY_FIELDS];
  for(const key of params.keys()) if(EVENTS_ONLY.includes(key))issues.push(`URL field “${key}” applies only to All events and was ignored.`);
    else if(!fields.includes(key))issues.push(`Unknown URL field “${key}” was ignored.`);
  const get=(key:string)=>{if(params.getAll(key).length>1)issues.push(`Repeated URL field “${key}”: first value used.`);return params.get(key);};
  const view=get("view");if(view!==null){if(view==="paired"||view==="radial"||view==="story"||view==="times")state.view=view;else issues.push("Invalid view: story restored.");}
  // An event without a records bundle has no stations: any station field in its URL is left out, visibly.
  if(!stations.length)for(const key of ["selected","pinned","window","product"])if(params.has(key))issues.push(`No station records are published for this event: URL field “${key}” was ignored.`);
  const selected=stations.length?get("selected"):null;if(selected!==null){if(stations.some(s=>s.station_id===selected))state.selectedStationId=selected;else issues.push(`Invalid selected station: ${name(state.selectedStationId)} restored.`);}
  const pinned=stations.length?get("pinned"):null;if(pinned!==null){if(pinned==="")state.pinnedStationId=null;else if(stations.some(s=>s.station_id===pinned))state.pinnedStationId=pinned;else issues.push(`Invalid pinned station: ${name(state.pinnedStationId)} restored.`);}
  // B is never A (owner rule, every view): a link that pins the selected station gets another B, visibly.
  if(stations.length&&state.pinnedStationId===state.selectedStationId){const other=stations.find(s=>s.station_id!==state.selectedStationId)??null;issues.push(`Pinned station B cannot be the selected station: ${other?.name??"none"} pinned instead.`);state.pinnedStationId=other?.station_id??null;}
  const window=stations.length?get("window"):null;if(window!==null){if(manifest.windows.some(w=>w.id===window))state.windowId=window;else issues.push("Invalid window: the default window restored.");}
  const product=stations.length?get("product"):null;if(product!==null){if(products.includes(product as ProductKey))state.productKey=product as ProductKey;else issues.push("Invalid product: the default product restored.");}
  const sort=get("sort");if(sort!==null){if(sort==="time"||sort==="distance")state.sort=sort;else issues.push("Invalid sort: reported time restored.");}
  return {state,issues};
}
/** The whole screen as a URL: station/window/product state plus the shared clock and lens fields, for every view. A non-default event leads;
 * a non-default Reported times sort follows the product, so every existing link stays byte-identical. `stations` false (an event without
 * stations, or a link to another event's defaults) leaves out selected, pinned, window and product. */
export function serializeState(state: DemoState, story: StoryParams, event: string | null = null, stations = true): string {
  return `?${new URLSearchParams({...(event===null?{}:{event}),view:state.view,
    ...(stations?{selected:state.selectedStationId,pinned:state.pinnedStationId??"",window:state.windowId,product:state.productKey}:{}),
    ...(state.sort==="distance"?{sort:state.sort}:{})})}&${storyQuery(story)}`;
}
/** The link an event change pushes: that event, the same view when it can show it (Paired and Station lens need records), the live clock, free
 * exploration (the guided steps belong to one event), and no station, pin, window or product, so the event opens on its own defaults. */
export function eventSearch(state: DemoState, story: StoryParams, next: EventEntry, index: EventsIndex): string {
  const view=next.records||(state.view!=="paired"&&state.view!=="radial")?state.view:"story";
  return serializeState({...state,view},{t:story.t,compare:false,step:"explore",at:null,z:1,from:null},next.event_id===index.default_event_id?null:next.event_id,false);
}
/** "Open this event" from All events: the event change above, into the Story view at the clock's start. */
export const openSearch=(next: EventEntry, index: EventsIndex)=>
  eventSearch({view:"story",selectedStationId:"",pinnedStationId:null,windowId:"",productKey:"raw_value"},{t:0,compare:false,step:"explore",at:null,z:1,from:null},next,index);

// All events (?view=events): the event under the lens (`event`), the list's order, one evidence filter, and its guided step (0 or 9) or the step to
// resume after Skip. It shows no station or clock.
export type EventsOrder = "date" | "magnitude" | "reports";
export type EventsHas = "records" | "contours" | "pairs" | "ncei";
type EventsStep = 0 | 9;
export type EventsState = { order: EventsOrder; has: EventsHas | null; step?: EventsStep; from?: EventsStep };
const ORDER_VALUES:readonly string[]=["date","magnitude","reports"],HAS_VALUES:readonly string[]=["records","contours","pairs","ncei"];
const EVENTS_ONLY=["order","has"],EVENTS_FIELDS=[...EVENTS_ONLY,"step","from"],NOT_IN_EVENTS=["selected","pinned","window","product","sort",...STORY_FIELDS.filter(k=>k!=="step"&&k!=="from")];
const eventsStep=(v:string|null)=>{const id=stepId(v);return id!==null&&STEPS[id].view==="events"?id as EventsStep:null;};
/** The URL's first view is All events. */
export const isEventsView=(search: string)=>new URLSearchParams(search).get("view")==="events";
export function parseEventsState(search: string): {state:EventsState;issues:string[]} {
  const params=new URLSearchParams(search),issues:string[]=[],state:EventsState={order:"date",has:null};
  for(const key of new Set(params.keys())) if(NOT_IN_EVENTS.includes(key))issues.push(`URL field “${key}” does not apply to All events and was ignored.`);
    else if(!["event","view",...EVENTS_FIELDS].includes(key))issues.push(`Unknown URL field “${key}” was ignored.`);
  const get=(key:string)=>{if(params.getAll(key).length>1)issues.push(`Repeated URL field “${key}”: first value used.`);return params.get(key);};
  get("view");
  const order=get("order");if(order!==null){if(ORDER_VALUES.includes(order))state.order=order as EventsOrder;else issues.push("Invalid order: date order restored.");}
  const has=get("has");if(has!==null){if(HAS_VALUES.includes(has))state.has=has as EventsHas;else issues.push("Invalid filter: all events shown.");}
  const step=get("step");if(step!==null){const id=eventsStep(step);if(id!==null)state.step=id;else issues.push("Invalid story step: free exploration opened.");}
  const from=get("from");if(from!==null){const id=eventsStep(from);if(id!==null)state.from=id;else issues.push("Invalid resume step: ignored.");}
  return {state,issues};
}
/** All events as a URL: a non-default event first, then the order and the filter when they are not the defaults, then the step or the step to resume. */
export const eventsSearch=(event: string | null, s: EventsState)=>
  `?${new URLSearchParams({...(event===null?{}:{event}),view:"events",...(s.order==="date"?{}:{order:s.order}),...(s.has?{has:s.has}:{}),
    ...(s.step===undefined?{}:{step:String(s.step)}),...(s.from===undefined?{}:{from:String(s.from)})})}`;
/** The link that opens a step entered from elsewhere: its own event (step 9: this one) and view, as authored, on the event's own station defaults. */
export function stepSearch(id: StepId, index: EventsIndex, current: EventEntry): string {
  const s=STEPS[id],ev=s.event??current.event_id,event=ev===index.default_event_id?null:ev;
  if(s.view==="events")return eventsSearch(event,{order:"date",has:null,step:id as EventsStep});
  return serializeState({view:s.view,selectedStationId:"",pinnedStationId:null,windowId:"",productKey:"raw_value",sort:"time"},
    {t:s.play?s.play[0]:s.t,compare:s.compare,step:id,at:null,z:1,from:null},event,false);
}
const VIEW_LABEL={events:"All events",story:"Story",times:"Reported times"} as const;
/** The first screen's link, before anything parses it: a plain link opens step 0 on All events; a step named on the wrong side of All events, or on another
 * event than its own, is repaired to its own view or event with a note (an unlisted event cannot be: parseStoryParams then opens free exploration). A step
 * link with no view takes its step's. Within one event, other views carry the step as before (Paired, or Story showing step 7). */
export function routeSearch(search: string, index: EventsIndex): {search:string;issues:string[]} {
  const q=new URLSearchParams(search),issues:string[]=[];
  if(![...q.keys()].length)return {search:stepSearch(0,index,index.events.find(e=>e.event_id===index.default_event_id)!),issues};
  const id=stepId(q.get("step"));if(id===null)return {search,issues};
  const s=STEPS[id],view=q.get("view"),n=id+1;let changed=false;
  if(view===null?s.view!=="story":(view==="events")!==(s.view==="events")){
    if(view!==null)issues.push(`Invalid view for story step ${n}: ${VIEW_LABEL[s.view]} restored.`);
    q.set("view",s.view);changed=true;}
  const own=s.view==="events"?null:index.events.find(e=>e.event_id===s.event);
  if(own&&(q.get("event")??index.default_event_id)!==own.event_id){
    if(own.event_id===index.default_event_id)q.delete("event");else q.set("event",own.event_id);
    issues.push(`Invalid event for story step ${n}: ${own.label} restored.`);changed=true;}
  return {search:changed?`?${q}`:search,issues};
}
