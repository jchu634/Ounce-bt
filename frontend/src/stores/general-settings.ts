import { createStore } from "@tanstack/react-store";

const CONTROLS_ONLY_STORAGE_KEY = "ounce-bt.controls-only-homepage";
const HIDE_MANUAL_CONTROL_STORAGE_KEY = "ounce-bt.controls-only-hide-manual-control";
const THEME_STORAGE_KEY = "ounce-bt.theme";

export type Theme = "dark" | "light" | "system";

type GeneralSettings = {
  controlsOnlyHomepage: boolean;
  hideManualControl: boolean;
  theme: Theme;
};

function isTheme(value: string | null): value is Theme {
  return value === "dark" || value === "light" || value === "system";
}

function loadSettings(): GeneralSettings {
  try {
    return {
      controlsOnlyHomepage: localStorage.getItem(CONTROLS_ONLY_STORAGE_KEY) === "true",
      hideManualControl: localStorage.getItem(HIDE_MANUAL_CONTROL_STORAGE_KEY) === "true",
      theme: getStoredTheme(),
    };
  } catch {
    return { controlsOnlyHomepage: false, hideManualControl: false, theme: "system" };
  }
}

function getStoredTheme(): Theme {
  const storedTheme = localStorage.getItem(THEME_STORAGE_KEY);
  return isTheme(storedTheme) ? storedTheme : "system";
}

export const generalSettingsStore = createStore(loadSettings());

const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle(
    "dark",
    theme === "dark" || (theme === "system" && systemTheme.matches),
  );
}

applyTheme(generalSettingsStore.state.theme);
systemTheme.addEventListener("change", () => {
  if (generalSettingsStore.state.theme === "system") applyTheme("system");
});

export function setControlsOnlyHomepage(enabled: boolean) {
  generalSettingsStore.setState((settings) => ({
    ...settings,
    controlsOnlyHomepage: enabled,
  }));
  try {
    localStorage.setItem(CONTROLS_ONLY_STORAGE_KEY, String(enabled));
  } catch {
    // Keep the setting usable for this session if storage is unavailable.
    console.log("Localstorage controls only write failed");
  }
}

export function setTheme(theme: Theme) {
  generalSettingsStore.setState((settings) => ({
    ...settings,
    theme,
  }));
  applyTheme(theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Keep the setting usable for this session if storage is unavailable.
    console.log("Localstorage theme write failed");
  }
}

export function setHideManualControl(enabled: boolean) {
  generalSettingsStore.setState((settings) => ({
    ...settings,
    hideManualControl: enabled,
  }));
  try {
    localStorage.setItem(HIDE_MANUAL_CONTROL_STORAGE_KEY, String(enabled));
  } catch {
    // Keep the setting usable for this session if storage is unavailable.
  }
}
