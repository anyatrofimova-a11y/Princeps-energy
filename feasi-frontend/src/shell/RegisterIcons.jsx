/**
 * Register-tile icon set — monochrome, 14px, stroke-1.5. No emojis.
 *
 * Each export takes optional {size, className} and inherits currentColor
 * so it picks up the tile's severity colour via CSS.
 */

import {
  BarChart3, Thermometer, BatteryWarning, Battery, Settings2, Droplets,
  Snowflake, Wind, Timer, Wrench, ShieldCheck, Shield, Leaf, Activity,
  CheckCircle2, Zap, ZapOff, AlertTriangle, ShieldAlert, ArrowUpCircle,
  RefreshCw, Flame, Lock, Scissors, PoundSterling, Cable, Gauge,
} from 'lucide-react';

const STROKE = 1.6;
const SIZE = 14;

const _wrap = (Icon) => (props = {}) => (
  <Icon size={props.size ?? SIZE} strokeWidth={props.strokeWidth ?? STROKE} aria-hidden {...props} />
);

// Data-Centre register icons
export const I = {
  pueDeviation:    _wrap(BarChart3),
  hotspots:        _wrap(Thermometer),
  upsHealth:       _wrap(BatteryWarning),
  gensetTest:      _wrap(Settings2),
  waterLeaks:      _wrap(Droplets),
  coolingOverride: _wrap(Snowflake),
  freeCooling:     _wrap(Wind),
  tti:             _wrap(Timer),
  workOrders:      _wrap(Wrench),
  security:        _wrap(ShieldCheck),
  bmsOverrides:    _wrap(Shield),
  cfeHours:        _wrap(Leaf),
  chillerLoad:     _wrap(Activity),
  redundancy:      _wrap(CheckCircle2),

  // BESS register icons
  cellImbalance:   _wrap(Zap),
  thermalWarn:     _wrap(Thermometer),
  groundFault:     _wrap(Cable),
  bmsFault:        _wrap(ShieldAlert),
  capacityTest:    _wrap(Battery),
  firmware:        _wrap(ArrowUpCircle),
  cycles:          _wrap(RefreshCw),
  fireDetector:    _wrap(Flame),
  isolationLocks:  _wrap(Lock),
  curtailment:     _wrap(Scissors),
  arbitrage:       _wrap(PoundSterling),
  contactor:       _wrap(ZapOff),
  alarm:           _wrap(AlertTriangle),
  gauge:           _wrap(Gauge),
};

export default I;
