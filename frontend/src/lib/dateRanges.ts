export interface RangeValue {
  start: Date;
  end: Date;
  label: string;
}

export interface RangePreset {
  key: string;
  label: string;
  compute: () => RangeValue;
}

function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

/** Monday-anchored start of the week containing `d`. */
function startOfWeek(d: Date): Date {
  const x = startOfDay(d);
  const day = (x.getDay() + 6) % 7; // Mon=0 .. Sun=6
  x.setDate(x.getDate() - day);
  return x;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function startOfYear(d: Date): Date {
  return new Date(d.getFullYear(), 0, 1);
}

function daysAgo(n: number): Date {
  const x = new Date();
  x.setDate(x.getDate() - n);
  return x;
}

function monthsAgo(n: number): Date {
  const x = new Date();
  x.setMonth(x.getMonth() - n);
  return x;
}

export const RELATIVE_PRESETS: RangePreset[] = [
  { key: "24h", label: "Last 24 hours", compute: () => ({ start: daysAgo(1), end: new Date(), label: "Last 24 hours" }) },
  { key: "7d", label: "Last 7 days", compute: () => ({ start: daysAgo(7), end: new Date(), label: "Last 7 days" }) },
  { key: "30d", label: "Last 30 days", compute: () => ({ start: daysAgo(30), end: new Date(), label: "Last 30 days" }) },
  { key: "90d", label: "Last 90 days", compute: () => ({ start: daysAgo(90), end: new Date(), label: "Last 90 days" }) },
  { key: "6mo", label: "Last 6 months", compute: () => ({ start: monthsAgo(6), end: new Date(), label: "Last 6 months" }) },
  { key: "1y", label: "Last year", compute: () => ({ start: monthsAgo(12), end: new Date(), label: "Last year" }) },
];

export const CALENDAR_PRESETS: RangePreset[] = [
  { key: "this-week", label: "This week", compute: () => ({ start: startOfWeek(new Date()), end: new Date(), label: "This week" }) },
  { key: "this-month", label: "This month", compute: () => ({ start: startOfMonth(new Date()), end: new Date(), label: "This month" }) },
  {
    key: "last-month",
    label: "Last month",
    compute: () => {
      const now = new Date();
      const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const end = startOfMonth(now);
      return { start, end, label: "Last month" };
    },
  },
  { key: "this-year", label: "This year", compute: () => ({ start: startOfYear(new Date()), end: new Date(), label: "This year" }) },
];

export const DEFAULT_PRESET_KEY = "7d";

export function presetByKey(key: string): RangePreset | undefined {
  return [...RELATIVE_PRESETS, ...CALENDAR_PRESETS].find((p) => p.key === key);
}
