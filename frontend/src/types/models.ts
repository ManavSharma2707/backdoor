import type { components } from "./api";

type S = components["schemas"];

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type LoginResponse = S["LoginResponse"];
export type MeResponse = S["MeResponse"];
export type TenantOut = S["TenantOut"];
export type UserOut = S["UserOut"];
export type AuthConfig = S["AuthConfig"];

export type Product = S["ProductOut"];
export type ProductCreate = S["ProductCreate"];
export type ProductPatch = S["ProductPatch"];
export type ProductStock = S["ProductStockOut"];
export type PriceHistory = S["PriceHistoryOut"];
export type Category = S["CategoryOut"];
export type TaxRate = S["TaxRateOut"];
export type Supplier = S["SupplierOut"];
export type SupplierTerm = S["TermOut"];

export type SaleListItem = S["SaleListItem"];
export type Sale = S["SaleOut"];
export type SaleLine = S["SaleLineOut"];
export type SaleCreate = S["SaleCreate"];
export type SaleWarning = S["SaleWarning"];
export type SalesSummary = S["SalesSummary"];
export type ReturnCreate = S["ReturnCreate"];
export type SaleReturn = S["ReturnOut"];

export type PurchaseListItem = S["POListItem"];
export type PurchaseOrder = S["POOut"];
export type PurchaseLine = S["POLineOut"];
export type PurchaseCreate = S["POCreate"];
export type ReceiptCreate = S["ReceiptCreate"];
export type Receipt = S["ReceiptOut"];
export type ReceiptSummary = S["ReceiptSummary"];

export type StockRow = S["StockRow"];
export type BatchRow = S["BatchRow"];
export type MovementRow = S["MovementRow"];
export type AdjustmentCreate = S["AdjustmentCreate"];
export type CountListItem = S["CountListItem"];
export type Count = S["CountOut"];
export type CountLine = S["CountLineOut"];
export type Stockout = S["StockoutOut"];

export type Settings = S["SettingsOut"];
export type SettingsPatch = S["SettingsPatch"];
export type CalendarEvent = S["CalendarEventOut"];

export type DashboardSummary = {
  plan: {
    id: string;
    week_start: string;
    version: number;
    generated_at: string;
    festival_note?: string | null;
  } | null;
  kpis: {
    stock_value: string;
    suggested_spend: string;
    budget: string | null;
    critical_lines: number;
    non_moving_value: string;
    near_expiry_value: string;
    expired_value: string;
    data_warnings: number;
    data_errors: number;
    needed_spend?: string;
  };
  needs_attention: AttentionItem[];
  [key: string]: unknown;
};

export type AttentionItem = {
  line_id?: string;
  report_id?: string;
  sku?: string;
  name?: string;
  risk_level?: string;
  headline?: string;
  projected_stockout_date?: string | null;
  kind?: string;
  [key: string]: unknown;
};

export type TrendsResponse = {
  weeks: { week_start: string; revenue: string; units: string }[];
  festival_bands: { event_key: string; name: string; start: string; end: string }[];
};

export type CoverResponse = {
  plan_id: string | null;
  categories: {
    category_id: string;
    category: string;
    usable_stock: string;
    daily_demand: string;
    days_of_cover: number | null;
    critical_lines: number;
    high_lines: number;
    lines: number;
  }[];
};

export type ActivityItem = {
  kind: "bill_saved" | "bill_voided" | "goods_received" | "order_created";
  at: string;
  entity_id: string;
  ref: string;
  party: string | null;
  amount: string | null;
};
