'use client';

import React from 'react';
import { ShieldCheck, CheckCircle2, AlertTriangle, ArrowLeft } from 'lucide-react';
import { CanonicalInvoice } from '@/types/invoice';

interface WorkspaceProps {
  invoice?: CanonicalInvoice;
  onBackToQueue: () => void;
}

export function Workspace({ invoice, onBackToQueue }: WorkspaceProps) {
  if (!invoice) {
    return (
      <main
        id="colWorkspace"
        className="flex-1 flex flex-col items-center justify-center card rounded-xl p-8 text-gray-400 font-mono text-sm"
      >
        Vui lòng chọn một hóa đơn từ hàng đợi
      </main>
    );
  }

  const fileName = invoice.source_file.split(/[\\/]/).pop() || 'invoice.pdf';
  const category = invoice.category || 'Khác';
  const docType = invoice.doc_type || 'goods_invoice';
  const isVerified = invoice.status === 'VERIFIED';

  const subtotal = invoice.subtotal !== undefined && invoice.subtotal !== null ? `$${invoice.subtotal}` : '$0.00';
  const tax = invoice.tax !== undefined && invoice.tax !== null ? `$${invoice.tax}` : '$0.00';
  const discount = invoice.discount !== undefined && invoice.discount !== null ? `-$${invoice.discount}` : '-$0.00';
  const grandTotal = invoice.grand_total !== undefined && invoice.grand_total !== null ? `$${invoice.grand_total}` : '$0.00';

  const hasLineItems = invoice.line_items && invoice.line_items.length > 0;
  const hasCharges = invoice.charges && invoice.charges.length > 0;

  return (
    <main
      id="colWorkspace"
      className="flex-1 flex flex-col gap-2 overflow-hidden min-w-0"
    >
      {/* Breadcrumb Bar & View Mode Toggles */}
      <div className="card rounded-xl px-4 py-2.5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2 text-xs text-gray-400 font-mono min-w-0 truncate">
          <button
            type="button"
            onClick={onBackToQueue}
            className="lg:hidden flex items-center gap-1 px-2 py-1 bg-snow-100 text-frost-600 rounded text-xs font-semibold mr-1"
          >
            <ArrowLeft className="w-3 h-3" />
            <span>Danh sách</span>
          </button>
          <span>08.Aug 2026</span>
          <span>/</span>
          <span className="text-gray-500 truncate">{category}</span>
          <span>/</span>
          <span className="text-gray-900 font-bold truncate">{fileName}</span>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="flex items-center gap-1.5 text-[11px] font-mono text-gray-500">
            <span className="w-1.5 h-1.5 rounded-full bg-grass-500" />
            <span>{docType}</span>
          </div>
          <div className="flex items-center gap-1 text-[11px] font-mono text-frost-600">
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>VLM End-to-End</span>
          </div>
        </div>
      </div>

      {/* Main Line Items & Charges Table Card */}
      <div className="card flex-1 rounded-xl overflow-hidden flex flex-col min-h-0">
        {/* Table Header */}
        <div className="px-4 py-3 border-b border-snow-200 bg-snow-50/80 grid grid-cols-12 text-[11px] font-bold text-gray-500 uppercase tracking-wider font-mono flex-shrink-0">
          <span className="col-span-1">#</span>
          <span className="col-span-2">Mã / Loại</span>
          <span className="col-span-4">Tên hàng / Khoản mục</span>
          <span className="col-span-1 text-center">SL</span>
          <span className="col-span-1 text-center">ĐVT</span>
          <span className="col-span-1 text-right">Đơn giá</span>
          <span className="col-span-2 text-right">Thành tiền</span>
        </div>

        {/* Table Body (Scrollable) */}
        <div className="flex-1 overflow-y-auto custom-scroll divide-y divide-snow-100">
          {hasLineItems ? (
            invoice.line_items!.map((it, idx) => (
              <div
                key={idx}
                className="px-4 py-2.5 grid grid-cols-12 hover:bg-snow-50 transition text-xs items-center"
              >
                <span className="col-span-1 text-gray-400 font-mono text-[11px]">
                  {String(idx + 1).padStart(2, '0')}
                </span>
                <span className="col-span-2 font-mono text-xs text-frost-600 font-medium truncate">
                  {it.kind || 'goods'}
                </span>
                <span
                  className="col-span-4 font-semibold text-gray-800 truncate pr-2"
                  title={it.item_name}
                >
                  {it.item_name}
                </span>
                <span className="col-span-1 text-center font-mono text-gray-700">
                  {it.qty ?? '1'}
                </span>
                <span className="col-span-1 text-center text-[10px] text-gray-400 font-mono">
                  {it.unit || 'EA'}
                </span>
                <span className="col-span-1 text-right font-mono text-gray-700">
                  ${it.unit_price ?? '0.00'}
                </span>
                <span className="col-span-2 text-right font-mono font-bold text-gray-900">
                  ${it.line_total ?? '0.00'}
                </span>
              </div>
            ))
          ) : hasCharges ? (
            invoice.charges!.map((ch, idx) => (
              <div
                key={idx}
                className="px-4 py-2.5 grid grid-cols-12 hover:bg-snow-50 transition text-xs items-center"
              >
                <span className="col-span-1 text-gray-400 font-mono text-[11px]">
                  {String(idx + 1).padStart(2, '0')}
                </span>
                <span className="col-span-2 font-mono text-xs text-amber-600 font-medium">
                  charge
                </span>
                <span
                  className="col-span-6 font-semibold text-gray-800 truncate pr-2"
                  title={ch.description}
                >
                  {ch.description}
                </span>
                <span className="col-span-3 text-right font-mono font-bold text-gray-900">
                  ${ch.amount ?? '0.00'}
                </span>
              </div>
            ))
          ) : (
            <div className="p-8 text-center text-gray-400 font-mono text-xs">
              Không có dữ liệu dòng hàng itemized
            </div>
          )}
        </div>

        {/* Bottom Reconciliation Bar */}
        <div className="border-t border-snow-200 bg-snow-50 px-5 py-3 flex flex-wrap items-center justify-between gap-3 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs font-semibold">
              {isVerified ? (
                <>
                  <CheckCircle2 className="w-4 h-4 text-grass-500" />
                  <span className="text-grass-700">
                    Toàn bộ 4 tầng kiểm tra số học đạt chuẩn (PASS 100%)
                  </span>
                </>
              ) : (
                <>
                  <AlertTriangle className="w-4 h-4 text-amber-500" />
                  <span className="text-amber-800">
                    Cần kế toán đối soát: phát hiện chênh lệch hoặc cảnh báo ngày
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-4 sm:gap-6 text-xs font-mono flex-wrap">
            <span className="text-gray-500">
              Tạm tính:{' '}
              <strong className="text-gray-800 text-sm font-bold">
                {subtotal}
              </strong>
            </span>
            <span className="text-gray-500">
              Thuế:{' '}
              <strong className="text-gray-800 text-sm font-bold">
                {tax}
              </strong>
            </span>
            <span className="text-gray-500">
              Giảm trừ:{' '}
              <strong className="text-gray-800 text-sm font-bold">
                {discount}
              </strong>
            </span>
            <div className="border-l border-snow-300 pl-4">
              <span className="text-gray-500">Tổng thanh toán: </span>
              <span className="font-extrabold text-base text-gray-900">
                {grandTotal}
              </span>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
