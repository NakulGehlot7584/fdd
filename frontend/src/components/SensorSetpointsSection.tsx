import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { DatasetDetailResponse } from '../types/api';

interface Props {
  dataset: DatasetDetailResponse;
}

interface SensorPair {
  sensorRole: string;
  sensorLabel: string;
  setpointRole: string | null;
  setpointLabel: string;
  unit: string;
  measuredColumn?: string;
  setpointColumn?: string;
  hasMeasured: boolean;
  hasSetpoint: boolean;
  statusText: string;
}

export const SensorSetpointsSection: React.FC<Props> = ({ dataset }) => {
  const [isExpanded, setIsExpanded] = useState<boolean>(true);

  // Map of canonical roles present in this dataset
  const roleToCol: Record<string, string> = {};
  for (const col of dataset.columns) {
    if (col.mapped && col.canonical_role) {
      roleToCol[col.canonical_role.toLowerCase()] = col.source_column;
    }
  }

  // Canonical pairs supported by Open-FDD and project extensions
  const supportedPairsConfig: Array<{
    sensorRole: string;
    sensorLabel: string;
    setpointRole: string | null;
    setpointLabel: string;
    defaultUnit: string;
  }> = [
    {
      sensorRole: 'sat',
      sensorLabel: 'Supply Air Temp (SAT)',
      setpointRole: 'sat_sp',
      setpointLabel: 'Supply Air Temp Setpoint (sat_sp)',
      defaultUnit: '°F',
    },
    {
      sensorRole: 'duct_static',
      sensorLabel: 'Duct Static Pressure',
      setpointRole: 'duct_static_sp',
      setpointLabel: 'Static Pressure Setpoint (duct_static_sp)',
      defaultUnit: 'in_wc',
    },
    {
      sensorRole: 'co2',
      sensorLabel: 'Indoor CO2 Concentration (Project Extension)',
      setpointRole: 'co2_sp',
      setpointLabel: 'CO2 Target Setpoint (co2_sp) [Project Extension]',
      defaultUnit: 'ppm',
    },
    {
      sensorRole: 'zone_flow',
      sensorLabel: 'Zone Airflow',
      setpointRole: 'min_flow_sp',
      setpointLabel: 'Min Airflow Setpoint (min_flow_sp)',
      defaultUnit: 'cfm',
    },
    {
      sensorRole: 'vav_total_flow',
      sensorLabel: 'Total Supply Airflow',
      setpointRole: 'min_flow_sp',
      setpointLabel: 'Min Flow Setpoint (min_flow_sp)',
      defaultUnit: 'cfm',
    },
    {
      sensorRole: 'chw_supply_t',
      sensorLabel: 'Chilled Water Supply Temp',
      setpointRole: 'chw_supply_sp',
      setpointLabel: 'CHW Supply Setpoint (chw_supply_sp)',
      defaultUnit: '°F',
    },
    {
      sensorRole: 'chw_dp',
      sensorLabel: 'Chilled Water Differential Pressure',
      setpointRole: 'chw_dp_sp',
      setpointLabel: 'CHW DP Setpoint (chw_dp_sp)',
      defaultUnit: 'psi',
    },
    {
      sensorRole: 'mat',
      sensorLabel: 'Mixed Air Temperature',
      setpointRole: null,
      setpointLabel: 'Setpoint not available',
      defaultUnit: '°F',
    },
    {
      sensorRole: 'rat',
      sensorLabel: 'Return Air Temperature',
      setpointRole: null,
      setpointLabel: 'Setpoint not available',
      defaultUnit: '°F',
    },
    {
      sensorRole: 'oa_t',
      sensorLabel: 'Outdoor Air Temperature',
      setpointRole: null,
      setpointLabel: 'Setpoint not available',
      defaultUnit: '°F',
    },
    {
      sensorRole: 'zone_t',
      sensorLabel: 'Zone Space Temperature',
      setpointRole: null,
      setpointLabel: 'Setpoint not available',
      defaultUnit: '°F',
    },
  ];

  const pairs: SensorPair[] = [];
  for (const cfg of supportedPairsConfig) {
    const hasMeasured = Boolean(roleToCol[cfg.sensorRole]);
    const hasSetpoint = cfg.setpointRole ? Boolean(roleToCol[cfg.setpointRole]) : false;

    // Only show row if measured sensor or setpoint exists in this dataset
    if (hasMeasured || hasSetpoint) {
      let status = 'Unregulated';
      if (hasMeasured && hasSetpoint) {
        status = 'Regulated (Paired)';
      } else if (hasMeasured && !hasSetpoint) {
        status = 'No Setpoint Available';
      } else if (!hasMeasured && hasSetpoint) {
        status = 'Target Only (Sensor Missing)';
      }

      pairs.push({
        sensorRole: cfg.sensorRole,
        sensorLabel: cfg.sensorLabel,
        setpointRole: cfg.setpointRole,
        setpointLabel: cfg.setpointLabel,
        unit: cfg.defaultUnit,
        measuredColumn: roleToCol[cfg.sensorRole],
        setpointColumn: cfg.setpointRole ? roleToCol[cfg.setpointRole] : undefined,
        hasMeasured,
        hasSetpoint,
        statusText: status,
      });
    }
  }

  const pairedCount = pairs.filter((p) => p.hasMeasured && p.hasSetpoint).length;

  return (
    <div className="st-expander font-sans select-none">
      {/* Streamlit st.expander header */}
      <button
        type="button"
        onClick={() => setIsExpanded((prev) => !prev)}
        className="st-expander-header w-full"
      >
        <span className="text-sm font-medium text-[#fafafa] flex items-center gap-2">
          All Sensor Setpoints
          <span className="text-xs text-[#8ec8f6] font-mono">
            ({pairedCount} paired)
          </span>
        </span>
        <span className="text-[#808495] text-xs">
          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </span>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-3 bg-[#0e1117]">
          {pairs.length === 0 ? (
            <div className="text-xs text-[#808495] py-4 text-center font-sans">
              No recognized sensor or setpoint telemetry roles found in the active dataset.
            </div>
          ) : (
            <div className="st-dataframe-container">
              <table className="st-dataframe-table font-mono">
                <thead>
                  <tr>
                    <th>Sensor Channel</th>
                    <th>Canonical Role</th>
                    <th>Mapped Source</th>
                    <th>Target Setpoint Role</th>
                    <th>Mapped Setpoint</th>
                    <th>Unit</th>
                    <th>Pairing Status</th>
                  </tr>
                </thead>
                <tbody>
                  {pairs.map((p, idx) => (
                    <tr key={idx}>
                      <td className="font-semibold text-[#fafafa]">{p.sensorLabel}</td>
                      <td className="text-[#8ec8f6]">{p.sensorRole}</td>
                      <td>
                        {p.measuredColumn ? (
                          <span>{p.measuredColumn}</span>
                        ) : (
                          <span className="text-[#808495] italic">Not mapped</span>
                        )}
                      </td>
                      <td className="text-[#a3e635]">
                        {p.setpointRole || <span className="text-[#808495]">—</span>}
                      </td>
                      <td>
                        {p.setpointColumn ? (
                          <span>{p.setpointColumn}</span>
                        ) : (
                          <span className="text-[#ff7c7c] italic">Setpoint not available</span>
                        )}
                      </td>
                      <td className="text-[#808495]">{p.unit}</td>
                      <td>
                        {p.hasMeasured && p.hasSetpoint ? (
                          <span className="text-[#09ab3b] font-medium">✓ Paired</span>
                        ) : p.hasMeasured ? (
                          <span className="text-[#ffc107]">No Setpoint</span>
                        ) : (
                          <span className="text-[#ff7c7c]">Missing Sensor</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
