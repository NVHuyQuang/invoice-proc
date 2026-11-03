'use client';

import React from 'react';
import {
  AlertTriangle,
  Pencil,
  ArrowRight,
  ArrowLeft,
} from 'lucide-react';
import { CanonicalInvoice } from '@/types/invoice';

interface AuditInspectorProps {
  invoice?: CanonicalInvoice;
  onApproveAndNext: () => void;
  onEditInvoice: () => void;
  onBackToWorkspace: () => void;
}

export function AuditInspector({
  invoice,
  onApproveAndNext,
  onEditInvoice,
  onBackToWorkspace,
}: AuditInspectorProps) {
  if (!invoice) {
    return null;
  }

  const isVerified = invoice.status === 'VERIFIED';
  const isUtility = invoice.doc_type === 'utility_bill';
  const hasReviewReasons = invoice.review_reasons && invoice.review_reasons.length > 0;

  return (
    <aside
      id="colInspector"
      className="w-full lg:w-72 flex flex-col gap-2 flex-shrink-0"
    >
      {/* Mobile back to workspace button */}
      <div className="lg:hidden flex items-center justify-between px-1 mb-1">
        <button
          type="button"
          onClick={onBackToWorkspace}
          className="flex items-center gap-1 px-2.5 py-1 bg-white border border-snow-200 text-frost-600 rounded-lg text-xs font-semibold shadow-[0_1px_2px_rgba(0,0,0,0.04)]"
        >
          <ArrowLeft className="w-3 h-3" />
          <span>Xem Bảng kê</span>
        </button>
        <span className="text-xs font-mono text-gray-400">Kiểm toán 4 tầng</span>
      </div>

      {/* Invoice Details Card */}
      <div className="card rounded-xl p-3.5 flex-shrink-0">
        <div className="text-[10px] font-bold text-gray-400 uppercase tracking-wider font-mono mb-2.5">
          Thông tin Hóa đơn
        </div>
        <div className="space-y-2 text-xs">
          <div>
            <div className="text-gray-400 text-[10px] mb-0.5">
              Nhà cung cấp / Đơn vị bán
            </div>
            <div className="font-bold text-gray-900 truncate text-sm">
              {invoice.vendor_name || 'N/A'}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-gray-400 text-[10px] mb-0.5">
                Số HĐ / Biên lai
              </div>
              <div className="font-mono text-gray-800 font-semibold truncate">
                {invoice.invoice_no || 'N/A'}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-[10px] mb-0.5">Tiền tệ</div>
              <div className="font-mono text-gray-800 font-semibold">
                {invoice.currency || 'USD'}
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-gray-400 text-[10px] mb-0.5">
                Ngày lập (Bill Date)
              </div>
              <div className="font-mono text-gray-800">
                {invoice.invoice_date || 'N/A'}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-[10px] mb-0.5">Hạn thanh toán</div>
              <div className="font-mono text-gray-800">
                {invoice.due_date || '-'}
              </div>
            </div>
          </div>
          <div className="pt-1 border-t border-snow-100 flex items-center justify-between">
            <span className="text-gray-400 text-[10px]">Phân loại chi phí:</span>
            <span className="tag bg-snow-100 text-gray-700 font-medium">
              {invoice.category || 'Khác'}
            </span>
          </div>
        </div>
      </div>

      {/* 4-Tier Arithmetic Audit Card */}
      <div className="card rounded-xl p-3.5 flex-shrink-0">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[10px] font-bold text-gray-400 uppercase tracking-wider font-mono">
            Kiểm toán 4 tầng số học
          </div>
          <span
            className={`tag text-[10px] ${
              isVerified ? 'tag-pass' : 'tag-flag'
            }`}
          >
            {isVerified ? '100% MATCH' : 'REVIEW NEEDED'}
          </span>
        </div>
        <div className="space-y-2 text-xs">
          {/* Tier 1 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  isVerified ? 'bg-grass-500' : 'bg-amber-500'
                }`}
              />
              <span className="text-gray-600 text-[11px]">
                Tầng 1: Đơn giá × SL = Dòng
              </span>
            </div>
            <span className="font-mono text-[11px] text-gray-700 font-medium">
              {isVerified ? 'PASS (0.00)' : 'CHECK'}
            </span>
          </div>

          {/* Tier 2 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  isVerified ? 'bg-grass-500' : 'bg-amber-500'
                }`}
              />
              <span className="text-gray-600 text-[11px]">
                Tầng 2: Tổng dòng = Subtotal
              </span>
            </div>
            <span className="font-mono text-[11px] text-gray-700 font-medium">
              {isVerified ? 'PASS (0.00)' : 'CHECK'}
            </span>
          </div>

          {/* Tier 3 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  isVerified ? 'bg-grass-500' : 'bg-amber-500'
                }`}
              />
              <span className="text-gray-600 text-[11px]">
                Tầng 3: Khớp Grand Total
              </span>
            </div>
            <span className="font-mono text-[11px] text-gray-700 font-medium">
              {isVerified ? 'PASS (0.00)' : 'CHECK'}
            </span>
          </div>

          {/* Tier 4 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${
                  isUtility ? 'bg-grass-500' : 'bg-slate-300'
                }`}
              />
              <span className="text-gray-600 text-[11px]">
                Tầng 4: Tiện ích / Nợ cũ
              </span>
            </div>
            <span
              className={`font-mono text-[11px] ${
                isUtility
                  ? 'text-grass-600 font-medium'
                  : 'text-gray-400'
              }`}
            >
              {isUtility ? 'PASS (Charges)' : 'N/A'}
            </span>
          </div>
        </div>

        <div className="mt-3 mini-bar">
          <div
            className={`mini-bar-fill ${
              isVerified ? 'bg-grass-500' : 'bg-amber-500'
            }`}
            style={{ width: isVerified ? '100%' : '70%' }}
          />
        </div>
      </div>

      {/* Review Alert Card (Shown only when status is REVIEW_NEEDED) */}
      {!isVerified && hasReviewReasons && (
        <div className="card rounded-xl p-3.5 bg-amber-50/70 border-amber-200">
          <div className="flex items-center gap-1.5 text-amber-800 text-xs font-bold mb-1.5">
            <AlertTriangle className="w-4 h-4 text-amber-600 flex-shrink-0" />
            <span>Gắn cờ kiểm soát thủ công</span>
          </div>
          <div className="text-[11px] text-amber-900/80 leading-relaxed space-y-1 font-mono">
            {invoice.review_reasons!.map((reason, idx) => (
              <div key={idx} className="flex items-start gap-1">
                <span>•</span>
                <span>{reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Footer Buttons */}
      <div className="mt-auto flex flex-col gap-2 pt-2">
        <button
          type="button"
          onClick={onEditInvoice}
          className="w-full py-2 rounded-xl border border-snow-200 text-gray-700 hover:bg-snow-100 text-xs font-semibold transition card flex items-center justify-center gap-2 focus-ring"
        >
          <Pencil className="w-3.5 h-3.5 text-gray-500" />
          <span>Sửa thông tin thủ công</span>
        </button>
        <button
          type="button"
          onClick={onApproveAndNext}
          className="w-full py-2.5 rounded-xl bg-grass-600 hover:bg-grass-700 text-white text-xs font-bold transition shadow-sm shadow-grass-600/20 flex items-center justify-center gap-1.5 focus-ring"
        >
          <span>Duyệt & Sang tiếp</span>
          <ArrowRight className="w-3.5 h-3.5" />
        </button>
        <div className="text-center text-[10px] text-gray-400 font-mono">
          Phím tắt: [Enter] Duyệt · [↑ / ↓] Chọn
        </div>
      </div>
    </aside>
  );
}
