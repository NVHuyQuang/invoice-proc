'use client';

import React, { useRef } from 'react';
import { Upload, Download, Loader2 } from 'lucide-react';

interface HeaderProps {
  verifiedCount: number;
  reviewCount: number;
  duplicateCount: number;
  totalSpend: number;
  isUploading: boolean;
  onFileUpload: (files: FileList | null) => void;
  onDownloadExcel: () => void;
}

export function Header({
  verifiedCount,
  reviewCount,
  duplicateCount,
  totalSpend,
  isUploading,
  onFileUpload,
  onDownloadExcel,
}: HeaderProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);

  const formattedSpend = `$${totalSpend.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

  const handleButtonClick = () => {
    fileInputRef.current?.click();
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileUpload(e.target.files);
      // Reset input value so subsequent uploads of the same file trigger onChange
      e.target.value = '';
    }
  };

  return (
    <header
      className="min-h-14 bg-white border-b border-snow-200 px-4 lg:px-6 py-2.5 lg:py-0 flex flex-wrap lg:flex-nowrap items-center justify-between flex-shrink-0 z-10 gap-2 shadow-[0_1px_2px_rgba(0,0,0,0.03)]"
    >
      <div className="flex items-center gap-3 lg:gap-4 flex-wrap">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-frost-600 flex items-center justify-center text-white font-bold text-sm shadow-sm font-mono tracking-tight">
            4P
          </div>
          <div>
            <div className="font-bold text-gray-900 text-sm leading-none flex items-center gap-2">
              Invoice Processor
              <span className="text-gray-400 font-mono text-[11px] font-normal">
                v3.0 VLM
              </span>
            </div>
            <div className="text-[10px] text-gray-500 font-mono mt-0.5">
              Kỳ kế toán: 2026-08 (±45 ngày)
            </div>
          </div>
        </div>

        <div className="h-5 w-px bg-snow-200 mx-1 hidden sm:block" />

        {/* Live Pipeline Stats Pills */}
        <div className="flex items-center gap-1.5 sm:gap-2 text-xs flex-wrap">
          <div className="flex items-center gap-1.5 bg-snow-100 text-gray-600 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full border border-snow-200">
            <span className="w-1.5 h-1.5 rounded-full bg-grass-500" />
            <span>
              <strong className="text-gray-900 font-mono">{verifiedCount}</strong> verified
            </span>
          </div>
          <div className="flex items-center gap-1.5 bg-amber-50 text-amber-800 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full border border-amber-200/60">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            <span>
              <strong className="text-amber-900 font-mono">{reviewCount}</strong> cần duyệt
            </span>
          </div>
          <div className="flex items-center gap-1.5 bg-snow-100 text-gray-500 px-2 py-0.5 sm:px-2.5 sm:py-1 rounded-full border border-snow-200">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            <span>
              <strong className="text-gray-800 font-mono">{duplicateCount}</strong> trùng
            </span>
          </div>
          <div className="hidden md:flex items-center gap-1.5 bg-frost-50 text-frost-700 px-2.5 py-1 rounded-full border border-frost-200/60 font-mono text-[11px]">
            <span className="w-1.5 h-1.5 rounded-full bg-frost-500 animate-pulse" />
            <span>Gemini 3.8 Flash (VLM)</span>
          </div>
        </div>
      </div>

      {/* Right Header Actions */}
      <div className="flex items-center gap-2 sm:gap-3 ml-auto">
        <div className="text-right font-mono text-xs hidden lg:block mr-2">
          <span className="text-gray-400">Tổng chi phí:</span>
          <span className="font-bold text-gray-900 text-sm ml-1">
            {formattedSpend}
          </span>
        </div>

        {/* Upload Trigger Button */}
        <button
          type="button"
          disabled={isUploading}
          onClick={handleButtonClick}
          className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-lg border border-snow-200 text-gray-700 hover:bg-snow-100 text-xs font-medium transition focus-ring disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isUploading ? (
            <Loader2 className="w-3.5 h-3.5 text-frost-600 animate-spin" />
          ) : (
            <Upload className="w-3.5 h-3.5 text-frost-600" />
          )}
          <span>{isUploading ? 'Đang tải...' : 'Tải lên'}</span>
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.png,.jpg,.jpeg,.webp,.heic"
          className="hidden"
          onChange={handleInputChange}
        />

        {/* Export Excel Button */}
        <button
          type="button"
          onClick={onDownloadExcel}
          className="flex items-center gap-1.5 px-3 sm:px-3.5 py-1.5 rounded-lg bg-frost-600 text-white text-xs font-semibold hover:bg-frost-700 transition focus-ring shadow-sm shadow-frost-600/20"
        >
          <Download className="w-3.5 h-3.5" />
          <span>Xuất Excel</span>
        </button>
      </div>
    </header>
  );
}
