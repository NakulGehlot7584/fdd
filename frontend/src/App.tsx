import React, { useEffect, useState, useMemo } from 'react';
import { DatasetManagement } from './components/DatasetManagement';
import { DataQualitySection } from './components/DataQualitySection';
import { CanonicalMappingSection } from './components/CanonicalMappingSection';
import { RuleReadinessSection } from './components/RuleReadinessSection';
import { ResultValidationSection } from './components/ResultValidationSection';
import { SidebarThresholds } from './components/SidebarThresholds';
import { FDDResultsView } from './components/FDDResultsView';
import {
  getDatasets,
  getDatasetDetails,
  deleteDataset,
  executeRulesForEquipment,
} from './services/api';
import {
  DatasetDetailResponse,
  DatasetSummary,
  FDDExecutionSummary,
} from './types/api';
import { Loader2, AlertCircle, RefreshCw, Play } from 'lucide-react';

export const App: React.FC = () => {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [currentDataset, setCurrentDataset] = useState<DatasetDetailResponse | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Two-View Navigation State: View 1 (Data Prep) vs View 2 (FDD Results)
  const [currentView, setCurrentView] = useState<'data_prep' | 'results'>('data_prep');

  // FDD Execution State
  const [parameterOverrides, setParameterOverrides] = useState<Record<string, Record<string, number>>>({});
  const [executionSummary, setExecutionSummary] = useState<FDDExecutionSummary | null>(null);
  const [isRunningFDD, setIsRunningFDD] = useState<boolean>(false);

  // Sidebar UI State
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(true);

  const fetchDatasets = async (targetIdToSelect?: string) => {
    setIsLoadingList(true);
    setErrorMessage(null);
    try {
      const res = await getDatasets();
      setDatasets(res.datasets);

      if (res.datasets.length > 0) {
        const nextId =
          targetIdToSelect && res.datasets.some((d) => d.dataset_id === targetIdToSelect)
            ? targetIdToSelect
            : selectedId && res.datasets.some((d) => d.dataset_id === selectedId)
            ? selectedId
            : res.datasets[0].dataset_id;
        setSelectedId(nextId);
      } else {
        setSelectedId(null);
        setCurrentDataset(null);
        setExecutionSummary(null);
      }
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to connect to Open-FDD backend');
    } finally {
      setIsLoadingList(false);
    }
  };

  useEffect(() => {
    fetchDatasets();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setCurrentDataset(null);
      setExecutionSummary(null);
      return;
    }

    const loadDetails = async () => {
      setIsLoadingDetail(true);
      setExecutionSummary(null);
      try {
        const details = await getDatasetDetails(selectedId);
        setCurrentDataset(details);
      } catch (err: any) {
        setErrorMessage(`Failed to load dataset details: ${err.message}`);
      } finally {
        setIsLoadingDetail(false);
      }
    };

    loadDetails();
  }, [selectedId]);

  // Reactive automatic FDD Execution upon dataset load or threshold parameter changes
  useEffect(() => {
    if (!currentDataset) {
      setExecutionSummary(null);
      return;
    }

    const timer = setTimeout(() => {
      const equipmentId = currentDataset.equipment_id || currentDataset.dataset_id;
      if (!equipmentId) return;

      setIsRunningFDD(true);
      executeRulesForEquipment(equipmentId, currentDataset.building_id, {
        parameter_overrides: parameterOverrides,
      })
        .then((summary) => {
          setExecutionSummary(summary);
        })
        .catch((err: any) => {
          setErrorMessage(`FDD Execution Error: ${err.message}`);
        })
        .finally(() => {
          setIsRunningFDD(false);
        });
    }, 350);

    return () => clearTimeout(timer);
  }, [currentDataset, parameterOverrides]);

  const handleRunFDD = async () => {
    if (!currentDataset) return;
    const equipmentId = currentDataset.equipment_id || currentDataset.dataset_id;
    if (!equipmentId) return;

    setIsRunningFDD(true);
    setErrorMessage(null);
    try {
      const summary = await executeRulesForEquipment(equipmentId, currentDataset.building_id, {
        parameter_overrides: parameterOverrides,
      });
      setExecutionSummary(summary);
      setCurrentView('results');
    } catch (err: any) {
      setErrorMessage(`FDD Execution Error: ${err.message}`);
    } finally {
      setIsRunningFDD(false);
    }
  };

  const handleDeleteDataset = async (id: string) => {
    try {
      await deleteDataset(id);
      const remaining = datasets.filter((d) => d.dataset_id !== id);
      setDatasets(remaining);
      if (remaining.length > 0) {
        setSelectedId(remaining[0].dataset_id);
      } else {
        setSelectedId(null);
        setCurrentDataset(null);
        setExecutionSummary(null);
      }
    } catch (err: any) {
      setErrorMessage(`Failed to delete dataset: ${err.message}`);
    }
  };

  const handleClearAll = async () => {
    for (const d of datasets) {
      try {
        await deleteDataset(d.dataset_id);
      } catch (e) {
        // Continue cleaning up remaining datasets
      }
    }
    setDatasets([]);
    setSelectedId(null);
    setCurrentDataset(null);
    setExecutionSummary(null);
  };

  const totalDetectedFaults = useMemo(() => {
    if (!executionSummary) return 0;
    let cnt = 0;
    for (const r of executionSummary.results) {
      for (const f of r.findings) {
        if (f.fault_detected) cnt++;
      }
    }
    return cnt;
  }, [executionSummary]);

  return (
    <div className="min-h-screen bg-[#0e1117] text-[#fafafa] flex font-sans select-none">
      {/* Streamlit st.sidebar docked on left */}
      <SidebarThresholds
        isOpen={isSidebarOpen}
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
        onThresholdsChange={setParameterOverrides}
        isRunExecuted={Boolean(executionSummary)}
        onApplyAndRerun={handleRunFDD}
      />

      {/* Main Page Layout Area (Offset by sidebar width) */}
      <div
        className={`flex-1 flex flex-col min-w-0 transition-all duration-300 ${
          isSidebarOpen ? 'md:ml-[21rem]' : 'md:ml-10'
        }`}
      >
        {/* Global Error Banner */}
        {errorMessage && (
          <div className="mx-6 mt-3 st-alert-error text-xs flex items-center justify-between font-mono">
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0 text-[#BD4043]" />
              <span>{errorMessage}</span>
            </div>
            <button
              onClick={() => fetchDatasets()}
              className="st-button-secondary text-xs px-2.5 py-1"
            >
              <RefreshCw className="w-3 h-3" /> Retry
            </button>
          </div>
        )}

        {/* Main Content Area */}
        <main className="px-6 py-6 space-y-5 max-w-6xl w-full mx-auto flex-1">
        {/* Title Header matching Streamlit st.title */}
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-[#fafafa] tracking-tight">
            AHU Multi-Point Fault Detection &amp; Diagnostics
          </h1>
        </div>

        {/* Two-View Navigation Tabs */}
        <div className="flex border-b border-[rgba(250,250,250,0.12)]">
          <button
            type="button"
            id="view-data-prep-btn"
            onClick={() => setCurrentView('data_prep')}
            className={`st-tab-btn flex items-center gap-2 ${
              currentView === 'data_prep' ? 'st-tab-btn-active' : ''
            }`}
          >
            <span>📁 CSV Import &amp; Data Preparation</span>
          </button>
          <button
            type="button"
            id="view-results-btn"
            onClick={() => setCurrentView('results')}
            className={`st-tab-btn flex items-center gap-2 ${
              currentView === 'results' ? 'st-tab-btn-active' : ''
            }`}
          >
            <span>📊 FDD Results &amp; Diagnostics</span>
            {totalDetectedFaults > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-mono bg-[#FF4B4B] text-white font-bold leading-none">
                {totalDetectedFaults}
              </span>
            )}
          </button>
        </div>

        {/* VIEW 1: CSV IMPORT & DATA PREPARATION */}
        {currentView === 'data_prep' && (
          <div className="space-y-5 pt-1">
            {/* Multi-file uploader and active site selector matching st.file_uploader & st.selectbox */}
            <DatasetManagement
              datasets={datasets}
              selectedId={selectedId}
              currentDataset={currentDataset}
              onSelectDataset={(id) => setSelectedId(id)}
              onDeleteDataset={handleDeleteDataset}
              onClearAll={handleClearAll}
              onUploadSuccess={(uploadRes) => {
                const firstNewId = uploadRes.datasets[0]?.dataset_id;
                fetchDatasets(firstNewId);
              }}
            />

            {isLoadingList ? (
              <div className="flex flex-col items-center justify-center gap-2 text-[#808495] text-xs py-20 font-mono">
                <Loader2 className="w-6 h-6 animate-spin text-[#FF4B4B]" />
                <span>Connecting to dataset registry...</span>
              </div>
            ) : isLoadingDetail ? (
              <div className="flex flex-col items-center justify-center gap-2 text-[#808495] text-xs py-20 font-mono">
                <Loader2 className="w-6 h-6 animate-spin text-[#FF4B4B]" />
                <span>Analyzing telemetry &amp; discovering canonical roles...</span>
              </div>
            ) : currentDataset ? (
              <div className="space-y-4">
                {/* Expander 1: Input Data Quality & Validation */}
                <DataQualitySection dataset={currentDataset} />

                {/* Expander 2: Canonical Point Mapping & Telemetry Discovery */}
                <CanonicalMappingSection dataset={currentDataset} />

                {/* Expander 3: Official Open-FDD Universal Catalog Readiness & Subsystem Audit */}
                <RuleReadinessSection
                  dataset={currentDataset}
                  executionSummary={executionSummary}
                />

                {/* Expander 4: FDD Result & Evidence Validation */}
                <ResultValidationSection
                  equipmentId={currentDataset.equipment_id || currentDataset.dataset_id}
                  buildingId={currentDataset.building_id}
                />

                {/* Primary Action Button: Run FDD Analysis & View Results */}
                <div className="pt-2 flex justify-end">
                  <button
                    type="button"
                    id="run-fdd-main-btn"
                    onClick={handleRunFDD}
                    disabled={isRunningFDD}
                    className="st-button-primary text-sm px-6 py-2.5 flex items-center gap-2 font-semibold shadow-sm"
                  >
                    {isRunningFDD ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Evaluating Open-FDD Rules...
                      </>
                    ) : (
                      <>
                        <Play className="w-4 h-4 fill-current" />
                        Run FDD Analysis &amp; View Results →
                      </>
                    )}
                  </button>
                </div>
              </div>
            ) : (
              <div className="st-alert-info text-xs py-4 text-center">
                Please upload a CSV dataset or select an existing dataset above to begin.
              </div>
            )}
          </div>
        )}

        {/* VIEW 2: FDD RESULTS & DIAGNOSTICS */}
        {currentView === 'results' && (
          <div className="space-y-4 pt-1">
            {isRunningFDD && (
              <div className="flex items-center gap-2 text-xs text-[#0054A3] font-mono py-2 bg-[rgba(28,131,225,0.08)] px-3 rounded border border-[rgba(28,131,225,0.3)]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Evaluating official Open-FDD SQL rules against canonical Parquet telemetry...</span>
              </div>
            )}

            {executionSummary && currentDataset ? (
              <FDDResultsView
                summary={executionSummary}
                equipmentId={currentDataset.equipment_id || currentDataset.dataset_id || ''}
                buildingId={currentDataset.building_id}
                availableEquipment={datasets.map((d) => d.equipment_id || d.dataset_id).filter(Boolean)}
                onSelectEquipment={(eq) => {
                  const matched = datasets.find((d) => (d.equipment_id || d.dataset_id) === eq);
                  if (matched && matched.dataset_id !== selectedId) {
                    setSelectedId(matched.dataset_id);
                  }
                }}
              />
            ) : currentDataset ? (
              <div className="st-alert-info text-xs py-8 text-center space-y-3">
                <p className="font-semibold text-sm">No FDD Analysis has been executed yet for this dataset.</p>
                <p className="text-[#808495]">Click the button below to evaluate all applicable Open-FDD rules against canonical telemetry.</p>
                <button
                  type="button"
                  onClick={handleRunFDD}
                  className="st-button-primary text-xs px-4 py-2 inline-flex items-center gap-1.5 font-semibold"
                >
                  <Play className="w-3.5 h-3.5 fill-current" /> Run FDD Analysis Now
                </button>
              </div>
            ) : (
              <div className="st-alert-info text-xs py-4 text-center">
                Please upload or select a dataset in CSV Import &amp; Data Preparation first.
              </div>
            )}
          </div>
        )}
        </main>

        {/* Streamlit Footer */}
        <footer className="px-6 py-4 border-t border-[rgba(250,250,250,0.12)] bg-[#1e2129] text-center text-xs text-[#a3a8b8] font-mono">
          Open-FDD Telemetry &amp; Diagnostics Pipeline • 100% Zero-Hardcoding Engine
        </footer>
      </div>
    </div>
  );
};
