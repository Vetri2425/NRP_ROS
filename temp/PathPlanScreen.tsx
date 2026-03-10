import React, { useState, useEffect, useRef, useCallback } from 'react';
import { View, StyleSheet, SafeAreaView, StatusBar, Alert, Modal, ScrollView, TouchableOpacity, Text } from 'react-native';
import { colors } from '../theme/colors';
import { PathPlanWaypoint } from '../types/pathplan';
import { useRover } from '../context/RoverContext';
import { PathSequenceSidebar } from '../components/pathplan/PathSequenceSidebar';
import MissionOpsPanel from '../components/pathplan/MissionOpsPanel';
import { MissionStatistics } from '../components/pathplan/MissionStatistics';
import { PathPlanMap } from '../components/pathplan/PathPlanMap';
import { DrawingToolsPanel } from '../components/pathplan/DrawingToolsPanel';
import { CircleGeneratorDialog } from '../components/pathplan/CircleGeneratorDialog';
import { SurveyGridDialog } from '../components/pathplan/SurveyGridDialog';
import { TextAnnotationDialog } from '../components/pathplan/TextAnnotationDialog';
import { FreeDrawDialog, DrawSettings } from '../components/pathplan/FreeDrawDialog';
import { DrawingCanvas } from '../components/pathplan/DrawingCanvas';
import { ManualPathConnectionCanvas } from '../components/pathplan/ManualPathConnectionCanvas';
import { ManualControlPanel } from '../components/pathplan/ManualControlPanel';
import { FailsafeModeSelector } from '../components/pathplan/FailsafeModeSelector';
import { FailsafeStrictPopup } from '../components/pathplan/FailsafeStrictPopup';
import { FailsafeRelaxNotification } from '../components/pathplan/FailsafeRelaxNotification';
import { haversineDistance } from '../utils/missionCalculator';
import { textToWaypointPath } from '../utils/textToPath';
import * as DocumentPicker from 'expo-document-picker';
import * as FileSystem from 'expo-file-system/legacy';
import * as Sharing from 'expo-sharing';
import { downloadFileToDevice } from '../utils/downloadHelper';
import PersistentStorage from '../services/PersistentStorage';
import {
  validateWaypoints,
  hasCriticalErrors,
  getCriticalErrors,
  getWarnings,
  formatValidationErrors,
  sanitizeWaypointsForUpload,
  ValidationError,
} from '../utils/waypointValidator';

// Toggle debug logging for this screen
const DEBUG_LOG = true;

