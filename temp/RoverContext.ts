/**
 * React Native Context: RoverContext
 * 
 * Provides rover telemetry and services to the entire app
 * Usage: Wrap App with <RoverProvider>, then use useRover() hook
 */

import React, { createContext, useContext, ReactNode, useState, useCallback, useEffect } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import useRoverTelemetry, {
  UseRoverTelemetryResult,
  RoverServices
} from '../hooks/useRoverTelemetry';
import { RoverTelemetry, GpsFailsafeMode, GpsFailsafeStatus, GpsFailsafeEvent } from '../types/telemetry';
import { Waypoint } from '../components/missionreport/types';
import PersistentStorage from '../services/PersistentStorage';

const TTS_LANGUAGE_STORAGE_KEY = 'tts_language';

export interface RoverContextValue extends UseRoverTelemetryResult {
  missionWaypoints: Waypoint[];
  setMissionWaypoints: (waypoints: Waypoint[]) => void;
  clearMissionWaypoints: () => void;
  missionMode: string;
  setMissionMode: (mode: string) => void;
  ttsLanguage: string;
  setTTSLanguage: (language: string) => void;
  gpsFailsafeMode: GpsFailsafeMode;
  setGpsFailsafeMode: (mode: GpsFailsafeMode) => void;
  gpsFailsafeStatus: GpsFailsafeStatus | null;
  onFailsafeAcknowledge: () => void;
  onFailsafeResume: () => void;
  onFailsafeRestart: () => void;
}

const RoverContext = createContext<RoverContextValue | null>(null);

interface RoverProviderProps {
  children: ReactNode;
}

/**
 * Provider Component: RoverProvider
 * 
 * Wrap your app with this to enable rover telemetry throughout
 * 
 * @example
 * ```tsx
 * <RoverProvider>
 *   <App />
 * </RoverProvider>
 * ```
 */
