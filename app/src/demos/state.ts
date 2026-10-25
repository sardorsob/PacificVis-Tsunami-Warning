import type { DemoManifest, DemoState, ProductKey } from "./types";
import { PRODUCT_KEYS } from "./loader";
import { STORY_FIELDS,storyQuery,type StoryParams } from "./story/url";

export function parseState(search: string, manifest: DemoManifest): {state:DemoState;issues:string[]} {
  const params=new URLSearchParams(search);const issues:string[]=[];
  const state:DemoState={view:"story",...manifest.default_state};
  const fields=["view","selected","pinned","window","product",...STORY_FIELDS];
  for(const key of params.keys()) if(!fields.includes(key))issues.push(`Unknown URL field “${key}” was ignored.`);
  const get=(key:string)=>{if(params.getAll(key).length>1)issues.push(`Repeated URL field “${key}”: first value used.`);return params.get(key);};
  const view=get("view");if(view!==null){if(view==="paired"||view==="radial"||view==="story")state.view=view;else issues.push("Invalid view: story restored.");}
  const selected=get("selected");if(selected!==null){if(manifest.stations.some(s=>s.station_id===selected))state.selectedStationId=selected;else issues.push("Invalid selected station: Hilo restored.");}
  const pinned=get("pinned");if(pinned!==null){if(pinned==="")state.pinnedStationId=null;else if(manifest.stations.some(s=>s.station_id===pinned))state.pinnedStationId=pinned;else issues.push("Invalid pinned station: Saipan restored.");}
  // B is never A (owner rule, every view): a link that pins the selected station gets another B, visibly.
  if(state.pinnedStationId===state.selectedStationId){const other=manifest.stations.find(s=>s.station_id!==state.selectedStationId)??null;issues.push(`Pinned station B cannot be the selected station: ${other?.name??"none"} pinned instead.`);state.pinnedStationId=other?.station_id??null;}
  const window=get("window");if(window!==null){if(manifest.windows.some(w=>w.id===window))state.windowId=window;else issues.push("Invalid window: common day restored.");}
  const product=get("product");if(product!==null){if(PRODUCT_KEYS.includes(product as ProductKey))state.productKey=product as ProductKey;else issues.push("Invalid product: raw value restored.");}
  return {state,issues};
}
/** The whole screen as a URL: station/window/product state plus the shared clock and lens fields, for every view. */
export function serializeState(state: DemoState, story: StoryParams): string {
  return `?${new URLSearchParams({view:state.view,selected:state.selectedStationId,pinned:state.pinnedStationId??"",window:state.windowId,product:state.productKey})}&${storyQuery(story)}`;
}
