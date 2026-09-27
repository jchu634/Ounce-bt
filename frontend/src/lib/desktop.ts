type DesktopApi = {
  get_auth_token: () => Promise<string | null>;
  close_application: () => Promise<void>;
};

declare global {
  interface Window {
    pywebview?: { api?: DesktopApi };
  }
}

let authRequired = true;

export function configureWebSocketAuth(required: boolean): void {
  authRequired = required;
}

export function desktopApi(): DesktopApi | undefined {
  return window.pywebview?.api;
}

async function waitForBridge(): Promise<DesktopApi> {
  const existing = desktopApi();
  if (existing) return existing;
  return new Promise((resolve, reject) => {
    const ready = () => {
      const api = desktopApi();
      if (!api) return;
      clearTimeout(timeout);
      window.removeEventListener("pywebviewready", ready);
      resolve(api);
    };
    const timeout = setTimeout(() => {
      window.removeEventListener("pywebviewready", ready);
      reject(new Error("The desktop bridge is unavailable"));
    }, 5000);
    window.addEventListener("pywebviewready", ready);
    ready();
  });
}

export async function websocketProtocols(): Promise<string[]> {
  if (!authRequired) return [];
  const api = await waitForBridge();
  const token = await api.get_auth_token();
  if (typeof token !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    throw new Error("The desktop bridge returned an invalid token");
  }
  return ["ounce-bt", `ounce-auth.${token}`];
}
