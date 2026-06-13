/**
 * Theme plumbing shared by the +layout ModeWatcher and the Settings
 * appearance toggle.
 *
 * The source of truth is localStorage['videoflow.theme'] which is one of
 * 'light' | 'dark' | 'system' (default 'dark', so the app keeps its current
 * look when nothing is set). app.html applies the saved value before first
 * paint to avoid a flash; this module keeps the <html> class in sync while the
 * app is running and lets any surface change the preference.
 *
 * Cross-component sync: writing the preference dispatches a window
 * 'videoflow:theme' event (same-tab) — the native 'storage' event only fires
 * in *other* tabs — so the Settings toggle and the layout stay in agreement
 * without importing each other.
 */

export type Theme = 'light' | 'dark' | 'system';

export const THEME_KEY = 'videoflow.theme';
const THEME_EVENT = 'videoflow:theme';

/** Read the saved preference, defaulting to dark. SSR-safe (returns 'dark'). */
export function getTheme(): Theme {
  if (typeof localStorage === 'undefined') return 'dark';
  const v = localStorage.getItem(THEME_KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'dark';
}

/** Resolve a preference to whether the dark class should be on <html>. */
function isDark(theme: Theme): boolean {
  if (theme === 'system') {
    return (
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches
    );
  }
  return theme === 'dark';
}

/** Toggle the <html> dark class to match a preference. */
export function applyTheme(theme: Theme = getTheme()): void {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('dark', isDark(theme));
}

/** Persist a preference, apply it, and notify same-tab listeners. */
export function setTheme(theme: Theme): void {
  if (typeof localStorage !== 'undefined') localStorage.setItem(THEME_KEY, theme);
  applyTheme(theme);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent<Theme>(THEME_EVENT, { detail: theme }));
  }
}

/**
 * Keep <html> in sync with the preference for the lifetime of the page:
 * reacts to same-tab writes (setTheme), other-tab writes (storage) and — when
 * the preference is 'system' — OS scheme changes. Returns an unsubscribe.
 */
export function watchTheme(): () => void {
  if (typeof window === 'undefined') return () => {};
  applyTheme();

  const onPref = () => applyTheme();
  const onStorage = (e: StorageEvent) => {
    if (e.key === THEME_KEY) applyTheme();
  };
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const onMedia = () => {
    if (getTheme() === 'system') applyTheme('system');
  };

  window.addEventListener(THEME_EVENT, onPref);
  window.addEventListener('storage', onStorage);
  media.addEventListener('change', onMedia);

  return () => {
    window.removeEventListener(THEME_EVENT, onPref);
    window.removeEventListener('storage', onStorage);
    media.removeEventListener('change', onMedia);
  };
}
