import { Immutable, MessageEvent, PanelExtensionContext } from "@foxglove/extension";
import { ReactElement, useEffect, useLayoutEffect, useState } from "react";
import { createRoot } from "react-dom/client";

// ---------- Message shapes ----------
// These must match what bridge.py publishes. If a field changes there,
// change it here too.
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

const SCAN_TOPIC = "/wifi/scan";

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

/** One row in the network list. */
function NetworkRow({ network }: { network: Network }): ReactElement {
    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns: "1fr 100px",
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
        </div>
    );
}

/** The whole panel. */
function SignalHunterPanel({ context }: { context: PanelExtensionContext }): ReactElement {
    const [scan, setScan] = useState<ScanMessage | undefined>();
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
                }
            }
        };

        context.watch("currentFrame");
        context.subscribe([{ topic: SCAN_TOPIC }]);
    }, [context]);

    // Tell Foxglove we finished drawing, so it can send the next batch
    useEffect(() => {
        renderDone?.();
    }, [renderDone]);

    const networks = scan?.networks ?? [];

    return (
        <div style={{ padding: 12, fontSize: 13, height: "100%", overflowY: "auto" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                <b>Signal Hunter</b>
                <span style={{ opacity: 0.7 }}>{scan?.count ?? 0} networks</span>
            </div>

            {networks.map((network) => (
                <NetworkRow key={network.id} network={network} />
            ))}

            {networks.length === 0 && <div style={{ opacity: 0.6 }}>Waiting for a scan...</div>}
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