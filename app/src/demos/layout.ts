export function isShortLandscape(width:number,height:number):boolean {
  return width>=600&&height<=450;
}
export function plotDateContext(startUtc:string,endUtc:string):string {
  const start=startUtc.slice(0,10),end=endUtc.slice(0,10);
  return `${start}${end!==start?` → ${end}`:""} UTC`;
}
