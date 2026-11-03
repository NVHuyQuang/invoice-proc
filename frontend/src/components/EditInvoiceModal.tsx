'use client';

import React, { useState, useEffect } from 'react';
import { X, Check } from 'lucide-react';
import { CanonicalInvoice } from '@/types/invoice';

interface EditInvoiceModalProps {
  isOpen: boolean;
  invoice?: CanonicalInvoice;
  onClose: () => void;
  onSave: (updatedFields: Partial<CanonicalInvoice>) => void;
}

interface EditInvoiceFormProps {
  invoice: CanonicalInvoice;
  onClose: () => void;
  onSave: (updatedFields: Partial<CanonicalInvoice>) => void;
}

function EditInvoiceForm({ invoice, onClose, onSave }: EditInvoiceFormProps) {
  const [vendorName, setVendorName] = useState(invoice.vendor_name || '');
  const [invoiceNo, setInvoiceNo] = useState(invoice.invoice_no || '');
  const [grandTotal, setGrandTotal] = useState(
    invoice.grand_total !== undefined ? String(invoice.grand_total) : ''
  );
  const [invoiceDate, setInvoiceDate] = useState(invoice.invoice_date || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsedTotal = parseFloat(grandTotal);
    onSave({
      vendor_name: vendorName.trim(),
      invoice_no: invoiceNo.trim(),
      grand_total: isNaN(parsedTotal) ? grandTotal : parsedTotal.toFixed(2),
      invoice_date: invoiceDate.trim(),
    });
    onClose();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-snow-200 overflow-hidden animate-in fade-in zoom-in-95 duration-150"
    >
      <div className="px-5 py-4 border-b border-snow-200 flex items-center justify-between bg-snow-50/50">
        <div>
          <h3 className="font-bold text-gray-900 text-sm">Sửa thông tin hóa đơn</h3>
          <p className="text-[11px] text-gray-500 font-mono mt-0.5">
            Cập nhật các trường số liệu để đối soát kế toán
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-snow-100 transition"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <form onSubmit={handleSubmit} className="p-5 space-y-4">
        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">
            Nhà cung cấp / Đơn vị bán
          </label>
          <input
            type="text"
            value={vendorName}
            onChange={(e) => setVendorName(e.target.value)}
            className="w-full px-3 py-2 text-xs border border-snow-200 rounded-lg bg-white placeholder-gray-400 text-gray-800 focus-ring font-sans"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1">
              Số HĐ / Biên lai
            </label>
            <input
              type="text"
              value={invoiceNo}
              onChange={(e) => setInvoiceNo(e.target.value)}
              className="w-full px-3 py-2 text-xs border border-snow-200 rounded-lg bg-white placeholder-gray-400 text-gray-800 focus-ring font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1">
              Ngày lập (YYYY-MM-DD)
            </label>
            <input
              type="text"
              value={invoiceDate}
              onChange={(e) => setInvoiceDate(e.target.value)}
              placeholder="2026-08-01"
              className="w-full px-3 py-2 text-xs border border-snow-200 rounded-lg bg-white placeholder-gray-400 text-gray-800 focus-ring font-mono"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-700 mb-1">
            Tổng thanh toán ($)
          </label>
          <input
            type="number"
            step="0.01"
            value={grandTotal}
            onChange={(e) => setGrandTotal(e.target.value)}
            className="w-full px-3 py-2 text-xs border border-snow-200 rounded-lg bg-white placeholder-gray-400 text-gray-800 focus-ring font-mono font-bold"
            required
          />
        </div>

        <div className="pt-3 border-t border-snow-200 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-2 text-xs font-medium text-gray-600 hover:bg-snow-100 rounded-lg transition"
          >
            Hủy
          </button>
          <button
            type="submit"
            className="flex items-center gap-1.5 px-4 py-2 bg-frost-600 text-white text-xs font-semibold rounded-lg hover:bg-frost-700 transition shadow-sm"
          >
            <Check className="w-3.5 h-3.5" />
            <span>Lưu thay đổi</span>
          </button>
        </div>
      </form>
    </div>
  );
}

export function EditInvoiceModal({
  isOpen,
  invoice,
  onClose,
  onSave,
}: EditInvoiceModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen || !invoice) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
      <EditInvoiceForm
        key={`${invoice.source_file}-${invoice.invoice_no || ''}`}
        invoice={invoice}
        onClose={onClose}
        onSave={onSave}
      />
    </div>
  );
}
