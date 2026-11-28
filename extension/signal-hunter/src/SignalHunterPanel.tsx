import { Immutable, MessageEvent, PanelExtensionContext } from "@foxglove/extension";
import { ReactElement, useEffect, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";

// ---------- Message shapes ----------
// These must match what bridge.py publishes. If a field changes there,
// change it here too, and TypeScript will point at everything that breaks.

/** One network inside a /wifi/scan message. */
type Network = {
    id: string;
    label: string;
    rssi: number;
    ch: number;
    open: boolean;
    mine: boolean;
};

/** A /wifi/scan message. */
type ScanMessage = {
    count: number;
    strongest_rssi: number | null;
    networks: Network[];
};

/** A /wifi/tracked message: live strength of the network being hunted. */
type TrackMessage = {
    id: string;
    label: string;
    rssi: number;
    raw_rssi: number;
    percent: number;
    found: boolean;
};

/** A command sent to the bridge on /esp32/cmd. */
type Command = { action: "track"; id: string } | { action: "stop" };

const SCAN_TOPIC = "/wifi/scan";
const TRACKED_TOPIC = "/wifi/tracked";
const COMMAND_TOPIC = "/esp32/cmd";

// Same RSSI range as config.py: -90 dBm is 0%, -35 dBm is 100%
const RSSI_WEAK = -90;
const RSSI_STRONG = -35;

// ---------- Helpers ----------

/** Convert RSSI in dBm to a 0..100 strength. */
function strengthPercent(rssi: number): number {
    const percent = ((rssi - RSSI_WEAK) / (RSSI_STRONG - RSSI_WEAK)) * 100;
    return Math.round(Math.max(0, Math.min(100, percent)));
}

/** 0% red, 50% yellow, 100% green, same as the radar and the ESP32 screen. */
function strengthColor(percent: number): string {
    const red = percent < 50 ? 255 : Math.round(255 - (percent - 50) * 5.1);
    const green = percent < 50 ? Math.round(percent * 5.1) : 255;
    return `rgb(${red}, ${green}, 40)`;
}

// ---------- Components ----------

/** A horizontal strength bar: gray track with a colored fill. */
function StrengthBar({ percent }: { percent: number }): ReactElement {
    return (
        <div style={{ background: "rgba(128, 128, 128, 0.25)", borderRadius: 4, height: 8 }}>
            <div
                style={{
                    width: `${percent}%`,
                    height: 8,
                    borderRadius: 4,
                    background: strengthColor(percent),
                }}
            />
        </div>
    );
}

/** One row in the network list, with a Track button. */
function NetworkRow({
    network,
    canTrack,
    onTrack,
}: {
    network: Network;
    canTrack: boolean;
    onTrack: (id: string) => void;
}): ReactElement {
    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px 64px",
                gap: 12,
                alignItems: "center",
                padding: "6px 0",
                borderBottom: "1px solid rgba(128, 128, 128, 0.2)",
            }}
        >
            <div>
                <div style={{ fontWeight: network.mine ? 700 : 400 }}>{network.label}</div>
                <div style={{ opacity: 0.6 }}>
                    ch {network.ch} | {network.rssi} dBm{network.open ? " | open" : ""}
                </div>
            </div>
            <StrengthBar percent={strengthPercent(network.rssi)} />
            <button
                disabled={!canTrack}
                onClick={() => {
                    onTrack(network.id);
                }}
            >
                Track
            </button>
        </div>
    );
}

/** The card shown while hunting a network: big dBm number, bar, and Stop. */
function TrackingCard({
    label,
    tracked,
    onStop,
}: {
    label: string;
    tracked: TrackMessage | undefined;
    onStop: () => void;
}): ReactElement {
    const percent = tracked?.percent ?? 0;
    let status = "waiting for the ESP32...";
    if (tracked != undefined) {
        status = tracked.found ? `${percent}% strength` : "not seen this scan";
    }

    return (
        <div
            style={{
                border: "1px solid rgba(128, 128, 128, 0.4)",
                borderRadius: 8,
                padding: 12,
                marginBottom: 12,
            }}
        >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>
                    Tracking <b>{label}</b>
                </span>
                <button onClick={onStop}>Stop</button>
            </div>
            <div style={{ fontSize: 32, margin: "8px 0" }}>
                {tracked != undefined ? `${tracked.rssi} dBm` : "--"}
            </div>
            <StrengthBar percent={percent} />
            <div style={{ opacity: 0.7, marginTop: 6 }}>{status}</div>
        </div>
    );
}

