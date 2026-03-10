// Basic types for Path Plan (will expand later with utilities)

export interface PathPlanWaypoint {
    id: number;
    lat: number;
    lon: number;
    alt: number;
    row?: string;
    block?: string;
    pile?: string;
    distance?: number; // Distance from previous waypoint in meters
}

export interface MissionData {
    id: string;
    name: string;
    createdAt: string;
    waypoints: PathPlanWaypoint[];
    totalDistance: number;
    totalWaypoints: number;
}

export type DrawingMode = 'none' | 'waypoint' | 'polygon' | 'line';
export type ExportFormat = 'qgc' | 'json' | 'csv' | 'kml' | 'dxf';
