import React, { useState, useCallback } from 'react';
import { Modal, Alert } from 'react-native';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, TextInput } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { colors } from '../../theme/colors';
import { PathPlanWaypoint } from '../../types/pathplan';
import { RowAssignmentDialog, BlockAssignmentDialog, PileAssignmentDialog, RowBlockPileButtons } from './RowBlockPileDialogs';
import { EditWaypointDialog } from './EditWaypointDialog';
import { DraggableWaypointsTable } from './DraggableWaypointsTable';
import { recalculateWaypointDistances } from '../../utils/missionCalculator';
import CheckBox from '@react-native-community/checkbox';
import * as FileSystem from 'expo-file-system';
import { Paths } from 'expo-file-system';

interface Props {
    waypoints: PathPlanWaypoint[];
    selectedWaypoint?: number | null;
    onSelectWaypoint?: (id: number) => void;
    onDeleteWaypoint?: (id: number) => void;
    onUpdateWaypoints?: (waypoints: PathPlanWaypoint[]) => void;
    missionName?: string;
    onMissionNameChange?: (name: string) => void;
}

export const PathSequenceSidebar: React.FC<Props> = ({
    waypoints,
    selectedWaypoint,
    onSelectWaypoint,
    onDeleteWaypoint,
    onUpdateWaypoints,
    missionName = 'DRAWN MISSION - 4:15:34',
    onMissionNameChange,
}) => {
    const [isEditingName, setIsEditingName] = useState(false);
    const [editedName, setEditedName] = useState(missionName);
    const [isFullScreenTable, setIsFullScreenTable] = useState(false);
    // Unicode icons: ↗ (arrow out), ↩ (arrow in)

    // Dialog states
    const [showRowDialog, setShowRowDialog] = useState(false);
    const [showBlockDialog, setShowBlockDialog] = useState(false);
    const [showPileDialog, setShowPileDialog] = useState(false);

    // Edit Dialog State
    const [showEditDialog, setShowEditDialog] = useState(false);
    const [editingWaypoint, setEditingWaypoint] = useState<PathPlanWaypoint | null>(null);

    // Bulk delete mode
    const [bulkDeleteMode, setBulkDeleteMode] = useState(false);
    const [selectedWaypoints, setSelectedWaypoints] = useState<number[]>([]);

    const handleSaveName = () => {
        if (onMissionNameChange) {
            onMissionNameChange(editedName);
        }
        setIsEditingName(false);
    };

    // Calculate distance from previous waypoint
    const getDistance = (index: number): string => {
        if (index === 0) return '0.0m';
        const wp = waypoints[index];
        return wp.distance ? `${wp.distance.toFixed(1)}m` : '0.0m';
    };

    const handleRowSave = (row: string, startSeq: number, endSeq: number) => {
        const updated = waypoints.map((wp, index) => {
            const seq = index + 1;
            if (seq >= startSeq && seq <= endSeq) {
                return { ...wp, row };
            }
            return wp;
        });
        onUpdateWaypoints?.(updated);
        setShowRowDialog(false);
    };

    const handleBlockSave = (block: string, startSeq: number, endSeq: number) => {
        const updated = waypoints.map((wp, index) => {
            const seq = index + 1;
            if (seq >= startSeq && seq <= endSeq) {
                return { ...wp, block };
            }
            return wp;
        });
        onUpdateWaypoints?.(updated);
        setShowBlockDialog(false);
    };

    const handlePileSave = (autoGenerate: boolean, prefix: string) => {
        const updated = waypoints.map((wp, index) => {
            const pile = autoGenerate ? `${index + 1}` : `${prefix}${index + 1}`;
            return { ...wp, pile };
        });
        onUpdateWaypoints?.(updated);
        setShowPileDialog(false);
    };

    const handleEditWaypoint = (wp: PathPlanWaypoint) => {
        setEditingWaypoint(wp);
        setShowEditDialog(true);
    };

    const handleSaveWaypoint = (updatedWp: PathPlanWaypoint) => {
        const updated = waypoints.map(wp => wp.id === updatedWp.id ? updatedWp : wp);
        onUpdateWaypoints?.(updated);
        setShowEditDialog(false);
        setEditingWaypoint(null);
    };

    const toggleBulkDeleteMode = () => {
        setBulkDeleteMode(!bulkDeleteMode);
        setSelectedWaypoints([]); // Clear selections when toggling mode
    };

    const handleWaypointSelect = (id: number) => {
        setSelectedWaypoints(prev =>
            prev.includes(id) ? prev.filter(wpId => wpId !== id) : [...prev, id]
        );
    };

    const handleBulkDelete = () => {
        if (onDeleteWaypoint) {
            selectedWaypoints.forEach(id => onDeleteWaypoint(id));
        }
        setBulkDeleteMode(false);
        setSelectedWaypoints([]);
    };

    const handleDistanceChange = (id: number, newDistance: number) => {
        const updatedWaypoints = waypoints.map(wp =>
            wp.id === id ? { ...wp, distance: newDistance } : wp
        );
        onUpdateWaypoints?.(updatedWaypoints);
    };

    const handleReorder = useCallback((fromIndex: number, toIndex: number) => {
        if (!onUpdateWaypoints) return;

        try {
            const reordered = [...waypoints];
            const [removed] = reordered.splice(fromIndex, 1);
            reordered.splice(toIndex, 0, removed);

            const updated = recalculateWaypointDistances(reordered);
            onUpdateWaypoints(updated);

            console.log(`Waypoint moved: ${fromIndex + 1} → ${toIndex + 1}`);
        } catch (error) {
            console.error('Reorder failed:', error);
            Alert.alert('Error', 'Failed to reorder waypoints');
        }
    }, [waypoints, onUpdateWaypoints]);

    const handleExportWaypoints = async (format: 'json' | 'csv' | 'kml') => {
        let content = '';
        if (format === 'json') {
            content = JSON.stringify(waypoints, null, 2);
        } else if (format === 'csv') {
            content = 'id,lat,lon,alt,row,block,pile,distance\n';
            content += waypoints.map(wp => `${wp.id},${wp.lat},${wp.lon},${wp.alt},${wp.row || ''},${wp.block || ''},${wp.pile || ''},${wp.distance || ''}`).join('\n');
        } else if (format === 'kml') {
            content = '<?xml version="1.0" encoding="UTF-8"?>\n';
            content += '<kml xmlns="http://www.opengis.net/kml/2.2">\n';
            content += '<Document>\n';
            waypoints.forEach(wp => {
                content += `<Placemark><name>Waypoint ${wp.id}</name><Point><coordinates>${wp.lon},${wp.lat},${wp.alt}</coordinates></Point></Placemark>\n`;
            });
            content += '</Document>\n';
            content += '</kml>';
        }

        const fileUri = `${Paths.document}/waypoints.${format}`;
        await FileSystem.writeAsStringAsync(fileUri, content);
        alert(`Waypoints exported as ${format.toUpperCase()}! File saved to: ${fileUri}`);
    };

    return (
        <View style={styles.container}>
            {/* Mission Header */}
            <View style={styles.header}>
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                    {isEditingName ? (
                        <View style={styles.editContainer}>
                            <TextInput
                                style={styles.nameInput}
                                value={editedName}
                                onChangeText={setEditedName}
                                onBlur={handleSaveName}
                                onSubmitEditing={handleSaveName}
                                autoFocus
                                selectTextOnFocus
                            />
                        </View>
                    ) : (
                        <TouchableOpacity onPress={() => setIsEditingName(true)} style={styles.nameContainer}>
                            <Text style={styles.missionName} numberOfLines={2}>{missionName}</Text>
                            <Text style={styles.editHint}>Tap to edit</Text>
                        </TouchableOpacity>
                    )}
                    <TouchableOpacity onPress={() => setIsFullScreenTable(true)} style={{ marginLeft: 8, width: 40, height: 40, justifyContent: 'center', alignItems: 'center', padding: 0, backgroundColor: '#FFD600', borderRadius: 12 }}> 
                        <Text style={{ fontSize: 24, color: '#222' }}>↗</Text>
                    </TouchableOpacity>
                </View>
            </View>


            {/* Waypoints List */}
            <ScrollView style={styles.waypointsList} showsVerticalScrollIndicator={true}>
                 {/* Table Header */}
                 <View style={styles.tableHeaderRow}>
                    <Text style={[styles.tableHeaderText, { flex: 0.4 }]}>Seq</Text>
                    <Text style={[styles.tableHeaderText, { flex: 1.2 }]}>Latitude</Text>
                    <Text style={[styles.tableHeaderText, { flex: 1.2 }]}>Longitude</Text>
                    <Text style={[styles.tableHeaderText, { flex: 0.6 }]}>Dist</Text>
                    <Text style={[styles.tableHeaderText, { flex: 0.5 }]}>Action</Text>
                </View>

                {waypoints.map((wp, index) => (
                    <TouchableOpacity
                        key={`${wp.id}-${index}`}
                        style={[
                            styles.waypointItem,
                            selectedWaypoint === wp.id && styles.waypointItemSelected,
                        ]}
                        onPress={() => onSelectWaypoint?.(wp.id)}
                    >
                        <Text style={[styles.waypointCell, { flex: 0.4, fontWeight: 'bold' }]}>{index + 1}</Text>
                        <Text style={[styles.waypointCell, { flex: 1.2, fontFamily: 'monospace', fontSize: 10 }]}>{wp.lat?.toFixed(7) ?? '0.0000000'}</Text>
                        <Text style={[styles.waypointCell, { flex: 1.2, fontFamily: 'monospace', fontSize: 10 }]}>{wp.lon?.toFixed(7) ?? '0.0000000'}</Text>
                        <Text style={[styles.waypointCell, { flex: 0.6 }]}>{wp.distance?.toFixed(1) ?? '0.0'}</Text>

                        {/* Action Buttons */}
                        <View style={{ flex: 0.5, alignItems: 'center' }}>
                            <TouchableOpacity
                                style={styles.actionBtn}
                                onPress={() => onDeleteWaypoint?.(wp.id)}
                            >
                                <Text style={styles.actionIcon}>🗑️</Text>
                            </TouchableOpacity>
                        </View>
                    </TouchableOpacity>
                ))}
                {waypoints.length === 0 && (
                    <View style={styles.emptyState}>
                        <Text style={styles.emptyText}>No marking points yet</Text>
                        <Text style={styles.emptyHint}>Tap on map to add</Text>
                    </View>
                )}
            </ScrollView>

            {/* Footer Stats */}
            <View style={styles.footer}>
                <Text style={styles.footerText}>Total: {waypoints.length} marking points</Text>
            </View>

            {/* Full Screen Modal for Waypoint Table */}
            <Modal visible={isFullScreenTable} animationType="slide" transparent={false}>
                <GestureHandlerRootView style={{ flex: 1 }}>
                <View style={{ flex: 1, backgroundColor: colors.panelBg, padding: 18 }}>
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: 24, backgroundColor: colors.cardBg, borderRadius: 16 }}>
                        <Text style={{ fontSize: 28, fontWeight: 'bold', color: colors.text }}>Marking Points Table</Text>
                        <View style={{ flexDirection: 'row', gap: 12 }}>
                            <TouchableOpacity 
                                onPress={() => {
                                    if (waypoints.length === 0) return;
                                    if (onUpdateWaypoints) {
                                        // Show confirmation alert
                                        Alert.alert(
                                            'Delete All Marking Points',
                                            `Are you sure you want to delete all ${waypoints.length} marking points? This action cannot be undone.`,
                                            [
                                                {
                                                    text: 'Cancel',
                                                    style: 'cancel'
                                                },
                                                {
                                                    text: 'Delete All',
                                                    style: 'destructive',
                                                    onPress: () => onUpdateWaypoints([])
                                                }
                                            ]
                                        );
                                    }
                                }}
                                disabled={waypoints.length === 0}
                                style={{ 
                                    paddingHorizontal: 20, 
                                    paddingVertical: 14, 
                                    backgroundColor: waypoints.length === 0 ? '#555' : '#dc2626', 
                                    borderRadius: 12,
                                    opacity: waypoints.length === 0 ? 0.5 : 1
                                }}
                            > 
                                <Text style={{ fontSize: 16, color: '#fff', fontWeight: '700' }}>🗑️ Delete All</Text>
                            </TouchableOpacity>
                            <TouchableOpacity onPress={() => setIsFullScreenTable(false)} style={{ width: 56, height: 56, justifyContent: 'center', alignItems: 'center', padding: 0, backgroundColor: '#FFD600', borderRadius: 16 }}> 
                                <Text style={{ fontSize: 32, color: '#222' }}>↩</Text>
                            </TouchableOpacity>
                        </View>
                    </View>
                    {/* Table Header */}
                    <View style={{ flex: 1, marginTop: 12, borderRadius: 16 }}>
                    <View style={{ flexDirection: 'row', backgroundColor: '#0a2540', paddingVertical: 10, borderBottomWidth: 2, borderBottomColor: colors.border, width: '100%', alignItems: 'center', borderTopLeftRadius: 16, borderTopRightRadius: 16 }}>
                        <View style={{ width: 36 }} />
                        <Text style={{ flex: 0.7, color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>#</Text>
                        <TouchableOpacity style={{ flex: 1.2 }} onPress={() => setShowBlockDialog(true)}>
                            <Text style={{ color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Block</Text>
                        </TouchableOpacity>
                        <TouchableOpacity style={{ flex: 1.2 }} onPress={() => setShowRowDialog(true)}>
                            <Text style={{ color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Row</Text>
                        </TouchableOpacity>
                        <TouchableOpacity style={{ flex: 1.2 }} onPress={() => setShowPileDialog(true)}>
                            <Text style={{ color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Pile</Text>
                        </TouchableOpacity>
                        <Text style={{ flex: 2, color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Latitude</Text>
                        <Text style={{ flex: 2, color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Longitude</Text>
                        <Text style={{ flex: 1.2, color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Altitude</Text>
                        <Text style={{ flex: 1.2, color: '#67E8F9', fontWeight: 'bold', textAlign: 'center', fontSize: 20 }}>Dist (m)</Text>
                        <View style={{ flex: 0.8 }} />
                    </View>
                    {/* Draggable Table */}
                    <DraggableWaypointsTable
                        waypoints={waypoints}
                        onReorder={handleReorder}
                        onDelete={onDeleteWaypoint}
                    />
                    </View>
                </View>
                </GestureHandlerRootView>
            </Modal>

            {/* Dialogs */}
            <RowAssignmentDialog
                visible={showRowDialog}
                onClose={() => setShowRowDialog(false)}
                onSave={handleRowSave}
            />
            <BlockAssignmentDialog
                visible={showBlockDialog}
                onClose={() => setShowBlockDialog(false)}
                onSave={handleBlockSave}
            />
            <PileAssignmentDialog
                visible={showPileDialog}
                onClose={() => setShowPileDialog(false)}
                onSave={handlePileSave}
            />
            <EditWaypointDialog
                visible={showEditDialog}
                waypoint={editingWaypoint}
                onClose={() => setShowEditDialog(false)}
                onSave={handleSaveWaypoint}
            />
        </View>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: colors.panelBg,
        borderRadius: 12,
        borderWidth: 1,
        borderColor: colors.border,
        overflow: 'hidden',
    },
    header: {
        backgroundColor: '#003366',
        paddingVertical: 12,
        paddingHorizontal: 12,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
    },
    nameContainer: {
        minHeight: 40,
        justifyContent: 'center',
    },
    missionName: {
        color: colors.text,
        fontSize: 14,
        fontWeight: '600',
        marginBottom: 2,
    },
    editHint: {
        color: colors.textSecondary,
        fontSize: 10,
        opacity: 0.6,
    },
    editContainer: {
        minHeight: 40,
    },
    nameInput: {
        backgroundColor: colors.inputBg,
        color: colors.text,
        fontSize: 14,
        fontWeight: '600',
        paddingHorizontal: 8,
        paddingVertical: 8,
        borderRadius: 6,
        borderWidth: 1,
        borderColor: colors.accent,
    },
    toolbar: {
        flexDirection: 'row',
        padding: 8,
        gap: 8,
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
        backgroundColor: 'rgba(0, 51, 102, 0.5)',
    },
    toolBtn: {
        flex: 1,
        backgroundColor: colors.cardBg,
        paddingVertical: 6,
        borderRadius: 4,
        alignItems: 'center',
        borderWidth: 1,
        borderColor: colors.border,
    },
    toolBtnText: {
        color: colors.text,
        fontSize: 11,
        fontWeight: '600',
    },
    tableHeaderRow: {
        flexDirection: 'row',
        backgroundColor: 'rgba(0, 51, 102, 0.7)',
        borderBottomWidth: 1,
        borderBottomColor: colors.border,
        paddingHorizontal: 6,
        paddingVertical: 8,
    },
    tableHeader: {
        flex: 1,
        paddingVertical: 10,
        alignItems: 'center',
        borderRightWidth: 1,
        borderRightColor: colors.border,
    },
    tableHeaderText: {
        color: colors.accent,
        fontSize: 11,
        fontWeight: '600',
        textAlign: 'center',
    },
    waypointsList: {
        flex: 1,
    },
    waypointItem: {
        flexDirection: 'row',
        alignItems: 'center',
        paddingVertical: 8,
        paddingHorizontal: 6,
        borderBottomWidth: 1,
        borderBottomColor: 'rgba(34, 211, 238, 0.1)',
        gap: 4,
    },
    waypointItemSelected: {
        backgroundColor: 'rgba(59, 130, 246, 0.2)',
        borderLeftWidth: 3,
        borderLeftColor: colors.accent,
    },
    waypointCell: {
        color: colors.textPrimary,
        fontSize: 11,
        textAlign: 'center',
    },
    waypointMeta: {
        flexDirection: 'row',
        flexWrap: 'wrap',
        gap: 4,
        marginBottom: 4,
    },
    metaTag: {
        color: '#67E8F9',
        fontSize: 9,
        backgroundColor: 'rgba(103, 232, 249, 0.1)',
        paddingHorizontal: 6,
        paddingVertical: 2,
        borderRadius: 4,
    },
    waypointDistance: {
        color: colors.textSecondary,
        fontSize: 10,
    },
    deleteButton: {
        padding: 6,
    },
    deleteIcon: {
        fontSize: 16,
    },
    emptyState: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        paddingVertical: 40,
    },
    emptyText: {
        color: colors.textSecondary,
        fontSize: 14,
        marginBottom: 4,
    },
    emptyHint: {
        color: colors.textMuted,
        fontSize: 12,
    },
    footer: {
        backgroundColor: '#003366',
        paddingVertical: 10,
        paddingHorizontal: 12,
        borderTopWidth: 1,
        borderTopColor: colors.border,
    },
    footerText: {
        color: '#67E8F9',
        fontSize: 11,
        fontWeight: '600',
    },
    actionButtons: {
        flexDirection: 'row',
        gap: 4,
    },
    actionBtn: {
        padding: 4,
    },
    actionIcon: {
        fontSize: 16,
    },
});