export default function PathPlanScreen() {
  const {
    telemetry,
    roverPosition,
    missionWaypoints,
    setMissionWaypoints,
    gpsFailsafeMode,
    setGpsFailsafeMode,
    gpsFailsafeStatus,
    onFailsafeAcknowledge,
    onFailsafeResume,
    onFailsafeRestart,
    services,
    socket,
  } = useRover();

  // Component mounted flag to prevent state updates after unmount
  const mountedRef = useRef(true);
  // Guard to prevent re-entrant upload handling causing recursive state updates
  const isUploadingRef = useRef(false);
  // Track ongoing async operations for proper cleanup
  const pendingOperationsRef = useRef<Set<Promise<any>>>(new Set());
  // Ref to track export operations
  const exportInProgressRef = useRef(false);
  // Cleanup timers
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  // Cleanup helper for timers
  const addTimer = (timer: ReturnType<typeof setTimeout>) => {
    timersRef.current.add(timer);
  };

  const clearTimer = (timer: ReturnType<typeof setTimeout>) => {
    clearTimeout(timer);
    timersRef.current.delete(timer);
  };

  const clearAllTimers = () => {
    timersRef.current.forEach(timer => clearTimeout(timer));
    timersRef.current.clear();
  };

  useEffect(() => {
    mountedRef.current = true;
    console.log('[PathPlanScreen] Component mounted');

    // App state listener to handle background/foreground transitions
    const { AppState } = require('react-native');
    const subscription = AppState.addEventListener('change', (nextAppState: string) => {
      if (nextAppState === 'active') {
        // App returned to foreground - reset export flag if stuck
        if (exportInProgressRef.current) {
          console.log('[PathPlanScreen] App returned to foreground - resetting export flag');
          exportInProgressRef.current = false;
        }
      }
    });

    return () => {
      mountedRef.current = false;

      // Remove app state listener
      subscription?.remove();

      // Clear all pending timers
      clearAllTimers();

      // Reset operation flags
      isUploadingRef.current = false;
      exportInProgressRef.current = false;

      // Cancel pending operations (they will check mountedRef)
      pendingOperationsRef.current.clear();

      console.log('[PathPlanScreen] Component unmounting - all async operations cancelled');
    };
  }, []);

  // Use context waypoints directly - convert format on the fly
  const waypoints = React.useMemo(() =>
    (missionWaypoints as any[]).map((wp, idx) => ({
      id: wp.sn ?? wp.id ?? idx + 1,
      lat: wp.lat,
      lon: wp.lng ?? wp.lon,
      alt: wp.alt ?? 0,
      row: wp.row ?? '',
      block: wp.block ?? '',
      pile: wp.pile ?? String(idx + 1),
      distance: wp.distance ?? 0,
    })),
    [missionWaypoints]
  );

  // Update waypoints in context
  const updateWaypoints = React.useCallback((newWaypoints: PathPlanWaypoint[]) => {
    setMissionWaypoints(
      newWaypoints.map((wp, idx) => ({
        sn: wp.id,
        block: wp.block ?? '',
        row: wp.row ?? '',
        pile: wp.pile ?? String(idx + 1),
        lat: wp.lat,
        lng: wp.lon,
        lon: wp.lon,
        alt: wp.alt,
        status: 'Pending' as const,
        time: '—',
        remark: '—',
        distance: wp.distance ?? 0,
      }))
    );
  }, [setMissionWaypoints]);
  const [selectedWaypoint, setSelectedWaypoint] = useState<number | null>(null);

  // GPS Failsafe state
  const [showFailsafeModeSelector, setShowFailsafeModeSelector] = useState(false);
  const [showStrictPopup, setShowStrictPopup] = useState(false);
  const [showRelaxNotification, setShowRelaxNotification] = useState(false);
  const [failsafeEvent, setFailsafeEvent] = useState<{ wpDistCm: number; thresholdCm: number } | null>(null);

  // Sync waypoints to context only when explicitly needed (e.g., on upload)
  // Removed automatic sync to prevent infinite loop
  const [missionName, setMissionName] = useState('DRAWN MISSION - 4:15:34');
  const [uploadPreviewWaypoints, setUploadPreviewWaypoints] = useState<PathPlanWaypoint[] | null>(null);
  const [uploadPreviewName, setUploadPreviewName] = useState<string>('');
  const [uploadPreviewValidationErrors, setUploadPreviewValidationErrors] = useState<ValidationError[]>([]);
  const [showUploadPreview, setShowUploadPreview] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [showUploadProgress, setShowUploadProgress] = useState<boolean>(false);
  const [downloadProgress, setDownloadProgress] = useState<number>(0);
  const [showDownloadProgress, setShowDownloadProgress] = useState<boolean>(false);
  const [pathAssignmentMode, setPathAssignmentMode] = useState<'auto' | 'manual'>('auto');
  const [manualPathConnections, setManualPathConnections] = useState<number[]>([]);
  const [isConnectingPath, setIsConnectingPath] = useState<boolean>(false);

  // Drawing tools state
  const [activeDrawingTool, setActiveDrawingTool] = useState<string | null>(null);
  const [showCircleDialog, setShowCircleDialog] = useState(false);
  const [showSurveyGridDialog, setShowSurveyGridDialog] = useState(false);
  const [showTextDialog, setShowTextDialog] = useState(false);
  const [showDrawDialog, setShowDrawDialog] = useState(false);
  const [isDrawingMode, setIsDrawingMode] = useState(false);
  const [drawSettings, setDrawSettings] = useState<DrawSettings | null>(null);
  const [homePosition, setHomePosition] = useState<{ lat: number; lng: number } | null>(null);
  const [isPinningHome, setIsPinningHome] = useState(false);

  // Manual control state
  const [showManualControl, setShowManualControl] = useState(false);

  // Full screen map state
  const [isMapFullscreen, setIsMapFullscreen] = useState(false);

  // Load persisted PathPlan state on mount
  useEffect(() => {
    const loadPersistedState = async () => {
      try {
        const [savedHomePosition, savedDrawSettings, savedDrawingMode, savedActiveTool, savedUIState] = await Promise.all([
          PersistentStorage.loadHomePosition(),
          PersistentStorage.loadDrawSettings(),
          PersistentStorage.loadDrawingMode(),
          PersistentStorage.loadActiveTool(),
          PersistentStorage.loadPathPlanUIState(),
        ]);

        if (savedHomePosition) {
          setHomePosition(savedHomePosition);
          console.log('[PathPlanScreen] 📂 Restored home position');
        }

        if (savedDrawSettings) {
          setDrawSettings(savedDrawSettings);
          console.log('[PathPlanScreen] 📂 Restored draw settings');
        }

        if (savedDrawingMode) {
          setIsDrawingMode(savedDrawingMode);
          console.log('[PathPlanScreen] 📂 Restored drawing mode');
        }

        if (savedActiveTool) {
          setActiveDrawingTool(savedActiveTool);
          console.log('[PathPlanScreen] 📂 Restored active tool');
        }

        // Restore UI state
        if (savedUIState) {
          if (savedUIState.selectedWaypoint !== undefined) {
            setSelectedWaypoint(savedUIState.selectedWaypoint);
            console.log('[PathPlanScreen] 📂 Restored selected waypoint:', savedUIState.selectedWaypoint);
          }
          // Map center and zoom are restored by the map component itself
        }
      } catch (error) {
        console.error('[PathPlanScreen] Failed to load persisted state:', error);
      }
    };

    loadPersistedState();
  }, []);

  // Listen for GPS Failsafe servo_suppressed events
  useEffect(() => {
    if (!socket) return;

    const handleServoSuppressed = (event: any) => {
      console.log('[PathPlanScreen] 🚫 Servo suppressed event received:', JSON.stringify(event, null, 2));
      console.log('[PathPlanScreen] 📋 Event details:', {
        mode: gpsFailsafeMode,
        wp_dist_cm: event.wp_dist_cm,
        xtrack_cm: event.xtrack_cm,
        threshold_cm: 6.0,
        mission_paused: event.mission_paused,
        waypoint_id: event.waypoint_id,
        timestamp: event.timestamp
      });

      setFailsafeEvent({
        wpDistCm: event.wp_dist_cm ?? 0,
        thresholdCm: 6.0,  // New threshold: 6.0 cm
      });

      console.log('[PathPlanScreen] GPS Failsafe mode:', gpsFailsafeMode);
      if (gpsFailsafeMode === 'strict') {
        console.log('[PathPlanScreen] ⚠️ STRICT MODE: Showing failsafe popup');
        console.log('[PathPlanScreen] ⚠️ Mission should be PAUSED by backend');
        setShowStrictPopup(true);
      } else if (gpsFailsafeMode === 'relax') {
        console.log('[PathPlanScreen] ℹ️ RELAX MODE: Showing failsafe notification');
        console.log('[PathPlanScreen] ℹ️ Mission continues with spray suppressed');
        setShowRelaxNotification(true);
      }
    };

    socket.on('servo_suppressed', handleServoSuppressed);
    console.log('[PathPlanScreen] 👂 Listening for servo_suppressed events');
    return () => {
      socket.off('servo_suppressed', handleServoSuppressed);
      console.log('[PathPlanScreen] 🔇 Stopped listening for servo_suppressed events');
    };
  }, [socket, gpsFailsafeMode]);

  // Consolidated auto-save using refs to prevent multiple useEffect triggers
  // This prevents infinite loops from cascading state updates
  const autoSaveTimersRef = useRef<Record<string, NodeJS.Timeout>>({});

  const debouncedAutoSave = useCallback(() => {
    // Clear existing timers
    Object.values(autoSaveTimersRef.current).forEach(timer => clearTimeout(timer));
    autoSaveTimersRef.current = {};

    // Home position - 500ms debounce
    if (homePosition) {
      autoSaveTimersRef.current.homePosition = setTimeout(() => {
        PersistentStorage.saveHomePosition(homePosition).catch(error => {
          console.error('[PathPlanScreen] Failed to persist home position:', error);
        });
      }, 500);
    }

    // Draw settings - 500ms debounce
    if (drawSettings) {
      autoSaveTimersRef.current.drawSettings = setTimeout(() => {
        PersistentStorage.saveDrawSettings(drawSettings).catch(error => {
          console.error('[PathPlanScreen] Failed to persist draw settings:', error);
        });
      }, 500);
    }

    // Drawing mode - 300ms debounce
    autoSaveTimersRef.current.drawingMode = setTimeout(() => {
      PersistentStorage.saveDrawingMode(isDrawingMode).catch(error => {
        console.error('[PathPlanScreen] Failed to persist drawing mode:', error);
      });
    }, 300);

    // Active tool - 300ms debounce
    if (activeDrawingTool) {
      autoSaveTimersRef.current.activeTool = setTimeout(() => {
        PersistentStorage.saveActiveTool(activeDrawingTool).catch(error => {
          console.error('[PathPlanScreen] Failed to persist active tool:', error);
        });
      }, 300);
    }

    // UI state - 300ms debounce
    autoSaveTimersRef.current.uiState = setTimeout(() => {
      PersistentStorage.savePathPlanUIState({
        selectedWaypoint,
      }).catch(error => {
        console.error('[PathPlanScreen] Failed to persist UI state:', error);
      });
    }, 300);
  }, [homePosition, drawSettings, isDrawingMode, activeDrawingTool, selectedWaypoint]);

  // Single consolidated useEffect for all auto-saves
  useEffect(() => {
    debouncedAutoSave();

    return () => {
      Object.values(autoSaveTimersRef.current).forEach(timer => clearTimeout(timer));
      autoSaveTimersRef.current = {};
    };
  }, [debouncedAutoSave]);

  // Toggle full screen map mode
  const toggleMapFullscreen = () => {
    setIsMapFullscreen(prev => !prev);
  };

  const handleMapPress = (coord: { latitude: number; longitude: number }) => {
    // Check if we're in home pinning mode
    if (isPinningHome) {
      setHomePosition({ lat: coord.latitude, lng: coord.longitude });
      setIsPinningHome(false);
      Alert.alert('Home Position Set', `Home set at ${coord.latitude.toFixed(6)}, ${coord.longitude.toFixed(6)}`);
      // Reopen draw dialog
      setShowDrawDialog(true);
      return;
    }

    const newId = waypoints.length + 1;
    const lastWp = waypoints[waypoints.length - 1];

    const dist = lastWp
      ? haversineDistance(
        { lat: lastWp.lat, lon: lastWp.lon },
        { lat: coord.latitude, lon: coord.longitude }
      )
      : 0;

    const newWp: PathPlanWaypoint = {
      id: newId,
      lat: coord.latitude,
      lon: coord.longitude,
      alt: 50.0,
      distance: dist,
      block: 'B1',
      row: 'R1',
      pile: String(newId),
    };

    updateWaypoints([...waypoints, newWp]);
  };

  const handleWaypointClick = (id: number) => {
    if (!isConnectingPath) return;

    // Check if waypoint is already in the connection list
    if (manualPathConnections.includes(id)) {
      Alert.alert('Already Connected', `Marking point #${id} is already in your path.`);
      return;
    }

    // Add waypoint to the connection sequence
    setManualPathConnections(prev => [...prev, id]);
  };

  const handleWaypointDrag = (id: number, coord: { latitude: number; longitude: number }) => {
    // Update waypoint coordinates and recalculate distances
    const updatedWaypoints = waypoints.map((wp, index) => {
      if (wp.id === id) {
        // Update the dragged waypoint's coordinates
        const prevWp = index > 0 ? waypoints[index - 1] : null;
        const distance = prevWp
          ? haversineDistance(
            { lat: prevWp.lat, lon: prevWp.lon },
            { lat: coord.latitude, lon: coord.longitude }
          )
          : 0;

        return {
          ...wp,
          lat: coord.latitude,
          lon: coord.longitude,
          distance,
        };
      } else if (index > 0 && waypoints[index - 1].id === id) {
        // Recalculate distance for the waypoint AFTER the dragged one
        const distance = haversineDistance(
          { lat: coord.latitude, lon: coord.longitude },
          { lat: wp.lat, lon: wp.lon }
        );

        return {
          ...wp,
          distance,
        };
      }
      return wp;
    });

    updateWaypoints(updatedWaypoints);
  };

  const handleDeleteWaypoint = (id: number) => {
    updateWaypoints(waypoints.filter(wp => wp.id !== id));
  };

  const handleAddWaypoints = (coords: { latitude: number; longitude: number }[]) => {
    if (coords.length === 0) {
      Alert.alert('No Marking Points', 'No coordinates to add.');
      return;
    }

    const newWaypoints = coords.map((coord, index) => {
      const newId = waypoints.length + index + 1;
      const lastWp = index === 0 && waypoints.length > 0 ? waypoints[waypoints.length - 1] : null;
      const prevWp = index > 0 ? { lat: coords[index - 1].latitude, lon: coords[index - 1].longitude } : lastWp;

      const dist = prevWp
        ? haversineDistance(
          { lat: prevWp.lat, lon: prevWp.lon },
          { lat: coord.latitude, lon: coord.longitude }
        )
        : 0;

      return {
        id: newId,
        lat: coord.latitude,
        lon: coord.longitude,
        alt: 50.0,
        distance: dist,
        block: 'AUTO',
        row: 'SHAPE',
        pile: String(newId),
      };
    });

    if (DEBUG_LOG) console.log('[PathPlan] Adding', newWaypoints.length, 'waypoints from drawing tool');
    updateWaypoints([...waypoints, ...newWaypoints]);
    setActiveDrawingTool(null); // Clear active tool after adding waypoints

    Alert.alert('Marking Points Added', `✓ ${newWaypoints.length} marking points added to mission`);
  };

  const handleTextAnnotation = (text: string, alignment: 'left' | 'center' | 'right', letterWidth: number, letterHeight: number, letterSpacing: number) => {
    const center = roverPosition ? { lat: roverPosition.lat, lng: roverPosition.lng } : { lat: 13.0827, lng: 80.2707 };

    // Generate waypoint coordinates for the text
    const textCoords = textToWaypointPath({
      text,
      centerLat: center.lat,
      centerLon: center.lng,
      letterWidth,
      letterHeight,
      letterSpacing,
      alignment,
    });

    if (textCoords.length === 0) {
      Alert.alert('No Marking Points', 'Unable to generate marking points for the given text.');
      return;
    }

    // Filter out separation markers (NaN coordinates) and convert to PathPlanWaypoint format
    const newWaypoints: PathPlanWaypoint[] = [];
    let lastValidWp: { lat: number; lon: number } | null = waypoints.length > 0 ? waypoints[waypoints.length - 1] : null;
    let wpId = waypoints.length + 1;

    for (let i = 0; i < textCoords.length; i++) {
      const coord = textCoords[i];

      // Check if this is a separation marker
      if (isNaN(coord.latitude) || isNaN(coord.longitude)) {
        // Reset distance calculation for next letter (don't connect to previous letter)
        lastValidWp = null;
        continue;
      }

      const dist = lastValidWp
        ? haversineDistance(
          { lat: lastValidWp.lat, lon: lastValidWp.lon },
          { lat: coord.latitude, lon: coord.longitude }
        )
        : 0;

      newWaypoints.push({
        id: wpId++,
        lat: coord.latitude,
        lon: coord.longitude,
        alt: 50.0,
        distance: dist,
        block: 'TEXT',
        row: text.substring(0, 10),
        pile: String(wpId - 1),
      });

      lastValidWp = { lat: coord.latitude, lon: coord.longitude };
    }

    updateWaypoints([...waypoints, ...newWaypoints]);
    Alert.alert('Text Path Created', `${newWaypoints.length} marking points generated for "${text}"`);
  };

  // Handle freehand drawing completion from DrawingCanvas
  const handleDrawingComplete = (coords: { latitude: number; longitude: number }[]) => {
    if (coords.length === 0) {
      setIsDrawingMode(false);
      setDrawSettings(null);
      return;
    }

    // Convert drawn coordinates to PathPlanWaypoint format
    // Filter out NaN separators and track path breaks for distance calculation
    const newWaypoints: PathPlanWaypoint[] = [];
    let lastValidWp: { lat: number; lon: number } | null = waypoints.length > 0 ? waypoints[waypoints.length - 1] : null;
    let wpId = waypoints.length + 1;
    let pathSegmentIndex = 1;

    if (DEBUG_LOG) console.log('[PathPlan] Drawing completed with', coords.length, 'coordinates');

    for (let i = 0; i < coords.length; i++) {
      const coord = coords[i];

      // Check if this is a NaN separator (path break)
      if (isNaN(coord.latitude) || isNaN(coord.longitude)) {
        // Reset last waypoint for next segment (don't connect across gaps)
        lastValidWp = null;
        pathSegmentIndex++;
        if (DEBUG_LOG) console.log('[PathPlan] Path break at index', i);
        continue;
      }

      // Calculate distance from previous waypoint
      const dist = lastValidWp
        ? haversineDistance(
          { lat: lastValidWp.lat, lon: lastValidWp.lon },
          { lat: coord.latitude, lon: coord.longitude }
        )
        : 0;

      newWaypoints.push({
        id: wpId,
        lat: coord.latitude,
        lon: coord.longitude,
        alt: 50.0,
        distance: dist,
        block: 'DRAW',
        row: `S${pathSegmentIndex}`,
        pile: String(wpId),
      });

      lastValidWp = { lat: coord.latitude, lon: coord.longitude };
      wpId++;
    }

    if (newWaypoints.length > 0) {
      if (DEBUG_LOG) console.log('[PathPlan] Adding', newWaypoints.length, 'waypoints from drawing');
      updateWaypoints([...waypoints, ...newWaypoints]);
      Alert.alert('Drawing Complete', `✓ ${newWaypoints.length} marking points created from your drawing`);
    } else {
      Alert.alert('No Marking Points', 'Drawing did not generate any marking points. Try drawing a longer path.');
    }

    setIsDrawingMode(false);
    setDrawSettings(null);
  };

  const handleStartDrawing = (settings: DrawSettings) => {
    setDrawSettings(settings);
    setIsDrawingMode(true);
    setActiveDrawingTool('draw');
    Alert.alert(
      'Drawing Mode Active',
      `Draw area: ${settings.drawingWidth}m × ${settings.drawingHeight}m\nMarking point spacing: ${settings.waypointSpacing}m\n\nTouch and drag on the map to draw. Double-tap to finish.`
    );
  };

  const handlePinHomeMode = () => {
    setShowDrawDialog(false);
    setIsPinningHome(true);
    Alert.alert('Pin Home Position', 'Tap on the map to set the home/start position for your drawing.');
  };

  // Manual control handlers
  const handleOpenManualControl = () => {
    setShowManualControl(true);
  };

  const handleCloseManualControl = () => {
    setShowManualControl(false);
  };

  const handleUpdateWaypoints = (updatedWaypoints: PathPlanWaypoint[]) => {
    updateWaypoints(updatedWaypoints);
  };

  // File type validation
  const ACCEPTED_EXTENSIONS = ['waypoint', 'waypoints', 'csv', 'dxf', 'json', 'kml'];

  const validateFileExtension = (filename: string): boolean => {
    const ext = filename.split('.').pop()?.toLowerCase() || '';
    if (DEBUG_LOG) console.log('[PathPlan] validateFileExtension:', { filename, ext });
    return ACCEPTED_EXTENSIONS.includes(ext);
  };

  const validateWaypoint = (wp: any, index: number): boolean => {
    const lat = Number(wp.lat);
    const lon = Number(wp.lon ?? wp.lng);
    const alt = Number(wp.alt ?? 0);

    if (isNaN(lat) || isNaN(lon) || isNaN(alt)) {
      throw new Error(`Invalid numeric values at waypoint ${index + 1}`);
    }

    if (lat < -90 || lat > 90) {
      throw new Error(`Invalid latitude ${lat} at waypoint ${index + 1}. Must be between -90 and 90.`);
    }

    if (lon < -180 || lon > 180) {
      throw new Error(`Invalid longitude ${lon} at waypoint ${index + 1}. Must be between -180 and 180.`);
    }

    return true;
  };

  const parseQGCWaypoints = (content: string): PathPlanWaypoint[] => {
    const lines = content.split(/\r?\n/).map(l => l.trim()).filter(Boolean);

    if (lines.length === 0 || !lines[0].startsWith('QGC WPL')) {
      throw new Error('Invalid QGC waypoint format. File must start with "QGC WPL 110".');
    }

    const dataLines = lines.slice(1); // Skip header
    const waypoints: PathPlanWaypoint[] = [];

    dataLines.forEach((line, idx) => {
      const parts = line.split(/\t/);

      if (parts.length < 11) {
        throw new Error(`Invalid QGC waypoint format at line ${idx + 2}. Expected at least 11 tab-separated fields.`);
      }

      const lat = parseFloat(parts[8]);
      const lon = parseFloat(parts[9]);
      const alt = parseFloat(parts[10]);

      const wp = {
        lat,
        lon,
        alt: isNaN(alt) ? 0 : alt,
      };

      validateWaypoint(wp, idx);

      waypoints.push({
        id: idx + 1,
        lat,
        lon,
        alt: wp.alt,
        distance: 0,
        block: '',
        row: '',
        pile: String(idx + 1),
      });
    });

    if (DEBUG_LOG) console.log('[PathPlan] parseQGCWaypoints -> parsed', waypoints.length, waypoints.slice(0, 6));

    return waypoints;
  };

  const parseCSV = (content: string): PathPlanWaypoint[] => {
    const lines = content.split(/\r?\n/).map(l => l.trim()).filter(Boolean);

    if (lines.length < 2) {
      throw new Error('CSV file must contain headers and at least one data row.');
    }

    const headers = lines[0].split(',').map(h => h.trim().toLowerCase());
    const latIndex = headers.findIndex(h => h === 'latitude' || h === 'lat');
    const lonIndex = headers.findIndex(h => h === 'longitude' || h === 'lon' || h === 'lng');
    const altIndex = headers.findIndex(h => h === 'altitude' || h === 'alt');

    // Optional field indices
    const blockIndex = headers.findIndex(h => h === 'block');
    const rowIndex = headers.findIndex(h => h === 'row');
    const pileIndex = headers.findIndex(h => h === 'pile');

    if (latIndex === -1 || lonIndex === -1) {
      throw new Error('CSV must contain "latitude" and "longitude" columns in the header.');
    }

    const waypoints: PathPlanWaypoint[] = [];
    const dataLines = lines.slice(1);

    dataLines.forEach((line, idx) => {
      const values = line.split(',').map(v => v.trim());

      if (values.length <= Math.max(latIndex, lonIndex)) {
        throw new Error(`Insufficient columns at row ${idx + 2}.`);
      }

      const lat = parseFloat(values[latIndex]);
      const lon = parseFloat(values[lonIndex]);
      const alt = altIndex !== -1 ? parseFloat(values[altIndex]) : 0;

      const wp = { lat, lon, alt: isNaN(alt) ? 0 : alt };
      validateWaypoint(wp, idx);

      waypoints.push({
        id: idx + 1,
        lat,
        lon,
        alt: wp.alt,
        distance: 0,
        block: blockIndex !== -1 && values[blockIndex] ? values[blockIndex] : '',
        row: rowIndex !== -1 && values[rowIndex] ? values[rowIndex] : '',
        pile: pileIndex !== -1 && values[pileIndex] ? values[pileIndex] : String(idx + 1),
      });
    });

    if (DEBUG_LOG) console.log('[PathPlan] parseCSV -> parsed', waypoints.length, waypoints.slice(0, 6));

    return waypoints;
  };

  const parseJSON = (content: string): PathPlanWaypoint[] => {
    const data = JSON.parse(content);

    if (!Array.isArray(data)) {
      throw new Error('JSON must be an array of waypoint objects.');
    }

    if (data.length === 0) {
      throw new Error('JSON array is empty.');
    }

    const waypoints: PathPlanWaypoint[] = [];

    data.forEach((item: any, idx: number) => {
      const lat = Number(item.lat ?? item.latitude);
      const lon = Number(item.lon ?? item.lng ?? item.longitude);
      const alt = Number(item.alt ?? item.altitude ?? 0);

      const wp = { lat, lon, alt };
      validateWaypoint(wp, idx);

      waypoints.push({
        id: item.id ?? idx + 1,
        lat,
        lon,
        alt,
        distance: Number(item.distance ?? 0),
        block: item.block ?? '',
        row: item.row ?? '',
        pile: item.pile ?? String(idx + 1),
      });
    });

    if (DEBUG_LOG) console.log('[PathPlan] parseJSON -> parsed', waypoints.length, waypoints.slice(0, 6));

    return waypoints;
  };

  const parseKML = (content: string): PathPlanWaypoint[] => {
    // Basic KML parsing for <coordinates> tags
    const coordsRegex = /<coordinates>([\s\S]*?)<\/coordinates>/g;
    const matches = [...content.matchAll(coordsRegex)];

    if (matches.length === 0) {
      throw new Error('No <coordinates> tags found in KML file.');
    }

    const waypoints: PathPlanWaypoint[] = [];
    let wpId = 1;

    matches.forEach((match) => {
      const coordsText = match[1].trim();
      const coordLines = coordsText.split(/\s+/).filter(Boolean);

      coordLines.forEach((coordStr, idx) => {
        const [lonStr, latStr, altStr] = coordStr.split(',');
        const lon = parseFloat(lonStr);
        const lat = parseFloat(latStr);
        const alt = altStr ? parseFloat(altStr) : 0;

        const wp = { lat, lon, alt: isNaN(alt) ? 0 : alt };
        validateWaypoint(wp, wpId - 1);

        waypoints.push({
          id: wpId++,
          lat,
          lon,
          alt: wp.alt,
          distance: 0,
          block: '',
          row: '',
          pile: String(wpId - 1),
        });
      });
    });

    if (DEBUG_LOG) console.log('[PathPlan] parseKML -> parsed', waypoints.length, waypoints.slice(0, 6));

    return waypoints;
  };

  const parseDXF = (content: string): PathPlanWaypoint[] => {
    const lines = content.split(/\r?\n/).map(l => l.trim());
    const waypoints: PathPlanWaypoint[] = [];
    let currentPoint: any = {};
    let wpId = 1;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      if (line === '10') {
        // X coordinate (longitude)
        currentPoint.lon = parseFloat(lines[i + 1]);
      } else if (line === '20') {
        // Y coordinate (latitude)
        currentPoint.lat = parseFloat(lines[i + 1]);
      } else if (line === '30') {
        // Z coordinate (altitude)
        currentPoint.alt = parseFloat(lines[i + 1]);

        // Complete point found
        if (currentPoint.lat !== undefined && currentPoint.lon !== undefined) {
          const wp = {
            lat: currentPoint.lat,
            lon: currentPoint.lon,
            alt: isNaN(currentPoint.alt) ? 0 : currentPoint.alt,
          };

          validateWaypoint(wp, wpId - 1);

          waypoints.push({
            id: wpId++,
            lat: wp.lat,
            lon: wp.lon,
            alt: wp.alt,
            distance: 0,
            block: '',
            row: '',
            pile: String(wpId - 1),
          });
        }

        currentPoint = {};
      }
    }

    if (waypoints.length === 0) {
      throw new Error('No valid POINT entities found in DXF file.');
    }

    if (DEBUG_LOG) console.log('[PathPlan] parseDXF -> parsed', waypoints.length, waypoints.slice(0, 6));

    return waypoints;
  };

  const calculateDistances = (waypoints: PathPlanWaypoint[]): PathPlanWaypoint[] => {
    return waypoints.map((wp, idx) => {
      if (idx === 0) {
        return { ...wp, distance: 0 };
      }
      const prev = waypoints[idx - 1];
      const dist = haversineDistance(
        { lat: prev.lat, lon: prev.lon },
        { lat: wp.lat, lon: wp.lon }
      );
      return { ...wp, distance: dist };
    });
  };

  // Helper function to get MIME type for each export format
  const getMimeType = (format: string): string => {
    switch (format) {
      case 'qgc':
        return 'text/plain';
      case 'json':
        return 'application/json';
      case 'kml':
        return 'application/vnd.google-earth.kml+xml';
      case 'csv':
        return 'text/csv';
      case 'dxf':
        return 'application/dxf';
      default:
        return 'text/plain';
    }
  };

  // Export mission file to device storage and share
  // CRITICAL FIX: Proper async handling and cleanup to prevent crashes
  const handleExportMission = async (format: string, content: string, filename?: string) => {
    // Prevent re-entrant exports
    if (exportInProgressRef.current) {
      console.log('[PathPlan] Export already in progress, ignoring request');
      Alert.alert('Export In Progress', 'Please wait for the current export to complete.');
      return;
    }

    // Check if component is mounted
    if (!mountedRef.current) {
      console.warn('[PathPlan] Component unmounted, aborting export');
      return;
    }

    exportInProgressRef.current = true;

    // Set a safety timeout to auto-reset flag if something goes wrong
    const safetyTimer = setTimeout(() => {
      if (exportInProgressRef.current) {
        console.warn('[PathPlan] Export safety timeout - resetting flag');
        exportInProgressRef.current = false;
      }
    }, 60000); // 60 second safety timeout
    addTimer(safetyTimer);

    try {
      if (!filename) {
        filename = `mission.${format === 'qgc' ? 'waypoints' : format}`;
      }

      // Create file path in app's temporary directory
      const fileUri = `${FileSystem.documentDirectory}${filename}`;

      if (DEBUG_LOG) console.log('[PathPlan] Exporting mission as', format, 'to', fileUri);

      // CRITICAL: Validate content before writing
      if (!content || content.length === 0) {
        throw new Error('Export content is empty');
      }

      // Check mount status before async file operation
      if (!mountedRef.current) {
        console.warn('[PathPlan] Component unmounted during export setup');
        clearTimer(safetyTimer);
        return;
      }

      // Write file to temporary storage first with timeout
      const writePromise = FileSystem.writeAsStringAsync(fileUri, content, {
        encoding: FileSystem.EncodingType.UTF8,
      });

      // Add timeout to prevent hanging
      const timeoutPromise = new Promise((_, reject) => {
        const timer = setTimeout(() => reject(new Error('File write timeout after 10 seconds')), 10000);
        addTimer(timer);
      });

      await Promise.race([writePromise, timeoutPromise]);

      // Check mount status after file write
      if (!mountedRef.current) {
        console.warn('[PathPlan] Component unmounted after file write');
        clearTimer(safetyTimer);
        return;
      }

      if (DEBUG_LOG) console.log('[PathPlan] File written successfully:', fileUri);

      // Use downloadFileToDevice to save directly to user-selected location
      // This opens native file picker on Android (SAF) or Share dialog on iOS
      // Wrap in timeout for permission dialogs
      console.log('[PathPlan] Requesting storage permission...');

      const downloadPromise = downloadFileToDevice(fileUri, filename, getMimeType(format));
      const downloadTimeout = new Promise<boolean>((_, reject) => {
        const timer = setTimeout(() => reject(new Error('Permission/download timeout after 30 seconds')), 30000);
        addTimer(timer);
      });

      const saved = await Promise.race([downloadPromise, downloadTimeout]);

      // Final mount check before showing result
      if (!mountedRef.current) {
        console.warn('[PathPlan] Component unmounted after download');
        clearTimer(safetyTimer);
        return;
      }

      clearTimer(safetyTimer);

      if (saved) {
        if (DEBUG_LOG) console.log('[PathPlan] File saved/shared successfully');
        Alert.alert('Export Successful', `Mission exported as ${filename}`);
      } else {
        // User cancelled - no action needed
        if (DEBUG_LOG) console.log('[PathPlan] User cancelled save operation');
      }
    } catch (error) {
      console.error('[PathPlan] Export error:', error);
      clearTimer(safetyTimer);

      // Only show alert if component is still mounted
      if (mountedRef.current) {
        // Don't show alert if user cancelled
        const errorMsg = error instanceof Error ? error.message : String(error);
        if (!errorMsg.includes('cancel') && !errorMsg.toLowerCase().includes('cancelled')) {
          Alert.alert(
            'Export Failed',
            `Failed to export mission:\n${errorMsg}\n\nTip: Make sure storage permissions are granted.`,
            [
              { text: 'OK' },
              { text: 'Retry', onPress: () => handleExportMission(format, content, filename) }
            ]
          );
        }
      }
    } finally {
      // Always reset flag and clear timer
      clearTimer(safetyTimer);
      exportInProgressRef.current = false;
      console.log('[PathPlan] Export operation completed - flag reset');
    }
  };

  // Load mission waypoints from controller/backend into the PathPlan editor
  const handleLoadFromController = async () => {
    // Check if component is mounted
    if (!mountedRef.current) {
      console.warn('[PathPlan] Component unmounted, aborting load from controller');
      return;
    }

    // Show progress UI and subscribe to progress events
    setDownloadProgress(0);
    setShowDownloadProgress(true);

    const unsubscribe = services.onDownloadProgress((progress) => {
      if (mountedRef.current) {
        setDownloadProgress(progress.percent);
      }
    });

    try {
      console.log('[PathPlan] Loading mission from controller...');

      const res: any = await services.downloadMission();

      // Validate response structure
      if (!res) {
        throw new Error('No response received from controller');
      }

      const wps = res?.waypoints ?? [];

      if (!Array.isArray(wps)) {
        throw new Error('Invalid response format - waypoints should be an array');
      }

      if (wps.length === 0) {
        Alert.alert(
          'No Mission',
          'No marking points available on controller.\n\nPlease upload a mission first or create marking points manually.',
          [{ text: 'OK' }]
        );
        return;
      }

      // Safely map waypoints with validation
      const mapped: PathPlanWaypoint[] = [];
      const errors: string[] = [];

      wps.forEach((wp: any, idx: number) => {
        try {
          const lat = Number(wp.lat ?? wp.latitude ?? 0);
          const lon = Number(wp.lon ?? wp.lng ?? wp.longitude ?? 0);
          const alt = Number(wp.alt ?? wp.altitude ?? 0);

          // Validate coordinates
          if (isNaN(lat) || isNaN(lon) || lat === 0 || lon === 0) {
            errors.push(`Waypoint ${idx + 1}: Invalid coordinates`);
            return;
          }

          if (lat < -90 || lat > 90 || lon < -180 || lon > 180) {
            errors.push(`Waypoint ${idx + 1}: Coordinates out of range`);
            return;
          }

          mapped.push({
            id: wp.id ?? idx + 1,
            lat,
            lon,
            alt: isNaN(alt) ? 0 : alt,
            distance: 0,
            block: String(wp.block ?? wp.block_id ?? ''),
            row: String(wp.row ?? wp.row_no ?? ''),
            pile: String(wp.pile ?? wp.pile_no ?? idx + 1),
          });
        } catch (wpError) {
          errors.push(`Waypoint ${idx + 1}: ${wpError instanceof Error ? wpError.message : 'Parse error'}`);
        }
      });

      if (mapped.length === 0) {
        const errorMsg = errors.length > 0 ? `\n\nErrors:\n${errors.slice(0, 3).join('\n')}` : '';
        throw new Error(`No valid waypoints could be loaded.${errorMsg}`);
      }

      // Check if still mounted before updating state
      if (!mountedRef.current) {
        console.warn('[PathPlan] Component unmounted during waypoint processing');
        return;
      }

      const withDistances = calculateDistances(mapped);
      updateWaypoints(withDistances);

      const warningMsg = errors.length > 0 ? `\n\nWarning: ${errors.length} waypoints had errors and were skipped.` : '';
      Alert.alert(
        'Mission Loaded',
        `Successfully loaded ${withDistances.length} marking points from controller.${warningMsg}`,
        [{ text: 'OK' }]
      );

      console.log(`[PathPlan] Loaded ${withDistances.length} waypoints from controller`);
    } catch (err) {
      console.error('[PathPlan] loadFromController error:', err);
      const errorMessage = err instanceof Error ? err.message : String(err);
      Alert.alert(
        'Load Failed',
        `Could not load mission from controller:\n\n${errorMessage}`,
        [
          { text: 'OK', style: 'default' },
          {
            text: 'Retry', onPress: () => {
              const timer = setTimeout(() => {
                if (mountedRef.current) {
                  handleLoadFromController();
                }
              }, 100);
              addTimer(timer);
            }, style: 'cancel'
          }
        ]
      );
    } finally {
      // Cleanup subscription and hide progress
      unsubscribe();
      setShowDownloadProgress(false);
      setDownloadProgress(0);
    }
  };

  // Load mission waypoints TO the controller (upload current waypoints to mission controller)
  const handleLoadMissionToController = async () => {
    // Check if component is mounted
    if (!mountedRef.current) {
      console.warn('[PathPlan] Component unmounted, aborting mission upload');
      return;
    }

    try {
      if (waypoints.length === 0) {
        Alert.alert(
          'No Marking Points',
          'No marking points to load to controller.\n\nPlease add marking points first by clicking on the map, importing a file, or using drawing tools.',
          [{ text: 'OK' }]
        );
        return;
      }

      console.log(`[PathPlan] Uploading ${waypoints.length} waypoints to controller...`);

      // Validate waypoints before sending
      const invalidWaypoints: number[] = [];
      waypoints.forEach((wp, idx) => {
        if (isNaN(wp.lat) || isNaN(wp.lon) || wp.lat === 0 || wp.lon === 0) {
          invalidWaypoints.push(idx + 1);
        }
      });

      if (invalidWaypoints.length > 0) {
        Alert.alert(
          'Invalid Marking Points',
          `The following marking points have invalid coordinates: ${invalidWaypoints.join(', ')}\n\nPlease fix or remove them before uploading.`,
          [{ text: 'OK' }]
        );
        return;
      }

      const controllerWaypoints = waypoints.map((wp, idx) => ({
        command: '16',
        param1: 0,
        param2: 0,
        param3: 0,
        param4: 0,
        lat: wp.lat,
        lng: wp.lon,
        alt: wp.alt,
        frame: 3,
        current: idx === 0 ? 1 : 0,
        autocontinue: 1,
        row: wp.row || '',
        block: wp.block || '',
        pile: wp.pile || String(idx + 1),
      }));

      // Show progress UI and subscribe to progress events
      setUploadProgress(0);
      setShowUploadProgress(true);

      const unsubscribe = services.onUploadProgress((progress) => {
        if (mountedRef.current) {
          setUploadProgress(progress.percent);
        }
      });

      try {
        const response = await services.loadMissionToController(controllerWaypoints);

        // Check if still mounted before updating state
        if (!mountedRef.current) {
          console.warn('[PathPlan] Component unmounted during upload');
          return;
        }

        if (response && response.success) {
          console.log(`[PathPlan] Mission uploaded successfully: ${waypoints.length} waypoints`);

          // Update context with waypoints in proper Waypoint format
          try {
            const contextWaypoints = waypoints.map((wp, idx) => ({
              sn: idx + 1,
              block: wp.block || '',
              row: wp.row || '',
              pile: wp.pile || String(idx + 1),
              lat: wp.lat,
              lon: wp.lon,
              distance: wp.distance ?? 0,
              alt: wp.alt,
              status: 'Pending' as const,
              time: new Date().toISOString(),
              remark: '',
            }));
            setMissionWaypoints(contextWaypoints);
          } catch (contextError) {
            console.error('[PathPlan] Failed to update context:', contextError);
            // Non-fatal error - mission was uploaded successfully
          }

          // BUGFIX: Clear mission runtime state when loading a new mission
          // This prevents the Mission Progress tab from showing stale "mission active" state
          // that was persisted from a previous mission session
          try {
            await Promise.all([
              PersistentStorage.saveMissionActive(false),        // Reset mission active flag
              PersistentStorage.saveStatusMap({}),               // Clear old waypoint statuses
              PersistentStorage.saveMissionStartTime(null),      // Clear old start time
              PersistentStorage.saveMissionEndTime(null),        // Clear old end time
            ]);
            console.log('[PathPlan] ✅ Cleared mission runtime state for new mission upload');
          } catch (storageError) {
            console.error('[PathPlan] ⚠️ Failed to clear mission runtime state:', storageError);
            // Non-fatal error - mission was uploaded successfully
          }

          Alert.alert(
            'Upload Successful',
            `Mission loaded successfully!\n\n${waypoints.length} marking points sent to controller.`,
            [{ text: 'OK' }]
          );
        } else {
          const errorMsg = response?.message || 'Unknown error occurred';
          throw new Error(errorMsg);
        }
      } catch (uploadError) {
        console.error('[PathPlan] loadMissionToController upload error:', uploadError);
        throw uploadError;
      } finally {
        // Cleanup subscription and hide progress
        unsubscribe();
        setShowUploadProgress(false);
        setUploadProgress(0);
      }
    } catch (err) {
      console.error('[PathPlan] loadMissionToController error:', err);
      const errorMessage = err instanceof Error ? err.message : String(err);

      Alert.alert(
        'Upload Failed',
        `Could not load mission to controller:\n\n${errorMessage}\n\nPlease check your connection and try again.`,
        [
          { text: 'OK', style: 'default' },
          {
            text: 'Retry', onPress: () => {
              const timer = setTimeout(() => {
                if (mountedRef.current) {
                  handleLoadMissionToController();
                }
              }, 100);
              addTimer(timer);
            }, style: 'cancel'
          }
        ]
      );
    }
  };

  const handleRequestUpload = async () => {
    if (isUploadingRef.current) {
      // Prevent re-entrant calls that can cause stack overflows
      if (DEBUG_LOG) console.log('[PathPlan] Upload already in progress, ignoring re-entrant call');
      return;
    }

    // Guard against component unmount during async operations
    if (!mountedRef.current) {
      console.warn('[PathPlan] Component unmounted, aborting upload');
      return;
    }

    isUploadingRef.current = true;
    try {
      if (DEBUG_LOG) console.log('[PathPlan] handleRequestUpload called - opening file picker dialog');

      const res = await DocumentPicker.getDocumentAsync({
        copyToCacheDirectory: true,
        type: '*/*' as any
      });

      if (DEBUG_LOG) console.log('[PathPlan] DocumentPicker response full:', res);
      if (DEBUG_LOG) console.log('[PathPlan] DocumentPicker response keys:', Object.keys(res));
      if (DEBUG_LOG) console.log('[PathPlan] DocumentPicker response.type:', (res as any).type);

      // Check both cancelled and success states
      if ((res as any).type === 'cancel' || (res as any).cancelled === true) {
        if (DEBUG_LOG) console.log('[PathPlan] DocumentPicker was cancelled by user');
        return;
      }

      if ((res as any).type !== 'success' && !(res as any).assets) {
        if (DEBUG_LOG) console.log('[PathPlan] DocumentPicker failed or cancelled - type:', (res as any).type);
        return;
      }

      // Handle both old and new response formats
      let uri: string;
      let name: string;

      if ((res as any).assets && Array.isArray((res as any).assets) && (res as any).assets.length > 0) {
        // New format with assets array
        const asset = (res as any).assets[0];
        uri = asset.uri;
        name = asset.name || asset.uri.split('/').pop() || 'waypoint.csv';
        if (DEBUG_LOG) console.log('[PathPlan] Using new DocumentPicker format:', { uri, name });
      } else if ((res as any).uri && (res as any).name) {
        // Old format with uri and name directly
        uri = (res as any).uri;
        name = (res as any).name;
        if (DEBUG_LOG) console.log('[PathPlan] Using old DocumentPicker format:', { uri, name });
      } else {
        if (DEBUG_LOG) console.log('[PathPlan] Unexpected DocumentPicker response format');
        Alert.alert('Upload Error', 'Unable to read file selection. Please try again.');
        return;
      }

      if (DEBUG_LOG) console.log('[PathPlan] Final extracted - uri:', uri, 'name:', name);

      // Validate file extension
      if (!validateFileExtension(name)) {
        Alert.alert(
          'Unsupported File Type',
          `Please select a valid file type: ${ACCEPTED_EXTENSIONS.join(', ')}`
        );
        return;
      }

      const ext = name.split('.').pop()?.toLowerCase() || '';
      if (DEBUG_LOG) console.log('[PathPlan] Selected file metadata:', { name, ext });

      // Check if component is still mounted before async file read
      if (!mountedRef.current) {
        console.warn('[PathPlan] Component unmounted during file selection');
        return;
      }

      let content: string;
      try {
        content = await FileSystem.readAsStringAsync(uri);
        if (DEBUG_LOG) console.log('[PathPlan] File content length:', content?.length ?? 0);
      } catch (readError) {
        console.error('[PathPlan] Failed to read file:', readError);
        Alert.alert(
          'File Read Error',
          `Could not read file: ${readError instanceof Error ? readError.message : String(readError)}\n\nPlease try selecting the file again.`
        );
        return;
      }

      // Validate content before parsing
      if (!content || content.length === 0) {
        Alert.alert('Empty File', 'The selected file appears to be empty.');
        return;
      }

      let parsed: PathPlanWaypoint[] = [];

      // Parse based on file type
      if (DEBUG_LOG) console.log('[PathPlan] Parsing as extension:', ext);
      switch (ext) {
        case 'waypoint':
        case 'waypoints':
          parsed = parseQGCWaypoints(content);
          break;
        case 'csv':
          parsed = parseCSV(content);
          break;
        case 'json':
          parsed = parseJSON(content);
          break;
        case 'kml':
          parsed = parseKML(content);
          break;
        case 'dxf':
          parsed = parseDXF(content);
          break;
        default:
          throw new Error(`Unsupported file format: ${ext}`);
      }

      if (DEBUG_LOG) console.log('[PathPlan] Parsed waypoints:', parsed.length, parsed.slice(0, 3));

      if (!parsed || parsed.length === 0) {
        Alert.alert('Import Failed', 'No valid marking points were found in the file.');
        return;
      }

      // Calculate distances between waypoints
      const waypointsWithDistances = calculateDistances(parsed);

      if (DEBUG_LOG) console.log('[PathPlan] Waypoints with distances:', waypointsWithDistances.length);

      // Validate waypoints and get errors/warnings
      const validationErrors = validateWaypoints(waypointsWithDistances);
      const criticalErrors = getCriticalErrors(validationErrors);
      const warnings = getWarnings(validationErrors);

      if (DEBUG_LOG) console.log('[PathPlan] Validation result:', { total: validationErrors.length, critical: criticalErrors.length, warnings: warnings.length });

      // Show preview modal instead of immediately replacing waypoints
      if (DEBUG_LOG) console.log('[PathPlan] Setting upload preview state and showing modal...');
      setUploadPreviewWaypoints(waypointsWithDistances);
      setUploadPreviewName(name);
      setUploadPreviewValidationErrors(validationErrors);

      if (DEBUG_LOG) console.log('[PathPlan] About to setShowUploadPreview(true)');
      setShowUploadPreview(true);
      if (DEBUG_LOG) console.log('[PathPlan] setShowUploadPreview(true) called - modal should now be visible');
    } catch (err) {
      console.error('[PathPlan] Import error:', err);

      // Provide user-friendly error messages
      const errorMessage = err instanceof Error ? err.message : String(err);
      let userMessage = errorMessage;

      // Add helpful guidance based on error type
      if (errorMessage.includes('coordinates')) {
        userMessage += '\n\nTip: Check that latitude and longitude values are valid numbers.';
      } else if (errorMessage.includes('format') || errorMessage.includes('extension')) {
        userMessage += '\n\nSupported formats: .waypoint, .waypoints, .csv, .json, .kml, .dxf';
      } else if (errorMessage.includes('empty')) {
        userMessage += '\n\nThe file may be corrupted or in an unsupported format.';
      }

      Alert.alert(
        'Mission Import Failed',
        userMessage,
        [
          { text: 'OK', style: 'default' },
          {
            text: 'Try Again', onPress: () => {
              const timer = setTimeout(() => {
                if (mountedRef.current) {
                  handleRequestUpload();
                }
              }, 100);
              addTimer(timer);
            }, style: 'cancel'
          }
        ]
      );
    } finally {
      // Release the guard after a short tick to avoid immediate re-entry
      const timer = setTimeout(() => {
        isUploadingRef.current = false;
      }, 0);
      addTimer(timer);
    }
  };

  // Commented out - too noisy on every render
  // if (DEBUG_LOG) {
  //   try { console.log('[PathPlan] handleRequestUpload ready (component render)'); } catch (e) {}
  // }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar backgroundColor={colors.headerBlue} barStyle="light-content" />

      {/* Main Content - full height */}
      <View style={styles.mainContent}>
        {isMapFullscreen ? (
          /* Full Screen Map Mode */
          <View style={styles.fullscreenMap}>
            <PathPlanMap
              waypoints={waypoints}
              onMapPress={handleMapPress}
              onWaypointDrag={handleWaypointDrag}
              onWaypointClick={handleWaypointClick}
              onAddWaypoints={handleAddWaypoints}
              roverPosition={roverPosition ? { lat: roverPosition.lat, lon: roverPosition.lng } : { lat: 0, lon: 0 }}
              heading={telemetry.attitude?.yaw_deg ?? null}
              activeDrawingTool={activeDrawingTool}
              onDrawingComplete={handleDrawingComplete}
              isDrawingMode={false}
              drawSettings={null}
              onToggleFullscreen={toggleMapFullscreen}
              isManualConnectionMode={isConnectingPath}
              manualConnections={manualPathConnections}
            />
          </View>
        ) : (
          <>
            {/* Left Sidebar - 25% width */}
            <View style={styles.leftPanel}>
              <View style={{ marginBottom: 12 }}>
                <DrawingToolsPanel
                  activeDrawingTool={activeDrawingTool}
                  onToolSelect={setActiveDrawingTool}
                  onShowCircleTool={() => setShowCircleDialog(true)}
                  onShowSurveyGridTool={() => setShowSurveyGridDialog(true)}
                  onShowTextTool={() => setShowTextDialog(true)}
                  onShowDrawTool={() => setShowDrawDialog(true)}
                />
              </View>
              <PathSequenceSidebar
                waypoints={isConnectingPath && manualPathConnections.length > 0
                  ? [...new Set(manualPathConnections)].map(id => waypoints.find(wp => wp.id === id)).filter(Boolean) as PathPlanWaypoint[]
                  : waypoints
                }
                selectedWaypoint={selectedWaypoint}
                onSelectWaypoint={setSelectedWaypoint}
                onDeleteWaypoint={handleDeleteWaypoint}
                onUpdateWaypoints={handleUpdateWaypoints}
                missionName={missionName}
                onMissionNameChange={setMissionName}
              />
            </View>

            {/* Center Map - flex: 1 */}
            <View style={styles.centerPanel}>
              <View style={styles.mapWrapper}>
                <PathPlanMap
                  waypoints={waypoints}
                  onMapPress={handleMapPress}
                  onWaypointDrag={handleWaypointDrag}
                  onWaypointClick={handleWaypointClick}
                  onAddWaypoints={handleAddWaypoints}
                  roverPosition={roverPosition ? { lat: roverPosition.lat, lon: roverPosition.lng } : { lat: 0, lon: 0 }}
                  heading={telemetry.attitude?.yaw_deg ?? null}
                  activeDrawingTool={activeDrawingTool}
                  onDrawingComplete={handleDrawingComplete}
                  isDrawingMode={false}
                  drawSettings={null}
                  onToggleFullscreen={toggleMapFullscreen}
                  isManualConnectionMode={isConnectingPath}
                  manualConnections={manualPathConnections}
                />
              </View>
            </View>

            {/* White Canvas Drawing Mode Overlay */}
            {isDrawingMode && drawSettings && (
              <DrawingCanvas
                visible={isDrawingMode}
                drawSettings={drawSettings}
                onDrawingComplete={handleDrawingComplete}
                onCancel={() => {
                  setIsDrawingMode(false);
                  setDrawSettings(null);
                }}
              />
            )}

            {/* Manual Path Connection Drawing Canvas */}
            <ManualPathConnectionCanvas
              visible={isConnectingPath}
              waypoints={waypoints}
              roverPosition={telemetry.global?.lat ? {
                lat: telemetry.global.lat,
                lng: telemetry.global.lon,
                heading: telemetry.attitude?.yaw_deg
              } : null}
              onConnectionsComplete={(connectedIds) => {
                // Remove duplicates to prevent React key errors
                const uniqueConnectedIds = [...new Set(connectedIds)];
                setManualPathConnections(uniqueConnectedIds);

                // ONLY keep connected waypoints in order (remove unconnected ones)
                const connectedWaypoints = uniqueConnectedIds.map(id =>
                  waypoints.find(wp => wp.id === id)
                ).filter(Boolean) as PathPlanWaypoint[];

                // Recalculate distances between connected waypoints
                const waypointsWithDistances = connectedWaypoints.map((wp, idx) => {
                  if (idx === 0) {
                    return { ...wp, distance: 0 };
                  }
                  const prevWp = connectedWaypoints[idx - 1];
                  const dist = haversineDistance(
                    { lat: prevWp.lat, lon: prevWp.lon },
                    { lat: wp.lat, lon: wp.lon }
                  );
                  return { ...wp, distance: dist };
                });

                // Update waypoints to ONLY show connected ones with recalculated distances
                updateWaypoints(waypointsWithDistances);
                setIsConnectingPath(false);
                Alert.alert('✓ Path Created', `Path created with ${uniqueConnectedIds.length} marking points. Unconnected marking points removed.`);
              }}
              onCancel={() => {
                setIsConnectingPath(false);
                setManualPathConnections([]);
              }}
            />

            {/* Old Manual Path Connection Mode Panel - REPLACED BY CANVAS */}
            {false && isConnectingPath && (
              <View style={{
                position: 'absolute',
                top: 16,
                left: '50%',
                transform: [{ translateX: -175 }],
                width: 350,
                backgroundColor: colors.panelBg,
                borderRadius: 12,
                padding: 16,
                borderWidth: 2,
                borderColor: '#4ADE80',
                shadowColor: '#000',
                shadowOffset: { width: 0, height: 4 },
                shadowOpacity: 0.3,
                shadowRadius: 8,
                elevation: 10,
                zIndex: 1000
              }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
                  <Text style={{ fontSize: 16, fontWeight: '700', color: '#4ADE80', flex: 1 }}>
                    ✏️ Manual Path Connection
                  </Text>
                  <TouchableOpacity
                    onPress={() => {
                      Alert.alert(
                        'Exit Manual Mode?',
                        'Your current connections will be saved. Continue?',
                        [
                          { text: 'Cancel', style: 'cancel' },
                          {
                            text: 'Exit', style: 'destructive', onPress: () => {
                              setIsConnectingPath(false);
                              if (manualPathConnections.length > 0) {
                                // Reorder waypoints based on connections
                                const reorderedWaypoints = manualPathConnections.map(id =>
                                  waypoints.find(wp => wp.id === id)
                                ).filter(Boolean) as PathPlanWaypoint[];

                                // Add any unconnected waypoints at the end
                                const connectedIds = new Set(manualPathConnections);
                                const unconnectedWaypoints = waypoints.filter(wp => !connectedIds.has(wp.id));

                                const finalWaypoints = [...reorderedWaypoints, ...unconnectedWaypoints];
                                updateWaypoints(finalWaypoints);
                                Alert.alert('✓ Path Saved', `Connected ${manualPathConnections.length} marking points in custom order.`);
                              }
                            }
                          }
                        ]
                      );
                    }}
                    style={{ padding: 6, backgroundColor: colors.inputBg, borderRadius: 6 }}>
                    <Text style={{ color: colors.text, fontSize: 12, fontWeight: '600' }}>✕</Text>
                  </TouchableOpacity>
                </View>

                <Text style={{ color: colors.textSecondary, fontSize: 12, marginBottom: 12 }}>
                  Tap waypoints in order to connect them. Each tap adds the waypoint to your path.
                </Text>

                <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                  <Text style={{ color: colors.accent, fontSize: 11, fontWeight: '600' }}>
                    Connected: {manualPathConnections.length}/{waypoints.length}
                  </Text>
                  {manualPathConnections.length > 0 && (
                    <TouchableOpacity
                      onPress={() => {
                        const lastId = manualPathConnections[manualPathConnections.length - 1];
                        setManualPathConnections(prev => prev.slice(0, -1));
                        Alert.alert('Undo', `Removed marking point #${lastId} from path.`);
                      }}
                      style={{ paddingVertical: 4, paddingHorizontal: 10, backgroundColor: colors.blueBtn, borderRadius: 6 }}>
                      <Text style={{ color: colors.text, fontSize: 10, fontWeight: '700' }}>↶ Undo</Text>
                    </TouchableOpacity>
                  )}
                </View>

                {/* Connection Sequence Display */}
                {manualPathConnections.length > 0 && (
                  <View style={{
                    maxHeight: 80,
                    backgroundColor: colors.cardBg,
                    borderRadius: 8,
                    padding: 8,
                    borderWidth: 1,
                    borderColor: colors.border
                  }}>
                    <Text style={{ color: colors.accent, fontSize: 10, fontWeight: '600', marginBottom: 4 }}>
                      Connection Sequence:
                    </Text>
                    <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                      <View style={{ flexDirection: 'row', gap: 6 }}>
                        {manualPathConnections.map((id, idx) => (
                          <View key={`manual-path-${id}-${idx}`} style={{ flexDirection: 'row', alignItems: 'center' }}>
                            <View style={{
                              backgroundColor: '#4ADE80',
                              paddingHorizontal: 8,
                              paddingVertical: 4,
                              borderRadius: 6
                            }}>
                              <Text style={{ color: '#000', fontSize: 10, fontWeight: '700' }}>#{id}</Text>
                            </View>
                            {idx < manualPathConnections.length - 1 && (
                              <Text style={{ color: colors.textSecondary, marginHorizontal: 4 }}>→</Text>
                            )}
                          </View>
                        ))}
                      </View>
                    </ScrollView>
                  </View>
                )}

                <View style={{ flexDirection: 'row', gap: 8, marginTop: 12 }}>
                  <TouchableOpacity
                    onPress={() => {
                      setManualPathConnections([]);
                      Alert.alert('Reset', 'All connections cleared.');
                    }}
                    style={{ flex: 1, paddingVertical: 8, backgroundColor: colors.inputBg, borderRadius: 8 }}>
                    <Text style={{ color: colors.text, textAlign: 'center', fontSize: 11, fontWeight: '700' }}>Clear All</Text>
                  </TouchableOpacity>

                  <TouchableOpacity
                    onPress={() => {
                      if (manualPathConnections.length < 2) {
                        Alert.alert('Not Enough Marking Points', 'Connect at least 2 marking points to create a path.');
                        return;
                      }

                      // Reorder waypoints based on connections
                      const reorderedWaypoints = manualPathConnections.map(id =>
                        waypoints.find(wp => wp.id === id)
                      ).filter(Boolean) as PathPlanWaypoint[];

                      // Add any unconnected waypoints at the end
                      const connectedIds = new Set(manualPathConnections);
                      const unconnectedWaypoints = waypoints.filter(wp => !connectedIds.has(wp.id));

                      const finalWaypoints = [...reorderedWaypoints, ...unconnectedWaypoints];
                      updateWaypoints(finalWaypoints);
                      setIsConnectingPath(false);
                      Alert.alert('✓ Path Created', `Successfully connected ${manualPathConnections.length} marking points in custom order.`);
                    }}
                    disabled={manualPathConnections.length < 2}
                    style={{
                      flex: 1,
                      paddingVertical: 8,
                      backgroundColor: manualPathConnections.length >= 2 ? colors.greenBtn : colors.inputBg,
                      borderRadius: 8,
                      opacity: manualPathConnections.length >= 2 ? 1 : 0.5
                    }}>
                    <Text style={{ color: colors.text, textAlign: 'center', fontSize: 11, fontWeight: '700' }}>✓ Finish</Text>
                  </TouchableOpacity>
                </View>
              </View>
            )}

            {/* Right Sidebar - 25% width, split into ops (top) and stats (bottom) */}
            <View style={styles.rightPanel}>
              <View style={styles.opsPanel}>
                <MissionOpsPanel
                  waypoints={waypoints}
                  roverPosition={roverPosition ? { lat: roverPosition.lat, lon: roverPosition.lng, alt: telemetry.global?.alt_rel ?? 0 } : { lat: 0, lon: 0, alt: 0 }}
                  onRequestUpload={() => {
                    // console.log('[PathPlan] onRequestUpload wrapper called');
                    handleRequestUpload();
                  }}
                  onLoadMission={handleLoadMissionToController}
                  onManualControlOpen={handleOpenManualControl}
                  onExportMission={handleExportMission}
                />
              </View>
              <View style={styles.statsPanel}>
                <MissionStatistics
                  waypoints={isConnectingPath && manualPathConnections.length > 0
                    ? manualPathConnections.map(id => waypoints.find(wp => wp.id === id)).filter(Boolean) as PathPlanWaypoint[]
                    : waypoints
                  }
                />
              </View>
            </View>
          </>
        )}
      </View>

      {/* Upload Preview Modal */}
      <Modal visible={showUploadPreview} transparent animationType="slide" onRequestClose={() => setShowUploadPreview(false)}>
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.6)', justifyContent: 'center', alignItems: 'center', padding: 16 }}>
          <View style={{ width: '100%', maxWidth: 900, backgroundColor: colors.panelBg, borderRadius: 12, padding: 16, borderWidth: 1, borderColor: colors.border, maxHeight: '90%' }}>
            <Text style={{ fontSize: 18, fontWeight: '700', color: colors.text, marginBottom: 8 }}>Import Preview</Text>
            <Text style={{ color: colors.textSecondary, marginBottom: 12 }}>{uploadPreviewName} — {uploadPreviewWaypoints ? uploadPreviewWaypoints.length : 0} marking points</Text>

            {/* Path Assignment Mode Selection */}
            <View style={{ marginBottom: 16, padding: 12, backgroundColor: colors.cardBg, borderRadius: 8, borderWidth: 1, borderColor: colors.border }}>
              <Text style={{ color: colors.accent, fontSize: 13, fontWeight: '600', marginBottom: 8 }}>Path Assignment Mode:</Text>
              <View style={{ flexDirection: 'row', gap: 10 }}>
                <TouchableOpacity
                  onPress={() => setPathAssignmentMode('auto')}
                  style={{
                    flex: 1,
                    paddingVertical: 10,
                    paddingHorizontal: 14,
                    backgroundColor: pathAssignmentMode === 'auto' ? colors.blueBtn : colors.inputBg,
                    borderRadius: 8,
                    borderWidth: 2,
                    borderColor: pathAssignmentMode === 'auto' ? '#4ADE80' : 'transparent'
                  }}>
                  <Text style={{ color: colors.text, fontWeight: '700', textAlign: 'center', fontSize: 12 }}>🤖 Auto</Text>
                  <Text style={{ color: colors.textSecondary, textAlign: 'center', fontSize: 9, marginTop: 2 }}>Sequential order</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => setPathAssignmentMode('manual')}
                  style={{
                    flex: 1,
                    paddingVertical: 10,
                    paddingHorizontal: 14,
                    backgroundColor: pathAssignmentMode === 'manual' ? colors.blueBtn : colors.inputBg,
                    borderRadius: 8,
                    borderWidth: 2,
                    borderColor: pathAssignmentMode === 'manual' ? '#4ADE80' : 'transparent'
                  }}>
                  <Text style={{ color: colors.text, fontWeight: '700', textAlign: 'center', fontSize: 12 }}>✏️ Manual</Text>
                  <Text style={{ color: colors.textSecondary, textAlign: 'center', fontSize: 9, marginTop: 2 }}>Draw connections</Text>
                </TouchableOpacity>
              </View>
              {pathAssignmentMode === 'manual' && (
                <View style={{ marginTop: 10, padding: 8, backgroundColor: 'rgba(74, 222, 128, 0.1)', borderRadius: 6, borderLeftWidth: 3, borderLeftColor: '#4ADE80' }}>
                  <Text style={{ color: colors.textSecondary, fontSize: 11 }}>
                    💡 Tip: In manual mode, waypoints will appear on the map without connections. Click waypoints in order to connect your custom path.
                  </Text>
                </View>
              )}
            </View>

            {/* Validation Errors/Warnings Section */}
            {uploadPreviewValidationErrors.length > 0 && (
              <View style={{ marginBottom: 12, padding: 10, backgroundColor: 'rgba(255,100,100,0.15)', borderRadius: 8, borderLeftWidth: 4, borderLeftColor: '#ff6464' }}>
                <Text style={{ color: '#ff6464', fontWeight: '700', marginBottom: 6 }}>
                  ⚠️ {uploadPreviewValidationErrors.length} Issue(s) Found
                </Text>
                <ScrollView style={{ maxHeight: 120 }}>
                  {getCriticalErrors(uploadPreviewValidationErrors).length > 0 && (
                    <View style={{ marginBottom: 8 }}>
                      <Text style={{ color: '#ff6464', fontWeight: '600', fontSize: 12, marginBottom: 4 }}>Critical Errors:</Text>
                      {getCriticalErrors(uploadPreviewValidationErrors).slice(0, 3).map((err, idx) => (
                        <Text key={`error-${err.message}-${idx}`} style={{ color: '#ff6464', fontSize: 11, marginBottom: 2 }}>
                          • {err.message}
                        </Text>
                      ))}
                      {getCriticalErrors(uploadPreviewValidationErrors).length > 3 && (
                        <Text style={{ color: '#ff6464', fontSize: 11 }}>... and {getCriticalErrors(uploadPreviewValidationErrors).length - 3} more</Text>
                      )}
                    </View>
                  )}
                  {getWarnings(uploadPreviewValidationErrors).length > 0 && (
                    <View>
                      <Text style={{ color: '#ffaa00', fontWeight: '600', fontSize: 12, marginBottom: 4 }}>Warnings:</Text>
                      {getWarnings(uploadPreviewValidationErrors).slice(0, 3).map((warn, idx) => (
                        <Text key={`warning-${warn.message}-${idx}`} style={{ color: '#ffaa00', fontSize: 11, marginBottom: 2 }}>
                          • {warn.message}
                        </Text>
                      ))}
                      {getWarnings(uploadPreviewValidationErrors).length > 3 && (
                        <Text style={{ color: '#ffaa00', fontSize: 11 }}>... and {getWarnings(uploadPreviewValidationErrors).length - 3} more</Text>
                      )}
                    </View>
                  )}
                </ScrollView>
              </View>
            )}

            {/* Waypoints Table */}
            <Text style={{ color: colors.accent, fontSize: 12, fontWeight: '600', marginBottom: 6 }}>Marking Point Details:</Text>
            <ScrollView style={{ maxHeight: 280, borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 8, backgroundColor: colors.cardBg }}>
              <View style={{ flexDirection: 'row', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border }}>
                <Text style={{ flex: 0.4, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>#</Text>
                <Text style={{ flex: 1.8, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>Latitude</Text>
                <Text style={{ flex: 1.8, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>Longitude</Text>
                <Text style={{ flex: 0.8, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>Alt(m)</Text>
                <Text style={{ flex: 0.8, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>Dist(m)</Text>
                <Text style={{ flex: 1, color: '#67E8F9', fontWeight: '700', fontSize: 11 }}>Block/Row</Text>
              </View>
              {uploadPreviewWaypoints && uploadPreviewWaypoints.map((wp) => (
                <View key={wp.id} style={{ flexDirection: 'row', paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.03)' }}>
                  <Text style={{ flex: 0.4, color: colors.text, fontSize: 11 }}>{wp.id}</Text>
                  <Text style={{ flex: 1.8, color: colors.text, fontFamily: 'monospace', fontSize: 10 }}>{wp.lat.toFixed(6)}</Text>
                  <Text style={{ flex: 1.8, color: colors.text, fontFamily: 'monospace', fontSize: 10 }}>{wp.lon.toFixed(6)}</Text>
                  <Text style={{ flex: 0.8, color: colors.text, fontSize: 10 }}>{wp.alt?.toFixed(1) || '0.0'}</Text>
                  <Text style={{ flex: 0.8, color: colors.text, fontSize: 10 }}>{(wp.distance || 0).toFixed(0)}</Text>
                  <Text style={{ flex: 1, color: colors.textSecondary, fontSize: 9 }}>
                    {wp.block || '—'}/{wp.row || '—'}
                  </Text>
                </View>
              ))}
            </ScrollView>

            <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 14, gap: 8 }}>
              <TouchableOpacity onPress={() => {
                if (uploadPreviewWaypoints) {
                  const criticalErrors = getCriticalErrors(uploadPreviewValidationErrors);

                  if (criticalErrors.length > 0) {
                    Alert.alert(
                      'Cannot Proceed',
                      `${criticalErrors.length} critical error(s) found:\n\n${formatValidationErrors(uploadPreviewValidationErrors, 3)}`,
                      [
                        { text: 'Back to Edit' },
                        {
                          text: 'Upload New File', onPress: () => {
                            setShowUploadPreview(false);
                            const timer = setTimeout(() => {
                              if (mountedRef.current) {
                                handleRequestUpload();
                              }
                            }, 200);
                            addTimer(timer);
                          }
                        }
                      ]
                    );
                    return;
                  }

                  const warnings = getWarnings(uploadPreviewValidationErrors);
                  if (warnings.length > 0) {
                    Alert.alert(
                      'Warnings Detected',
                      `${warnings.length} warning(s) found:\n\n${formatValidationErrors(uploadPreviewValidationErrors)}`,
                      [
                        { text: 'Cancel' },
                        {
                          text: 'Proceed Anyway', onPress: () => {
                            const sanitized = sanitizeWaypointsForUpload(uploadPreviewWaypoints);

                            // Check pathAssignmentMode even when there are warnings
                            if (pathAssignmentMode === 'manual') {
                              if (DEBUG_LOG) console.log('[PathPlan] Importing waypoints in MANUAL mode (with warnings):', sanitized.length);
                              updateWaypoints(sanitized);
                              setManualPathConnections([]);
                              setIsConnectingPath(true);
                              Alert.alert(
                                '✏️ Manual Path Mode',
                                `${sanitized.length} marking points imported. Click marking points in order to create your custom path. Tap a marking point to start, then tap others to connect them.`,
                                [{ text: 'Start Connecting' }]
                              );
                              setShowUploadPreview(false);
                            } else {
                              // Auto mode: Sequential import as usual
                              if (DEBUG_LOG) console.log('[PathPlan] Applying imported waypoints (Proceed with warnings):', sanitized.length, sanitized.slice(0, 3));
                              updateWaypoints(sanitized);
                              Alert.alert('✓ Import Complete', `Successfully imported ${sanitized.length} marking points.`);
                              setShowUploadPreview(false);
                            }
                          }
                        }
                      ]
                    );
                  } else {
                    // Handle mode-specific import
                    if (pathAssignmentMode === 'manual') {
                      // Manual mode: Import waypoints without sequential ordering, enable connection mode
                      const sanitized = sanitizeWaypointsForUpload(uploadPreviewWaypoints);
                      if (DEBUG_LOG) console.log('[PathPlan] Importing waypoints in MANUAL mode:', sanitized.length);
                      updateWaypoints(sanitized);
                      setManualPathConnections([]);
                      setIsConnectingPath(true);
                      Alert.alert(
                        '✏️ Manual Path Mode',
                        `${sanitized.length} marking points imported. Click marking points in order to create your custom path. Tap a marking point to start, then tap others to connect them.`,
                        [{ text: 'Start Connecting' }]
                      );
                      setShowUploadPreview(false);
                    } else {
                      // Auto mode: Sequential import as usual
                      const sanitized = sanitizeWaypointsForUpload(uploadPreviewWaypoints);
                      if (DEBUG_LOG) console.log('[PathPlan] Applying imported waypoints (Proceed clean):', sanitized.length, sanitized.slice(0, 3));
                      updateWaypoints(sanitized);
                      Alert.alert('✓ Import Complete', `Successfully imported ${sanitized.length} marking points.`);
                      setShowUploadPreview(false);
                    }
                  }
                }
              }} style={{ flex: 1, paddingVertical: 12, paddingHorizontal: 12, backgroundColor: colors.greenBtn, borderRadius: 8 }}>
                <Text style={{ color: colors.text, fontWeight: '700', textAlign: 'center' }}>✓ Proceed</Text>
              </TouchableOpacity>

              <TouchableOpacity onPress={() => {
                setShowUploadPreview(false);
                const timer = setTimeout(() => {
                  if (mountedRef.current) {
                    handleRequestUpload();
                  }
                }, 200);
                addTimer(timer);
              }} style={{ flex: 1, paddingVertical: 12, paddingHorizontal: 12, backgroundColor: colors.blueBtn, borderRadius: 8 }}>
                <Text style={{ color: colors.text, fontWeight: '700', textAlign: 'center' }}>📤 Upload New</Text>
              </TouchableOpacity>

              <TouchableOpacity onPress={() => {
                setShowUploadPreview(false);
              }} style={{ flex: 1, paddingVertical: 12, paddingHorizontal: 12, backgroundColor: colors.inputBg, borderRadius: 8 }}>
                <Text style={{ color: colors.text, fontWeight: '700', textAlign: 'center' }}>Cancel</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Circle Generator Dialog */}
      <CircleGeneratorDialog
        visible={showCircleDialog}
        onClose={() => setShowCircleDialog(false)}
        onGenerate={handleAddWaypoints}
        defaultCenter={
          roverPosition
            ? { lat: roverPosition.lat, lng: roverPosition.lng, alt: telemetry.global?.alt_rel ?? 30 }
            : undefined
        }
      />

      {/* Survey Grid Dialog */}
      <SurveyGridDialog
        visible={showSurveyGridDialog}
        onClose={() => setShowSurveyGridDialog(false)}
        onGenerate={handleAddWaypoints}
        defaultCenter={
          roverPosition
            ? { lat: roverPosition.lat, lng: roverPosition.lng, alt: telemetry.global?.alt_rel ?? 30 }
            : undefined
        }
      />

      {/* Text Annotation Dialog */}
      <TextAnnotationDialog
        visible={showTextDialog}
        onClose={() => setShowTextDialog(false)}
        onConfirm={handleTextAnnotation}
        defaultCenter={
          roverPosition
            ? { lat: roverPosition.lat, lng: roverPosition.lng }
            : undefined
        }
      />

      {/* Free Draw Dialog */}
      <FreeDrawDialog
        visible={showDrawDialog}
        onClose={() => setShowDrawDialog(false)}
        onStartDrawing={handleStartDrawing}
        onPinHome={handlePinHomeMode}
        hasHomePosition={!!(homePosition || roverPosition)}
        homePosition={homePosition || (roverPosition ? { lat: roverPosition.lat, lng: roverPosition.lng } : null)}
      />

      {/* Home Pinning Overlay */}
      {isPinningHome && (
        <View style={styles.pinningOverlay}>
          <View style={styles.pinningBanner}>
            <Text style={styles.pinningText}>📍 Tap on map to set home position</Text>
            <TouchableOpacity onPress={() => setIsPinningHome(false)} style={styles.pinningCancel}>
              <Text style={styles.pinningCancelText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      )}

      {/* Manual Control Modal */}
      <Modal
        visible={showManualControl}
        transparent={false}
        animationType="slide"
        onRequestClose={handleCloseManualControl}
      >
        <View style={{ flex: 1, backgroundColor: colors.primary }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 12, backgroundColor: colors.headerBlue }}>
            <TouchableOpacity onPress={handleCloseManualControl} style={{ padding: 8, marginRight: 8 }}>
              <Text style={{ color: colors.text, fontSize: 16 }}>✕ Close</Text>
            </TouchableOpacity>
            <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700' }}>Manual Control</Text>
            <View style={{ width: 60 }} />
          </View>
          <ManualControlPanel onExitManualMode={handleCloseManualControl} />
        </View>
      </Modal>

      {/* GPS Failsafe Mode Selector */}
      <FailsafeModeSelector
        visible={showFailsafeModeSelector}
        currentMode={gpsFailsafeMode}
        onModeChange={setGpsFailsafeMode}
        onClose={() => setShowFailsafeModeSelector(false)}
        disabled={telemetry.mission.status !== 'IDLE'}
      />

      {/* GPS Failsafe Strict Mode Popup */}
      {showStrictPopup && failsafeEvent && (
        <FailsafeStrictPopup
          visible={showStrictPopup}
          wpDistCm={failsafeEvent.wpDistCm}
          thresholdCm={failsafeEvent.thresholdCm}
          onAcknowledge={onFailsafeAcknowledge}
          onResume={() => {
            onFailsafeResume();
            setShowStrictPopup(false);
          }}
          onRestart={() => {
            onFailsafeRestart();
            setShowStrictPopup(false);
          }}
          onStop={() => {
            services.stopMission();
            setShowStrictPopup(false);
          }}
        />
      )}

      {/* GPS Failsafe Relax Mode Notification */}
      {showRelaxNotification && failsafeEvent && (
        <FailsafeRelaxNotification
          visible={showRelaxNotification}
          accuracyError={failsafeEvent.wpDistCm}
          threshold={failsafeEvent.thresholdCm}
          onDismiss={() => setShowRelaxNotification(false)}
        />
      )}

      {/* Mission Upload Progress Modal */}
      {showUploadProgress && (
        <View style={styles.progressOverlay}>
          <View style={styles.progressCard}>
            <Text style={styles.progressTitle}>Uploading Mission</Text>
            <View style={styles.progressBarContainer}>
              <View style={[styles.progressBarFill, { width: `${uploadProgress}%` }]} />
            </View>
            <Text style={styles.progressText}>{Math.round(uploadProgress)}%</Text>
          </View>
        </View>
      )}

      {showDownloadProgress && (
        <View style={styles.progressOverlay}>
          <View style={styles.progressCard}>
            <Text style={styles.progressTitle}>Downloading Mission</Text>
            <View style={styles.progressBarContainer}>
              <View style={[styles.progressBarFill, { width: `${downloadProgress}%` }]} />
            </View>
            <Text style={styles.progressText}>{Math.round(downloadProgress)}%</Text>
          </View>
        </View>
      )}

    </SafeAreaView>
  );

}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.primary,
  },
  mainContent: {
    flex: 1,
    flexDirection: 'row',
    backgroundColor: colors.primary,
    paddingTop: 12,
    gap: 12,
    paddingHorizontal: 12,
  },
  leftPanel: {
    flex: 0.5,
    width: '25%',
    height: '98%',
    backgroundColor: colors.primary,
  },
  centerPanel: {
    flex: 1,
    height: '98%',
    backgroundColor: colors.primary,
  },
  mapWrapper: {
    flex: 1,
    backgroundColor: colors.panelBg,
    borderRadius: 16,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: colors.border,
  },
  rightPanel: {
    width: '25%',
    height: '99%',
    backgroundColor: colors.primary,
  },
  opsPanel: {
    flex: 0.46,
    backgroundColor: colors.primary,
  },
  statsPanel: {
    flex: 0.53,
    backgroundColor: colors.primary,
    marginTop: 8,
  },
  bottomBar: {
    flex: 0.30,
    backgroundColor: colors.primary,
    paddingHorizontal: 12,
    paddingTop: 12,
    paddingBottom: 12,
  },
  pinningOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 1000,
  },
  pinningBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: 'rgba(59, 130, 246, 0.95)',
    paddingVertical: 12,
    paddingHorizontal: 16,
    gap: 16,
  },
  pinningText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '600',
  },
  pinningCancel: {
    backgroundColor: 'rgba(255,255,255,0.2)',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
  },
  pinningCancelText: {
    color: colors.text,
    fontSize: 12,
    fontWeight: '600',
  },
  // Drawing mode overlay styles
  drawingOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 1000,
  },
  drawingBanner: {
    backgroundColor: 'rgba(255, 193, 7, 0.95)',
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderBottomLeftRadius: 8,
    borderBottomRightRadius: 8,
    marginHorizontal: 8,
  },
  drawingText: {
    color: '#333',
    fontSize: 12,
    fontWeight: '600',
    flex: 1,
  },
  drawingCancel: {
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 4,
  },
  drawingCancelText: {
    color: '#333',
    fontSize: 11,
    fontWeight: '600',
  },
  fullscreenMap: {
    flex: 1,
    backgroundColor: colors.primary,
  },
  progressOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 9999,
  },
  progressCard: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 24,
    width: '80%',
    maxWidth: 400,
    alignItems: 'center',
  },
  progressTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.primary,
    marginBottom: 16,
  },
  progressBarContainer: {
    width: '100%',
    height: 8,
    backgroundColor: '#E0E0E0',
    borderRadius: 4,
    overflow: 'hidden',
    marginBottom: 12,
  },
  progressBarFill: {
    height: '100%',
    backgroundColor: colors.primary,
    borderRadius: 4,
  },
  progressText: {
    fontSize: 16,
    fontWeight: '500',
    color: '#333',
  },
});