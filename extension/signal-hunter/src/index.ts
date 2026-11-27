import { ExtensionContext } from "@foxglove/extension";

import { initSignalHunterPanel } from "./SignalHunterPanel";

export function activate(extensionContext: ExtensionContext): void {
  extensionContext.registerPanel({ name: "Signal Hunter", initPanel: initSignalHunterPanel });
}
