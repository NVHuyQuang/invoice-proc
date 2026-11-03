export type InvoiceStatus = 'VERIFIED' | 'REVIEW_NEEDED' | 'FAILED' | 'DUPLICATE';

export type FilterType = 'ALL' | 'VERIFIED' | 'REVIEW_NEEDED' | 'DUPLICATE';

export type DocType =
  | 'goods_invoice'
  | 'receipt'
  | 'utility_bill'
  | 'credit_memo'
  | 'statement'
  | 'other';

export type LineItemKind =
  | 'goods'
  | 'fee'
  | 'discount'
  | 'tax_line'
  | 'deposit'
  | 'shipping';

export interface LineItem {
  item_name: string;
  qty?: string | number;
  unit_price?: string | number;
  line_total?: string | number;
  unit?: string;
  kind?: LineItemKind | string;
  checkable?: boolean;
  math_error?: string | null;
}

export interface UtilityCharge {
  description: string;
  amount: string | number;
}

export interface CanonicalInvoice {
  source_file: string;
  source_sha256?: string;
  vendor_name?: string;
  invoice_no?: string;
  invoice_date?: string;
  due_date?: string;
  currency?: string;
  category?: string;
  doc_type?: DocType | string;
  subtotal?: string | number;
  tax?: string | number;
  discount?: string | number;
  shipping?: string | number;
  tip?: string | number;
  fees?: (string | number)[];
  grand_total?: string | number;
  amount_due?: string | number;
  status: InvoiceStatus;
  review_reasons?: string[];
  line_items?: LineItem[];
  charges?: UtilityCharge[];
  is_duplicate?: boolean;
  duplicate_of?: string | null;
  schema_version?: string;
}

export interface BatchSummaryResponse {
  total_files: number;
  verified_count: number;
  review_needed_count: number;
  failed_count: number;
  duplicate_count: number;
  execution_time_seconds: number;
  invoices: CanonicalInvoice[];
}