/** The whole panel. */
function SignalHunterPanel({ context }: { context: PanelExtensionContext }): ReactElement {
    const [scan, setScan] = useState<ScanMessage | undefined>();
    const [tracked, setTracked] = useState<TrackMessage | undefined>();
    const [trackingId, setTrackingId] = useState<string | undefined>();
    const [canPublish, setCanPublish] = useState(false);
    const [renderDone, setRenderDone] = useState<(() => void) | undefined>();

    // Runs once when the panel appears: tell Foxglove what we want to receive
    useLayoutEffect(() => {
        context.onRender = (renderState, done) => {
            // Save done() so we can call it after React has drawn (see useEffect below)
            setRenderDone(() => done);

            // currentFrame holds the messages that arrived since the last render
            const frame: Immutable<MessageEvent[]> | undefined = renderState.currentFrame;
            if (frame == undefined) {
                return;
            }
            for (const event of frame) {
                if (event.topic === SCAN_TOPIC) {
                    setScan(event.message as ScanMessage);
                } else if (event.topic === TRACKED_TOPIC) {
                    setTracked(event.message as TrackMessage);
                }
            }
        };

        context.watch("currentFrame");
        context.subscribe([{ topic: SCAN_TOPIC }, { topic: TRACKED_TOPIC }]);

        // advertise() only exists when the data source accepts messages:
        // live with our bridge, yes; replaying an MCAP file, no.
        if (context.advertise != undefined) {
            context.advertise(COMMAND_TOPIC, "wifidar.Command");
            setCanPublish(true);
        }

        // When the panel is removed, stop advertising
        return () => {
            context.unadvertise?.(COMMAND_TOPIC);
        };
    }, [context]);

    // Tell Foxglove we finished drawing, so it can send the next batch
    useEffect(() => {
        renderDone?.();
    }, [renderDone]);

    /** Send a command to the bridge over the WebSocket. */
    const sendCommand = (command: Command) => {
        context.publish?.(COMMAND_TOPIC, command);
    };

    const startTracking = (id: string) => {
        sendCommand({ action: "track", id });
        setTrackingId(id);
        setTracked(undefined); // clear the old reading so we don't show a stale number
    };

    const stopTracking = () => {
        sendCommand({ action: "stop" });
        setTrackingId(undefined);
    };

    const networks = scan?.networks ?? [];
    const trackedLabel =
        networks.find((network) => network.id === trackingId)?.label ?? trackingId ?? "";

    return (
        <div style={{ padding: 12, fontSize: 13, height: "100%", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                <b>Signal Hunter</b>
                <span style={{ opacity: 0.7 }}>
                    {canPublish ? "live" : "replay, tracking off"} | {scan?.count ?? 0} networks
                </span>
            </div>

            {trackingId != undefined && (
                <TrackingCard label={trackedLabel} tracked={tracked} onStop={stopTracking} />
            )}

            {trackingId == undefined &&
                networks.map((network) => (
                    <NetworkRow
                        key={network.id}
                        network={network}
                        canTrack={canPublish}
                        onTrack={startTracking}
                    />
                ))}

            {trackingId == undefined && networks.length === 0 && (
                <div style={{ opacity: 0.6 }}>Waiting for a scan...</div>
            )}
        </div>
    );
}

// ---------- Entry point ----------

/** Foxglove calls this when someone adds the panel to a layout. */
export function initSignalHunterPanel(context: PanelExtensionContext): () => void {
    const root = createRoot(context.panelElement);
    root.render(<SignalHunterPanel context={context} />);

    // Foxglove calls this when the panel is removed
    return () => {
        root.unmount();
    };
}