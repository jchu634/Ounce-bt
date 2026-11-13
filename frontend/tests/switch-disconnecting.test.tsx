import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ConnectionToggleButton } from "@/src/components/panels/connection";
import { connectionDetail, type BluetoothStatus } from "@/src/lib/bluetooth";

describe("disconnect cleanup", () => {
  it("disables reconnect until cleanup completes and explains why", () => {
    const address = "12:34:56:78:90:AB/P";
    const status: BluetoothStatus = {
      available: true,
      pairing: false,
      state: "disconnecting",
      address: null,
      peers: [address],
      names: {},
      failure_id: 0,
      failure: null,
    };
    const render = (current: BluetoothStatus) =>
      renderToStaticMarkup(
        <ConnectionToggleButton
          status={current}
          address={address}
          disabled={false}
          busy={false}
          onReconnect={vi.fn()}
          onDisconnect={vi.fn()}
        />,
      );
    const closing = render(status);
    expect(closing).toContain("Disconnecting…");
    expect(closing).toMatch(/<button[^>]*\sdisabled=""/);
    expect(connectionDetail(status)).toContain("Please wait");
    const ready = render({ ...status, state: "disconnected" });
    expect(ready).toContain("Reconnect Controller");
    expect(ready).not.toMatch(/<button[^>]*\sdisabled=""/);
  });
});
