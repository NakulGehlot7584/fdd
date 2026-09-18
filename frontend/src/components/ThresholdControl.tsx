import React, { useState, useEffect, useMemo } from 'react';
import {
  AlertTriangle,
  RotateCcw,
  Sliders,
  Search,
} from 'lucide-react';
import { ThresholdCatalogResponse, ThresholdItem } from '../types/api';
import { getThresholdMetadata } from '../services/api';

export type PresetName = 'Standard' | 'Sensitive' | 'Lenient' | 'Custom';

interface Props {
  onThresholdsChange: (overrides: Record<string, Record<string, number>>) => void;
  isRunExecuted?: boolean;
}

export const ThresholdControl: React.FC<Props> = ({ onThresholdsChange, isRunExecuted }) => {
  const [catalog, setCatalog] = useState<ThresholdCatalogResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Active settings map: param_name -> value
  const [currentValues, setCurrentValues] = useState<Record<string, number>>({});
  const [selectedPreset, setSelectedPreset] = useState<PresetName>('Standard');
  const [activeTier, setActiveTier] = useState<'TIER_A' | 'TIER_B'>('TIER_A');
  const [selectedCategory, setSelectedCategory] = useState<string>('All');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isDirtyAfterRun, setIsDirtyAfterRun] = useState<boolean>(false);

  // Fetch dynamic metadata from backend
  useEffect(() => {
    let isMounted = true;
    async function loadMetadata() {
      setIsLoading(true);
      setLoadError(null);
      try {
        const data = await getThresholdMetadata();
        if (!isMounted) return;
        setCatalog(data);

        // Initialize values from Standard preset merged with defaults
        const initial: Record<string, number> = {};
        const standardPreset = data.presets['Standard'] || {};
        for (const item of data.parameters) {
          initial[item.param_name] = standardPreset[item.param_name] ?? item.default_value;
        }
        setCurrentValues(initial);
      } catch (err: any) {
        if (!isMounted) return;
        setLoadError(err.message || 'Failed to load threshold metadata from backend');
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }
    loadMetadata();
    return () => {
      isMounted = false;
    };
  }, []);

  // Compute rule parameter overrides whenever currentValues or preset changes
  useEffect(() => {
    if (!catalog) return;

    const overrides: Record<string, Record<string, number>> = {};
    if (selectedPreset !== 'Standard') {
      for (const item of catalog.parameters) {
        const val = currentValues[item.param_name];
        if (val !== undefined) {
          for (const ruleId of item.applicable_rules) {
            if (!overrides[ruleId]) {
              overrides[ruleId] = {};
            }
            overrides[ruleId][item.param_name] = val;
          }
        }
      }
    }

    onThresholdsChange(overrides);
  }, [catalog, currentValues, selectedPreset, onThresholdsChange]);

  // Handle Preset Selection
  const handleSelectPreset = (preset: PresetName) => {
    if (!catalog) return;
    setSelectedPreset(preset);

    if (preset !== 'Custom') {
      const presetValues = catalog.presets[preset] || {};
      const nextValues: Record<string, number> = {};
      for (const item of catalog.parameters) {
        nextValues[item.param_name] = presetValues[item.param_name] ?? item.default_value;
      }
      setCurrentValues(nextValues);
      if (isRunExecuted) setIsDirtyAfterRun(true);
    }
  };

  // Handle Individual Parameter Change
  const handleParamChange = (paramName: string, value: number) => {
    setSelectedPreset('Custom');
    setCurrentValues((prev) => ({
      ...prev,
      [paramName]: value,
    }));
    if (isRunExecuted) setIsDirtyAfterRun(true);
  };

  // Reset all values to baseline defaults
  const handleResetToDefaults = () => {
    if (!catalog) return;
    setSelectedPreset('Standard');
    const initial: Record<string, number> = {};
    const standardPreset = catalog.presets['Standard'] || {};
    for (const item of catalog.parameters) {
      initial[item.param_name] = standardPreset[item.param_name] ?? item.default_value;
    }
    setCurrentValues(initial);
    setIsDirtyAfterRun(false);
  };

  // Reset single parameter to default
  const handleResetSingle = (item: ThresholdItem) => {
    const defaultVal = catalog?.presets['Standard']?.[item.param_name] ?? item.default_value;
    handleParamChange(item.param_name, defaultVal);
  };

  // Filtered parameters list based on active tier, category, and search query
  const filteredParameters = useMemo(() => {
    if (!catalog) return [];
    return catalog.parameters.filter((item) => {
      // Tier match
      if (item.tier !== activeTier) return false;

      // Category match
      if (selectedCategory !== 'All' && item.category !== selectedCategory) return false;

      // Search match
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = item.param_name.toLowerCase().includes(q);
        const matchLabel = item.label.toLowerCase().includes(q);
        const matchDesc = item.description.toLowerCase().includes(q);
        const matchRules = item.applicable_rules.some((r) => r.toLowerCase().includes(q));
        if (!matchName && !matchLabel && !matchDesc && !matchRules) return false;
      }

      return true;
    });
  }, [catalog, activeTier, selectedCategory, searchQuery]);

  if (isLoading) {
    return (
      <div className="py-6 text-center text-xs text-[#808495] font-mono animate-pulse">
        Loading verified rule thresholds from Open-FDD catalog...
      </div>
    );
  }

  if (loadError || !catalog) {
    return (
      <div className="p-3 bg-[#3d1818] border border-[#ff4b4b] rounded text-xs text-[#ff7c7c] space-y-1">
        <div className="font-semibold flex items-center gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          <span>Failed to load threshold metadata</span>
        </div>
        <p className="text-[11px] opacity-90">{loadError}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3 font-sans select-none text-xs">
      {/* Dirty Re-run Notification */}
      {isDirtyAfterRun && (
        <div className="p-2.5 bg-[#3d2b14] border border-[#ffc107] rounded text-xs text-[#ffc107] flex items-center justify-between gap-2 animate-fadeIn">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 shrink-0 text-[#ffc107]" />
            <span>Thresholds modified — re-run required to evaluate with new settings</span>
          </div>
          <span className="text-[10px] uppercase font-mono tracking-wider font-semibold px-1.5 py-0.5 bg-[#523812] rounded">
            Unapplied
          </span>
        </div>
      )}

      {/* Preset Selector Banner */}
      <div className="p-3 bg-[#1e2029] rounded border border-[#383b42] space-y-2">
        <div className="flex items-center justify-between">
          <span className="font-semibold text-[#fafafa] flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5 text-[#ff4b4b]" />
            Sensitivity Preset
          </span>
          <button
            type="button"
            onClick={handleResetToDefaults}
            className="text-[11px] text-[#808495] hover:text-[#fafafa] flex items-center gap-1 hover:underline"
            title="Reset all thresholds to baseline defaults"
          >
            <RotateCcw className="w-3 h-3" />
            Reset Defaults
          </button>
        </div>

        <div className="grid grid-cols-4 gap-1.5 bg-[#0e1117] p-1 rounded border border-[#2b2d38]">
          {(['Standard', 'Sensitive', 'Lenient', 'Custom'] as PresetName[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => handleSelectPreset(p)}
              className={`py-1.5 px-2 rounded text-[11px] font-medium transition-all text-center ${
                selectedPreset === p
                  ? 'bg-[#ff4b4b] text-white font-semibold shadow-sm'
                  : 'text-[#808495] hover:text-[#fafafa] hover:bg-[#262730]'
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        <p className="text-[11px] text-[#808495]">
          {selectedPreset === 'Standard' && 'Standard Open-FDD baseline (15m confirm, 5°F SAT deviation, 1.15°F mix tolerance).'}
          {selectedPreset === 'Sensitive' && 'Sensitive commissioning mode (5m confirm, 2.5°F SAT dev, tight damper/valve tolerances).'}
          {selectedPreset === 'Lenient' && 'Nuisance filter mode (30m confirm, 8°F SAT dev, loose margins for aging mechanical plants).'}
          {selectedPreset === 'Custom' && 'User-defined overrides applied directly to the active execution run.'}
        </p>
      </div>

      {/* Tier Switcher: User-Facing vs Advanced */}
      <div className="flex items-center justify-between border-b border-[#383b42] pb-2 pt-1">
        <div className="flex items-center gap-1 bg-[#1e2029] p-0.5 rounded border border-[#383b42]">
          <button
            type="button"
            onClick={() => setActiveTier('TIER_A')}
            className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
              activeTier === 'TIER_A'
                ? 'bg-[#ff4b4b] text-white'
                : 'text-[#808495] hover:text-[#fafafa]'
            }`}
          >
            Recommended Tuning ({catalog.tier_a_count})
          </button>
          <button
            type="button"
            onClick={() => setActiveTier('TIER_B')}
            className={`px-3 py-1 rounded text-[11px] font-medium transition-colors ${
              activeTier === 'TIER_B'
                ? 'bg-[#31333f] text-[#8ec8f6] font-semibold'
                : 'text-[#808495] hover:text-[#fafafa]'
            }`}
          >
            Advanced Parameters ({catalog.tier_b_count})
          </button>
        </div>

        <span className="text-[10px] text-[#808495] font-mono hidden sm:inline">
          {filteredParameters.length} of {catalog.total_parameters} available
        </span>
      </div>

      {/* Filters: Category Selector & Search Input */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 text-[#808495] absolute left-2.5 top-2.5 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search parameter, rule, or keyword..."
            className="w-full bg-[#1e2029] border border-[#383b42] rounded pl-8 pr-3 py-1.5 text-xs text-[#fafafa] placeholder-[#808495] focus:outline-none focus:border-[#ff4b4b]"
          />
        </div>

        <select
          value={selectedCategory}
          onChange={(e) => setSelectedCategory(e.target.value)}
          className="bg-[#1e2029] border border-[#383b42] rounded px-2.5 py-1.5 text-xs text-[#fafafa] focus:outline-none focus:border-[#ff4b4b]"
        >
          <option value="All">All Categories ({catalog.categories.length})</option>
          {catalog.categories.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {/* Dynamic Parameters List */}
      <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
        {filteredParameters.length === 0 ? (
          <div className="py-8 text-center text-xs text-[#808495] font-mono">
            No parameters found matching the selected filters.
          </div>
        ) : (
          filteredParameters.map((item) => {
            const currentVal = currentValues[item.param_name] ?? item.default_value;
            const isModified = Math.abs(currentVal - item.default_value) > 1e-4;

            return (
              <div
                key={item.placeholder}
                className={`p-3 rounded border transition-colors ${
                  isModified
                    ? 'bg-[#1a2130] border-[#8ec8f6]/40'
                    : 'bg-[#1a1c24] border-[#2e313c] hover:border-[#383b42]'
                }`}
              >
                {/* Header: Label, Parameter tag, Category, Reset */}
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-semibold text-[#fafafa]">{item.label}</span>
                      <span className="font-mono text-[10px] text-[#8ec8f6] bg-[#0e1117] px-1.5 py-0.5 rounded border border-[#2b2d38]">
                        {item.param_name}
                      </span>
                      {isModified && (
                        <span className="text-[9px] text-[#ffc107] font-semibold uppercase px-1 rounded bg-[#3d2b14] border border-[#ffc107]/40">
                          Customized
                        </span>
                      )}
                    </div>
                    <p className="text-[11px] text-[#808495] line-clamp-2 leading-relaxed">
                      {item.description}
                    </p>
                  </div>

                  {isModified && (
                    <button
                      type="button"
                      onClick={() => handleResetSingle(item)}
                      title={`Reset to default (${item.default_value} ${item.unit})`}
                      className="text-[#808495] hover:text-[#fafafa] p-1 rounded hover:bg-[#262730] shrink-0"
                    >
                      <RotateCcw className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {/* Slider and Value Display Controls */}
                <div className="space-y-1 mt-2">
                  <div className="flex items-center justify-between text-[11px] font-mono">
                    <span className="text-[#808495]">
                      Range: {item.min_value} – {item.max_value} {item.unit}
                    </span>
                    <div className="flex items-center gap-1">
                      <span className="text-[#808495] text-[10px]">Current:</span>
                      <span className="font-bold text-[#fafafa] bg-[#0e1117] px-2 py-0.5 rounded border border-[#383b42]">
                        {currentVal} {item.unit}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <input
                      type="range"
                      min={item.min_value}
                      max={item.max_value}
                      step={item.step}
                      value={currentVal}
                      onChange={(e) => handleParamChange(item.param_name, parseFloat(e.target.value))}
                      className="flex-1 accent-[#ff4b4b] cursor-pointer h-1.5 bg-[#262730] rounded"
                    />
                    <input
                      type="number"
                      min={item.min_value}
                      max={item.max_value}
                      step={item.step}
                      value={currentVal}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value);
                        if (!isNaN(val)) {
                          handleParamChange(item.param_name, val);
                        }
                      }}
                      className="w-16 bg-[#0e1117] border border-[#383b42] rounded px-1.5 py-0.5 text-xs text-right font-mono text-[#fafafa] focus:outline-none focus:border-[#ff4b4b]"
                    />
                  </div>
                </div>

                {/* Footer: Applicable Rules Badge */}
                <div className="mt-2 pt-1.5 border-t border-[#262730] flex items-center justify-between text-[10px] text-[#808495]">
                  <span className="truncate max-w-[280px]">
                    Applies to:{' '}
                    <span className="text-[#fafafa] font-mono">
                      {item.applicable_rules.slice(0, 4).join(', ')}
                      {item.applicable_rules.length > 4 && ` +${item.applicable_rules.length - 4} more`}
                    </span>
                  </span>
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-[#262730] text-[#808495]">
                    {item.category}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
