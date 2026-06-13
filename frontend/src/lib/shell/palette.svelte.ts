/**
 * Global command-palette store. The palette is a single app-wide instance
 * mounted in the root layout so Cmd/Ctrl+K works on EVERY route (it used to
 * live only in the Studio page, contradicting onboarding's "press Ctrl/⌘ K
 * anytime"). Singleton, in the spirit of activity.svelte.ts.
 *
 * Studio-specific callbacks (focus a canvas node, seed a new story in the
 * chat) only make sense on `/`. The Studio page registers them on mount and
 * clears them on unmount; the layout-owned palette reads them through here.
 * Everywhere else they are simply undefined and the palette navigates instead.
 */

type StudioHandlers = {
  /** Focus an existing graph node on the Studio canvas. */
  onfocus?: (id: string) => void;
  /** Seed the chat composer for a fresh story. */
  onnewstory?: () => void;
};

const store = $state({
  open: false,
  handlers: {} as StudioHandlers
});

export const palette = {
  get open(): boolean {
    return store.open;
  },
  set open(v: boolean) {
    store.open = v;
  },
  toggle(): void {
    store.open = !store.open;
  },
  /** Studio registers its canvas/chat callbacks here on mount. */
  get handlers(): StudioHandlers {
    return store.handlers;
  },
  setHandlers(h: StudioHandlers): void {
    store.handlers = h;
  },
  clearHandlers(): void {
    store.handlers = {};
  }
};
