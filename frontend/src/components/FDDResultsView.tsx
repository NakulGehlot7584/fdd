import React, { useState, useEffect, useMemo } from 'react';
import {
  Download,
  ChevronDown,
  ChevronUp,
  Table,
} from 'lucide-react';
import {
  FDDExecutionSummary,
  FaultDetailRecord,
  GraphPayload,
  FaultTimelinePayload,
} from '../types/api';
import {
  getEquipmentFaults,
  getTelemetryGraph,
  getRuleGraph,
  getFaultTimeline,
  getHistorianEquipmentTelemetry,
} from '../services/api';
import { TelemetryGraph } from './TelemetryGraph';
import { FaultTimelineGraph } from './FaultTimelineGraph';

interface Props {
  summary: FDDExecutionSummary;
  equipmentId: string;
  buildingId?: string | null;
  availableEquipment?: string[];
  onSelectEquipment?: (eq: string) => void;
}

export const FDDResultsView: React.FC<Props> = ({
  summary,
  equipmentId,
  buildingId,
  availableEquipment = [],
  onSelectEquipment,
}) => {
  const [selectedEquipment, setSelectedEquipment] = useState<string>(equipmentId);
  const [activeTab, setActiveTab] = useState<'faults' | 'temperature' | 'airside' | 'chw'>('faults');
  const [faultDetails, setFaultDetails] = useState<FaultDetailRecord[]>([]);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [ruleGraphData, setRuleGraphData] = useState<GraphPayload | null>(null);
  const [timelineData, setTimelineData] = useState<FaultTimelinePayload | null>(null);
  const [tempGraphData, setTempGraphData] = useState<GraphPayload | null>(null);
  const [airsideGraphData, setAirsideGraphData] = useState<GraphPayload | null>(null);
  const [chwGraphData, setChwGraphData] = useState<GraphPayload | null>(null);
  const [isEpisodesExpanded, setIsEpisodesExpanded] = useState<boolean>(false);

  // Normalized sensor data table state
  const [normalizedRecords, setNormalizedRecords] = useState<Record<string, any>[]>([]);
  const [normalizedColumns, setNormalizedColumns] = useState<string[]>([]);
  const [isLoadingNormalized, setIsLoadingNormalized] = useState<boolean>(false);

  // Sync selectedEquipment when prop changes
  useEffect(() => {
    if (equipmentId && selectedEquipment !== 'All AHUs') {
      setSelectedEquipment(equipmentId);
    }
  }, [equipmentId]);

  const eqList = useMemo(() => {
    const set = new Set<string>();
    if (equipmentId) set.add(equipmentId);
    for (const eq of availableEquipment) {
      if (eq) set.add(eq);
    }
    for (const r of summary.results) {
      for (const f of r.findings) {
        if (f.equipment_id) set.add(f.equipment_id);
      }
    }
    return Array.from(set).sort();
  }, [equipmentId, availableEquipment, summary]);

  const isFleetView = selectedEquipment === 'All AHUs';
  const effectiveEquipmentId = isFleetView ? (eqList[0] || equipmentId) : selectedEquipment;

  // Equipment options matching st.selectbox("Equipment", ...)
  const equipmentOptions = useMemo(() => {
    if (eqList.length > 1) {
      return ['All AHUs', ...eqList];
    }
    return eqList.length > 0 ? eqList : [equipmentId];
  }, [eqList, equipmentId]);

  // Grouped findings from execution summary
  const findingsList = useMemo(() => {
    const list: Array<{
      equipment_id: string;
      rule_id: string;
      fault_name: string;
      severity: string;
      samples: number;
      episodes: number;
      total_duration_hours: number;
      first_seen?: string;
      last_seen?: string;
      detail?: FaultDetailRecord;
      display_label: string;
    }> = [];

    for (const r of summary.results) {
      for (const f of r.findings) {
        if (f.fault_detected) {
          const eqVal = f.equipment_id || summary.equipment_id || equipmentId;
          const codeVal = f.rule_id;
          const nameVal = f.detail?.title || f.description;
          const sevVal = f.severity || f.detail?.severity || 'HIGH';
          const sampleCount = f.sample_count || (f.episodes ? f.episodes.reduce((a, b) => a + b.samples, 0) : 0);
          const epCount = f.episodes ? f.episodes.length : (f.detail?.episode_count || 1);
          const durHours = f.fault_hours || (f.detail?.total_fault_hours || 0);

          list.push({
            equipment_id: eqVal,
            rule_id: codeVal,
            fault_name: nameVal,
            severity: sevVal,
            samples: sampleCount,
            episodes: epCount,
            total_duration_hours: durHours,
            first_seen: f.episodes && f.episodes.length > 0 ? f.episodes[0].start : undefined,
            last_seen: f.episodes && f.episodes.length > 0 ? f.episodes[f.episodes.length - 1].end : undefined,
            detail: f.detail || undefined,
            display_label: isFleetView ? `[${eqVal}] ${codeVal} — ${nameVal}` : `${codeVal} — ${nameVal}`,
          });
        }
      }
    }
    return list;
  }, [summary, isFleetView, equipmentId]);

  // Filter findings for active selection
  const filteredFindings = useMemo(() => {
    if (isFleetView) return findingsList;
    return findingsList.filter(
      (f) => f.equipment_id.toLowerCase() === selectedEquipment.toLowerCase()
    );
  }, [findingsList, isFleetView, selectedEquipment]);

  // Auto-select first fault rule if none selected
  useEffect(() => {
    if (filteredFindings.length > 0) {
      if (!selectedRuleId || !filteredFindings.some((f) => f.rule_id === selectedRuleId)) {
        setSelectedRuleId(filteredFindings[0].rule_id);
      }
    } else {
      setSelectedRuleId(null);
    }
  }, [filteredFindings, selectedRuleId]);

  // Fetch fault details and timeline for effective equipment
  useEffect(() => {
    const loadData = async () => {
      if (!effectiveEquipmentId) return;
      try {
        const [faults, timeline] = await Promise.all([
          getEquipmentFaults(effectiveEquipmentId, buildingId),
          getFaultTimeline(effectiveEquipmentId, buildingId).catch(() => null),
        ]);
        setFaultDetails(faults);
        setTimelineData(timeline);
      } catch (e) {
        console.error('Failed to load fault diagnostics:', e);
      }
    };
    loadData();
  }, [effectiveEquipmentId, buildingId]);

  // Fetch normalized sensor telemetry from historian
  useEffect(() => {
    const loadNormalized = async () => {
      if (!effectiveEquipmentId) return;
      setIsLoadingNormalized(true);
      try {
        const res = await getHistorianEquipmentTelemetry(effectiveEquipmentId, buildingId, 100);
        setNormalizedColumns(res.columns || []);
        setNormalizedRecords((res as any).preview_rows || (res as any).records || []);
      } catch (e) {
        console.error('Failed to load normalized telemetry:', e);
      } finally {
        setIsLoadingNormalized(false);
      }
    };
    loadNormalized();
  }, [effectiveEquipmentId, buildingId]);

  // Fetch rule-specific graph when selectedRuleId changes
  useEffect(() => {
    const loadRuleGraph = async () => {
      if (!effectiveEquipmentId || !selectedRuleId) return;
      try {
        const g = await getRuleGraph(effectiveEquipmentId, selectedRuleId, buildingId);
        setRuleGraphData(g);
      } catch (e) {
        console.error(`Failed to load graph for rule ${selectedRuleId}:`, e);
      }
    };
    if (activeTab === 'faults' && selectedRuleId) {
      loadRuleGraph();
    }
  }, [effectiveEquipmentId, selectedRuleId, buildingId, activeTab]);

  // Fetch category graphs when switching tabs
  useEffect(() => {
    const loadCategoryGraph = async () => {
      if (!effectiveEquipmentId || isFleetView) return;
      try {
        if (activeTab === 'temperature') {
          const g = await getTelemetryGraph(effectiveEquipmentId, buildingId, 'temperature_dynamics');
          setTempGraphData(g);
        } else if (activeTab === 'airside') {
          const g = await getTelemetryGraph(effectiveEquipmentId, buildingId, 'airside');
          setAirsideGraphData(g);
        } else if (activeTab === 'chw') {
          const g = await getTelemetryGraph(effectiveEquipmentId, buildingId, 'hydronic');
          setChwGraphData(g);
        }
      } catch (e) {
        console.error(`Failed to load ${activeTab} graph:`, e);
      }
    };
    loadCategoryGraph();
  }, [activeTab, effectiveEquipmentId, buildingId, isFleetView]);

  // Fleet summary statistics
  const fleetSummaryRows = useMemo(() => {
    if (!isFleetView) return [];
    return eqList.map((eq) => {
      const eqFindings = findingsList.filter((f) => f.equipment_id.toLowerCase() === eq.toLowerCase());
      const uniqueTypes = new Set(eqFindings.map((f) => f.rule_id)).size;
      const highCount = eqFindings.filter((f) => f.severity === 'HIGH' || f.severity === 'CRITICAL').length;
      return {
        equipment_id: eq,
        fault_samples: eqFindings.reduce((a, b) => a + b.samples, 0),
        unique_fault_types: uniqueTypes,
        high_severity_faults: highCount,
      };
    });
  }, [isFleetView, eqList, findingsList]);

  // Top metric card values
  const highCount = filteredFindings.filter(
    (f) => f.severity === 'CRITICAL' || f.severity === 'HIGH'
  ).length;
  const uniqueFaults = new Set(filteredFindings.map((f) => f.rule_id)).size;
  const totalFaultSamples = filteredFindings.reduce((a, b) => a + b.samples, 0);

  // Selected fault record
  const selectedDetail = useMemo(() => {
    if (!selectedRuleId) return null;
    const match = faultDetails.find((d) => d.rule_id.toLowerCase() === selectedRuleId.toLowerCase());
    if (match) return match;
    const findMatch = filteredFindings.find((f) => f.rule_id.toLowerCase() === selectedRuleId.toLowerCase());
    return findMatch?.detail || null;
  }, [selectedRuleId, faultDetails, filteredFindings]);

  // CSV Export handler matching st.download_button
  const handleDownloadCSV = () => {
    if (filteredFindings.length === 0) return;
    const headers = isFleetView
      ? ['equipment_id', 'fault_code', 'fault_name', 'severity', 'samples', 'episodes', 'total_duration_hours', 'first_seen', 'last_seen']
      : ['fault_code', 'fault_name', 'severity', 'samples', 'episodes', 'total_duration_hours', 'first_seen', 'last_seen'];

    const rows = filteredFindings.map((f) => {
      const base = [
        f.rule_id,
        `"${f.fault_name.replace(/"/g, '""')}"`,
        f.severity,
        f.samples,
        f.episodes,
        f.total_duration_hours.toFixed(2),
        f.first_seen || '',
        f.last_seen || '',
      ];
      return isFleetView ? [f.equipment_id, ...base] : base;
    });

    const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `fdd_diagnostic_findings_${selectedEquipment}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Airside table columns to display below Airside graph matching D:\csvopenfdd
  const airsideCols = useMemo(() => {
    const candidates = [
      'timestamp',
      'ec_fan_speed_command_pct',
      'fan_cmd',
      'fan_vfd_speed',
      'duct_static_pressure_pa',
      'duct_static',
      'duct_static_pressure_setpoint_pa',
      'duct_static_sp',
      'co2_ppm',
      'co2',
      'room_humidity_pct',
      'room_humidity',
      'ahu_run_status',
    ];
    return candidates.filter((c) => normalizedColumns.includes(c));
  }, [normalizedColumns]);

  return (
    <div className="space-y-5 font-sans select-none text-[#fafafa]">
      {/* Equipment Discovery & Selector matching st.selectbox("Equipment", ...) */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[rgba(250,250,250,0.12)] pb-3">
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-[#a3a8b8] whitespace-nowrap">Equipment:</label>
          <select
            id="equipment-selector"
            value={selectedEquipment}
            onChange={(e) => {
              const val = e.target.value;
              setSelectedEquipment(val);
              if (val !== 'All AHUs' && onSelectEquipment) {
                onSelectEquipment(val);
              }
            }}
            className="st-input cursor-pointer font-sans font-semibold text-sm px-3 py-1.5 min-w-44"
          >
            {equipmentOptions.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        </div>

        {/* 4 Streamlit Metrics matching c1, c2, c3, c4 = st.columns(4) */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 flex-1 max-w-2xl">
          {isFleetView ? (
            <>
              <div className="st-metric-card">
                <div className="st-metric-label">Fleet Validated Timestamps</div>
                <div className="st-metric-value font-mono text-[#fafafa]">{normalizedRecords.length}</div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Active Equipment Units</div>
                <div className="st-metric-value font-mono text-[#58a6ff]">{eqList.length}</div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Total Fleet Fault Samples</div>
                <div className="st-metric-value font-mono text-[#ff7b72]">{totalFaultSamples}</div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Unique Fault Types</div>
                <div className="st-metric-value font-mono text-[#ff7b72]">{uniqueFaults}</div>
                {highCount > 0 && <div className="st-metric-delta-neg">↓ {highCount} high-severity</div>}
              </div>
            </>
          ) : (
            <>
              <div className="st-metric-card">
                <div className="st-metric-label">Validated Timestamps</div>
                <div className="st-metric-value font-mono text-[#fafafa]">{normalizedRecords.length}</div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Mapped Points</div>
                <div className="st-metric-value font-mono text-[#58a6ff]">
                  {normalizedColumns.filter((c) => !['timestamp', 'equipment_id'].includes(c)).length}
                </div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Fault Samples</div>
                <div className="st-metric-value font-mono text-[#ff7b72]">{totalFaultSamples}</div>
              </div>
              <div className="st-metric-card">
                <div className="st-metric-label">Unique Fault Types</div>
                <div className="st-metric-value font-mono text-[#ff7b72]">{uniqueFaults}</div>
                {highCount > 0 && <div className="st-metric-delta-neg">↓ {highCount} high-severity</div>}
              </div>
            </>
          )}
        </div>
      </div>


      {/* 4 Main Tabs matching tab1, tab2, tab3, tab4 = st.tabs(...) */}
      <div className="flex border-b border-[rgba(250,250,250,0.12)]">
        {[
          { id: 'faults', label: 'Faults & Diagnostics' },
          { id: 'temperature', label: 'Air temperatures' },
          { id: 'airside', label: 'Airside' },
          { id: 'chw', label: 'Chilled water' },
        ].map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id as any)}
            className={`st-tab-btn ${activeTab === t.id ? 'st-tab-btn-active' : ''}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="space-y-4 pt-1">
        {/* TAB 1: FAULTS & DIAGNOSTICS */}
        {activeTab === 'faults' && (
          <div className="space-y-4">
            {/* Fleet Summary Table if All AHUs selected */}
            {isFleetView && (
              <div className="space-y-2 pb-2">
                <h4 className="text-xs font-semibold text-[#fafafa] uppercase tracking-wider font-mono">
                  Fleet-Wide Equipment Fault Summary
                </h4>
                <div className="st-dataframe-container">
                  <table className="st-dataframe-table font-mono text-xs">
                    <thead>
                      <tr>
                        <th>Equipment ID</th>
                        <th>Fault Samples</th>
                        <th>Unique Fault Types</th>
                        <th>High Severity Faults</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fleetSummaryRows.map((row, idx) => (
                        <tr key={idx}>
                          <td className="text-[#58a6ff] font-bold">{row.equipment_id}</td>
                          <td>{row.fault_samples}</td>
                          <td>{row.unique_fault_types}</td>
                          <td className={row.high_severity_faults > 0 ? 'text-[#ff7b72] font-bold' : 'text-[#a3a8b8]'}>
                            {row.high_severity_faults}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Fault Summary Table matching st.dataframe */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-[#a3a8b8]">
                  Detected Fault Summary ({filteredFindings.length} active fault findings)
                </span>
                <button
                  type="button"
                  id="download-diagnostic-csv-btn"
                  onClick={handleDownloadCSV}
                  className="st-button-secondary text-xs px-2.5 py-1 flex items-center gap-1.5"
                >
                  <Download className="w-3.5 h-3.5 text-[#58a6ff]" />
                  Download diagnostic CSV
                </button>
              </div>

              {filteredFindings.length === 0 ? (
                <div className="st-alert-success text-xs">
                  ✓ No persistent faults were detected for the active selection.
                </div>
              ) : (
                <div className="st-dataframe-container max-h-64 overflow-auto">
                  <table id="faults-detected-table" className="st-dataframe-table font-mono text-xs">
                    <thead>
                      <tr>
                        {isFleetView && <th>Equipment</th>}
                        <th>Fault Code</th>
                        <th>Fault Name</th>
                        <th>Severity</th>
                        <th>Samples</th>
                        <th>Episodes</th>
                        <th>Duration (Hours)</th>
                        <th>First Seen</th>
                        <th>Last Seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredFindings.map((f, idx) => {
                        const isSelected = selectedRuleId?.toLowerCase() === f.rule_id.toLowerCase();
                        return (
                          <tr
                            key={idx}
                            onClick={() => setSelectedRuleId(f.rule_id)}
                            className={`cursor-pointer ${isSelected ? 'bg-[#262730] font-semibold' : ''}`}
                          >
                            {isFleetView && <td className="text-[#58a6ff]">{f.equipment_id}</td>}
                            <td className="text-[#58a6ff] font-bold">{f.rule_id}</td>
                            <td className="text-[#fafafa] font-sans">{f.fault_name}</td>
                            <td>
                              <span
                                className={
                                  f.severity === 'CRITICAL' || f.severity === 'HIGH'
                                    ? 'text-[#ff7b72] font-semibold'
                                    : 'text-[#f0883e]'
                                }
                              >
                                {f.severity}
                              </span>
                            </td>
                            <td>{f.samples}</td>
                            <td>{f.episodes}</td>
                            <td className="text-[#ff7b72] font-bold">{f.total_duration_hours.toFixed(1)}</td>
                            <td className="text-[#a3a8b8]">
                              {f.first_seen ? new Date(f.first_seen).toLocaleDateString() : '--'}
                            </td>
                            <td className="text-[#a3a8b8]">
                              {f.last_seen ? new Date(f.last_seen).toLocaleDateString() : '--'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Inspect fault selectbox matching st.selectbox("Inspect fault", ...) */}
            {filteredFindings.length > 0 && (
              <div className="space-y-1">
                <label className="text-xs font-medium text-[#a3a8b8] block">Inspect fault</label>
                <select
                  id="inspect-fault-select"
                  value={selectedRuleId || ''}
                  onChange={(e) => setSelectedRuleId(e.target.value)}
                  className="w-full st-input cursor-pointer font-sans text-xs"
                >
                  {filteredFindings.map((f) => (
                    <option key={f.rule_id} value={f.rule_id}>
                      {f.display_label} ({f.total_duration_hours.toFixed(1)} hrs)
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Diagnostic Insight 2-Column Panel matching st.columns(2) */}
            {selectedDetail && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-2">
                {/* Left Column: Evidence, Sources, Basis */}
                <div className="space-y-3">
                  <div className="st-alert-error text-sm">
                    <strong className="block font-mono">
                      [{selectedDetail.rule_id}] {selectedDetail.severity}: {selectedDetail.title} (Equipment:{' '}
                      {selectedDetail.equipment_id || effectiveEquipmentId})
                    </strong>
                  </div>

                  <p className="text-xs text-[#a3a8b8]">
                    Diagnostic Confidence:{' '}
                    <strong className="text-[#fafafa]">
                      {selectedDetail.evidence?.[0]?.confidence || 'CONFIRMED'}
                    </strong>{' '}
                    | Total Duration:{' '}
                    <strong className="text-[#fafafa]">
                      {selectedDetail.total_fault_hours.toFixed(1)} hrs
                    </strong>{' '}
                    across{' '}
                    <strong className="text-[#fafafa]">
                      {selectedDetail.episodes?.length || 1} episode(s)
                    </strong>
                  </p>

                  <div>
                    <h4 className="text-sm font-bold text-[#fafafa] mb-1">Evidence</h4>
                    <p className="text-xs text-[#fafafa] leading-relaxed">
                      {selectedDetail.evidence?.[0]?.evidence_text || selectedDetail.description}
                    </p>
                  </div>

                  {selectedDetail.associated_roles && selectedDetail.associated_roles.length > 0 && (
                    <p className="text-xs text-[#a3a8b8]">
                      <strong className="text-[#fafafa]">Evidence Sources</strong>:{' '}
                      <code className="text-[#58a6ff] font-mono bg-[#262730] px-1.5 py-0.5 rounded border border-[rgba(250,250,250,0.12)]">
                        history.parquet ({selectedDetail.associated_roles.join(', ')})
                      </code>
                    </p>
                  )}

                  <p className="text-xs text-[#a3a8b8] italic">
                    Diagnostic Basis: Continuous physical telemetry evaluation against official Open-FDD SQL rules
                  </p>
                </div>

                {/* Right Column: Possible causes & Recommended checks */}
                <div className="space-y-3">
                  <div>
                    <h4 className="text-sm font-bold text-[#fafafa] mb-1">Possible causes</h4>
                    <ul className="space-y-1 text-xs text-[#fafafa]">
                      {selectedDetail.possible_causes && selectedDetail.possible_causes.length > 0 ? (
                        selectedDetail.possible_causes.map((c, i) => (
                          <li key={i} className="flex items-start gap-1.5">
                            <span className="text-[#a3a8b8]">•</span>
                            <span>{c}</span>
                          </li>
                        ))
                      ) : (
                        <li className="text-[#a3a8b8] italic">No specific causes cataloged</li>
                      )}
                    </ul>
                  </div>

                  <div>
                    <h4 className="text-sm font-bold text-[#fafafa] mb-1">Recommended checks</h4>
                    <ul className="space-y-1 text-xs text-[#fafafa]">
                      {selectedDetail.recommended_checks && selectedDetail.recommended_checks.length > 0 ? (
                        selectedDetail.recommended_checks.map((chk, i) => (
                          <li key={i} className="flex items-start gap-1.5">
                            <span className="text-[#a3a8b8]">•</span>
                            <span>{chk}</span>
                          </li>
                        ))
                      ) : (
                        <li className="text-[#a3a8b8] italic">No specific checks cataloged</li>
                      )}
                    </ul>
                  </div>
                </div>
              </div>
            )}

            {/* Contiguous Fault Episodes Expander matching st.expander(...) */}
            {selectedDetail && selectedDetail.episodes && selectedDetail.episodes.length > 0 && (
              <div className="st-expander mt-3">
                <button
                  type="button"
                  id="episodes-toggle"
                  onClick={() => setIsEpisodesExpanded((prev) => !prev)}
                  className="st-expander-header w-full"
                >
                  <span className="text-sm font-medium text-[#fafafa]">
                    Contiguous Fault Episodes ({selectedDetail.episodes.length} active streaks)
                  </span>
                  <span className="text-[#a3a8b8] text-xs">
                    {isEpisodesExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </span>
                </button>
                {isEpisodesExpanded && (
                  <div className="p-3 bg-[#1e2129]">
                    <div className="st-dataframe-container">
                      <table className="st-dataframe-table font-mono text-xs">
                        <thead>
                          <tr>
                            <th>Episode Start</th>
                            <th>Episode End</th>
                            <th>Fault Records</th>
                            <th>Duration (Hours)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {selectedDetail.episodes.map((ep, i) => (
                            <tr key={i}>
                              <td>{ep.start}</td>
                              <td>{ep.end}</td>
                              <td>{ep.samples}</td>
                              <td className="text-[#ff7b72] font-bold">
                                {ep.duration_hours.toFixed(2)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Related Telemetry Trend & Active Period Highlight Graph */}
            {ruleGraphData && (
              <div className="space-y-2 pt-2">
                <h4 className="text-xs font-semibold text-[#fafafa] uppercase tracking-wider font-mono">
                  Related Telemetry Trend & Active Period Highlight ({effectiveEquipmentId} — [{selectedRuleId}])
                </h4>
                <TelemetryGraph data={ruleGraphData} height={340} />
              </div>
            )}

            {/* Fault Timeline Swimlanes */}
            {timelineData && (
              <div className="pt-2">
                <FaultTimelineGraph
                  timeline={timelineData}
                  selectedRuleId={selectedRuleId}
                  onSelectRule={(rid) => setSelectedRuleId(rid)}
                />
              </div>
            )}
          </div>
        )}

        {/* TAB 2: AIR TEMPERATURES */}
        {activeTab === 'temperature' && (
          <div>
            {isFleetView ? (
              <div className="st-alert-info text-xs font-mono py-4">
                ℹ Select an individual equipment unit from the Equipment selector above to view dedicated temperature time-series graphs.
              </div>
            ) : tempGraphData ? (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-[#fafafa] font-mono">
                  Temperature Trends — {selectedEquipment}
                </h4>
                <TelemetryGraph data={tempGraphData} height={380} />
              </div>
            ) : (
              <div className="text-xs text-[#a3a8b8] py-12 text-center font-mono">
                Loading temperature dynamics telemetry...
              </div>
            )}
          </div>
        )}

        {/* TAB 3: AIRSIDE */}
        {activeTab === 'airside' && (
          <div className="space-y-4">
            {isFleetView ? (
              <div className="st-alert-info text-xs font-mono py-4">
                ℹ Select an individual equipment unit from the Equipment selector above to view dedicated airside time-series graphs.
              </div>
            ) : airsideGraphData ? (
              <div className="space-y-4">
                <div className="space-y-2">
                  <h4 className="text-xs font-semibold text-[#fafafa] font-mono">
                    Airside Trends — {selectedEquipment}
                  </h4>
                  <TelemetryGraph data={airsideGraphData} height={380} />
                </div>

                {/* Airside Telemetry Data Table matching D:\csvopenfdd */}
                {airsideCols.length > 0 && normalizedRecords.length > 0 && (
                  <div className="space-y-2 pt-2">
                    <span className="text-xs font-semibold text-[#fafafa] block font-mono">
                      Airside Telemetry Data ({airsideCols.length} channels)
                    </span>
                    <div className="st-dataframe-container max-h-56 overflow-y-auto">
                      <table className="st-dataframe-table font-mono text-xs">
                        <thead>
                          <tr>
                            {airsideCols.map((col, idx) => (
                              <th key={idx}>{col}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {normalizedRecords.slice(0, 50).map((row, rIdx) => (
                            <tr key={rIdx}>
                              {airsideCols.map((col, cIdx) => (
                                <td key={cIdx}>
                                  {row[col] !== null && row[col] !== undefined
                                    ? typeof row[col] === 'number'
                                      ? row[col].toFixed(2)
                                      : String(row[col])
                                    : '—'}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-xs text-[#a3a8b8] py-12 text-center font-mono">
                Loading airside and duct static telemetry...
              </div>
            )}
          </div>
        )}

        {/* TAB 4: CHILLED WATER */}
        {activeTab === 'chw' && (
          <div>
            {isFleetView ? (
              <div className="st-alert-info text-xs font-mono py-4">
                ℹ Select an individual equipment unit from the Equipment selector above to view dedicated chilled water time-series graphs.
              </div>
            ) : chwGraphData ? (
              <div className="space-y-2">
                <h4 className="text-xs font-semibold text-[#fafafa] font-mono">
                  Chilled Water Trends — {selectedEquipment}
                </h4>
                <TelemetryGraph data={chwGraphData} height={380} />
              </div>
            ) : (
              <div className="text-xs text-[#a3a8b8] py-12 text-center font-mono">
                Loading hydronic / chilled water telemetry...
              </div>
            )}
          </div>
        )}
      </div>

      {/* Subheader below tabs matching st.subheader("Normalized sensor data") */}
      <div className="pt-6 border-t border-[rgba(250,250,250,0.12)] space-y-2">
        <h3 className="text-sm font-semibold text-[#fafafa] flex items-center gap-2 font-mono">
          <Table className="w-4 h-4 text-[#58a6ff]" />
          Normalized sensor data ({effectiveEquipmentId})
        </h3>
        {isLoadingNormalized ? (
          <div className="text-xs text-[#a3a8b8] py-4 text-center font-mono">
            Loading normalized sensor records...
          </div>
        ) : normalizedRecords.length === 0 ? (
          <div className="text-xs text-[#a3a8b8] py-4 text-center font-mono">
            No normalized sensor records available.
          </div>
        ) : (
          <div className="st-dataframe-container max-h-72 overflow-auto">
            <table className="st-dataframe-table font-mono text-xs">
              <thead>
                <tr>
                  {normalizedColumns.map((col, idx) => (
                    <th key={idx}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {normalizedRecords.map((row, rIdx) => (
                  <tr key={rIdx}>
                    {normalizedColumns.map((col, cIdx) => (
                      <td key={cIdx}>
                        {row[col] !== null && row[col] !== undefined
                          ? typeof row[col] === 'number'
                            ? row[col].toFixed(2)
                            : String(row[col])
                          : '—'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
