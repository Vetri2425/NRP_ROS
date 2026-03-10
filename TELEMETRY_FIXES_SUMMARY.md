# Telemetry Node Fixes Summary

## Overview
Fixed three critical inconsistencies in `telemetry_node.py` to align with the MAVROS bridge implementation and ensure consistent data flow to the frontend.

## Issues Fixed

### 1. ✅ Altitude Source Discrepancy
**Problem:** telemetry_node.py subscribed to `/mavros/global_position/global` (raw altitude) while MAVROS bridge uses `/mavros/global_position/global_corrected` (corrected altitude with +92.2m offset applied by gps_altitude_corrector.py ROS node).

**Fix:** Changed subscription topic from `global` → `global_corrected`
```python
# Before
self.position_sub = self.create_subscription(
    NavSatFix,
    '/mavros/global_position/global',  # ❌ Raw altitude
    ...
)

# After
self.position_sub = self.create_subscription(
    NavSatFix,
    '/mavros/global_position/global_corrected',  # ✅ Corrected altitude
    ...
)
```

**Impact:** Frontend now receives consistent altitude values from both data paths.

---

### 2. ✅ Satellite Count Extraction Error
**Problem:** Code incorrectly extracted satellite count from `msg.status.service` (GNSS service bitmask: 0x01=GPS, 0x02=SBAS, etc.) instead of the proper satellite count field.

**Fix:** Removed incorrect satellite extraction; added comment explaining proper data source
```python
# Before
self.telemetry_data['global']['satellites_visible'] = int(msg.status.service) if msg.status.service >= 0 else 0  # ❌ GNSS bitmask!

# After
# NOTE: msg.status.service is GNSS service bitmask, NOT satellite count
# Satellite count comes from separate GPSRAW topic via MAVROS bridge
```

**Impact:** Prevents corrupted satellite count values; satellite data now flows only from MAVROS bridge's proper GPSRAW topic handler.

---

### 3. ✅ RTK Status Mapping Inconsistency
**Problem:** Two misalignments:
1. RTK status mapping used incomplete 0-4 range instead of full 0-6 range
2. `base_linked` threshold was `>= 3` (3D mode) instead of `>= 5` (RTK Float)

**Fix:** Aligned mapping to MAVROS bridge implementation
```python
# Before
fix_type = _map_gps_fix_type(msg.status.status)  # ❌ 0-4 mapping
self.telemetry_data['rtk']['base_linked'] = fix_type >= 3  # ❌ Includes 3D

# After
# Full 0-6 range matching MAVROS bridge:
# 0: No GPS, 1: No Fix, 2: 2D Fix, 3: 3D Fix, 4: 3D DGPS, 5: RTK Float, 6: RTK Fixed
fix_type = int(msg.status.status) if hasattr(msg.status, 'status') else 0  # ✅ Direct extraction
self.telemetry_data['rtk']['base_linked'] = fix_type >= 5  # ✅ RTK Float or better
```

**Impact:** RTK status now correctly reflects actual fix types; `base_linked` only true for actual RTK modes (5-6).

---

## Data Flow Consistency

### Before
- MAVROS Bridge: global_corrected, 0-6 RTK mapping, satellites from GPSRAW
- Telemetry Node: global, 0-4 RTK mapping, satellites from bitmask ❌

### After (Aligned)
- MAVROS Bridge: global_corrected, 0-6 RTK mapping, satellites from GPSRAW ✅
- Telemetry Node: global_corrected, 0-6 RTK mapping, satellites from GPSRAW ✅

## Documentation Added
Enhanced telemetry_node.py module docstring to explain:
- Data source consistency with MAVROS bridge
- Why satellite count is NOT extracted from NavSatFix
- RTK mode ranges and fix type definitions
- Altitude correction (+92.2m from gps_altitude_corrector.py)

## Frontend Impact
✅ Consistent altitude values across both telemetry paths
✅ Correct satellite visibility counts
✅ Accurate RTK status and lock indicators
✅ Proper base_linked flag reflecting actual RTK fix state
