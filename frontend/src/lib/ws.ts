import type { ControllersFrame, ServerFrame, StatusFrame, WsInbound } from "./types";
import { websocketProtocols } from "./desktop";

export type ConnectionState = "connecting" | "open" | "closed";

const MAX_QUEUED = 32;
const BACKOFF_BASE_MS = 500;
const BACKOFF_MAX_MS = 10_000;

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

class ControllerSocket {
  private ws: WebSocket | null = null;
  private state: ConnectionState = "closed";
  private attempts = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private started = false;
  private queue: WsInbound[] = [];
  private frameHandlers = new Set<(frame: ServerFrame) => void>();
  private stateHandlers = new Set<(state: ConnectionState) => void>();
  private lastStatus: StatusFrame | null = null;
  private lastControllers: ControllersFrame | null = null;

  start(): void {
    if (this.started) return;
    this.started = true;
    this.open();
  }

  private async open(): Promise<void> {
    if (this.ws !== null) return;
    this.setState("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl(), await websocketProtocols());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempts = 0;
      this.setState("open");
      const pending = this.queue.splice(0, this.queue.length);
      for (const msg of pending) this.rawSend(msg);
    };
    ws.onmessage = (ev) => this.handleMessage(ev.data);
    ws.onclose = () => {
      this.ws = null;
      this.lastStatus = null;
      this.lastControllers = null;
      if (this.started) this.scheduleReconnect();
      else this.setState("closed");
    };
    ws.onerror = () => {
      /* onclose follows; reconnect handled there */
    };
  }

  private scheduleReconnect(): void {
    this.setState(this.started ? "connecting" : "closed");
    if (this.retryTimer !== null) return;
    const delay = Math.min(BACKOFF_BASE_MS * 2 ** this.attempts, BACKOFF_MAX_MS);
    this.attempts += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      this.open();
    }, delay);
  }

  private handleMessage(raw: unknown): void {
    if (typeof raw !== "string") return;
    let frame: ServerFrame;
    try {
      frame = JSON.parse(raw) as ServerFrame;
    } catch {
      return;
    }
    if (frame?.type === "status") this.lastStatus = frame;
    if (frame?.type === "controllers") this.lastControllers = frame;
    for (const handler of [...this.frameHandlers]) {
      try {
        handler(frame);
      } catch {
        /* subscriber bugs must not break the socket */
      }
    }
  }

  getState(): ConnectionState {
    return this.state;
  }

  getStatus(): StatusFrame | null {
    return this.lastStatus;
  }

  getControllers(): ControllersFrame | null {
    return this.lastControllers;
  }

  send(msg: WsInbound): boolean {
    if (this.state === "open") return this.rawSend(msg);
    if (this.queue.length >= MAX_QUEUED) return false;
    this.queue.push(msg);
    return true;
  }

  private rawSend(msg: WsInbound): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    try {
      this.ws.send(JSON.stringify(msg));
      return true;
    } catch {
      return false;
    }
  }

  onFrame(handler: (frame: ServerFrame) => void): () => void {
    this.frameHandlers.add(handler);
    return () => this.frameHandlers.delete(handler);
  }

  onState(handler: (state: ConnectionState) => void): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  private setState(next: ConnectionState): void {
    if (this.state === next) return;
    this.state = next;
    for (const handler of [...this.stateHandlers]) {
      try {
        handler(next);
      } catch {
        /* ignore subscriber errors */
      }
    }
  }
}

export const socket = new ControllerSocket();