export function RoverProvider({ children }: RoverProviderProps): React.ReactElement {
  const rover = useRoverTelemetry();
  const [missionWaypoints, setMissionWaypointsState] = useState<Waypoint[]>([]);
  const [missionMode, setMissionModeState] = useState<string>('DGPS Mark');
  const [ttsLanguage, setTTSLanguageState] = useState<string>('en');
  const [gpsFailsafeMode, setGpsFailsafeModeState] = useState<GpsFailsafeMode>('disable');
  const [gpsFailsafeStatus, setGpsFailsafeStatus] = useState<GpsFailsafeStatus | null>(null);

  // Load TTS language from AsyncStorage on mount
  useEffect(() => {
    const loadTTSLanguage = async () => {
      try {
        const savedLanguage = await AsyncStorage.getItem(TTS_LANGUAGE_STORAGE_KEY);
        if (savedLanguage) {
          console.log('[RoverContext] Loaded TTS language:', savedLanguage);
          setTTSLanguageState(savedLanguage);
        }
      } catch (error) {
        console.error('[RoverContext] Failed to load TTS language:', error);
      }
    };
    loadTTSLanguage();
  }, []);

  // Update GPS failsafe status from telemetry
  useEffect(() => {
    if (rover.telemetry.gps_failsafe) {
      console.log('[RoverContext] 🛡️ GPS Failsafe status updated:', rover.telemetry.gps_failsafe);
      setGpsFailsafeStatus(rover.telemetry.gps_failsafe);
    }
  }, [rover.telemetry.gps_failsafe]);

  const setMissionWaypoints = useCallback((waypoints: Waypoint[]) => {
    // Avoid redundant updates that can trigger render/effect loops
    setMissionWaypointsState(prev => {
      const sameLength = prev.length === waypoints.length;
      const shallowSame = sameLength && prev.every((p, i) => {
          const n = waypoints[i];
          const pDistance = (p as any).distance ?? 0;
          const nDistance = (n as any).distance ?? 0;
          return p.lat === n.lat && p.lon === n.lon && p.alt === n.alt && p.sn === n.sn && p.status === n.status && Number(pDistance) === Number(nDistance);
        });
      if (shallowSame) {
        return prev;
      }
      console.log('[RoverContext] Mission waypoints updated:', waypoints.length);
      // Auto-save to persistent storage only when changed
      PersistentStorage.saveWaypoints(waypoints).catch(error => {
        console.error('[RoverContext] Failed to persist waypoints:', error);
      });
      return waypoints;
    });
  }, []);

  const clearMissionWaypoints = useCallback(() => {
    setMissionWaypointsState([]);
    console.log('[RoverContext] Mission waypoints cleared');
    // Clear from persistent storage
    PersistentStorage.clearMissionData().catch(error => {
      console.error('[RoverContext] Failed to clear persisted data:', error);
    });
  }, []);

  const setMissionMode = useCallback((mode: string) => {
    setMissionModeState(mode);
    console.log('[RoverContext] Mission mode updated:', mode);
  }, []);

  const setTTSLanguage = useCallback(async (language: string) => {
    try {
      setTTSLanguageState(language);
      await AsyncStorage.setItem(TTS_LANGUAGE_STORAGE_KEY, language);
      console.log('[RoverContext] TTS language updated:', language);
    } catch (error) {
      console.error('[RoverContext] Failed to save TTS language:', error);
    }
  }, []);

  const setGpsFailsafeMode = useCallback((mode: GpsFailsafeMode) => {
    console.log('[RoverContext] Setting GPS failsafe mode:', mode);
    setGpsFailsafeModeState(mode);
    
    // Emit to backend
    if (rover.socket) {
      rover.socket.emit('set_gps_failsafe_mode', { mode });
    }
  }, [rover.socket]);

  const onFailsafeAcknowledge = useCallback(() => {
    console.log('[RoverContext] Acknowledging GPS failsafe');
    if (rover.socket) {
      rover.socket.emit('failsafe_acknowledge');
    }
  }, [rover.socket]);

  const onFailsafeResume = useCallback(() => {
    console.log('[RoverContext] Resuming mission after failsafe');
    if (rover.socket) {
      rover.socket.emit('failsafe_resume_mission');
    }
  }, [rover.socket]);

  const onFailsafeRestart = useCallback(() => {
    console.log('[RoverContext] Restarting mission after failsafe');
    if (rover.socket) {
      rover.socket.emit('failsafe_restart_mission');
    }
  }, [rover.socket]);

  // Listen for GPS failsafe events
  useEffect(() => {
    if (!rover.socket || !rover.socket.connected) {
      console.log('[RoverContext] ⚠️ Socket not connected yet for GPS failsafe listener. Connection state:', rover.connectionState);
      return;
    }

    console.log('[RoverContext] 🔌 Registering GPS failsafe listeners. Connection state:', rover.connectionState);

    const handleServoSuppressed = (event: GpsFailsafeEvent) => {
      console.log('[RoverContext] 🚫 Servo suppressed event:', event);
    };

    const handleFailsafeModeChanged = (data: { mode: GpsFailsafeMode }) => {
      console.log('═══════════════════════════════════════');
      console.log('[RoverContext] 🔔 RECEIVED FAILSAFE MODE FROM BACKEND');
      console.log('═══════════════════════════════════════');
      console.log('Previous Mode:', gpsFailsafeMode);
      console.log('New Mode:', data.mode);
      console.log('Full Data:', data);
      console.log('═══════════════════════════════════════');
      setGpsFailsafeModeState(data.mode);
      console.log('✅ State updated to:', data.mode);
    };

    rover.socket.on('servo_suppressed', handleServoSuppressed);
    rover.socket.on('failsafe_mode_changed', handleFailsafeModeChanged);
    console.log('[RoverContext] ✅ GPS failsafe listeners registered');

    // ✅ FIX: Request current GPS failsafe mode after registering listener
    // This prevents race condition where backend sends mode before listener is ready
    console.log('[RoverContext] 📡 Requesting current GPS failsafe mode from backend');
    rover.socket.emit('request_gps_failsafe_mode');

    return () => {
      console.log('[RoverContext] 🔌 Unregistering GPS failsafe listeners');
      rover.socket?.off('servo_suppressed', handleServoSuppressed);
      rover.socket?.off('failsafe_mode_changed', handleFailsafeModeChanged);
    };
  }, [rover.socket, rover.connectionState]);

  // ✅ CRITICAL FIX: Memoize stable values separately to prevent infinite loops
  // while still allowing telemetry updates to propagate instantly to consumers.
  //
  // The key insight: services, reconnect, onMissionEvent are stable functions that
  // don't need to change on every telemetry update. By memoizing them separately,
  // components that depend on these (like VoiceSettingsModal) won't re-trigger
  // their effects on every telemetry update, preventing infinite loops.
  //
  // Meanwhile, telemetry and roverPosition DO update frequently, causing consumers
  // like VehicleStatusCard and MissionMap to re-render with fresh data instantly.
  const contextValue = React.useMemo<RoverContextValue>(() => ({
    telemetry: rover.telemetry,           // ✅ Updates frequently - live updates work
    roverPosition: rover.roverPosition,   // ✅ Updates frequently - map updates work
    connectionState: rover.connectionState,
    reconnect: rover.reconnect,           // ✅ Stable function - won't cause loops
    services: rover.services,             // ✅ Stable object - won't cause loops
    onMissionEvent: rover.onMissionEvent, // ✅ Stable function - won't cause loops
    socket: rover.socket,                 // ✅ Stable reference - socket instance
    missionWaypoints,                     // ✅ Only changes on mission updates
    setMissionWaypoints,                  // ✅ Stable callback
    clearMissionWaypoints,                // ✅ Stable callback
    missionMode,                          // ✅ Only changes on mode updates
    setMissionMode,                       // ✅ Stable callback
    ttsLanguage,                          // ✅ Only changes on language updates
    setTTSLanguage,                       // ✅ Stable callback
    gpsFailsafeMode,                      // ✅ GPS failsafe mode
    setGpsFailsafeMode,                   // ✅ Stable callback
    gpsFailsafeStatus,                    // ✅ GPS failsafe status
    onFailsafeAcknowledge,                // ✅ Stable callback
    onFailsafeResume,                     // ✅ Stable callback
    onFailsafeRestart,                    // ✅ Stable callback
  }), [
    rover.telemetry,        // Changes frequently for live updates
    rover.roverPosition,    // Changes frequently for live updates
    rover.connectionState,  // Changes on connection state
    rover.reconnect,        // Stable
    rover.services,         // Stable - already memoized in useRoverTelemetry
    rover.onMissionEvent,   // Stable
    rover.socket,           // Stable - socket instance
    missionWaypoints,       // Changes on mission updates
    setMissionWaypoints,    // Stable
    clearMissionWaypoints,  // Stable
    missionMode,            // Changes on mode updates
    setMissionMode,         // Stable
    ttsLanguage,            // Changes on language updates
    setTTSLanguage,         // Stable
    gpsFailsafeMode,        // GPS failsafe mode
    setGpsFailsafeMode,     // Stable
    gpsFailsafeStatus,      // GPS failsafe status
    onFailsafeAcknowledge,  // Stable
    onFailsafeResume,       // Stable
    onFailsafeRestart,      // Stable
  ]);

  return React.createElement(
    RoverContext.Provider,
    { value: contextValue },
    children
  );
}

/**
 * Hook: useRover
 * 
 * Access rover telemetry and services throughout your app
 * Must be used within <RoverProvider>
 * 
 * @example
 * ```tsx
 * const { telemetry, services, connectionState } = useRover();
 * ```
 */
export function useRover(): RoverContextValue {
  const ctx = useContext(RoverContext);
  if (!ctx) {
    throw new Error('useRover must be used within a RoverProvider');
  }
  return ctx;
}

// Re-export types
export type { RoverTelemetry, RoverServices };

export default RoverContext;
