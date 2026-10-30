import type { SVGProps } from 'react'

const base = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true } as const

export const IconPhone = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" /></svg>
)
export const IconChat = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M4 5h16v11H9l-5 4z" /></svg>
)
export const IconCheck = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} strokeWidth={2.2} {...p}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
)
export const IconCross = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} strokeWidth={2.2} {...p}><path d="M6 6l12 12M18 6L6 18" /></svg>
)
export const IconQuestion = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} strokeWidth={2.2} {...p}><path d="M9.2 9a3 3 0 1 1 4.3 2.7c-.9.4-1.5 1.2-1.5 2.2V14" /><path d="M12 18h.01" /></svg>
)
export const IconBack = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M15 5l-7 7 7 7" /></svg>
)
export const IconHome = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" /></svg>
)
export const IconCalls = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M4 6h16M4 12h16M4 18h10" /></svg>
)
export const IconBell = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15z" /><path d="M10 20a2 2 0 0 0 4 0" /></svg>
)
export const IconWeek = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M4 10h16M9 3v4M15 3v4" /></svg>
)
export const IconUser = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><circle cx="12" cy="8" r="4" /><path d="M4 20a8 8 0 0 1 16 0" /></svg>
)
export const IconVoice = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" /></svg>
)
export const IconArrow = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M5 12h13M13 6l6 6-6 6" /></svg>
)
export const IconPlus = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M12 5v14M5 12h14" /></svg>
)
export const IconTrash = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 24 24" {...base} {...p}><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12" /></svg>
)

/** Saath mark: a small lamp (diya) with a marigold flame — the evening call. */
export const BrandMark = (p: SVGProps<SVGSVGElement>) => (
  <svg viewBox="0 0 32 32" aria-hidden="true" {...p}>
    <path d="M16 3c3 4 4.2 6.6 4.2 8.6A4.2 4.2 0 0 1 16 15.8a4.2 4.2 0 0 1-4.2-4.2C11.8 9.6 13 7 16 3z" fill="#E8A33D" />
    <path d="M3.5 18h25c-1.2 6-6.2 10-12.5 10S4.7 24 3.5 18z" fill="#1E2140" />
    <path d="M28.5 18c1.4-.4 2.4-1.3 2.9-2.6" stroke="#1E2140" strokeWidth="2" strokeLinecap="round" fill="none" />
  </svg>
)
