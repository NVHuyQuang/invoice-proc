import { CanonicalInvoice, BatchSummaryResponse } from '@/types/invoice';
import { FALLBACK_INVOICES } from '@/data/mock-invoices';

export async function fetchInvoices(): Promise<CanonicalInvoice[]> {
  try {
    const res = await fetch('/api/v1/invoices', { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        return data;
      }
    }
  } catch (err) {
    console.warn('API /api/v1/invoices unreachable, loading preloaded dataset...', err);
  }
  return FALLBACK_INVOICES;
}

export async function uploadSingleInvoice(
  file: File,
  targetMonth: string = '2026-08'
): Promise<CanonicalInvoice> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('target_month', targetMonth);

  const res = await fetch('/api/v1/extract', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    let errorDetail = 'Lỗi trích xuất hóa đơn';
    try {
      const errJson = await res.json();
      if (errJson.detail) errorDetail = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }

  return (await res.json()) as CanonicalInvoice;
}

export async function uploadBatchInvoices(
  files: File[],
  targetMonth: string = '2026-08',
  workers: number = 8
): Promise<{
  total_files: number;
  verified_count: number;
  review_needed_count: number;
  failed_count?: number;
  duplicate_count?: number;
  execution_time_seconds?: number;
  invoices: CanonicalInvoice[];
}> {
  const formData = new FormData();
  for (let i = 0; i < files.length; i++) {
    formData.append('files', files[i]);
  }
  formData.append('target_month', targetMonth);
  formData.append('workers', String(workers));

  const res = await fetch('/api/v1/extract-batch', {
    method: 'POST',
    body: formData,
  });

  if (!res.ok) {
    let errorDetail = 'Lỗi xử lý batch từ server';
    try {
      const errJson = await res.json();
      if (errJson.detail) errorDetail = errJson.detail;
    } catch {
      // ignore
    }
    throw new Error(errorDetail);
  }

  const result: BatchSummaryResponse = await res.json();
  return result;
}

export function getDownloadExcelUrl(month: string = '2026-08'): string {
  return `/api/v1/download-excel?month=${encodeURIComponent(month)}`;
}
