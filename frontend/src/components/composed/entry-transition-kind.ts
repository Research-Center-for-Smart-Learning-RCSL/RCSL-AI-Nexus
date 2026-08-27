/**
 * Which of the two entrances a curtain is playing. It lives in a file of its
 * own, owned by neither side, because the two modules that need it are held
 * apart on purpose: `entry-transition.tsx` reaches the scenes only through
 * `next/dynamic`, which is what keeps three.js off the first load of every
 * route the shell renders.
 *
 * Declared in either module, this type is a static edge between them. It is
 * erased today — both sides say `import type` — but the erasure is the only
 * thing separating a shared string union from an import that drags a 238 kB
 * gzip chunk into the bundle it was split out of, and nothing in the type
 * checker distinguishes the two. Here there is no edge to accidentally load.
 */
export type EntrySceneKind = 'tunnel' | 'layers';
