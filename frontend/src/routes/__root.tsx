import { Outlet, createRootRoute } from "@tanstack/react-router";
import { SocketProvider } from "@/src/hooks/use-socket";
import { CaptureProvider } from "@/src/hooks/use-capture";
import { Toaster } from "@/src/components/ui/toast";
import { TooltipProvider } from "@/src/components/ui/tooltip";
import { StartupGate } from "@/src/components/startup-gate";

export const Route = createRootRoute({
  component: RootComponent,
});

function RootComponent() {
  return (
    <StartupGate>
      <SocketProvider>
        <CaptureProvider>
          <TooltipProvider>
            <Outlet />
            <Toaster />
          </TooltipProvider>
        </CaptureProvider>
        {/*<TanStackRouterDevtools position="bottom-right" />*/}
      </SocketProvider>
    </StartupGate>
  );
}
