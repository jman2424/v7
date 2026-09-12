export type ReplyTotals = {inbound:number;eligible:number;replied:number;answered:number;response_seconds:number};
export type ReplyReport = {total:ReplyTotals;daily:(ReplyTotals & {day:string})[]};
export type Product = {sku:string;name:string;unit:string;interest:number;units:number;amount_pence:number;quantity:number|null;threshold:number;available:boolean;archived:boolean};
export type Sale = {id:string;sku:string;name:string;quantity:number;amount_pence:number;occurred_utc:string;channel:string};
export type Commerce = {products:Product[];interest_daily:{day:string;sku:string;count:number}[];
  sales_daily:{day:string;sku:string;units:number;amount_pence:number;entries:number}[];
  inventory:{sku:string;ts_utc:string;quantity:number|null;threshold:number;in_stock:number}[];
  recent_sales:Sale[];interest_tracking_since:string|null};
