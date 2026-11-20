import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { socket, type ConnectionState } from "@/src/lib/ws";
import type { ControllersFrame, ErrorFrame, StatusFrame, WsInbound } from "@/src/lib/types";

type SocketContextValue = {
  connection: ConnectionState;
  status: StatusFrame | null;
  controllers: ControllersFrame | null;
  lastError: ErrorFrame | null;
  clearError: () => void;
  send: (msg: WsInbound) => boolean;
};

const SocketContext = createContext<SocketContextValue | null>(null);
const send = (message: WsInbound) => socket.send(message);

export function SocketProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<ConnectionState>(socket.getState());
  const [status, setStatus] = useState<StatusFrame | null>(socket.getStatus());
  const [controllers, setControllers] = useState<ControllersFrame | null>(socket.getControllers());
  const [lastError, setLastError] = useState<ErrorFrame | null>(null);

  useEffect(() => {
    socket.start();
    const offFrame = socket.onFrame((frame) => {
      switch (frame.type) {
        case "status":
          setStatus(frame);
          break;
        case "controllers":
          setControllers(frame);
          break;
        case "error":
          setLastError(frame);
          break;
      }
    });
    const offState = socket.onState(setConnection);
    return () => {
      offFrame();
      offState();
    };
  }, []);

  return (
    <SocketContext.Provider
      value={{
        connection,
        status,
        controllers,
        lastError,
        clearError: () => setLastError(null),
        send,
      }}
    >
      {children}
    </SocketContext.Provider>
  );
}

export function useSocket(): SocketContextValue {
  const ctx = useContext(SocketContext);
  if (ctx === null) {
    throw new Error("useSocket must be used within <SocketProvider>");
  }
  return ctx;
}
