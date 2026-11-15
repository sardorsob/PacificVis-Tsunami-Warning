import type { DemoManifest, DemoState, EventEntry, EventsIndex, ProductKey } from "./types";
import { PRODUCT_KEYS } from "./loader";
import { STORY_FIELDS,storyQuery,type StoryParams } from "./story/url";

/** The URL's event: none means the index default; an unknown one is repaired to the default, visibly. */
export function parseEvent(search: string, index: EventsIndex): {entry:EventEntry;issues:string[]} {
  const params=new URLSearchParams(search);const issues:string[]=[];const fallback=index.events.find(e=>e.event_id===index.default_event_id)!;
  if(params.getAll("event").length>1)issues.push("Repeated URL field “event”: first value used.");
  const id=params.get("event");const entry=id===null?fallback:index.events.find(e=>e.event_id===id);
  if(!entry)issues.push(`Unknown event: ${fallback.label} restored.`);
  return {entry:entry??fallback,issues};
}
export function parseState(search: string, manifest: DemoManifest): {state:DemoState;issues:string[]} {
  const params=new URLSearchParams(search);const issues:string[]=[];
  const state:DemoState={view:"story",sort:"time",...manifest.default_state};
  const name=(id:string|null)=>manifest.stations.find(s=>s.station_id===id)?.name??"none";
  const fields=["event","view","selected","pinned","window","product","sort",...STORY_FIELDS];
  for(const key of params.keys()) if(!fields.includes(key))issues.push(`Unknown URL field “${key}” was ignored.`);
  const get=(key:string)=>{if(params.getAll(key).length>1)issues.push(`Repeated URL field “${key}”: first value used.`);return params.get(key);};
  const view=get("view");if(view!==null){if(view==="paired"||view==="radial"||view==="story"||view==="times")state.view=view;else issues.push("Invalid view: story restored.");}
  const selected=get("selected");if(selected!==null){if(manifest.stations.some(s=>s.station_id===selected))state.selectedStationId=selected;else issues.push(`Invalid selected station: ${name(state.selectedStationId)} restored.`);}
  const pinned=get("pinned");if(pinned!==null){if(pinned==="")state.pinnedStationId=null;else if(manifest.stations.some(s=>s.station_id===pinned))state.pinnedStationId=pinned;else issues.push(`Invalid pinned station: ${name(state.pinnedStationId)} restored.`);}
  // B is never A (owner rule, every view): a link that pins the selected station gets another B, visibly.
  if(state.pinnedStationId===state.selectedStationId){const other=manifest.stations.find(s=>s.station_id!==state.selectedStationId)??null;issues.push(`Pinned station B cannot be the selected station: ${other?.name??"none"} pinned instead.`);state.pinnedStationId=other?.station_id??null;}
  const window=get("window");if(window!==null){if(manifest.windows.some(w=>w.id===window))state.windowId=window;else issues.push("Invalid window: common day restored.");}
  const product=get("product");if(product!==null){if(PRODUCT_KEYS.includes(product as ProductKey))state.productKey=product as ProductKey;else issues.push("Invalid product: raw value restored.");}
  const sort=get("sort");if(sort!==null){if(sort==="time"||sort==="distance")state.sort=sort;else issues.push("Invalid sort: reported time restored.");}
  return {state,issues};
}
/** The whole screen as a URL: station/window/product state plus the shared clock and lens fields, for every view. A non-default event leads;
 * a non-default Reported times sort follows the product, so every existing link stays byte-identical. */
export function serializeState(state: DemoState, story: StoryParams, event: string | null = null): string {
  return `?${new URLSearchParams({...(event===null?{}:{event}),view:state.view,selected:state.selectedStationId,pinned:state.pinnedStationId??"",window:state.windowId,product:state.productKey,
    ...(state.sort==="distance"?{sort:state.sort}:{})})}&${storyQuery(story)}`;
}
