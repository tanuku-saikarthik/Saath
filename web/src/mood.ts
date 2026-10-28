// Mood colour: dusk indigo (low) → lilac (flat) → sage (steady) → marigold lamp-light (bright).
const STOPS: [number, [number, number, number]][] = [
  [-0.4, [74, 78, 134]],
  [0.0, [154, 156, 196]],
  [0.22, [127, 163, 138]],
  [0.5, [232, 163, 61]],
]

export function moodColor(mood: number | null | undefined): string {
  if (mood === null || mood === undefined) return 'transparent'
  const m = Math.max(STOPS[0][0], Math.min(STOPS[STOPS.length - 1][0], mood))
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [a, ca] = STOPS[i]
    const [b, cb] = STOPS[i + 1]
    if (m <= b) {
      const t = (m - a) / (b - a)
      const c = ca.map((v, j) => Math.round(v + (cb[j] - v) * t))
      return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
    }
  }
  const c = STOPS[STOPS.length - 1][1]
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`
}

export function moodWord(mood: number | null | undefined): string {
  if (mood === null || mood === undefined) return 'No call'
  if (mood >= 0.35) return 'Bright'
  if (mood >= 0.15) return 'Steady'
  if (mood >= -0.25) return 'Low'
  return 'Very low'
}

export const EMOTION_WORDS: Record<string, string> = {
  joy: 'Joy', contentment: 'Content', gratitude: 'Grateful', love: 'Loving', hope: 'Hopeful', neutral: 'Neutral',
  sadness: 'Sad', loneliness: 'Lonely', worry: 'Worried', fear: 'Afraid', anger: 'Angry', frustration: 'Frustrated',
  fatigue: 'Tired', pain: 'In pain', confusion: 'Confused',
}

export const VOICE_WORDS: Record<string, string> = {
  happy: 'Happy', neutral: 'Neutral', sad: 'Sad', fearful: 'Anxious', angry: 'Angry', surprised: 'Surprised',
  disgusted: 'Upset', other: 'Other', unknown: 'Unclear',
}
