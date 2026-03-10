import React, { useCallback, memo, useState } from 'react';
import { View, Text, StyleSheet, Platform, TouchableOpacity as RNTouchableOpacity } from 'react-native';
import { TouchableOpacity } from 'react-native-gesture-handler';
import { Ionicons } from '@expo/vector-icons';
import { colors } from '../../theme/colors';
import { PathPlanWaypoint } from '../../types/pathplan';

// ── Native-only imports (top-level so React never sees a new component type) ──
// These are safe to import on web too; the library has web stubs.
// We just avoid RENDERING the native list on web via Platform.OS check.
import DraggableFlatList, { ScaleDecorator, RenderItemParams } from 'react-native-draggable-flatlist';

interface Props {
    waypoints: PathPlanWaypoint[];
    onReorder: (fromIndex: number, toIndex: number) => void;
    onDelete?: (id: number) => void;
}

// ─── Web Drag-and-Drop Row ────────────────────────────────────────────────────
const WebDraggableRow: React.FC<{
    item: PathPlanWaypoint;
    index: number;
    isDragDisabled: boolean;
    onDelete?: (id: number) => void;
    onDragStart: (index: number) => void;
    onDragEnter: (index: number) => void;
    onDragEnd: () => void;
    isDragOver: boolean;
    isDragging: boolean;
}> = memo(({ item, index, isDragDisabled, onDelete, onDragStart, onDragEnter, onDragEnd, isDragOver, isDragging }) => {
    return (
        <div
            draggable={!isDragDisabled}
            onDragStart={isDragDisabled ? undefined : () => onDragStart(index)}
            onDragEnter={isDragDisabled ? undefined : () => onDragEnter(index)}
            onDragEnd={isDragDisabled ? undefined : onDragEnd}
            onDragOver={(e) => { e.preventDefault(); }}
            style={{
                display: 'flex',
                flexDirection: 'row',
                alignItems: 'center',
                backgroundColor: isDragging
                    ? 'rgba(59, 130, 246, 0.3)'
                    : isDragOver
                        ? 'rgba(6, 182, 212, 0.2)'
                        : index % 2 === 0 ? '#112e4a' : '#0a2540',
                paddingTop: 7,
                paddingBottom: 7,
                paddingLeft: 16,
                paddingRight: 16,
                minHeight: 60,
                borderBottom: isDragOver ? '2px solid #22d3ee' : '1px solid rgba(34, 211, 238, 0.1)',
                width: '100%',
                cursor: isDragDisabled ? 'default' : 'grab',
                boxSizing: 'border-box',
                opacity: isDragging ? 0.5 : 1,
                transition: 'background-color 0.15s, border-color 0.15s',
                userSelect: 'none',
            } as React.CSSProperties}
        >
            {/* Drag Handle */}
            <div style={{ width: 29, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                <Ionicons
                    name="chevron-expand-outline"
                    size={24}
                    color={isDragDisabled ? '#4a5568' : '#67E8F9'}
                />
            </div>
            {/* Data Cells */}
            <Text style={[styles.cell, styles.colSeq]}>{index + 1}</Text>
            <Text style={[styles.cell, styles.colBlock]}>{item.block || '-'}</Text>
            <Text style={[styles.cell, styles.colRow]}>{item.row || '-'}</Text>
            <Text style={[styles.cell, styles.colPile]}>{item.pile || '-'}</Text>
            <Text style={[styles.cell, styles.colLat]}>{item.lat?.toFixed(7) ?? '0.0000000'}</Text>
            <Text style={[styles.cell, styles.colLon]}>{item.lon?.toFixed(7) ?? '0.0000000'}</Text>
            <Text style={[styles.cell, styles.colAlt]}>{item.alt?.toFixed(2) || '0.00'}</Text>
            <Text style={[styles.cell, styles.colDist]}>{item.distance?.toFixed(2) || '0.00'}</Text>
            {/* Delete Button */}
            {onDelete && (
                <RNTouchableOpacity style={styles.deleteBtn} onPress={() => onDelete(item.id)}>
                    <Ionicons name="trash-outline" size={22} color="#F87171" />
                </RNTouchableOpacity>
            )}
        </div>
    );
});
WebDraggableRow.displayName = 'WebDraggableRow';

// ─── Web Draggable List ───────────────────────────────────────────────────────
const WebDraggableList: React.FC<Props> = ({ waypoints, onReorder, onDelete }) => {
    const [dragFromIndex, setDragFromIndex] = useState<number | null>(null);
    const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);
    const isDragDisabled = waypoints.length <= 1;

    const handleDragStart = useCallback((index: number) => {
        setDragFromIndex(index);
    }, []);

    const handleDragEnter = useCallback((index: number) => {
        setDragOverIndex(index);
    }, []);

    const handleDragEnd = useCallback(() => {
        if (dragFromIndex !== null && dragOverIndex !== null && dragFromIndex !== dragOverIndex) {
            onReorder(dragFromIndex, dragOverIndex);
        }
        setDragFromIndex(null);
        setDragOverIndex(null);
    }, [dragFromIndex, dragOverIndex, onReorder]);

    if (waypoints.length === 0) {
        return (
            <View style={styles.emptyState}>
                <Text style={styles.emptyText}>No marking points yet</Text>
                <Text style={styles.emptyHint}>Tap on map to add</Text>
            </View>
        );
    }

    return (
        <div
            style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', borderBottomLeftRadius: 16, borderBottomRightRadius: 16, overflow: 'hidden' } as React.CSSProperties}
            onDragOver={(e) => e.preventDefault()}
        >
            {waypoints.map((item, index) => (
                <WebDraggableRow
                    key={`wp-${item.id}`}
                    item={item}
                    index={index}
                    isDragDisabled={isDragDisabled}
                    onDelete={onDelete}
                    onDragStart={handleDragStart}
                    onDragEnter={handleDragEnter}
                    onDragEnd={handleDragEnd}
                    isDragOver={dragOverIndex === index && dragFromIndex !== index}
                    isDragging={dragFromIndex === index}
                />
            ))}
        </div>
    );
};

// ─── Native Row (Android / iOS) ───────────────────────────────────────────────
// Defined outside NativeDraggableList so React always sees the same component type.
const NativeWaypointRow = memo((
    { item, drag, isActive, onDelete, isDragDisabled, getIndex }: RenderItemParams<PathPlanWaypoint> & {
        onDelete?: (id: number) => void;
        isDragDisabled?: boolean;
    }
) => {
    const index = getIndex() ?? 0;
    return (
        <ScaleDecorator>
            <View
                style={[
                    styles.row,
                    index % 2 === 0 && styles.rowAlt,
                    isActive && styles.rowActive,
                ]}
            >
                <TouchableOpacity
                    onLongPress={isDragDisabled ? undefined : drag}
                    disabled={isDragDisabled}
                    delayLongPress={150}
                    style={styles.dragHandle}
                    hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                >
                    <Ionicons
                        name="chevron-expand-outline"
                        size={24}
                        color={isDragDisabled ? '#4a5568' : '#67E8F9'}
                    />
                </TouchableOpacity>
                <Text style={[styles.cell, styles.colSeq]}>{index + 1}</Text>
                <Text style={[styles.cell, styles.colBlock]}>{item.block || '-'}</Text>
                <Text style={[styles.cell, styles.colRow]}>{item.row || '-'}</Text>
                <Text style={[styles.cell, styles.colPile]}>{item.pile || '-'}</Text>
                <Text style={[styles.cell, styles.colLat]}>{item.lat?.toFixed(7) ?? '0.0000000'}</Text>
                <Text style={[styles.cell, styles.colLon]}>{item.lon?.toFixed(7) ?? '0.0000000'}</Text>
                <Text style={[styles.cell, styles.colAlt]}>{item.alt?.toFixed(2) || '0.00'}</Text>
                <Text style={[styles.cell, styles.colDist]}>{item.distance?.toFixed(2) || '0.00'}</Text>
                {onDelete && (
                    <TouchableOpacity
                        style={styles.deleteBtn}
                        onPress={() => onDelete(item.id)}
                        disabled={isActive}
                        hitSlop={{ top: 10, bottom: 10, left: 10, right: 10 }}
                    >
                        <Ionicons name="trash-outline" size={22} color="#F87171" />
                    </TouchableOpacity>
                )}
            </View>
        </ScaleDecorator>
    );
});
NativeWaypointRow.displayName = 'NativeWaypointRow';

// ─── Native Draggable List (Android / iOS) ────────────────────────────────────
const NativeDraggableList: React.FC<Props> = ({ waypoints, onReorder, onDelete }) => {
    const isDragDisabled = waypoints.length <= 1;

    const renderItem = useCallback(
        (params: RenderItemParams<PathPlanWaypoint>) => (
            <NativeWaypointRow
                {...params}
                onDelete={onDelete}
                isDragDisabled={isDragDisabled}
            />
        ),
        [onDelete, isDragDisabled]
    );

    const handleDragEnd = useCallback(
        ({ from, to }: { from: number; to: number }) => {
            if (from !== to) onReorder(from, to);
        },
        [onReorder]
    );

    if (waypoints.length === 0) {
        return (
            <View style={styles.emptyState}>
                <Text style={styles.emptyText}>No marking points yet</Text>
                <Text style={styles.emptyHint}>Tap on map to add</Text>
            </View>
        );
    }

    return (
        <DraggableFlatList
            data={waypoints}
            renderItem={renderItem}
            keyExtractor={(item) => `wp-${item.id}`}
            onDragEnd={handleDragEnd}
            activationDistance={15}
            containerStyle={styles.listContainer}
        />
    );
};

// ─── Exported Component ───────────────────────────────────────────────────────
export const DraggableWaypointsTable: React.FC<Props> = (props) => {
    if (Platform.OS === 'web') {
        return <WebDraggableList {...props} />;
    }
    return <NativeDraggableList {...props} />;
};

const styles = StyleSheet.create({
    container: { flex: 1 },
    listContainer: { flex: 1, borderBottomLeftRadius: 16, borderBottomRightRadius: 16, overflow: 'hidden' },
    row: {
        flexDirection: 'row',
        backgroundColor: '#112e4a',
        paddingVertical: 9,
        paddingHorizontal: 10,
        minHeight: 60,
        alignItems: 'center',
        borderBottomWidth: 1,
        borderBottomColor: 'rgba(34, 211, 238, 0.1)',
        width: '100%',
    },
    rowAlt: { backgroundColor: '#0a2540' },
    rowActive: {
        backgroundColor: 'rgba(59, 130, 246, 0.3)',
        elevation: 5,
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3,
        shadowRadius: 8,
    },
    cell: {
        color: '#ffffff',
        textAlign: 'center',
        fontSize: 21,
    },
    dragHandle: {
        width: 29,
        justifyContent: 'center',
        alignItems: 'center',
    },
    colSeq: { flex: 0.56, fontWeight: 'bold' },
    colBlock: { flex: 0.96 },
    colRow: { flex: 0.96 },
    colPile: { flex: 0.96 },
    colLat: { flex: 1.6, fontFamily: 'monospace' },
    colLon: { flex: 1.6, fontFamily: 'monospace' },
    colAlt: { flex: 0.96 },
    colDist: { flex: 0.96 },
    deleteBtn: { flex: 0.64, alignItems: 'center', padding: 4 },
    emptyState: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        paddingVertical: 40,
    },
    emptyText: {
        color: colors.textSecondary,
        fontSize: 18,
        marginBottom: 8,
    },
    emptyHint: {
        color: colors.textSecondary,
        fontSize: 14,
        opacity: 0.7,
    },
});
