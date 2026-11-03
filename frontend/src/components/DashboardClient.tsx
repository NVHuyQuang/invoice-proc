'use client';

import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { CanonicalInvoice, FilterType } from '@/types/invoice';
import { fetchInvoices, uploadSingleInvoice, uploadBatchInvoices, getDownloadExcelUrl } from '@/lib/api';
import { Header } from './Header';
import { QueueSidebar } from './QueueSidebar';
import { Workspace } from './Workspace';
import { AuditInspector } from './AuditInspector';
import { EditInvoiceModal } from './EditInvoiceModal';
import { AlertCircle, CheckCircle } from 'lucide-react';

export function DashboardClient() {
  const [invoices, setInvoices] = useState<CanonicalInvoice[]>([]);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);
  const [currentFilter, setCurrentFilter] = useState<FilterType>('ALL');
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [currentMobileTab, setCurrentMobileTab] = useState<'queue' | 'workspace' | 'inspector'>('queue');
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState<boolean>(false);
  const [toast, setToast] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Load initial invoices on mount
  useEffect(() => {
    async function load() {
      const data = await fetchInvoices();
      setInvoices(data);
    }
    load();
  }, []);

  // Filtered invoices
  const filteredInvoices = useMemo(() => {
    const term = searchTerm.toLowerCase().trim();
    return invoices.filter((inv) => {
      if (currentFilter !== 'ALL' && inv.status !== currentFilter) {
        return false;
      }
      if (term) {
        const matchVendor = (inv.vendor_name || '').toLowerCase().includes(term);
        const matchInvNo = (inv.invoice_no || '').toLowerCase().includes(term);
        const matchFile = (inv.source_file || '').toLowerCase().includes(term);
        if (!matchVendor && !matchInvNo && !matchFile) return false;
      }
      return true;
    });
  }, [invoices, currentFilter, searchTerm]);

  // Safe selected index
  const activeIndex = Math.min(selectedIndex, Math.max(0, filteredInvoices.length - 1));
  const activeInvoice = filteredInvoices[activeIndex];

  // Pipeline metrics
  const verifiedCount = useMemo(
    () => invoices.filter((i) => i.status === 'VERIFIED').length,
    [invoices]
  );
  const reviewCount = useMemo(
    () => invoices.filter((i) => i.status === 'REVIEW_NEEDED').length,
    [invoices]
  );
  const duplicateCount = useMemo(
    () => invoices.filter((i) => i.status === 'DUPLICATE' || i.is_duplicate).length,
    [invoices]
  );
  const autoReconcileRate = useMemo(() => {
    if (invoices.length === 0) return '0.0% Auto-Pass';
    return `${((verifiedCount / invoices.length) * 100).toFixed(1)}% Auto-Pass`;
  }, [invoices.length, verifiedCount]);

  const totalSpend = useMemo(() => {
    return invoices.reduce((acc, curr) => {
      const val = parseFloat(String(curr.grand_total)) || 0;
      return acc + val;
    }, 0);
  }, [invoices]);

  // Actions
  const handleApproveAndNext = useCallback(() => {
    if (!activeInvoice) return;

    setInvoices((prev) =>
      prev.map((inv) =>
        inv === activeInvoice
          ? { ...inv, status: 'VERIFIED', review_reasons: [] }
          : inv
      )
    );

    if (activeIndex < filteredInvoices.length - 1) {
      setSelectedIndex(activeIndex + 1);
    }
  }, [activeInvoice, activeIndex, filteredInvoices.length]);

  const handleEditSave = useCallback(
    (updatedFields: Partial<CanonicalInvoice>) => {
      if (!activeInvoice) return;

      setInvoices((prev) =>
        prev.map((inv) =>
          inv === activeInvoice ? { ...inv, ...updatedFields } : inv
        )
      );

      setToast({
        type: 'success',
        message: 'Cập nhật thông tin hóa đơn thành công!',
      });
      setTimeout(() => setToast(null), 3000);
    },
    [activeInvoice]
  );

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setIsUploading(true);
    setToast(null);

    const fileArray = Array.from(files);

    try {
      if (fileArray.length === 1) {
        const result = await uploadSingleInvoice(fileArray[0], '2026-08');
        setInvoices((prev) => [result, ...prev]);
        setSelectedIndex(0);
        setCurrentFilter('ALL');
        setToast({
          type: 'success',
          message: `Xử lý thành công hóa đơn ${result.vendor_name || result.source_file} ($${result.grand_total || '0.00'})`,
        });
      } else {
        const batchResult = await uploadBatchInvoices(fileArray, '2026-08', 8);
        if (batchResult.invoices && batchResult.invoices.length > 0) {
          setInvoices((prev) => [...batchResult.invoices, ...prev]);
          setSelectedIndex(0);
          setCurrentFilter('ALL');
        }
        setToast({
          type: 'success',
          message: `Xử lý hoàn tất ${batchResult.total_files} files! (${batchResult.verified_count} verified, ${batchResult.review_needed_count} cần duyệt)`,
        });
      }
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : 'Lỗi không xác định khi tải lên';
      setToast({
        type: 'error',
        message: errMsg,
      });
    } finally {
      setIsUploading(false);
      setTimeout(() => setToast(null), 4000);
    }
  };

  const handleDownloadExcel = () => {
    window.open(getDownloadExcelUrl('2026-08'), '_blank');
  };

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore if currently typing inside an input/textarea or if modal is open
      const target = e.target as HTMLElement | null;
      if (
        isEditModalOpen ||
        target?.tagName === 'INPUT' ||
        target?.tagName === 'TEXTAREA' ||
        target?.tagName === 'SELECT'
      ) {
        return;
      }

      if (e.key === 'Enter') {
        e.preventDefault();
        handleApproveAndNext();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (activeIndex < filteredInvoices.length - 1) {
          setSelectedIndex(activeIndex + 1);
        }
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (activeIndex > 0) {
          setSelectedIndex(activeIndex - 1);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [activeIndex, filteredInvoices.length, handleApproveAndNext, isEditModalOpen]);

  const handleSelectInvoice = (index: number) => {
    setSelectedIndex(index);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      setCurrentMobileTab('workspace');
    }
  };

  return (
    <div className="h-screen flex flex-col overflow-hidden text-sm">
      {/* Top Header */}
      <Header
        verifiedCount={verifiedCount}
        reviewCount={reviewCount}
        duplicateCount={duplicateCount}
        totalSpend={totalSpend}
        isUploading={isUploading}
        onFileUpload={handleFileUpload}
        onDownloadExcel={handleDownloadExcel}
      />

      {/* Toast Notification */}
      {toast && (
        <div
          className={`fixed top-16 right-4 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl border shadow-lg text-xs font-medium animate-in fade-in slide-in-from-top-2 duration-200 ${
            toast.type === 'success'
              ? 'bg-grass-50 border-grass-200 text-grass-700'
              : 'bg-ember-50 border-ember-200 text-ember-700'
          }`}
        >
          {toast.type === 'success' ? (
            <CheckCircle className="w-4 h-4 text-grass-600 flex-shrink-0" />
          ) : (
            <AlertCircle className="w-4 h-4 text-ember-600 flex-shrink-0" />
          )}
          <span>{toast.message}</span>
        </div>
      )}

      {/* Mobile Segmented Tab Switcher (Visible only on < lg screens) */}
      <div className="flex lg:hidden bg-white border-b border-snow-200 px-3 py-1.5 gap-2 text-xs font-mono overflow-x-auto flex-shrink-0 shadow-[0_1px_2px_rgba(0,0,0,0.03)]">
        <button
          type="button"
          onClick={() => setCurrentMobileTab('queue')}
          className={`flex-1 py-1.5 px-2 rounded-lg transition text-center ${
            currentMobileTab === 'queue'
              ? 'font-bold bg-frost-50 text-frost-600 border border-frost-200 shadow-[0_1px_2px_rgba(0,0,0,0.04)]'
              : 'text-gray-500 hover:bg-snow-100'
          }`}
        >
          Hàng đợi ({filteredInvoices.length})
        </button>
        <button
          type="button"
          onClick={() => setCurrentMobileTab('workspace')}
          className={`flex-1 py-1.5 px-2 rounded-lg transition text-center ${
            currentMobileTab === 'workspace'
              ? 'font-bold bg-frost-50 text-frost-600 border border-frost-200 shadow-[0_1px_2px_rgba(0,0,0,0.04)]'
              : 'text-gray-500 hover:bg-snow-100'
          }`}
        >
          Chi tiết & Bảng kê
        </button>
        <button
          type="button"
          onClick={() => setCurrentMobileTab('inspector')}
          className={`flex-1 py-1.5 px-2 rounded-lg transition text-center ${
            currentMobileTab === 'inspector'
              ? 'font-bold bg-frost-50 text-frost-600 border border-frost-200 shadow-[0_1px_2px_rgba(0,0,0,0.04)]'
              : 'text-gray-500 hover:bg-snow-100'
          }`}
        >
          Kiểm toán 4 Tầng
        </button>
      </div>

      {/* Main Work Area (3 Columns: Queue | Workspace | Audit Inspector) */}
      <div className="flex-1 flex flex-col lg:flex-row gap-3 p-3 overflow-hidden bg-[#f0f2f5]">
        {/* Left Column: Invoice Queue */}
        <div className={`h-full flex flex-col lg:flex ${currentMobileTab === 'queue' ? 'flex' : 'hidden lg:flex'}`}>
          <QueueSidebar
            invoices={filteredInvoices}
            selectedIndex={activeIndex}
            currentFilter={currentFilter}
            searchTerm={searchTerm}
            autoReconcileRate={autoReconcileRate}
            onSelectInvoice={handleSelectInvoice}
            onFilterChange={(filter) => {
              setCurrentFilter(filter);
              setSelectedIndex(0);
            }}
            onSearchChange={(search) => {
              setSearchTerm(search);
              setSelectedIndex(0);
            }}
          />
        </div>

        {/* Center Column: Workspace */}
        <div className={`h-full flex-1 flex flex-col min-w-0 ${currentMobileTab === 'workspace' ? 'flex' : 'hidden lg:flex'}`}>
          <Workspace
            invoice={activeInvoice}
            onBackToQueue={() => setCurrentMobileTab('queue')}
          />
        </div>

        {/* Right Column: Audit Inspector */}
        <div className={`h-full flex flex-col lg:flex ${currentMobileTab === 'inspector' ? 'flex' : 'hidden lg:flex'}`}>
          <AuditInspector
            invoice={activeInvoice}
            onApproveAndNext={handleApproveAndNext}
            onEditInvoice={() => setIsEditModalOpen(true)}
            onBackToWorkspace={() => setCurrentMobileTab('workspace')}
          />
        </div>
      </div>

      {/* Edit Invoice Modal */}
      <EditInvoiceModal
        isOpen={isEditModalOpen}
        invoice={activeInvoice}
        onClose={() => setIsEditModalOpen(false)}
        onSave={handleEditSave}
      />
    </div>
  );
}
