import React, { useState, useRef, useEffect } from 'react';
import { Database, Play, MoreVertical, X } from 'lucide-react';
import { DatasetDetailResponse } from '../types/api';
import { ThresholdControl } from './ThresholdControl';

interface HeaderProps {
  currentDataset: DatasetDetailResponse | null;
  activeView: 'import' | 'results';
  onSelectView: (view: 'import' | 'results') => void;
  faultCount?: number;
  onRunFDD?: () => void;
  isRunning?: boolean;
  onThresholdsChange: (overrides: Record<string, Record<string, number>>) => void;
  isRunExecuted?: boolean;
  isAdvancedDrawerOpen?: boolean;
  onToggleAdvancedDrawer?: (open: boolean) => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentDataset,
  activeView,
  onSelectView,
  faultCount = 0,
  onRunFDD,
  isRunning = false,
  onThresholdsChange,
  isRunExecuted = false,
  isAdvancedDrawerOpen,
  onToggleAdvancedDrawer,
}) => {
  const [internalMenuOpen, setInternalMenuOpen] = useState(false);
  const isMenuOpen = isAdvancedDrawerOpen !== undefined ? isAdvancedDrawerOpen : internalMenuOpen;
  const setIsMenuOpen = onToggleAdvancedDrawer || setInternalMenuOpen;
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on click outside or Escape key
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsMenuOpen(false);
      }
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setIsMenuOpen(false);
      }
    };

    if (isMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [isMenuOpen, setIsMenuOpen]);

  return (
    <header className="px-6 pt-6 pb-2 select-none font-sans bg-[#0e1117] relative">
      <div className="flex flex-wrap items-start justify-between gap-4">
        {/* Title & Caption matching st.title and st.caption */}
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#fafafa] tracking-tight">
            AHU Multi-Point Fault Detection & Diagnostics
          </h1>
        </div>

        {/* Right: Actions, Active dataset badge, and Three-Dot Menu (⋮) */}
        <div className="flex items-center gap-3">
          {currentDataset && onRunFDD && (
            <button
              type="button"
              onClick={onRunFDD}
              disabled={isRunning}
              className="st-button-primary text-xs"
            >
              <Play className={`w-3.5 h-3.5 fill-current ${isRunning ? 'animate-spin' : ''}`} />
              <span>{isRunning ? 'Evaluating Rules...' : 'Run FDD Diagnostics ▶'}</span>
            </button>
          )}

          <div className="px-3 py-1.5 rounded bg-[#262730] border border-[#383b42] text-[#8ec8f6] text-xs font-mono flex items-center gap-2">
            <Database className="w-3.5 h-3.5 text-[#808495] shrink-0" />
            <span className="text-[#808495] hidden sm:inline">Active:</span>
            <span className="font-semibold text-[#fafafa] truncate max-w-[180px]">
              {currentDataset ? currentDataset.file_name : 'No dataset'}
            </span>
          </div>

          {/* Three-Dot Menu Button (⋮) */}
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              title="Rule Thresholds & Parameters"
              aria-label="Rule Thresholds"
              className={`p-2 rounded bg-[#262730] hover:bg-[#31333f] text-[#808495] hover:text-[#fafafa] border ${
                isMenuOpen ? 'border-[#ff4b4b] text-[#fafafa]' : 'border-[#383b42]'
              } transition-colors cursor-pointer flex items-center justify-center`}
            >
              <MoreVertical className="w-4 h-4" />
            </button>

            {/* Compact Floating Thresholds Overlay Dropdown */}
            {isMenuOpen && (
              <div className="absolute right-0 top-12 z-50 w-[92vw] sm:w-[540px] max-h-[85vh] overflow-y-auto bg-[#262730] border border-[#383b42] rounded shadow-2xl p-4 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-[#383b42]">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[#fafafa]">
                    Rule Thresholds
                  </span>
                  <button
                    type="button"
                    onClick={() => setIsMenuOpen(false)}
                    className="text-[#808495] hover:text-[#fafafa] p-1 rounded hover:bg-[#31333f]"
                    title="Close"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>

                <ThresholdControl
                  onThresholdsChange={onThresholdsChange}
                  isRunExecuted={isRunExecuted}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Streamlit Tab Bar for Workflow Views */}
      <div className="flex border-b border-[#383b42] mt-5">
        <button
          type="button"
          id="view-data-prep-btn"
          onClick={() => onSelectView('import')}
          className={`st-tab-btn ${activeView === 'import' ? 'st-tab-btn-active' : ''}`}
        >
          📁 CSV Import & Data Preparation
        </button>

        <button
          type="button"
          id="view-results-btn"
          onClick={() => onSelectView('results')}
          disabled={!currentDataset}
          className={`st-tab-btn ${activeView === 'results' ? 'st-tab-btn-active' : ''} ${
            !currentDataset ? 'opacity-40 cursor-not-allowed' : ''
          }`}
        >
          📊 FDD Results & Diagnostics {faultCount > 0 ? `(${faultCount})` : ''}
        </button>
      </div>
    </header>
  );
};
