'use client';

import React from 'react';
import { Search } from 'lucide-react';
import { CanonicalInvoice, FilterType } from '@/types/invoice';

interface QueueSidebarProps {
  invoices: CanonicalInvoice[];
  selectedIndex: number;
  currentFilter: FilterType;
  searchTerm: string;
  autoReconcileRate: string;
  onSelectInvoice: (index: number) => void;
  onFilterChange: (filter: FilterType) => void;
  onSearchChange: (search: string) => void;
}

export function QueueSidebar({
  invoices,
  selectedIndex,
  currentFilter,
  searchTerm,
  autoReconcileRate,
  onSelectInvoice,
  onFilterChange,
  onSearchChange,
}: QueueSidebarProps) {
  const filterTabs: { label: string; value: FilterType }[] = [
    { label: 'All', value: 'ALL' },
    { label: 'Pass', value: 'VERIFIED' },
    { label: 'Flag', value: 'REVIEW_NEEDED' },
    { label: 'Dup', value: 'DUPLICATE' },
  ];

  return (
    <aside
      id="colQueue"
      className="w-full lg:w-72 flex flex-col gap-2 flex-shrink-0"
    >
      {/* Search Input */}
      <div className="relative">
        <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={searchTerm}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="Tìm theo nhà cung cấp, số HĐ..."
          type="text"
          className="w-full pl-8 pr-3 py-1.5 text-xs border border-snow-200 rounded-lg bg-white placeholder-gray-400 text-gray-800 focus-ring font-sans"
        />
      </div>

      {/* Queue Card */}
      <div className="card flex-1 rounded-xl overflow-hidden flex flex-col min-h-0">
        {/* Filter Tabs */}
        <div className="px-3 py-2 border-b border-snow-200 flex items-center justify-between bg-snow-50/50 flex-shrink-0">
          <span className="text-[11px] font-bold text-gray-500 uppercase tracking-wider font-mono">
            Hàng đợi ({invoices.length})
          </span>
          <div className="flex gap-1 text-[10px] font-mono">
            {filterTabs.map((tab) => {
              const isActive = currentFilter === tab.value;
              return (
                <button
                  key={tab.value}
                  type="button"
                  onClick={() => onFilterChange(tab.value)}
                  className={`px-2 py-0.5 rounded-md transition ${
                    isActive
                      ? 'font-semibold bg-white border border-snow-200 text-frost-600 shadow-[0_1px_2px_rgba(0,0,0,0.04)]'
                      : 'text-gray-500 hover:text-gray-800'
                  }`}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Invoice List */}
        <div className="flex-1 overflow-y-auto custom-scroll divide-y divide-snow-100">
          {invoices.length === 0 ? (
            <div className="p-6 text-center text-gray-400 font-mono text-xs">
              Không tìm thấy hóa đơn
            </div>
          ) : (
            invoices.map((inv, idx) => {
              const isActive = idx === selectedIndex;
              const fileName = inv.source_file.split(/[\\/]/).pop() || 'invoice.pdf';
              const vendor = inv.vendor_name || fileName;
              const total = inv.grand_total ? `$${inv.grand_total}` : '$0.00';
              const date = inv.invoice_date || 'Không có ngày';
              const itemCount =
                (inv.line_items && inv.line_items.length) ||
                (inv.charges && inv.charges.length) ||
                0;

              let tagElem = <span className="tag tag-pass">PASS</span>;
              if (inv.status === 'REVIEW_NEEDED') {
                tagElem = <span className="tag tag-flag">FLAG</span>;
              } else if (inv.status === 'FAILED') {
                tagElem = <span className="tag tag-fail">FAIL</span>;
              } else if (inv.status === 'DUPLICATE' || inv.is_duplicate) {
                tagElem = <span className="tag tag-dup">DUP</span>;
              }

              return (
                <div
                  key={`${inv.source_file}-${idx}`}
                  onClick={() => onSelectInvoice(idx)}
                  className={`p-3 cursor-pointer transition select-none ${
                    isActive ? 'active-row' : 'hover:bg-snow-50'
                  }`}
                >
                  <div className="flex items-start justify-between gap-1">
                    <div className="min-w-0 flex-1">
                      <div className="text-xs font-semibold text-gray-900 truncate">
                        {vendor}
                      </div>
                      <div className="text-[10px] text-gray-400 font-mono mt-0.5 truncate">
                        {date} · {itemCount} mục
                      </div>
                    </div>
                    <div className="flex-shrink-0 text-right ml-2">
                      <div className="text-xs font-bold text-gray-900 font-mono">
                        {total}
                      </div>
                      <div className="mt-0.5 flex justify-end">{tagElem}</div>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer Batch Info */}
        <div className="p-2.5 border-t border-snow-200 bg-snow-50 text-[11px] font-mono text-gray-500 flex justify-between flex-shrink-0">
          <span>Batch: 08.Aug 2026</span>
          <span className="text-grass-600 font-bold">{autoReconcileRate}</span>
        </div>
      </div>
    </aside>
  );
}
